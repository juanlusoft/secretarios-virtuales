CREATE TABLE IF NOT EXISTS facts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS facts_employee_key
    ON facts(employee_id, key);

CREATE INDEX IF NOT EXISTS facts_employee_category
    ON facts(employee_id, category);

ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE facts FORCE ROW LEVEL SECURITY;

CREATE POLICY facts_isolation ON facts
    USING (employee_id = current_setting('app.current_employee_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON facts TO svapp;
