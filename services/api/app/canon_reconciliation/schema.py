"""SQLite schema for approval-driven Canon reconciliation."""

CANON_RECONCILIATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS chapter_approvals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    chapter_revision INTEGER NOT NULL CHECK(chapter_revision > 0),
    chapter_content_sha256 TEXT NOT NULL CHECK(length(chapter_content_sha256) = 64),
    chapter_version_id TEXT NOT NULL UNIQUE
        REFERENCES chapter_versions(id) ON DELETE RESTRICT,
    source_writing_outcome_id TEXT
        REFERENCES chapter_writing_outcomes(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE(chapter_id, chapter_revision)
);
CREATE INDEX IF NOT EXISTS idx_chapter_approvals_project_created
ON chapter_approvals(project_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS canon_reconciliations (
    id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL UNIQUE
        REFERENCES chapter_approvals(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK(state IN ('pending', 'ready', 'decided', 'stale', 'failed')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    context_packet_id TEXT,
    context_packet_sha256 TEXT
        CHECK(context_packet_sha256 IS NULL OR length(context_packet_sha256) = 64),
    context_dependency_fingerprint_sha256 TEXT CHECK(
        context_dependency_fingerprint_sha256 IS NULL
        OR length(context_dependency_fingerprint_sha256) = 64
    ),
    analysis_sha256 TEXT CHECK(
        analysis_sha256 IS NULL OR length(analysis_sha256) = 64
    ),
    preference_skip_reason TEXT CHECK(
        preference_skip_reason IS NULL OR length(preference_skip_reason) <= 500
    ),
    error_message TEXT CHECK(error_message IS NULL OR length(error_message) <= 1000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK(
        (context_packet_id IS NULL AND context_packet_sha256 IS NULL
            AND context_dependency_fingerprint_sha256 IS NULL)
        OR
        (context_packet_id IS NOT NULL AND context_packet_sha256 IS NOT NULL
            AND context_dependency_fingerprint_sha256 IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_canon_reconciliations_chapter_created
ON canon_reconciliations(chapter_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_canon_reconciliations_project_state
ON canon_reconciliations(project_id, state, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS canon_delta_candidates (
    id TEXT PRIMARY KEY,
    reconciliation_id TEXT NOT NULL
        REFERENCES canon_reconciliations(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    kind TEXT NOT NULL CHECK(kind IN (
        'character_state', 'relationship', 'resource_state', 'location_state',
        'character_knowledge', 'future_knowledge', 'story_thread',
        'progression', 'timeline_event'
    )),
    subject_key TEXT NOT NULL CHECK(length(subject_key) BETWEEN 1 AND 240),
    summary TEXT NOT NULL CHECK(length(summary) BETWEEN 1 AND 1200),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256) = 64),
    conflicts_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(conflicts_json)),
    state TEXT NOT NULL DEFAULT 'candidate'
        CHECK(state IN ('candidate', 'accepted', 'rejected', 'stale')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    rejection_reason TEXT CHECK(
        rejection_reason IS NULL OR length(rejection_reason) BETWEEN 1 AND 1000
    ),
    accepted_record_id TEXT REFERENCES canon_records(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(reconciliation_id, ordinal),
    CHECK((state = 'accepted') = (accepted_record_id IS NOT NULL)),
    CHECK((state IN ('accepted', 'rejected')) = (decided_at IS NOT NULL)),
    CHECK((state = 'rejected') = (rejection_reason IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_canon_candidates_reconciliation_state
ON canon_delta_candidates(reconciliation_id, state, ordinal, id);
CREATE INDEX IF NOT EXISTS idx_canon_candidates_project_kind
ON canon_delta_candidates(project_id, kind, state, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS canon_records (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN (
        'character_state', 'relationship', 'resource_state', 'location_state',
        'character_knowledge', 'future_knowledge', 'story_thread',
        'progression', 'timeline_event'
    )),
    subject_key TEXT NOT NULL CHECK(length(subject_key) BETWEEN 1 AND 240),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active', 'deleted')),
    source_candidate_id TEXT
        REFERENCES canon_delta_candidates(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_records_active_subject
ON canon_records(project_id, kind, subject_key) WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_canon_records_project_kind
ON canon_records(project_id, kind, state, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS author_preference_candidates (
    id TEXT PRIMARY KEY,
    reconciliation_id TEXT NOT NULL
        REFERENCES canon_reconciliations(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('project', 'genre', 'chapter')),
    scope_value TEXT NOT NULL CHECK(length(scope_value) BETWEEN 1 AND 200),
    dimension TEXT NOT NULL CHECK(dimension IN (
        'pacing', 'paragraphing', 'dialogue_density', 'narrative_distance',
        'tension', 'sentence_style'
    )),
    compact_rule TEXT NOT NULL CHECK(length(compact_rule) BETWEEN 1 AND 500),
    rule_sha256 TEXT NOT NULL CHECK(length(rule_sha256) = 64),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    comparison_metrics_json TEXT NOT NULL CHECK(json_valid(comparison_metrics_json)),
    source_writing_outcome_id TEXT NOT NULL
        REFERENCES chapter_writing_outcomes(id) ON DELETE RESTRICT,
    source_candidate_version_id TEXT NOT NULL
        REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    candidate_content_sha256 TEXT NOT NULL CHECK(length(candidate_content_sha256) = 64),
    final_content_sha256 TEXT NOT NULL CHECK(length(final_content_sha256) = 64),
    state TEXT NOT NULL DEFAULT 'candidate'
        CHECK(state IN ('candidate', 'confirmed', 'rejected', 'stale')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    rejection_reason TEXT CHECK(
        rejection_reason IS NULL OR length(rejection_reason) BETWEEN 1 AND 1000
    ),
    confirmed_preference_id TEXT REFERENCES author_preferences(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(reconciliation_id, ordinal),
    CHECK((state = 'confirmed') = (confirmed_preference_id IS NOT NULL)),
    CHECK((state IN ('confirmed', 'rejected')) = (decided_at IS NOT NULL)),
    CHECK((state = 'rejected') = (rejection_reason IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_preference_candidates_reconciliation_state
ON author_preference_candidates(reconciliation_id, state, ordinal, id);

CREATE TABLE IF NOT EXISTS author_preferences (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('project', 'genre', 'chapter')),
    scope_value TEXT NOT NULL CHECK(length(scope_value) BETWEEN 1 AND 200),
    dimension TEXT NOT NULL CHECK(dimension IN (
        'pacing', 'paragraphing', 'dialogue_density', 'narrative_distance',
        'tension', 'sentence_style'
    )),
    compact_rule TEXT NOT NULL CHECK(length(compact_rule) BETWEEN 1 AND 500),
    rule_sha256 TEXT NOT NULL CHECK(length(rule_sha256) = 64),
    fingerprint_sha256 TEXT NOT NULL CHECK(length(fingerprint_sha256) = 64),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK(occurrence_count > 0),
    state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active', 'deleted')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_author_preferences_active_fingerprint
ON author_preferences(project_id, fingerprint_sha256) WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_author_preferences_project_scope
ON author_preferences(project_id, state, scope_kind, dimension, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS author_preference_sources (
    preference_id TEXT NOT NULL REFERENCES author_preferences(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL UNIQUE
        REFERENCES author_preference_candidates(id) ON DELETE RESTRICT,
    source_writing_outcome_id TEXT NOT NULL
        REFERENCES chapter_writing_outcomes(id) ON DELETE RESTRICT,
    source_candidate_version_id TEXT NOT NULL
        REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    approval_id TEXT NOT NULL REFERENCES chapter_approvals(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(preference_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_author_preference_sources_preference
ON author_preference_sources(preference_id, created_at, candidate_id);

CREATE TABLE IF NOT EXISTS canon_decision_batches (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    reconciliation_id TEXT NOT NULL
        REFERENCES canon_reconciliations(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 8 AND 160),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_canon_decision_batches_reconciliation
ON canon_decision_batches(reconciliation_id, created_at, id);

CREATE TABLE IF NOT EXISTS rolling_plan_replenishments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    reconciliation_id TEXT NOT NULL UNIQUE
        REFERENCES canon_reconciliations(id) ON DELETE CASCADE,
    source_decision_batch_id TEXT
        REFERENCES canon_decision_batches(id) ON DELETE SET NULL,
    source_chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    source_canon_record_ids_json TEXT NOT NULL CHECK(json_valid(source_canon_record_ids_json)),
    state TEXT NOT NULL CHECK(state IN (
        'candidate', 'adopted', 'rejected', 'stale', 'not_needed'
    )),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    volume_plan_id TEXT REFERENCES volume_plans(id) ON DELETE RESTRICT,
    base_blueprint_id TEXT REFERENCES book_blueprints(id) ON DELETE SET NULL,
    base_blueprint_revision INTEGER CHECK(
        base_blueprint_revision IS NULL OR base_blueprint_revision >= 0
    ),
    base_blueprint_content_sha256 TEXT CHECK(
        base_blueprint_content_sha256 IS NULL
        OR length(base_blueprint_content_sha256) = 64
    ),
    protected_chapter_numbers_json TEXT NOT NULL DEFAULT '[]' CHECK(
        json_valid(protected_chapter_numbers_json)
    ),
    plans_json TEXT NOT NULL CHECK(json_valid(plans_json)),
    plans_sha256 TEXT NOT NULL CHECK(length(plans_sha256) = 64),
    blocked_reason TEXT CHECK(blocked_reason IS NULL OR length(blocked_reason) <= 500),
    adoption_idempotency_key TEXT CHECK(
        adoption_idempotency_key IS NULL
        OR length(adoption_idempotency_key) BETWEEN 8 AND 160
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    CHECK(
        (base_blueprint_id IS NULL AND base_blueprint_revision IS NULL
            AND base_blueprint_content_sha256 IS NULL)
        OR
        (base_blueprint_id IS NOT NULL AND base_blueprint_revision IS NOT NULL
            AND base_blueprint_content_sha256 IS NOT NULL)
    ),
    CHECK((state IN ('adopted', 'rejected')) = (decided_at IS NOT NULL)),
    CHECK((state = 'adopted') = (adoption_idempotency_key IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_rolling_replenishments_project_state
ON rolling_plan_replenishments(project_id, state, updated_at DESC, id DESC);
"""
