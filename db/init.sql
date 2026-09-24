-- pgvector extension for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Semantic search embeddings for KB entities (tables, transforms, glossary)
-- Populated during KB reload from S3 or startup
CREATE TABLE IF NOT EXISTS kb_embeddings (
    id              BIGSERIAL PRIMARY KEY,
    entity_type     TEXT NOT NULL,              -- 'table', 'transform', 'glossary'
    entity_key      TEXT NOT NULL,              -- schema.table, dag_id, or term_key
    content_text    TEXT NOT NULL,              -- the text that was embedded
    embedding       vector(1024),               -- Bedrock Titan Text Embeddings v2
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(entity_type, entity_key)
);

CREATE INDEX IF NOT EXISTS idx_kb_embeddings_type ON kb_embeddings(entity_type);
-- HNSW index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_kb_embeddings_vector ON kb_embeddings
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS usage_events (
    id                          BIGSERIAL PRIMARY KEY,
    user_id                     TEXT NOT NULL DEFAULT 'local-dev',
    capability                  TEXT NOT NULL,
    pillar                      TEXT,
    environment                 TEXT,
    input_tokens                INTEGER DEFAULT 0,
    output_tokens               INTEGER DEFAULT 0,
    estimated_cost              NUMERIC(10,6) DEFAULT 0,
    redshift_query_duration_ms  INTEGER,
    query_text                  TEXT,
    model                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_usage_events_created ON usage_events(created_at);
CREATE INDEX idx_usage_events_capability ON usage_events(capability);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'local-dev',
    pillar      TEXT,
    title       TEXT,
    messages    JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chat_sessions_user ON chat_sessions(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id         TEXT PRIMARY KEY,
    session_id      TEXT,
    persona         TEXT NOT NULL DEFAULT 'engineer',
    system_prompt   TEXT NOT NULL DEFAULT '',
    user_context    TEXT NOT NULL DEFAULT '',
    user_context_optimized TEXT NOT NULL DEFAULT '',
    redshift_config JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table operations: ANALYZE, PROFILE, classification tracking
CREATE TABLE IF NOT EXISTS table_registry (
    id                  BIGSERIAL PRIMARY KEY,
    schema_name         TEXT NOT NULL,
    table_name          TEXT NOT NULL,
    database            TEXT NOT NULL DEFAULT 'dw',
    table_type          TEXT,                              -- 'fact', 'dimension', 'staging', 'view', null=unclassified
    table_type_auto     TEXT,                              -- auto-classified type
    table_type_manual   TEXT,                              -- manual override
    row_count           BIGINT,
    size_mb             NUMERIC(12,2),
    last_analyzed_at    TIMESTAMPTZ,
    last_profiled_at    TIMESTAMPTZ,
    analyze_enabled     BOOLEAN NOT NULL DEFAULT false,
    profile_enabled     BOOLEAN NOT NULL DEFAULT false,
    profile_data        JSONB,                             -- min/max/null/cardinality per column
    metadata            JSONB NOT NULL DEFAULT '{}',       -- distkey, sortkey, etc.
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(schema_name, table_name, database)
);

CREATE INDEX IF NOT EXISTS idx_table_registry_schema ON table_registry(schema_name, table_name);

-- Job queue for sequential table operations
CREATE TABLE IF NOT EXISTS table_ops_jobs (
    id              BIGSERIAL PRIMARY KEY,
    operation       TEXT NOT NULL,                         -- 'analyze', 'profile'
    schema_name     TEXT NOT NULL,
    table_name      TEXT NOT NULL,
    database        TEXT NOT NULL DEFAULT 'dw',
    environment     TEXT NOT NULL DEFAULT 'prd',           -- analyze=prd, profile=np
    status          TEXT NOT NULL DEFAULT 'queued',        -- queued, running, completed, failed, killed, timeout
    timeout_seconds INTEGER NOT NULL DEFAULT 120,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_seconds NUMERIC(10,2),
    result          JSONB,                                 -- output data or error
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_table_ops_jobs_status ON table_ops_jobs(status, created_at);

-- Schedules for recurring table operations
CREATE TABLE IF NOT EXISTS table_ops_schedules (
    id              BIGSERIAL PRIMARY KEY,
    operation       TEXT NOT NULL,                         -- 'analyze', 'profile'
    schema_name     TEXT,                                  -- null = all tables with X_enabled
    table_name      TEXT,
    cron_expression TEXT NOT NULL,                         -- e.g. '0 2 * * 0' (Sunday 2am)
    timeout_seconds INTEGER NOT NULL DEFAULT 120,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kb_builds (
    id              BIGSERIAL PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'running',  -- queued, running, success, error
    triggered_by    TEXT DEFAULT 'manual',
    duration_seconds NUMERIC(10,2),
    sources         JSONB DEFAULT '{}',               -- which sources were included (mwaa, repo, redshift)
    stats           JSONB DEFAULT '{}',               -- table_count, transform_count, etc.
    diff            JSONB DEFAULT '{}',               -- added/removed/changed per category
    snapshot        JSONB DEFAULT '{}',               -- lightweight: table names, transform IDs, glossary terms
    progress        JSONB DEFAULT '{}',               -- live build progress (phase, logs, errors) for job mode
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_builds_created ON kb_builds(created_at DESC);

CREATE TABLE IF NOT EXISTS feedback_tickets (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'open',       -- open, in_progress, resolved, closed
    priority        TEXT NOT NULL DEFAULT 'medium',     -- low, medium, high
    category        TEXT NOT NULL DEFAULT 'chat',       -- chat, data, glossary, pipeline, other
    created_by      TEXT NOT NULL,
    assigned_to     TEXT,                               -- user email, defaults to admin
    chat_session_id TEXT,                               -- link to chat for context
    chat_messages   JSONB,                              -- snapshot of relevant messages
    resolution      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_tickets_status ON feedback_tickets(status);
CREATE INDEX IF NOT EXISTS idx_feedback_tickets_assigned ON feedback_tickets(assigned_to);

CREATE TABLE IF NOT EXISTS kb_repos (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    token       TEXT,
    branch      TEXT NOT NULL DEFAULT 'main',
    clone_path  TEXT,
    is_active   BOOLEAN DEFAULT true,
    parse_all   BOOLEAN DEFAULT false,  -- true = parse all files, false = YAML+SQL only
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    password_hash   TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL DEFAULT 'viewer',
    pillar          TEXT,
    team            TEXT,
    is_active       BOOLEAN DEFAULT true,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    git_name        TEXT,
    git_email       TEXT,
    github_token    TEXT
);

-- Seed admin account (first login with any password sets it)
INSERT INTO users (email, name, role) VALUES ('admin@example.com', 'Sri Maru', 'admin')
ON CONFLICT (email) DO NOTHING;

CREATE TABLE IF NOT EXISTS scheduled_reports (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL,
    chat_question   TEXT NOT NULL,
    cron_expression TEXT NOT NULL DEFAULT '0 7 * * *',
    context         TEXT DEFAULT '',
    pillar          TEXT,
    environment     TEXT DEFAULT 'np',
    enabled         BOOLEAN DEFAULT true,
    last_run_at     TIMESTAMPTZ,
    last_output     TEXT,
    last_status     TEXT DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    type            TEXT NOT NULL,
    title           TEXT NOT NULL,
    message         TEXT,
    link            TEXT,
    is_read         BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduled_reports_enabled ON scheduled_reports(enabled, cron_expression);

CREATE TABLE IF NOT EXISTS glossary_feedback (
    id              BIGSERIAL PRIMARY KEY,
    term            TEXT NOT NULL,
    correction      TEXT NOT NULL,
    submitted_by    TEXT NOT NULL DEFAULT 'local-dev',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Credential cache: SSO tokens, GitHub token, DOMO creds, Statsig key, KB S3 config
CREATE TABLE IF NOT EXISTS credential_cache (
    session_id      TEXT NOT NULL,
    environment     TEXT NOT NULL,
    cred_type       TEXT NOT NULL,
    data            JSONB NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, environment, cred_type)
);

CREATE INDEX IF NOT EXISTS idx_credential_cache_expires ON credential_cache(expires_at);

-- Glossary entries: PR-style review workflow (draft → in_review → approved → merged)
CREATE TABLE IF NOT EXISTS glossary_entries (
    id              BIGSERIAL PRIMARY KEY,
    term_key        TEXT NOT NULL UNIQUE,
    term            TEXT NOT NULL,
    definition      TEXT NOT NULL,
    formula         TEXT,
    source_tables   JSONB DEFAULT '[]',
    dimensions      JSONB DEFAULT '[]',
    filters         TEXT,
    dag             TEXT,
    domo_dataset_id TEXT,
    view_name       TEXT,
    confidence      NUMERIC(3,2) DEFAULT 0.5,
    status          TEXT NOT NULL DEFAULT 'draft',
    expert_notes    TEXT,
    auto_generated  BOOLEAN DEFAULT false,
    sql_hash        TEXT,
    sources         JSONB DEFAULT '[]',
    created_by      TEXT,
    created_by_type TEXT DEFAULT 'system',
    workflow_state  TEXT DEFAULT 'draft',
    assigned_to     TEXT,
    assigned_at     TIMESTAMPTZ,
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_glossary_entries_status ON glossary_entries(status);
CREATE INDEX IF NOT EXISTS idx_glossary_entries_term ON glossary_entries(term);

-- Glossary comments: discussion thread per entry
CREATE TABLE IF NOT EXISTS glossary_comments (
    id              BIGSERIAL PRIMARY KEY,
    entry_id        BIGINT NOT NULL REFERENCES glossary_entries(id) ON DELETE CASCADE,
    author          TEXT NOT NULL,
    comment         TEXT NOT NULL,
    action          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_glossary_comments_entry ON glossary_comments(entry_id);

-- Glossary history: audit trail of changes
CREATE TABLE IF NOT EXISTS glossary_history (
    id              BIGSERIAL PRIMARY KEY,
    entry_id        BIGINT NOT NULL REFERENCES glossary_entries(id) ON DELETE CASCADE,
    action          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_glossary_history_entry ON glossary_history(entry_id);

-- Redshift connections: direct credential storage
CREATE TABLE IF NOT EXISTS redshift_connections (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    host            TEXT NOT NULL,
    port            INTEGER NOT NULL DEFAULT 5439,
    database        TEXT NOT NULL,
    username        TEXT NOT NULL,
    password        TEXT NOT NULL,
    environment     TEXT NOT NULL DEFAULT 'np',
    is_default      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Report execution history
CREATE TABLE IF NOT EXISTS report_executions (
    id              BIGSERIAL PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES scheduled_reports(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    output          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_report_executions_report ON report_executions(report_id);

-- Saved/shared queries: team query library
CREATE TABLE IF NOT EXISTS saved_queries (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    sql             TEXT NOT NULL,
    environment     TEXT DEFAULT 'np',
    tags            TEXT[] DEFAULT '{}',
    pillar          TEXT,
    created_by      TEXT NOT NULL,
    created_by_name TEXT,
    is_public       BOOLEAN DEFAULT true,
    use_count       INTEGER DEFAULT 0,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_queries_public ON saved_queries(is_public, use_count DESC);

-- Schedule runner config: KB build scheduler state
CREATE TABLE IF NOT EXISTS schedule_runner_config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Agent prompt overrides: custom agent personas from UI
CREATE TABLE IF NOT EXISTS agent_prompt_overrides (
    agent_id        TEXT PRIMARY KEY,
    prompt          TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Registration requests: user access requests from login page
CREATE TABLE IF NOT EXISTS registration_requests (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    team            TEXT,
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    reviewed_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_registration_requests_status ON registration_requests(status);

-- Lineage cache — persists lineage from S3/KB builds so it survives container restarts
CREATE TABLE IF NOT EXISTS lineage_cache (
    table_key       TEXT PRIMARY KEY,
    upstream        JSONB NOT NULL DEFAULT '[]',
    downstream      JSONB NOT NULL DEFAULT '[]',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lineage_cache_updated ON lineage_cache(updated_at);

-- Comments thread per task (feedback_tickets). Mirrors glossary_comments shape.
CREATE TABLE IF NOT EXISTS feedback_comments (
    id          BIGSERIAL PRIMARY KEY,
    ticket_id   BIGINT NOT NULL REFERENCES feedback_tickets(id) ON DELETE CASCADE,
    author      TEXT NOT NULL,
    comment     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_comments_ticket ON feedback_comments(ticket_id, created_at);

-- Table ownership: primary/secondary owner + business area per warehouse table/view.
-- Kept separate from table_registry (profiler-owned) so ownership works even if
-- a table was never profiled. Owner/business_area stored as text — dropdown
-- options are computed at read time from users table + distinct values + seed lists.
CREATE TABLE IF NOT EXISTS table_ownership (
    id                  BIGSERIAL PRIMARY KEY,
    database            TEXT NOT NULL,
    schema_name         TEXT NOT NULL,
    table_name          TEXT NOT NULL,
    primary_owner       TEXT,
    secondary_owner     TEXT,
    business_area       TEXT,
    updated_by_user_id  BIGINT REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(database, schema_name, table_name)
);

CREATE INDEX IF NOT EXISTS idx_table_ownership_db_schema ON table_ownership(database, schema_name);

-- Admin-mediated password resets. User submits via "Forgot password?", admin
-- approves and a temp password is generated server-side. No email tokens —
-- the admin shares the temp password out of band (Slack, etc.).
CREATE TABLE IF NOT EXISTS password_reset_requests (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    reviewed_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_password_reset_requests_status ON password_reset_requests(status);
CREATE INDEX IF NOT EXISTS idx_password_reset_requests_email ON password_reset_requests(email);
