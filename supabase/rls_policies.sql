-- =====================================================================
-- Row-Level Security - checks 1 to 4 pushed all the way down to Postgres.
--
-- The application already runs these as WHERE clauses, so RLS is defence in
-- depth: it answers "what if someone bypasses the API and queries the
-- database directly?" with "they get the same filtered rows".
--
-- Session context is set per request:
--   SELECT set_config('brahmo.user_id',    'U-PRIYA', true);
--   SELECT set_config('brahmo.org_id',     'supra',   true);
--   SELECT set_config('brahmo.ceiling',    '10',      true);
--   SELECT set_config('brahmo.clearance',  'MNPI',    true);
--   SELECT set_config('brahmo.read_all',   'false',   true);
--
-- Note what is NOT here: check 5 (derivability). Derivability is a relevance
-- judgement, not an access-control decision. Enforcing it in RLS would mean
-- the database refuses to show an administrator a node purely because it is
-- obvious - wrong layer. Security checks belong in RLS; quality checks belong
-- in the pipeline.
-- =====================================================================

ALTER TABLE knowledge_nodes ENABLE ROW LEVEL SECURITY;

CREATE POLICY p_isolation ON knowledge_nodes FOR SELECT
    USING (org_id = current_setting('brahmo.org_id', true));

CREATE POLICY p_compliance ON knowledge_nodes FOR SELECT
    USING (
        compliance_tags = '{}'
        OR compliance_tags <@ string_to_array(
              coalesce(current_setting('brahmo.clearance', true), ''), ',')
    );

CREATE POLICY p_permission ON knowledge_nodes FOR SELECT
    USING (
        coalesce(current_setting('brahmo.read_all', true), 'false') = 'true'
        OR zone = 2
        OR hierarchy_level >=
             coalesce(current_setting('brahmo.ceiling', true), '15')::int
    );

CREATE POLICY p_temporal ON knowledge_nodes FOR SELECT
    USING (
        status NOT IN ('SUPERSEDED','EXPIRED')
        AND (valid_until IS NULL OR valid_until > NOW())
    );

-- Postgres ANDs multiple PERMISSIVE policies for the same command, so a row
-- must satisfy all four. A node failing any one is not "denied" - it is
-- simply not in the result. That is the silent exclusion property, enforced
-- by the database rather than trusted to the application.
