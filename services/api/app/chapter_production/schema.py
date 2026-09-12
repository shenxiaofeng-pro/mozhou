"""Additive schema for the M33 ChapterProduction aggregate."""

CHAPTER_PRODUCTION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS chapter_productions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    base_chapter_revision INTEGER NOT NULL CHECK(base_chapter_revision >= 0),
    base_chapter_content_sha256 TEXT NOT NULL CHECK(length(base_chapter_content_sha256) = 64),
    state TEXT NOT NULL CHECK(state IN (
        'created', 'outline_ready', 'preflight_blocked', 'draft_ready',
        'candidate_ready', 'reviewed', 'adopted', 'rejected'
    )),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    current_outline_candidate_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapter_productions_chapter_created
ON chapter_productions(chapter_id, created_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_productions_open_base
ON chapter_productions(chapter_id, base_chapter_revision, base_chapter_content_sha256)
WHERE state NOT IN ('adopted', 'rejected');

CREATE TABLE IF NOT EXISTS chapter_production_events (
    id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL REFERENCES chapter_productions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(length(event_type) BETWEEN 1 AND 80),
    from_state TEXT,
    to_state TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json)),
    created_at TEXT NOT NULL,
    UNIQUE(production_id, sequence)
);

CREATE TABLE IF NOT EXISTS chapter_outline_candidates (
    id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL REFERENCES chapter_productions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 120),
    state TEXT NOT NULL CHECK(state IN ('available', 'adopted', 'rejected')),
    current_revision INTEGER NOT NULL CHECK(current_revision >= 0),
    current_content_sha256 TEXT NOT NULL CHECK(length(current_content_sha256) = 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(production_id, ordinal)
);

CREATE TABLE IF NOT EXISTS chapter_outline_candidate_versions (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES chapter_outline_candidates(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    operation TEXT NOT NULL CHECK(operation IN ('model_draft', 'author_edit')),
    parent_version_id TEXT REFERENCES chapter_outline_candidate_versions(id) ON DELETE RESTRICT,
    source_job_id TEXT UNIQUE REFERENCES jobs(id) ON DELETE SET NULL,
    context_purpose TEXT CHECK(context_purpose IS NULL OR context_purpose = 'brief'),
    context_packet_id TEXT,
    context_packet_sha256 TEXT CHECK(context_packet_sha256 IS NULL OR length(context_packet_sha256) = 64),
    context_dependency_fingerprint_sha256 TEXT CHECK(
        context_dependency_fingerprint_sha256 IS NULL OR length(context_dependency_fingerprint_sha256) = 64
    ),
    context_compiler_version TEXT,
    profile_fingerprint_sha256 TEXT CHECK(
        profile_fingerprint_sha256 IS NULL OR length(profile_fingerprint_sha256) = 64
    ),
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(candidate_id, revision),
    CHECK(
        (operation = 'author_edit' AND context_purpose IS NULL AND context_packet_id IS NULL
            AND context_packet_sha256 IS NULL AND context_dependency_fingerprint_sha256 IS NULL
            AND context_compiler_version IS NULL AND provider IS NULL AND model IS NULL
            AND prompt_version IS NULL)
        OR
        (operation = 'model_draft' AND context_purpose = 'brief' AND context_packet_id IS NOT NULL
            AND context_packet_sha256 IS NOT NULL
            AND context_dependency_fingerprint_sha256 IS NOT NULL
            AND context_compiler_version IS NOT NULL AND provider IS NOT NULL
            AND model IS NOT NULL AND prompt_version IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS chapter_preflight_checks (
    id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL REFERENCES chapter_productions(id) ON DELETE CASCADE,
    outline_candidate_id TEXT NOT NULL REFERENCES chapter_outline_candidates(id) ON DELETE CASCADE,
    outline_version_id TEXT NOT NULL REFERENCES chapter_outline_candidate_versions(id) ON DELETE RESTRICT,
    outline_revision INTEGER NOT NULL CHECK(outline_revision >= 0),
    outline_content_sha256 TEXT NOT NULL CHECK(length(outline_content_sha256) = 64),
    reader_promise INTEGER NOT NULL CHECK(reader_promise IN (0, 1)),
    opening_hook INTEGER NOT NULL CHECK(opening_hook IN (0, 1)),
    state_change INTEGER NOT NULL CHECK(state_change IN (0, 1)),
    emotional_payoff INTEGER NOT NULL CHECK(emotional_payoff IN (0, 1)),
    ending_cliffhanger INTEGER NOT NULL CHECK(ending_cliffhanger IN (0, 1)),
    missing_fields_json TEXT NOT NULL CHECK(json_valid(missing_fields_json)),
    passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapter_preflight_production_created
ON chapter_preflight_checks(production_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS chapter_draft_candidates (
    id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL REFERENCES chapter_productions(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 120),
    state TEXT NOT NULL CHECK(state IN ('available', 'adopted', 'rejected')),
    source_outline_candidate_id TEXT REFERENCES chapter_outline_candidates(id) ON DELETE RESTRICT,
    source_outline_version_id TEXT REFERENCES chapter_outline_candidate_versions(id) ON DELETE RESTRICT,
    source_outline_revision INTEGER CHECK(source_outline_revision IS NULL OR source_outline_revision >= 0),
    source_outline_content_sha256 TEXT CHECK(
        source_outline_content_sha256 IS NULL OR length(source_outline_content_sha256) = 64
    ),
    current_revision INTEGER NOT NULL CHECK(current_revision >= 0),
    current_content_sha256 TEXT NOT NULL CHECK(length(current_content_sha256) = 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(
        (source_outline_candidate_id IS NULL AND source_outline_version_id IS NULL
            AND source_outline_revision IS NULL AND source_outline_content_sha256 IS NULL)
        OR
        (source_outline_candidate_id IS NOT NULL AND source_outline_version_id IS NOT NULL
            AND source_outline_revision IS NOT NULL AND source_outline_content_sha256 IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_chapter_draft_candidates_production_created
ON chapter_draft_candidates(production_id, created_at, id);

CREATE TABLE IF NOT EXISTS chapter_draft_candidate_versions (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES chapter_draft_candidates(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 2000000),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    operation TEXT NOT NULL CHECK(operation IN ('model_draft', 'author_edit', 'local_rewrite', 'undo', 'merge')),
    parent_version_id TEXT REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    restored_from_version_id TEXT REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    source_job_id TEXT UNIQUE REFERENCES jobs(id) ON DELETE SET NULL,
    context_purpose TEXT CHECK(context_purpose IS NULL OR context_purpose IN ('draft', 'candidate_review')),
    context_packet_id TEXT,
    context_packet_sha256 TEXT CHECK(context_packet_sha256 IS NULL OR length(context_packet_sha256) = 64),
    context_dependency_fingerprint_sha256 TEXT CHECK(
        context_dependency_fingerprint_sha256 IS NULL OR length(context_dependency_fingerprint_sha256) = 64
    ),
    context_compiler_version TEXT,
    profile_fingerprint_sha256 TEXT CHECK(
        profile_fingerprint_sha256 IS NULL OR length(profile_fingerprint_sha256) = 64
    ),
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    instruction TEXT NOT NULL DEFAULT '' CHECK(length(instruction) <= 2000),
    created_at TEXT NOT NULL,
    UNIQUE(candidate_id, revision),
    CHECK(
        (context_purpose IS NULL AND context_packet_id IS NULL AND context_packet_sha256 IS NULL
            AND context_dependency_fingerprint_sha256 IS NULL AND context_compiler_version IS NULL
            AND provider IS NULL AND model IS NULL AND prompt_version IS NULL)
        OR
        (context_purpose IS NOT NULL AND context_packet_id IS NOT NULL
            AND context_packet_sha256 IS NOT NULL
            AND context_dependency_fingerprint_sha256 IS NOT NULL
            AND context_compiler_version IS NOT NULL AND provider IS NOT NULL
            AND model IS NOT NULL AND prompt_version IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS chapter_draft_candidate_locks (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES chapter_draft_candidates(id) ON DELETE CASCADE,
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    locked_text TEXT NOT NULL CHECK(length(locked_text) BETWEEN 1 AND 200000),
    locked_text_sha256 TEXT NOT NULL CHECK(length(locked_text_sha256) = 64),
    created_from_version_id TEXT NOT NULL REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapter_candidate_locks_candidate_range
ON chapter_draft_candidate_locks(candidate_id, start_char, end_char, id);

CREATE TABLE IF NOT EXISTS chapter_candidate_reviews (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES chapter_draft_candidates(id) ON DELETE CASCADE,
    candidate_version_id TEXT NOT NULL REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    candidate_revision INTEGER NOT NULL CHECK(candidate_revision >= 0),
    candidate_content_sha256 TEXT NOT NULL CHECK(length(candidate_content_sha256) = 64),
    source_job_id TEXT UNIQUE REFERENCES jobs(id) ON DELETE SET NULL,
    context_purpose TEXT NOT NULL CHECK(context_purpose = 'candidate_review'),
    context_packet_id TEXT NOT NULL,
    context_packet_sha256 TEXT NOT NULL CHECK(length(context_packet_sha256) = 64),
    context_dependency_fingerprint_sha256 TEXT NOT NULL CHECK(length(context_dependency_fingerprint_sha256) = 64),
    context_compiler_version TEXT NOT NULL,
    profile_fingerprint_sha256 TEXT CHECK(
        profile_fingerprint_sha256 IS NULL OR length(profile_fingerprint_sha256) = 64
    ),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    findings_json TEXT NOT NULL CHECK(json_valid(findings_json)),
    created_at TEXT NOT NULL,
    UNIQUE(candidate_id, candidate_version_id)
);

CREATE TABLE IF NOT EXISTS chapter_candidate_merge_sources (
    result_candidate_id TEXT NOT NULL REFERENCES chapter_draft_candidates(id) ON DELETE CASCADE,
    result_version_id TEXT NOT NULL REFERENCES chapter_draft_candidate_versions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    source_candidate_id TEXT NOT NULL REFERENCES chapter_draft_candidates(id) ON DELETE RESTRICT,
    source_version_id TEXT NOT NULL REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    source_revision INTEGER NOT NULL CHECK(source_revision >= 0),
    source_content_sha256 TEXT NOT NULL CHECK(length(source_content_sha256) = 64),
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    selected_text_sha256 TEXT NOT NULL CHECK(length(selected_text_sha256) = 64),
    PRIMARY KEY(result_candidate_id, ordinal),
    UNIQUE(result_candidate_id, source_candidate_id, source_version_id)
);

CREATE TABLE IF NOT EXISTS chapter_writing_outcomes (
    id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL REFERENCES chapter_productions(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES chapter_draft_candidates(id) ON DELETE RESTRICT,
    candidate_version_id TEXT NOT NULL REFERENCES chapter_draft_candidate_versions(id) ON DELETE RESTRICT,
    candidate_revision INTEGER NOT NULL CHECK(candidate_revision >= 0),
    candidate_content_sha256 TEXT NOT NULL CHECK(length(candidate_content_sha256) = 64),
    source_outline_candidate_id TEXT REFERENCES chapter_outline_candidates(id) ON DELETE RESTRICT,
    source_outline_version_id TEXT REFERENCES chapter_outline_candidate_versions(id) ON DELETE RESTRICT,
    source_outline_revision INTEGER CHECK(source_outline_revision IS NULL OR source_outline_revision >= 0),
    source_outline_content_sha256 TEXT CHECK(
        source_outline_content_sha256 IS NULL OR length(source_outline_content_sha256) = 64
    ),
    decision TEXT NOT NULL CHECK(decision IN ('adopted', 'rejected')),
    adoption_mode TEXT CHECK(adoption_mode IS NULL OR adoption_mode IN ('whole', 'partial')),
    base_chapter_revision INTEGER NOT NULL CHECK(base_chapter_revision >= 0),
    base_chapter_content_sha256 TEXT NOT NULL CHECK(length(base_chapter_content_sha256) = 64),
    final_chapter_revision INTEGER NOT NULL CHECK(final_chapter_revision >= 0),
    final_chapter_content_sha256 TEXT NOT NULL CHECK(length(final_chapter_content_sha256) = 64),
    final_chapter_status TEXT NOT NULL CHECK(final_chapter_status IN ('planned', 'drafted', 'reviewing', 'approved')),
    chapter_version_id TEXT REFERENCES chapter_versions(id) ON DELETE RESTRICT,
    adoption_detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(adoption_detail_json)),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 8 AND 160),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    reason TEXT NOT NULL DEFAULT '' CHECK(length(reason) <= 1000),
    created_at TEXT NOT NULL,
    UNIQUE(production_id, idempotency_key),
    CHECK(
        (decision = 'adopted' AND adoption_mode IS NOT NULL AND chapter_version_id IS NOT NULL)
        OR (decision = 'rejected' AND adoption_mode IS NULL AND chapter_version_id IS NULL)
    ),
    CHECK(
        (source_outline_candidate_id IS NULL AND source_outline_version_id IS NULL
            AND source_outline_revision IS NULL AND source_outline_content_sha256 IS NULL)
        OR
        (source_outline_candidate_id IS NOT NULL AND source_outline_version_id IS NOT NULL
            AND source_outline_revision IS NOT NULL AND source_outline_content_sha256 IS NOT NULL)
    )
);
"""
