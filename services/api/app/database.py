import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.migrations import MIGRATIONS

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    genre TEXT NOT NULL,
    rebirth_year INTEGER NOT NULL,
    rebirth_location TEXT NOT NULL,
    chapter_target_words INTEGER NOT NULL,
    safety_buffer_chapters INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_recovery_points (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 80),
    kind TEXT NOT NULL CHECK(kind IN ('manual')),
    payload_zlib BLOB NOT NULL,
    archive_sha256 TEXT NOT NULL CHECK(length(archive_sha256) = 64),
    uncompressed_bytes INTEGER NOT NULL CHECK(uncompressed_bytes > 0),
    compressed_bytes INTEGER NOT NULL CHECK(compressed_bytes > 0),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_project_recovery_points_project_created
ON project_recovery_points(project_id, created_at, id);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    volume_number INTEGER NOT NULL CHECK(volume_number > 0),
    chapter_number INTEGER NOT NULL CHECK(chapter_number > 0),
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    reader_promise TEXT NOT NULL DEFAULT '',
    opening_hook TEXT NOT NULL DEFAULT '',
    state_change TEXT NOT NULL DEFAULT '',
    emotional_payoff TEXT NOT NULL DEFAULT '',
    ending_cliffhanger TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, chapter_number)
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    expected_chapter_revision INTEGER NOT NULL,
    candidate_content TEXT,
    error_message TEXT,
    provider TEXT NOT NULL DEFAULT 'demo',
    model TEXT NOT NULL DEFAULT 'replay-v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapter_events (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, sequence)
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    layer TEXT NOT NULL CHECK(layer IN ('original', 'novel')),
    event_year INTEGER NOT NULL CHECK(event_year BETWEEN -3000 AND 2100),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    summary TEXT NOT NULL DEFAULT '' CHECK(length(summary) <= 1000),
    source_chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_timeline_events_project_layer_year
ON timeline_events(project_id, layer, event_year, created_at);

CREATE TABLE IF NOT EXISTS story_facts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('state_change', 'open_thread')),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 300),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_story_facts_project_created
ON story_facts(project_id, created_at);

CREATE TABLE IF NOT EXISTS fact_change_sets (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    chapter_revision INTEGER NOT NULL CHECK(chapter_revision >= 0),
    state TEXT NOT NULL CHECK(state IN ('candidate', 'applied', 'rejected')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(chapter_id, chapter_revision)
);

CREATE TABLE IF NOT EXISTS fact_changes (
    id TEXT PRIMARY KEY,
    change_set_id TEXT NOT NULL REFERENCES fact_change_sets(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('state_change', 'open_thread')),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 300),
    event_year INTEGER CHECK(event_year BETWEEN -3000 AND 2100)
);

CREATE INDEX IF NOT EXISTS idx_fact_changes_set
ON fact_changes(change_set_id);

CREATE TABLE IF NOT EXISTS future_knowledge (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    future_year INTEGER NOT NULL CHECK(future_year BETWEEN -3000 AND 2100),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 500),
    source_note TEXT NOT NULL DEFAULT '' CHECK(length(source_note) <= 500),
    confidence TEXT NOT NULL CHECK(confidence IN ('certain', 'likely', 'uncertain')),
    status TEXT NOT NULL CHECK(status IN ('valid', 'candidate_invalid', 'invalid')),
    divergence_event_id TEXT REFERENCES timeline_events(id) ON DELETE SET NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_future_knowledge_project_year
ON future_knowledge(project_id, future_year, status);

CREATE TABLE IF NOT EXISTS story_entities (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('character', 'resource')),
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    role TEXT NOT NULL DEFAULT '' CHECK(length(role) <= 300),
    goal TEXT NOT NULL DEFAULT '' CHECK(length(goal) <= 500),
    current_state TEXT NOT NULL DEFAULT '' CHECK(length(current_state) <= 1000),
    relationship_notes TEXT NOT NULL DEFAULT '' CHECK(length(relationship_notes) <= 1000),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_story_entities_project_kind_name
ON story_entities(project_id, kind, name);

CREATE TABLE IF NOT EXISTS story_threads (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 300),
    summary TEXT NOT NULL DEFAULT '' CHECK(length(summary) <= 1000),
    status TEXT NOT NULL CHECK(status IN ('open', 'resolved', 'abandoned')),
    planted_chapter_number INTEGER CHECK(planted_chapter_number > 0),
    resolved_chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, source_chapter_id, title)
);

CREATE INDEX IF NOT EXISTS idx_story_threads_project_status
ON story_threads(project_id, status, created_at);

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
    source_filename TEXT NOT NULL CHECK(length(source_filename) BETWEEN 1 AND 255),
    source_format TEXT NOT NULL CHECK(source_format IN ('txt', 'markdown', 'pdf')),
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    source_encoding TEXT NOT NULL CHECK(length(source_encoding) BETWEEN 1 AND 40),
    encoding_confidence REAL NOT NULL CHECK(encoding_confidence BETWEEN 0 AND 1),
    import_state TEXT NOT NULL CHECK(import_state IN ('ready', 'needs_review')),
    source_spans_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_spans_json)),
    duplicate_of_id TEXT REFERENCES source_documents(id) ON DELETE SET NULL,
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 20000000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_documents_hash_created
ON source_documents(content_sha256, created_at, id);

CREATE TABLE IF NOT EXISTS source_cards (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('historical_record', 'news', 'industry', 'personal_note')),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
    source_reference TEXT NOT NULL CHECK(length(source_reference) BETWEEN 1 AND 1000),
    applicable_year_start INTEGER NOT NULL CHECK(applicable_year_start BETWEEN -3000 AND 2100),
    applicable_year_end INTEGER NOT NULL CHECK(applicable_year_end BETWEEN -3000 AND 2100),
    confidence TEXT NOT NULL CHECK(confidence IN ('high', 'medium', 'low')),
    excerpt TEXT NOT NULL DEFAULT '' CHECK(length(excerpt) <= 4000),
    source_document_id TEXT REFERENCES source_documents(id) ON DELETE SET NULL,
    source_date TEXT CHECK(source_date IS NULL OR length(source_date) <= 40),
    page_number_start INTEGER CHECK(page_number_start IS NULL OR page_number_start > 0),
    page_number_end INTEGER CHECK(page_number_end IS NULL OR page_number_end >= page_number_start),
    start_char INTEGER CHECK(start_char IS NULL OR start_char >= 0),
    end_char INTEGER CHECK(end_char IS NULL OR end_char > start_char),
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(applicable_year_end >= applicable_year_start)
);

CREATE INDEX IF NOT EXISTS idx_source_cards_project_years
ON source_cards(project_id, applicable_year_start, applicable_year_end, confirmed);

CREATE TABLE IF NOT EXISTS reference_works (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
    source_filename TEXT NOT NULL CHECK(length(source_filename) BETWEEN 1 AND 255),
    source_format TEXT NOT NULL CHECK(source_format IN ('txt', 'markdown', 'pdf')),
    rights_basis TEXT NOT NULL CHECK(rights_basis IN ('self_owned', 'authorized', 'public_domain')),
    total_characters INTEGER NOT NULL CHECK(total_characters BETWEEN 1 AND 20000000),
    segment_target_characters INTEGER NOT NULL CHECK(segment_target_characters BETWEEN 100000 AND 1000000),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
    source_encoding TEXT NOT NULL CHECK(length(source_encoding) BETWEEN 1 AND 40),
    encoding_confidence REAL NOT NULL CHECK(encoding_confidence BETWEEN 0 AND 1),
    import_state TEXT NOT NULL CHECK(import_state IN ('ready', 'needs_review')),
    source_spans_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_spans_json)),
    duplicate_of_id TEXT REFERENCES reference_works(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reference_works_hash_created
ON reference_works(content_sha256, created_at, id);

CREATE TABLE IF NOT EXISTS project_reference_works (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    reference_work_id TEXT NOT NULL REFERENCES reference_works(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, reference_work_id)
);

CREATE INDEX IF NOT EXISTS idx_project_reference_works_work
ON project_reference_works(reference_work_id, project_id);

CREATE TABLE IF NOT EXISTS reference_segments (
    id TEXT PRIMARY KEY,
    reference_work_id TEXT NOT NULL REFERENCES reference_works(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    character_count INTEGER NOT NULL CHECK(character_count > 0),
    chapter_start TEXT CHECK(chapter_start IS NULL OR length(chapter_start) <= 120),
    chapter_end TEXT CHECK(chapter_end IS NULL OR length(chapter_end) <= 120),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(end_char - start_char = character_count),
    UNIQUE(reference_work_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_reference_segments_work_ordinal
ON reference_segments(reference_work_id, ordinal);

CREATE TABLE IF NOT EXISTS reference_analysis_cache (
    cache_key TEXT PRIMARY KEY CHECK(length(cache_key) = 64),
    asset_level TEXT NOT NULL CHECK(asset_level IN ('chunk', 'segment', 'book', 'fusion')),
    reference_work_id TEXT REFERENCES reference_works(id) ON DELETE CASCADE,
    source_fingerprint_sha256 TEXT NOT NULL CHECK(length(source_fingerprint_sha256) = 64),
    prompt_version TEXT NOT NULL CHECK(length(prompt_version) BETWEEN 1 AND 100),
    provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 40),
    model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reference_analysis_cache_work_level
ON reference_analysis_cache(reference_work_id, asset_level, created_at);

CREATE TABLE IF NOT EXISTS reference_analysis_cache_sources (
    cache_key TEXT NOT NULL REFERENCES reference_analysis_cache(cache_key) ON DELETE CASCADE,
    reference_work_id TEXT NOT NULL REFERENCES reference_works(id) ON DELETE CASCADE,
    PRIMARY KEY(cache_key, reference_work_id)
);

CREATE INDEX IF NOT EXISTS idx_reference_analysis_cache_sources_work
ON reference_analysis_cache_sources(reference_work_id, cache_key);

CREATE TABLE IF NOT EXISTS reference_pattern_cards (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    selected_segment_ids_json TEXT NOT NULL,
    author_focus TEXT NOT NULL CHECK(length(author_focus) <= 1000),
    proposal_json TEXT NOT NULL CHECK(length(proposal_json) BETWEEN 2 AND 50000),
    provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 40),
    model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reference_pattern_cards_project_created
ON reference_pattern_cards(project_id, created_at, id);

CREATE TABLE IF NOT EXISTS reference_pattern_applications (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pattern_card_id TEXT NOT NULL REFERENCES reference_pattern_cards(id) ON DELETE CASCADE,
    selected_dimensions_json TEXT NOT NULL,
    dimensions_json TEXT NOT NULL CHECK(length(dimensions_json) BETWEEN 2 AND 20000),
    relationship_recomposition TEXT NOT NULL CHECK(length(relationship_recomposition) BETWEEN 1 AND 1200),
    application_note TEXT NOT NULL CHECK(length(application_note) <= 1000),
    blueprint_json TEXT NOT NULL CHECK(length(blueprint_json) BETWEEN 2 AND 100000),
    originality_status TEXT NOT NULL CHECK(originality_status IN ('needs_check', 'blocked', 'review_required', 'passed')),
    risk_level TEXT CHECK(risk_level IS NULL OR risk_level IN ('low', 'medium', 'high')),
    latest_report_id TEXT,
    threshold_version TEXT CHECK(threshold_version IS NULL OR length(threshold_version) BETWEEN 1 AND 80),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, pattern_card_id)
);

CREATE INDEX IF NOT EXISTS idx_reference_pattern_applications_project_created
ON reference_pattern_applications(project_id, created_at, id);

CREATE TABLE IF NOT EXISTS reference_blueprint_versions (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES reference_pattern_applications(id) ON DELETE CASCADE,
    blueprint_revision INTEGER NOT NULL CHECK(blueprint_revision >= 0),
    blueprint_json TEXT NOT NULL CHECK(length(blueprint_json) BETWEEN 2 AND 100000),
    changed_dimensions_json TEXT NOT NULL CHECK(length(changed_dimensions_json) BETWEEN 2 AND 500),
    relationship_changed INTEGER NOT NULL CHECK(relationship_changed IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(application_id, blueprint_revision)
);

CREATE INDEX IF NOT EXISTS idx_reference_blueprint_versions_application
ON reference_blueprint_versions(application_id, blueprint_revision DESC);

CREATE TABLE IF NOT EXISTS originality_reports (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES reference_pattern_applications(id) ON DELETE CASCADE,
    blueprint_revision INTEGER NOT NULL CHECK(blueprint_revision >= 0),
    risk_level TEXT NOT NULL CHECK(risk_level IN ('low', 'medium', 'high')),
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
    threshold_version TEXT NOT NULL CHECK(length(threshold_version) BETWEEN 1 AND 80),
    checked_dimensions_json TEXT NOT NULL CHECK(length(checked_dimensions_json) BETWEEN 2 AND 500),
    evidence_json TEXT NOT NULL CHECK(length(evidence_json) BETWEEN 2 AND 50000),
    source_segment_ids_json TEXT NOT NULL CHECK(length(source_segment_ids_json) BETWEEN 2 AND 5000),
    input_sha256 TEXT NOT NULL CHECK(length(input_sha256) = 64),
    viewed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(application_id, blueprint_revision)
);

CREATE INDEX IF NOT EXISTS idx_originality_reports_application
ON originality_reports(application_id, blueprint_revision DESC);

CREATE TABLE IF NOT EXISTS book_blueprints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    idea TEXT NOT NULL CHECK(length(idea) BETWEEN 1 AND 3000),
    content_json TEXT NOT NULL CHECK(length(content_json) BETWEEN 2 AND 30000),
    locks_json TEXT NOT NULL CHECK(length(locks_json) BETWEEN 2 AND 3000),
    field_versions_json TEXT NOT NULL CHECK(length(field_versions_json) BETWEEN 2 AND 3000),
    stale_fields_json TEXT NOT NULL DEFAULT '[]' CHECK(length(stale_fields_json) BETWEEN 2 AND 3000),
    plan_stale INTEGER NOT NULL DEFAULT 1 CHECK(plan_stale IN (0, 1)),
    source_candidate_id TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS volume_plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    volume_number INTEGER NOT NULL CHECK(volume_number BETWEEN 1 AND 100),
    content_json TEXT NOT NULL CHECK(length(content_json) BETWEEN 2 AND 30000),
    locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, volume_number)
);

CREATE INDEX IF NOT EXISTS idx_volume_plans_project_number
ON volume_plans(project_id, volume_number);

CREATE TABLE IF NOT EXISTS rolling_chapter_plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    volume_plan_id TEXT NOT NULL REFERENCES volume_plans(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL CHECK(chapter_number BETWEEN 1 AND 10000),
    content_json TEXT NOT NULL CHECK(length(content_json) BETWEEN 2 AND 100000),
    locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, chapter_number)
);

CREATE INDEX IF NOT EXISTS idx_rolling_chapter_plans_project_number
ON rolling_chapter_plans(project_id, chapter_number);

CREATE TABLE IF NOT EXISTS chapter_versions (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK(version_number > 0),
    chapter_revision INTEGER NOT NULL CHECK(chapter_revision >= 0),
    content TEXT NOT NULL CHECK(length(content) <= 2000000),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    source TEXT NOT NULL CHECK(source IN (
        'initial', 'manual_save', 'generation_candidate',
        'generation_apply', 'change_set_apply', 'rollback'
    )),
    source_id TEXT,
    parent_version_id TEXT REFERENCES chapter_versions(id) ON DELETE SET NULL,
    is_candidate INTEGER NOT NULL DEFAULT 0 CHECK(is_candidate IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(chapter_id, version_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_versions_source
ON chapter_versions(chapter_id, source, source_id)
WHERE source_id IS NOT NULL AND source IN (
    'generation_candidate', 'generation_apply', 'change_set_apply'
);

CREATE INDEX IF NOT EXISTS idx_chapter_versions_chapter_number
ON chapter_versions(chapter_id, version_number DESC);

CREATE TABLE IF NOT EXISTS review_findings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    chapter_revision INTEGER NOT NULL CHECK(chapter_revision >= 0),
    review_job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    dimension TEXT NOT NULL CHECK(dimension IN (
        'continuity', 'serial_rhythm', 'character', 'realism',
        'rebirth_logic', 'style', 'format'
    )),
    severity TEXT NOT NULL CHECK(severity IN ('info', 'warning', 'critical')),
    code TEXT NOT NULL CHECK(length(code) BETWEEN 1 AND 80),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
    evidence_json TEXT NOT NULL CHECK(length(evidence_json) BETWEEN 2 AND 20000),
    explanation TEXT NOT NULL CHECK(length(explanation) BETWEEN 1 AND 1200),
    suggestion TEXT NOT NULL CHECK(length(suggestion) BETWEEN 1 AND 1200),
    suggested_replacement TEXT CHECK(
        suggested_replacement IS NULL OR length(suggested_replacement) <= 2000
    ),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    dedupe_key TEXT NOT NULL CHECK(length(dedupe_key) = 64),
    state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open', 'accepted', 'rejected', 'resolved')),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_findings_chapter_revision
ON review_findings(chapter_id, chapter_revision, dimension, created_at DESC);

CREATE TABLE IF NOT EXISTS text_change_sets (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    base_chapter_revision INTEGER NOT NULL CHECK(base_chapter_revision >= 0),
    base_content_sha256 TEXT NOT NULL CHECK(length(base_content_sha256) = 64),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
    state TEXT NOT NULL CHECK(state IN ('candidate', 'applied', 'rejected')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_text_change_sets_chapter_created
ON text_change_sets(chapter_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS text_changes (
    id TEXT PRIMARY KEY,
    change_set_id TEXT NOT NULL REFERENCES text_change_sets(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    original_text TEXT NOT NULL CHECK(length(original_text) <= 4000),
    replacement_text TEXT NOT NULL CHECK(length(replacement_text) <= 4000),
    rationale TEXT NOT NULL CHECK(length(rationale) BETWEEN 1 AND 1200),
    review_finding_id TEXT REFERENCES review_findings(id) ON DELETE SET NULL,
    selected INTEGER CHECK(selected IS NULL OR selected IN (0, 1)),
    applied_replacement TEXT CHECK(
        applied_replacement IS NULL OR length(applied_replacement) <= 4000
    ),
    UNIQUE(change_set_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_text_changes_set
ON text_changes(change_set_id, ordinal);

CREATE TABLE IF NOT EXISTS manuscript_volumes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    volume_number INTEGER NOT NULL CHECK(volume_number > 0),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    sort_key INTEGER NOT NULL CHECK(sort_key > 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, volume_number)
);

CREATE INDEX IF NOT EXISTS idx_manuscript_volumes_project_sort
ON manuscript_volumes(project_id, deleted_at, sort_key, id);

CREATE TABLE IF NOT EXISTS manuscript_scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    summary TEXT NOT NULL DEFAULT '' CHECK(length(summary) <= 2000),
    sort_key INTEGER NOT NULL CHECK(sort_key > 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_manuscript_scenes_chapter_sort
ON manuscript_scenes(chapter_id, deleted_at, sort_key, id);

CREATE TABLE IF NOT EXISTS directory_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK(action IN ('create', 'rename', 'move', 'delete')),
    node_kind TEXT NOT NULL CHECK(node_kind IN ('volume', 'chapter', 'scene')),
    node_id TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(length(payload_json) BETWEEN 2 AND 2000000),
    undone_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_directory_events_project_created
ON directory_events(project_id, undone_at, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS serial_daily_goals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    goal_date TEXT NOT NULL CHECK(length(goal_date) = 10),
    target_characters INTEGER NOT NULL CHECK(target_characters BETWEEN 0 AND 100000),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, goal_date)
);

CREATE TABLE IF NOT EXISTS beta_feedback (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK(category IN (
        'workflow', 'ai_quality', 'reliability', 'originality', 'usability'
    )),
    context TEXT NOT NULL CHECK(context IN (
        'writing', 'director', 'review', 'reference', 'recovery', 'release'
    )),
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    note TEXT NOT NULL DEFAULT '' CHECK(length(note) <= 2000),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_beta_feedback_project_created
ON beta_feedback(project_id, created_at, id);

CREATE TABLE IF NOT EXISTS beta_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK(event_type IN (
        'manuscript_export', 'project_export', 'recovery_restore', 'report_export'
    )),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_beta_events_project_type_created
ON beta_events(project_id, event_type, created_at, id);

CREATE TABLE IF NOT EXISTS sandbox_snapshots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 120),
    engine_version TEXT NOT NULL CHECK(length(engine_version) BETWEEN 1 AND 80),
    actor_count INTEGER NOT NULL CHECK(actor_count BETWEEN 5 AND 20),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256) = 64),
    source_counts_json TEXT NOT NULL CHECK(json_valid(source_counts_json)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sandbox_snapshots_project_created
ON sandbox_snapshots(project_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS sandbox_branches (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES sandbox_snapshots(id) ON DELETE CASCADE,
    parent_branch_id TEXT REFERENCES sandbox_branches(id) ON DELETE SET NULL,
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 120),
    seed INTEGER NOT NULL CHECK(seed BETWEEN 0 AND 2147483647),
    variables_json TEXT NOT NULL CHECK(json_valid(variables_json)),
    forced_actions_json TEXT NOT NULL CHECK(json_valid(forced_actions_json)),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sandbox_branches_snapshot_created
ON sandbox_branches(snapshot_id, created_at, id);

CREATE TABLE IF NOT EXISTS sandbox_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES sandbox_branches(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK(state IN (
        'ready', 'running', 'completed', 'cancelled', 'budget_exhausted'
    )),
    requested_rounds INTEGER NOT NULL CHECK(requested_rounds BETWEEN 3 AND 10),
    completed_rounds INTEGER NOT NULL DEFAULT 0 CHECK(completed_rounds BETWEEN 0 AND 10),
    action_budget INTEGER NOT NULL CHECK(action_budget BETWEEN 5 AND 200),
    actions_used INTEGER NOT NULL DEFAULT 0 CHECK(actions_used BETWEEN 0 AND 200),
    current_state_json TEXT NOT NULL CHECK(json_valid(current_state_json)),
    current_state_sha256 TEXT NOT NULL CHECK(length(current_state_sha256) = 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sandbox_runs_branch_created
ON sandbox_runs(branch_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS sandbox_rounds (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES sandbox_runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 10),
    actions_json TEXT NOT NULL CHECK(json_valid(actions_json)),
    outcomes_json TEXT NOT NULL CHECK(json_valid(outcomes_json)),
    assumptions_json TEXT NOT NULL CHECK(json_valid(assumptions_json)),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    state_before_sha256 TEXT NOT NULL CHECK(length(state_before_sha256) = 64),
    state_after_sha256 TEXT NOT NULL CHECK(length(state_after_sha256) = 64),
    created_at TEXT NOT NULL,
    UNIQUE(run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_sandbox_rounds_run_ordinal
ON sandbox_rounds(run_id, ordinal);

CREATE TABLE IF NOT EXISTS sandbox_candidates (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES sandbox_runs(id) ON DELETE CASCADE,
    target_chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    source_round INTEGER NOT NULL CHECK(source_round BETWEEN 1 AND 10),
    kind TEXT NOT NULL CHECK(kind IN ('chapter_outline', 'fact_change')),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    state TEXT NOT NULL CHECK(state IN ('candidate', 'approved', 'rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sandbox_candidates_project_created
ON sandbox_candidates(project_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS ai_provider_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(name) BETWEEN 1 AND 80),
    provider TEXT NOT NULL CHECK(provider IN ('openai', 'openai_compatible')),
    base_url TEXT NOT NULL CHECK(length(base_url) BETWEEN 1 AND 2048),
    model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
    capabilities_json TEXT NOT NULL CHECK(length(capabilities_json) BETWEEN 2 AND 1000),
    input_cost_microusd_per_million INTEGER
        CHECK(input_cost_microusd_per_million IS NULL OR input_cost_microusd_per_million >= 0),
    output_cost_microusd_per_million INTEGER
        CHECK(output_cost_microusd_per_million IS NULL OR output_cost_microusd_per_million >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_task_defaults (
    task_type TEXT PRIMARY KEY
        CHECK(task_type IN ('chapter_brief', 'chapter_draft', 'reference_analysis', 'review')),
    profile_id TEXT NOT NULL REFERENCES ai_provider_profiles(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_packets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    chapter_revision INTEGER NOT NULL CHECK(chapter_revision >= 0),
    task_type TEXT NOT NULL CHECK(task_type IN ('chapter_brief', 'chapter_draft')),
    compiler_version TEXT NOT NULL CHECK(length(compiler_version) BETWEEN 1 AND 80),
    token_budget INTEGER NOT NULL CHECK(token_budget BETWEEN 1000 AND 200000),
    used_tokens INTEGER NOT NULL CHECK(used_tokens > 0),
    overflow_tokens INTEGER NOT NULL CHECK(overflow_tokens >= 0),
    packet_sha256 TEXT NOT NULL CHECK(length(packet_sha256) = 64),
    source_fingerprint_sha256 TEXT NOT NULL CHECK(length(source_fingerprint_sha256) = 64),
    packet_json TEXT NOT NULL CHECK(length(packet_json) BETWEEN 2 AND 5000000),
    rendered_context TEXT NOT NULL CHECK(length(rendered_context) BETWEEN 2 AND 5000000),
    created_at TEXT NOT NULL,
    UNIQUE(chapter_id, task_type, packet_sha256)
);

CREATE INDEX IF NOT EXISTS idx_context_packets_chapter_created
ON context_packets(chapter_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS context_directives (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK(length(source_kind) BETWEEN 1 AND 40),
    source_id TEXT NOT NULL CHECK(length(source_id) BETWEEN 1 AND 200),
    action TEXT NOT NULL CHECK(action IN ('pin', 'exclude')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(chapter_id, source_kind, source_id)
);

CREATE INDEX IF NOT EXISTS idx_context_directives_chapter
ON context_directives(chapter_id, source_kind, source_id);
"""


class DatabaseIntegrityError(RuntimeError):
    """Raised when SQLite reports that an existing database is damaged."""


class UnsupportedDatabaseVersionError(RuntimeError):
    """Raised when a database was created by a newer version of Mozhou."""


class DatabaseBackupError(RuntimeError):
    """Raised when an upgrade backup cannot be completed safely."""


class DatabaseMigrationError(RuntimeError):
    """Raised when a versioned migration fails before replacing the source database."""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        database_exists = self.path.is_file() and self.path.stat().st_size > 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema_version = 0
        if database_exists:
            schema_version = self._inspect_existing_database()
            if schema_version > CURRENT_SCHEMA_VERSION:
                raise UnsupportedDatabaseVersionError(
                    f"数据库版本 {schema_version} 高于程序支持版本 {CURRENT_SCHEMA_VERSION}"
                )
            if schema_version < CURRENT_SCHEMA_VERSION:
                self._backup_before_upgrade(CURRENT_SCHEMA_VERSION)
        if schema_version == CURRENT_SCHEMA_VERSION:
            return
        self._migrate_staged_copy(schema_version, database_exists=database_exists)

    def _migrate_staged_copy(self, source_version: int, *, database_exists: bool) -> None:
        staging_path = self.path.with_name(f".mozhou-migrate-{uuid4().hex}.db")
        try:
            if database_exists:
                with (
                    closing(sqlite3.connect(self.path, timeout=5)) as source_connection,
                    closing(sqlite3.connect(staging_path)) as staging_connection,
                ):
                    source_connection.backup(staging_connection)

            with closing(sqlite3.connect(staging_path, timeout=5)) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                for migration in MIGRATIONS:
                    if migration.version <= source_version:
                        continue
                    try:
                        migration.upgrade(connection, SCHEMA)
                        connection.execute(f"PRAGMA user_version={migration.version}")
                        connection.commit()
                    except Exception as error:
                        connection.rollback()
                        raise DatabaseMigrationError(
                            f"数据库迁移 v{migration.version - 1}→v{migration.version} 失败，原库保持不变"
                        ) from error

                check_results = connection.execute("PRAGMA quick_check").fetchall()
                if check_results != [("ok",)]:
                    raise DatabaseMigrationError("迁移副本完整性检查未通过，原库保持不变")
                connection.execute("PRAGMA journal_mode=WAL").fetchone()

            self._remove_sqlite_sidecars(staging_path)
            if database_exists:
                self._checkpoint_source_before_replace()
            staging_path.replace(self.path)
        except DatabaseMigrationError:
            raise
        except (OSError, sqlite3.DatabaseError) as error:
            raise DatabaseMigrationError("数据库迁移失败，原库保持不变") from error
        finally:
            staging_path.unlink(missing_ok=True)
            self._remove_sqlite_sidecars(staging_path)

    @staticmethod
    def _remove_sqlite_sidecars(database_path: Path) -> None:
        database_path.with_name(f"{database_path.name}-wal").unlink(missing_ok=True)
        database_path.with_name(f"{database_path.name}-shm").unlink(missing_ok=True)

    def _checkpoint_source_before_replace(self) -> None:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is not None and int(checkpoint[0]) != 0:
                raise DatabaseMigrationError("原库仍被其他进程占用，未替换已完成的迁移副本")
        self._remove_sqlite_sidecars(self.path)

    def _inspect_existing_database(self) -> int:
        try:
            with closing(sqlite3.connect(self.path, timeout=5)) as connection:
                check_results = connection.execute("PRAGMA quick_check").fetchall()
                if check_results != [("ok",)]:
                    raise DatabaseIntegrityError("数据库完整性检查未通过")
                version_row = connection.execute("PRAGMA user_version").fetchone()
        except DatabaseIntegrityError:
            raise
        except sqlite3.DatabaseError as error:
            raise DatabaseIntegrityError("数据库无法读取，未执行任何升级") from error
        return int(version_row[0]) if version_row is not None else 0

    def _backup_before_upgrade(self, target_version: int) -> Path:
        backup_directory = self.path.parent / "backups"
        backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_directory / f"mozhou-before-v{target_version}-{timestamp}.db"
        temporary_path = backup_directory / f".{backup_path.name}.{uuid4().hex}.tmp"
        try:
            with (
                closing(sqlite3.connect(self.path, timeout=5)) as source_connection,
                closing(sqlite3.connect(temporary_path)) as backup_connection,
            ):
                source_connection.backup(backup_connection)
                backup_connection.execute("PRAGMA journal_mode=DELETE").fetchone()
                check_results = backup_connection.execute("PRAGMA quick_check").fetchall()
                if check_results != [("ok",)]:
                    raise DatabaseBackupError("升级前备份完整性检查未通过")
            try:
                backup_path.hardlink_to(temporary_path)
            except FileExistsError as error:
                raise DatabaseBackupError("升级前备份文件名冲突") from error
        except DatabaseBackupError:
            raise
        except (OSError, sqlite3.DatabaseError) as error:
            raise DatabaseBackupError("无法创建数据库升级前备份") from error
        finally:
            temporary_path.unlink(missing_ok=True)
            temporary_path.with_name(f"{temporary_path.name}-wal").unlink(missing_ok=True)
            temporary_path.with_name(f"{temporary_path.name}-shm").unlink(missing_ok=True)
        return backup_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
