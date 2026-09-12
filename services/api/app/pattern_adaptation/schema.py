"""Additive M31 C+D schema introduced by schema version 27."""

PATTERN_ADAPTATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS writing_pattern_adaptation_proposals (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    profile_version_id TEXT NOT NULL
        REFERENCES writing_pattern_profile_versions(id) ON DELETE RESTRICT,
    profile_fingerprint_sha256 TEXT NOT NULL CHECK(length(profile_fingerprint_sha256) = 64),
    recipe_version_id TEXT NOT NULL
        REFERENCES writing_pattern_recipe_versions(id) ON DELETE RESTRICT,
    recipe_content_sha256 TEXT NOT NULL CHECK(length(recipe_content_sha256) = 64),
    topic_decision_version_id TEXT NOT NULL
        REFERENCES topic_decision_versions(id) ON DELETE RESTRICT,
    topic_revision INTEGER NOT NULL CHECK(topic_revision > 0),
    topic_content_sha256 TEXT NOT NULL CHECK(length(topic_content_sha256) = 64),
    base_blueprint_id TEXT,
    base_blueprint_revision INTEGER CHECK(base_blueprint_revision IS NULL OR base_blueprint_revision >= 0),
    base_blueprint_content_sha256 TEXT
        CHECK(base_blueprint_content_sha256 IS NULL OR length(base_blueprint_content_sha256) = 64),
    lock_snapshot_json TEXT NOT NULL CHECK(json_valid(lock_snapshot_json)),
    lock_snapshot_sha256 TEXT NOT NULL CHECK(length(lock_snapshot_sha256) = 64),
    dependency_fingerprint_sha256 TEXT NOT NULL CHECK(length(dependency_fingerprint_sha256) = 64),
    safe_context_sha256 TEXT NOT NULL CHECK(length(safe_context_sha256) = 64),
    provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 40),
    provider_profile_id TEXT,
    provider_profile_revision INTEGER
        CHECK(provider_profile_revision IS NULL OR provider_profile_revision >= 0),
    model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
    input_cost_microusd_per_million INTEGER
        CHECK(input_cost_microusd_per_million IS NULL OR input_cost_microusd_per_million >= 0),
    output_cost_microusd_per_million INTEGER
        CHECK(output_cost_microusd_per_million IS NULL OR output_cost_microusd_per_million >= 0),
    prompt_version TEXT NOT NULL CHECK(length(prompt_version) BETWEEN 1 AND 100),
    estimated_input_tokens INTEGER NOT NULL CHECK(estimated_input_tokens >= 0),
    estimated_output_tokens INTEGER NOT NULL CHECK(estimated_output_tokens >= 0),
    estimated_cost_microusd INTEGER
        CHECK(estimated_cost_microusd IS NULL OR estimated_cost_microusd >= 0),
    cost_status TEXT NOT NULL CHECK(cost_status IN ('free', 'known', 'unavailable')),
    result_state TEXT NOT NULL CHECK(result_state IN ('pending', 'available', 'stale', 'invalid')),
    stale_reason TEXT CHECK(stale_reason IS NULL OR length(stale_reason) <= 200),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK((base_blueprint_revision IS NULL) = (base_blueprint_content_sha256 IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_pattern_adaptation_proposals_project_created
ON writing_pattern_adaptation_proposals(project_id, created_at DESC, id);

CREATE TABLE IF NOT EXISTS writing_pattern_adaptation_candidates (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL
        REFERENCES writing_pattern_adaptation_proposals(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 3),
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 80),
    why_distinct TEXT NOT NULL CHECK(length(why_distinct) BETWEEN 1 AND 800),
    distinct_axes_json TEXT NOT NULL CHECK(json_valid(distinct_axes_json)),
    risk_hypotheses_json TEXT NOT NULL CHECK(json_valid(risk_hypotheses_json)),
    current_revision INTEGER NOT NULL CHECK(current_revision >= 0),
    current_content_sha256 TEXT NOT NULL CHECK(length(current_content_sha256) = 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(proposal_id, ordinal)
);

CREATE TABLE IF NOT EXISTS writing_pattern_adaptation_candidate_versions (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL
        REFERENCES writing_pattern_adaptation_candidates(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    blueprint_json TEXT NOT NULL CHECK(json_valid(blueprint_json)),
    key_scene_sequence_json TEXT NOT NULL CHECK(json_valid(key_scene_sequence_json)),
    transformation_notes_json TEXT NOT NULL CHECK(json_valid(transformation_notes_json)),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    changed_fields_json TEXT NOT NULL CHECK(json_valid(changed_fields_json)),
    source TEXT NOT NULL CHECK(source IN ('model', 'author_edit')),
    created_at TEXT NOT NULL,
    UNIQUE(candidate_id, revision),
    UNIQUE(candidate_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_pattern_adaptation_candidate_versions_candidate
ON writing_pattern_adaptation_candidate_versions(candidate_id, revision DESC);

CREATE TABLE IF NOT EXISTS writing_pattern_adoptions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    proposal_id TEXT NOT NULL
        REFERENCES writing_pattern_adaptation_proposals(id) ON DELETE RESTRICT,
    candidate_id TEXT NOT NULL
        REFERENCES writing_pattern_adaptation_candidates(id) ON DELETE RESTRICT,
    candidate_version_id TEXT NOT NULL
        REFERENCES writing_pattern_adaptation_candidate_versions(id) ON DELETE RESTRICT,
    blueprint_id TEXT NOT NULL REFERENCES book_blueprints(id) ON DELETE RESTRICT,
    blueprint_revision INTEGER NOT NULL CHECK(blueprint_revision >= 0),
    blueprint_content_sha256 TEXT NOT NULL CHECK(length(blueprint_content_sha256) = 64),
    profile_fingerprint_sha256 TEXT NOT NULL CHECK(length(profile_fingerprint_sha256) = 64),
    recipe_content_sha256 TEXT NOT NULL CHECK(length(recipe_content_sha256) = 64),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 8 AND 160),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, idempotency_key),
    UNIQUE(project_id, blueprint_revision)
);

CREATE INDEX IF NOT EXISTS idx_writing_pattern_adoptions_project_created
ON writing_pattern_adoptions(project_id, created_at DESC, id);

CREATE TABLE IF NOT EXISTS writing_pattern_originality_reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    adoption_id TEXT NOT NULL REFERENCES writing_pattern_adoptions(id) ON DELETE RESTRICT,
    profile_fingerprint_sha256 TEXT NOT NULL CHECK(length(profile_fingerprint_sha256) = 64),
    recipe_content_sha256 TEXT NOT NULL CHECK(length(recipe_content_sha256) = 64),
    blueprint_id TEXT NOT NULL REFERENCES book_blueprints(id) ON DELETE RESTRICT,
    blueprint_revision INTEGER NOT NULL CHECK(blueprint_revision >= 0),
    blueprint_content_sha256 TEXT NOT NULL CHECK(length(blueprint_content_sha256) = 64),
    candidate_version_id TEXT NOT NULL
        REFERENCES writing_pattern_adaptation_candidate_versions(id) ON DELETE RESTRICT,
    candidate_content_sha256 TEXT NOT NULL CHECK(length(candidate_content_sha256) = 64),
    risk_level TEXT NOT NULL CHECK(risk_level IN ('low', 'medium', 'high')),
    status TEXT NOT NULL CHECK(status IN ('blocked', 'review_required', 'passed')),
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
    threshold_version TEXT NOT NULL CHECK(length(threshold_version) BETWEEN 1 AND 80),
    input_sha256 TEXT NOT NULL CHECK(length(input_sha256) = 64),
    source_availability TEXT NOT NULL CHECK(source_availability IN ('source_verified', 'abstract_only')),
    viewed_at TEXT,
    acknowledged_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(adoption_id, threshold_version, input_sha256)
);

CREATE INDEX IF NOT EXISTS idx_pattern_originality_reports_project_created
ON writing_pattern_originality_reports(project_id, created_at DESC, id);

CREATE TABLE IF NOT EXISTS writing_pattern_originality_findings (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL
        REFERENCES writing_pattern_originality_reports(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    signal TEXT NOT NULL CHECK(length(signal) BETWEEN 1 AND 80),
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
    summary TEXT NOT NULL CHECK(length(summary) BETWEEN 1 AND 500),
    source_fingerprint_sha256 TEXT NOT NULL CHECK(length(source_fingerprint_sha256) = 64),
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256) = 64),
    UNIQUE(report_id, ordinal)
);
"""
