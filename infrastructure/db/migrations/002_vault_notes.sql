CREATE TABLE IF NOT EXISTS vault_notes (
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

CREATE UNIQUE INDEX IF NOT EXISTS vault_notes_employee_source_path
    ON vault_notes(employee_id, source, vault_path);
CREATE INDEX IF NOT EXISTS vault_notes_employee_id
    ON vault_notes(employee_id);

ALTER TABLE vault_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_notes FORCE ROW LEVEL SECURITY;

CREATE POLICY vault_notes_isolation ON vault_notes
    USING (
        source = 'shared'
        OR employee_id = current_setting('app.current_employee_id', true)::uuid
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON vault_notes TO svapp;
