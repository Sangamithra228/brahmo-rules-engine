-- =====================================================================
-- BRAHMO Rules Engine - schema (PostgreSQL / Supabase)
-- Run this first, then seed.sql, then optionally rls_policies.sql.
-- =====================================================================

CREATE TABLE organizations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    segment     TEXT NOT NULL CHECK (segment IN ('hospital','law_firm','software')),
    config      JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- The org DAG. parent_ids is an ARRAY, which is what makes a node
-- multi-parent (Post-TKR Protocol belongs to Ortho AND Surgery).
CREATE TABLE hierarchy_levels (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL REFERENCES organizations(id),
    level_number  INTEGER NOT NULL CHECK (level_number BETWEEN 1 AND 15),
    level_name    TEXT NOT NULL,
    department    TEXT,
    parent_ids    TEXT[] DEFAULT '{}',
    zone          INTEGER NOT NULL DEFAULT 1 CHECK (zone IN (1,2,3)),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, level_number, department)
);

CREATE TABLE knowledge_nodes (
    id                 TEXT PRIMARY KEY,
    org_id             TEXT NOT NULL REFERENCES organizations(id),
    hierarchy_level_id TEXT NOT NULL REFERENCES hierarchy_levels(id),
    type               TEXT NOT NULL CHECK (type IN
                         ('CONSTRAINT','DECISION','ANTI_PATTERN','FACT')),
    title              TEXT NOT NULL,
    content            TEXT NOT NULL,
    importance         DECIMAL(3,2) NOT NULL CHECK (importance BETWEEN 0.0 AND 1.0),
    zone               INTEGER NOT NULL DEFAULT 1 CHECK (zone IN (1,2,3)),
    status             TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN
                         ('ACTIVE','REVIEW_REQUIRED','SUPERSEDED','EXPIRED','LEGAL_HOLD')),
    derivability_score DECIMAL(3,2) NOT NULL DEFAULT 0.0
                         CHECK (derivability_score BETWEEN 0.0 AND 1.0),
    compliance_tags    TEXT[] DEFAULT '{}',
    valid_until        TIMESTAMPTZ,
    superseded_by      TEXT REFERENCES knowledge_nodes(id),
    department         TEXT,
    -- Denormalised from hierarchy_levels.level_number. The permission check
    -- runs on every candidate row, so this saves a join per query; the graph
    -- is static, and the trigger below keeps it honest if that changes.
    hierarchy_level    INTEGER NOT NULL DEFAULT 0,
    created_by         TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE edges (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    source_id   TEXT NOT NULL REFERENCES knowledge_nodes(id),
    target_id   TEXT NOT NULL REFERENCES knowledge_nodes(id),
    edge_type   TEXT NOT NULL CHECK (edge_type IN
                  ('SUPPORTS','CONTRADICTS','SUPERSEDES','DERIVED_FROM','REQUIRES')),
    confidence  DECIMAL(3,2) DEFAULT 1.0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
    id                   TEXT PRIMARY KEY,
    org_id               TEXT NOT NULL REFERENCES organizations(id),
    name                 TEXT NOT NULL,
    role                 TEXT NOT NULL CHECK (role IN
                           ('ADMIN','HOD','EDITOR','VIEWER','QUALITY','AUDITOR')),
    department           TEXT NOT NULL,
    ceiling_level        INTEGER NOT NULL CHECK (ceiling_level BETWEEN 1 AND 15),
    write_ceiling        INTEGER,
    compliance_clearance TEXT[] DEFAULT '{}',
    status               TEXT DEFAULT 'ACTIVE',
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE audit_log (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    node_id    TEXT REFERENCES knowledge_nodes(id),
    action     TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    actor_id   TEXT REFERENCES users(id),
    org_id     TEXT NOT NULL,
    timestamp  TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- Indexes. Each one backs a specific predicate in the five-check pipeline,
-- which is why the pipeline stays flat as the graph grows.
-- ---------------------------------------------------------------------
CREATE INDEX idx_nodes_org        ON knowledge_nodes(org_id);              -- check 1
CREATE INDEX idx_nodes_compliance ON knowledge_nodes USING GIN(compliance_tags); -- check 2
CREATE INDEX idx_nodes_level      ON knowledge_nodes(hierarchy_level);     -- check 3
CREATE INDEX idx_nodes_status     ON knowledge_nodes(status);              -- check 4
CREATE INDEX idx_nodes_deriv      ON knowledge_nodes(derivability_score);  -- check 5
CREATE INDEX idx_nodes_zone       ON knowledge_nodes(zone);                -- zone 2 injection
CREATE INDEX idx_nodes_hierarchy  ON knowledge_nodes(hierarchy_level_id);  -- BFS level lookup
CREATE INDEX idx_nodes_dept       ON knowledge_nodes(department);
CREATE INDEX idx_edges_source     ON edges(source_id);
CREATE INDEX idx_edges_target     ON edges(target_id);
CREATE INDEX idx_hierarchy_org    ON hierarchy_levels(org_id);
CREATE INDEX idx_hierarchy_parent ON hierarchy_levels USING GIN(parent_ids);

-- Composite covering the hot path: org + tier + freshness + derivability.
CREATE INDEX idx_nodes_pipeline ON knowledge_nodes
    (org_id, hierarchy_level, status, derivability_score);

-- ---------------------------------------------------------------------
-- Keep the denormalised level in step with the DAG.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sync_hierarchy_level() RETURNS TRIGGER AS $$
BEGIN
    SELECT level_number INTO NEW.hierarchy_level
    FROM hierarchy_levels WHERE id = NEW.hierarchy_level_id;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_hierarchy_level
    BEFORE INSERT OR UPDATE OF hierarchy_level_id ON knowledge_nodes
    FOR EACH ROW EXECUTE FUNCTION sync_hierarchy_level();

-- ---------------------------------------------------------------------
-- Cycle guard. The graph is declared acyclic; enforce it on write rather
-- than discovering a loop at query time.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION reject_hierarchy_cycles() RETURNS TRIGGER AS $$
DECLARE offending TEXT;
BEGIN
    WITH RECURSIVE ancestors(id, path) AS (
        SELECT unnest(NEW.parent_ids), ARRAY[NEW.id]
        UNION ALL
        SELECT unnest(h.parent_ids), a.path || h.id
        FROM hierarchy_levels h JOIN ancestors a ON h.id = a.id
        WHERE NOT h.id = ANY(a.path)
    )
    SELECT id INTO offending FROM ancestors WHERE id = NEW.id LIMIT 1;

    IF offending IS NOT NULL THEN
        RAISE EXCEPTION
          'cycle rejected: % would become its own ancestor', NEW.id;
    END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reject_cycles
    BEFORE INSERT OR UPDATE OF parent_ids ON hierarchy_levels
    FOR EACH ROW EXECUTE FUNCTION reject_hierarchy_cycles();
