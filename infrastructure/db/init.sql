CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE employees (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    telegram_chat_id TEXT UNIQUE,
    is_orchestrator BOOLEAN NOT NULL DEFAULT false,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'telegram',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON conversations(employee_id, created_at DESC);

CREATE TABLE documents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    filepath     TEXT NOT NULL,
    content_text TEXT,
    embedding    vector,
    mime_type    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON documents(employee_id);

CREATE TABLE credentials (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    service_type TEXT NOT NULL,
    encrypted    TEXT NOT NULL,
    UNIQUE(employee_id, service_type)
);

CREATE TABLE tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON tasks(employee_id, status);

-- Row Level Security
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents     ENABLE ROW LEVEL SECURITY;
ALTER TABLE credentials   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks         ENABLE ROW LEVEL SECURITY;

CREATE POLICY isolate ON conversations
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);
CREATE POLICY isolate ON documents
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);
CREATE POLICY isolate ON credentials
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);
CREATE POLICY isolate ON tasks
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);

-- Application role (non-superuser, subject to RLS)
CREATE ROLE svapp LOGIN;
GRANT CONNECT ON DATABASE secretarios TO svapp;
GRANT USAGE ON SCHEMA public TO svapp;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO svapp;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO svapp;

-- Force RLS even for table owners
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
ALTER TABLE documents     FORCE ROW LEVEL SECURITY;
ALTER TABLE credentials   FORCE ROW LEVEL SECURITY;
ALTER TABLE tasks         FORCE ROW LEVEL SECURITY;

CREATE TABLE vault_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    source       TEXT NOT NULL CHECK (source IN ('shared', 'personal')),
    vault_path   TEXT NOT NULL,
    title        TEXT,
    tags         TEXT[],
    content_text TEXT,
    embedding    vector(1024),
    modified_at  TIMESTAMPTZ NOT NULL,
    indexed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX ON vault_notes(employee_id, source, vault_path);
CREATE INDEX ON vault_notes(employee_id);

ALTER TABLE vault_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_notes FORCE ROW LEVEL SECURITY;

CREATE POLICY vault_notes_isolation ON vault_notes
    USING (
        source = 'shared'
        OR employee_id = current_setting('app.current_employee_id', true)::uuid
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON vault_notes TO svapp;
