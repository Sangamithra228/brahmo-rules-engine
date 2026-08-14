# BRAHMO Rules Engine — BFS Traversal + 5-Check Filter Pipeline

Takes a knowledge graph and a user, and produces the candidate set that user
should see. Traverses a DAG upward from the user's entry point, injects
hospital-wide safety nodes, then applies five sequential checks.

**Zero LLM. Zero runtime embeddings. Fully deterministic.**

Seven seeded users query the same 50-node graph and get seven different
answers, from one code path:

| User | Role | Ceiling | Department | Entry point | Final |
|---|---|---:|---|---|---:|
| Nurse Priya | VIEWER | L10 | ortho | Ortho Ward (L10) | 11 |
| Dr. Vikram | HOD | L4 | ortho | Ortho Dept (L5) | 13 |
| Dr. Ananya | EDITOR | L8 | medicine | Medicine General (L8) | 9 |
| Dr. Sharma | HOD | L4 | medicine | Medicine Dept (L5) | 12 |
| Pharmacist Ravi | VIEWER | L12 | pharmacy | Hospital (org-wide off) | 8 |
| Dr. Sunita | QUALITY | L6 | quality | Hospital (org-wide) | 22 |
| Admin Suresh | ADMIN | L1 | admin | Hospital (org-wide) | 42 |

Measured 1–7 ms per run against the 500 ms target, on the SQLite fallback.
Timing on Supabase will be higher (network round trips) and has not been
measured — see *Known tradeoffs*.

---

## Architecture

```
User profile
   │
   ├─ Permission Compiler ──── compiled once per session into an O(1)
   │                           {level: {can_read, can_write}} map + clearance set
   ├─ Entry Point Resolver ─── department + ceiling → starting DAG tier
   │
   ├─ BFS Traversal ────────── UPWARD only, following parent_ids to the root;
   │                           FIFO queue + visited set; multi-parent safe;
   │                           distance_from_entry recorded
   ├─ Zone 2 Injection ─────── GLOBAL nodes merged into the candidate pool,
   │                           after BFS and before the checks
   │
   ├─ Check 1  ISOLATION ───── org_id = user.org_id
   ├─ Check 2  COMPLIANCE ──── clearance-driven; the profile decides, not the code
   ├─ Check 3  PERMISSION ──── hierarchy ceiling from the compiled map
   ├─ Check 4  TEMPORAL ────── status, superseded_by, valid_until
   ├─ Check 5  DERIVABILITY ── precomputed score vs configured threshold
   │
   └─ Candidate Set ────────── annotated with type, importance, zone,
                               hierarchy_level, distance_from_entry,
                               compression_hint
```

The checks are **sequential**. Each contributes one SQL predicate, and the
repository ANDs them progressively: stage *k* runs with predicates 1..*k*, so
the rows entering check *k+1* are exactly the rows that survived check *k*.
They are never evaluated independently or in parallel.

Full reasoning, including three places where the assessment brief contradicts
itself, is in [`docs/architecture.md`](docs/architecture.md).

---

## Tech stack

| Layer | Choice |
|---|---|
| Database | Supabase / PostgreSQL (**primary**), SQLite (offline fallback) |
| Backend | Python 3.11+, FastAPI |
| Frontend | React 18, Vite, Tailwind CSS |
| Tests | `unittest`, 133 tests, standard library only |

The React frontend is real (Vite + React 18 + Tailwind, source in
`frontend/src`). The build and lint should be verified in your deployment
environment — see *Verification status*.

---

## Setup

### 1. Load the schema and seed into Supabase

In the Supabase **SQL Editor**, run these three files **in this order**:

1. `supabase/schema.sql` — tables, indexes, triggers
2. `supabase/seed.sql` — 50 nodes, 7 users, 20 tiers, 10 edges
3. `supabase/rls_policies.sql` — optional, checks 1–4 as Row-Level Security

Then confirm the supplied dataset loaded:

```sql
SELECT COUNT(*) FROM knowledge_nodes;   -- 50
SELECT COUNT(*) FROM users;             -- 7
SELECT COUNT(*) FROM hierarchy_levels;  -- 20
SELECT COUNT(*) FROM edges;             -- 10
```

Nothing about the dataset is hardcoded in Python at runtime: the application
reads users, tiers and nodes from whichever database is configured.
`backend/data/seed_data.py` exists only to generate `seed.sql` and to build
the local SQLite fallback.

### 2. Environment

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

**How this backend connects.** The five checks execute as progressive SQL
`WHERE` clauses *inside* the database, so the application needs a direct
PostgreSQL connection (psycopg). A publishable / anon key addresses the
PostgREST API and cannot drive those predicates, so the key alone is not
sufficient — a database credential is required as well. The anon key is
recorded in configuration but is **not** used to read data, and it is never
sent to the browser.

Set **`SUPABASE_DB_URL`** to the complete connection string from Project
Settings → Database → Connection string → URI. Nothing is derived from
`SUPABASE_URL`; the DSN is used exactly as given.

On an **IPv4 network use the Session Pooler string**, which Supabase proxies
over IPv4:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

The direct `db.<project-ref>.supabase.co` host is IPv6-only on current
projects and fails with `failed to resolve host` on IPv4-only networks.

If your password contains `@ : / #`, percent-encode it in the URI
(`@`→`%40`, `:`→`%3A`, `/`→`%2F`, `#`→`%23`); otherwise it silently corrupts
the DSN and surfaces as an authentication failure.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_BACKEND` | `supabase` | `supabase` or `sqlite` |
| `SUPABASE_URL` | — | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | — | Publishable/anon key. Recorded, not used to read data |
| `SUPABASE_DB_URL` | — | **Complete** PostgreSQL DSN, used verbatim. Session Pooler URI on IPv4 |
| `BRAHMO_ORG_ID` | `supra` | Tenant |
| `BRAHMO_DERIVABILITY_THRESHOLD` | `0.7` | Check 5 cutoff (dashboard shows it read-only) |
| `BRAHMO_PERMISSION_MODE` | `strict` | Internal; the dashboard exposes no selector |
| `BRAHMO_ADMIN_TOKEN` | _unset_ | When set, `/admin` requires an `X-Admin-Token` header. Unset = loopback only |
| `BRAHMO_CORS_ORIGINS` | localhost:5173, localhost:8000 | Comma-separated allowed origins |

A **service-role key is not used by this project** and must never be
committed or exposed to the browser.

### 2a. Verify the connection

```bash
pip install "psycopg[binary]"
python scripts/verify_supabase.py
```

This connects through the same repository the application uses, checks the
row counts above, and runs one real pipeline per user. It prints no
credentials.

`.env` is gitignored. No credentials are committed anywhere in this repo.

### 3. Backend

```bash
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

The Vite dev server proxies `/health`, `/users`, `/hierarchy`, `/pipeline` and
`/admin` to `localhost:8000`, so both run side by side with no CORS setup.

To build once and serve everything from FastAPI:

```bash
cd frontend && npm run build      # emits frontend/dist
uvicorn backend.main:app --port 8000    # now also serves the dashboard at /
```

### Offline fallback

If Supabase is not reachable, or you want to run with nothing installed:

```bash
DATABASE_BACKEND=sqlite python run_demo.py
# PowerShell:  $env:DATABASE_BACKEND="sqlite"; python run_demo.py
```

This seeds a local SQLite copy of the same supplied dataset and serves the API
on the standard library alone. **It is an explicit opt-in.** With
`DATABASE_BACKEND` unset the app targets Supabase and fails with setup
instructions rather than silently using the wrong database.

---

## Verification status

Being explicit about what was actually executed, so nothing here has to be
taken on trust:

| Item | Status |
|---|---|
| Backend test suite | **133 passing**, run against the SQLite fallback |
| Pipeline behaviour, silent exclusion, timing | Verified live over HTTP |
| Frontend lint (`npm run lint`) | **Passing** — ESLint clean, 0 problems |
| Frontend JSX/ESM parse | **Passing** — all 10 modules parse |
| Frontend build (`npm run build`) | **Not executed** — the vendored `node_modules` carries the Windows rollup binary, not the Linux one. Run it on your machine |
| Supabase connection | **Not executed.** No network here — run `python scripts/verify_supabase.py` |
| Supabase timing | **Not measured.** Run `python scripts/benchmark_pipeline.py` |
| `schema.sql` / `seed.sql` / `rls_policies.sql` | **Not executed.** Run them in the Supabase SQL Editor, in that order |
| RLS policies | Written and reviewed; not executed against a live instance |

Every runtime figure in this README came from the SQLite fallback. Supabase
timing will be higher because of network round trips.

## Tests

```bash
python -m unittest discover -s backend/tests -t .
```

133 tests, no dependencies. They run against the SQLite fallback, so the
PostgreSQL dialect is verified by asserting on the SQL the builder emits
rather than by executing it. Coverage:

| Area | File |
|---|---|
| BFS upward traversal, multi-parent, visited set, cycles | `test_bfs.py` |
| Permission compilation, clearance scoping, fail-closed roles | `test_permission_compiler.py` |
| Each of the five checks, ordering, thresholds | `test_five_checks.py` |
| Per-user differentiation, silent exclusion, determinism, latency | `test_pipeline.py` |
| Unseen users, new departments, unknown roles | `test_surprise_users.py` |
| Expired / superseded nodes, compression hints | `test_temporal_and_metadata.py` |
| API surface, database config, SQL dialects, sequential execution | `test_api_and_config.py` |
| Derivability scorer calibration | `test_derivability.py` |
| Multi-tenant isolation, Zone 2 de-duplication, admin gate | `test_isolation_and_injection.py` |

---

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Counts, active backend, `graph_acyclic`, `llm_calls: 0` |
| GET | `/users` | All seeded profiles |
| GET | `/users/{user_id}` | One profile |
| GET | `/hierarchy` | The 20-tier DAG |
| POST | `/pipeline/run` | Run the pipeline |
| GET | `/pipeline/compare?users=A,B,C` | Several users side by side |
| GET | `/pipeline/{run_id}` | Replay a completed run |
| GET | `/admin/audit?user=…` | Operator-only exclusion trail |
| GET | `/admin/derivability` | Scorer calibration report |

`POST /pipeline/run` accepts either a seeded user or an inline profile:

```jsonc
{ "user": "U-PRIYA", "zone2": true }

// or a profile that exists in no database:
{ "role": "AUDITOR", "department": "audit", "ceiling": 3,
  "clearance": ["MNPI"], "name": "External Auditor" }
```

`zone2` is the only caller-controllable option. The derivability threshold and
permission mode are organization configuration and are ignored if sent, so no
request can relax a core filtering rule; the effective values are echoed under
`options` for read-only display.

---

## Security model

**Silent exclusion.** A node the user may not see is simply absent. The
response carries no removed count, no placeholder row, no 403, no "restricted"
marker. `PipelineResult` has two serialisers — a public one that cannot
express an exclusion, and an operator one behind `/admin/audit` — rather than
one serialiser with a flag, because a flag is one careless `if` from leaking.
The audit path returns node ids and titles only, never content.

The DAG panel shows hierarchy *tiers*, not node identities, so it cannot
become a side channel around this. There is a test asserting that no node id
appears in the traversal payload.

**Filtering happens in the database.** Checks 1–4 execute as progressive SQL
`WHERE` clauses, so restricted rows are never read on the user's behalf and
never cross the network (GAP 5). Only the final survivors have their content
fetched. `supabase/rls_policies.sql` carries isolation, compliance,
permission and temporal into Row-Level Security as defence in depth — the
answer to "what if someone bypasses the API and queries the database
directly?" The RLS compliance policy is a deliberate simplification: it tests
the flattened clearance list, where the application additionally scopes a
HOD's implicit MNPI to their own department. RLS is a floor for direct
database access, not an exact mirror of the pipeline, and it has not been run
against a live instance — see *Known tradeoffs*.

Check 5 is deliberately **not** in RLS: derivability is a relevance judgement,
not access control, and Postgres should not refuse an administrator a node
purely for being obvious.

**The audit trail is gated.** `/admin/audit` names the ids and titles of the
nodes a user was not given, which is exactly what silent exclusion hides, so
the route cannot be open. By default the `/admin` routes serve loopback
clients only — the local demo works with no configuration. Set
`BRAHMO_ADMIN_TOKEN` and an `X-Admin-Token` header is required from every
host, which is what any non-local deployment must do. Refusals are `404`
rather than `403`, because a `403` confirms the endpoint exists and has
something behind it. `/health` reports `admin_api_token_required` so the
posture is never a guess. CORS origins are an explicit list, not `*`, so no
third-party site can read the trail from a logged-in browser.

**Errors reveal nothing.** Unhandled exceptions are logged server-side and
answered with a generic `Internal server error`. An echoed exception body can
carry SQL fragments, file paths, or the content of rows the caller is not
cleared to see, which would defeat silent exclusion through the error channel.

**Isolation is verified against a real second tenant.** The supplied seed data
has one organization, so `org_id = ?` matched everything and check 1 could
never be observed working. The test suite inserts a rival tenant with nodes
planted on tiers Supra users genuinely traverse, and asserts that no user —
including the administrator — ever receives one.

**Nothing is hardcoded per user.** Role behaviour lives in a declarative table
(`backend/policy/role_policy.py`). There is no `if user == "Priya"` anywhere;
unknown roles fall through to a policy that grants nothing.

---

## Performance

### The Supabase round-trip problem

Against SQLite the pipeline runs in about 1 ms. Against a hosted database in
`ap-southeast-1` the same code took roughly 900–1600 ms, and the cause was not
query cost — it was **eleven network round trips per pipeline run**:

| # | Query |
|---|---|
| 1 | fetch the user |
| 2 | count nodes reachable by BFS |
| 3 | fetch the Zone 2 node ids |
| 4 | count after Zone 2 injection |
| 5–9 | one `COUNT(*)` per check, to build the funnel |
| 10 | fetch the surviving rows |
| 11 | count all nodes in the org |

At ~100 ms RTT that is ~1.1 s of pure latency before the database does any
work.

### What changed

Queries 2–11 collapse into **one statement** built by
`backend/repository/pipeline_sql.py`. The five checks remain five chained
CTEs — `c2_compliance` selects `FROM c1_isolation`, `c3_permission` selects
`FROM c2_compliance`, and so on — so the sequence is preserved and legible in
the generated SQL. The funnel counts come from those same CTEs, and the final
rows are joined onto them, so counts and candidates arrive together.

**Round trips per run: 11 → 2** (one to fetch the user, one for everything
else). The hierarchy DAG is loaded once per session, not per run.

Two things deliberately did *not* change: BFS still walks only the user's
reachable subgraph rather than scanning the table, and node content is still
fetched only for rows that survive all five checks.

The audit path (`/admin/audit`) keeps the original progressive
implementation, because it needs the per-stage id lists. That also makes it
the reference implementation the optimization is tested against.

### Measurements

| Backend | Median per run | Round trips |
|---|---|---|
| SQLite (this environment) | 0.9–1.7 ms | 2 |
| Supabase Session Pooler | **not measured — see below** | 2 |

Run it yourself:

```bash
python scripts/benchmark_pipeline.py --runs 8
```

The first run per user is reported separately (connection and plan-cache
warm-up); the median of the rest is the meaningful number.

**The Supabase figure has not been measured.** This environment has no network
access, so the 11 → 2 reduction is verified by counting statements, not by
timing them against your database. With two round trips the expected floor is
roughly `2 × RTT`; at ~100 ms that is ~200 ms, inside the 500 ms budget, but
you should confirm with the benchmark script before relying on it.

### Indexes

Added for the new query shape, each because a specific predicate uses it:

| Index | Why |
|---|---|
| `(org_id, hierarchy_level_id)` | the BFS arm of the pool CTE filters on both |
| `(org_id, zone)` | the Zone 2 arm filters on both |
| `valid_until WHERE NOT NULL` | check 4; partial because the column is mostly NULL |
| `hierarchy_levels(org_id, department)` | entry-point resolution |
| `users(org_id)` | on the hot path twice |

The pre-existing GIN index on `compliance_tags` is retained: check 2 uses
array membership on PostgreSQL, which is what GIN accelerates. Not added:
`users(department)` (7 rows — the index would cost more than the scan) and
anything on `title` (never filtered).

### Why the checks are still sequential

The assessment requires check *N* to receive the output of check *N−1*. That
is preserved literally: each check is a CTE reading the previous CTE. Running
them as five independent filters over the original set would give the same
final answer on this dataset but would attribute exclusions to the wrong rule
in the audit trail, and would have every check evaluate rows an earlier check
had already condemned. `test_single_query_parity.py` asserts the chaining is
present in the generated SQL.

- Permissions compile **once** per run into a dict — no per-node query, no N+1.
- BFS walks the hierarchy DAG (tens of tiers), not the knowledge nodes, so a
  user's traversal cost is independent of total graph size.
- Checks 1–4 are indexed SQL predicates; every one has a supporting index plus
  a composite covering the hot path.
- Derivability is a precomputed column — the scoring cost sits at ingest.
- Measured 1–7 ms per run across all seven users on the SQLite fallback. The
  dashboard displays the figure the backend reports, never a fabricated one.
  Supabase timing is not yet measured.

---

## Demo scenarios

1. **Nurse Priya** — full pipeline. 50 → BFS 15 → +Zone 2 25 → 11. The funnel
   shows compliance taking 5, permission 7, derivability 2.
2. **Dr. Vikram** — same graph, 13 nodes. Different entry point, and his HOD
   role clears his own department's MNPI: he sees `N-O11` (budget) but not
   `N-O12`, because every tag must clear, not any.
3. **Silent exclusion** — Priya's set has zero Cardiology, Paediatrics or
   Medicine nodes and no indication they exist. Then show `/admin/audit` to
   prove the trail exists on a separate operator endpoint.
4. **Zone 2** — toggle off: Priya drops 11 → 3 and loses all eight drug-safety
   globals including the Warfarin/NSAID rule. Toggle on. Note that two Zone 2
   nodes (`N-G04`, `N-G06`) are still removed by check 5, so injection widens
   the input to the sieve rather than punching through it.
5. **Surprise user** — type their profile into "Test an unseen profile". No
   code change, no database write.

---

## Known tradeoffs

- **BFS is upward-only, which costs some of the setup guide's expected
  counts.** The guide predicts roughly 15 / 22 / 40 final nodes for Priya /
  Vikram / Suresh; upward-only traversal yields 11 / 13 / 42. The guide's
  sample candidate set also shows Priya seeing nodes that live below her ward
  and so are unreachable by an upward walk. The prose ("walks UP the DAG")
  and the numbers disagree; the prose was followed. See Decision 1.

- See *Verification status* for what has and has not been executed.

- **Per-check timings are apportioned, not individually measured.** The five
  checks run as five progressive SQL statements; timing each separately would
  add round trips to report a number already under 2 ms in total.
- **RLS is provided, reviewed, and unverified.** The policies have never been
  executed against a live Supabase instance in this repository's test runs,
  which target the SQLite fallback. The compliance policy is also a
  simplification of the application rule (it does not model department-scoped
  HOD clearance), so it is a floor for direct database access rather than an
  exact mirror of the pipeline.
- **The SQLite fallback denormalises `compliance_tags`** into a `required_tags`
  string because SQLite has no array type. PostgreSQL uses native `TEXT[]` with
  a GIN index. The predicate builder is dialect-aware; the rules are identical.
- **`scope_aware` permission mode still exists in the backend** but is not
  exposed in the dashboard; the demo runs the assessment-compliant `strict`
  behaviour throughout. See Decision 4 in `docs/architecture.md`.
