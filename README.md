# BRAHMO Rules Engine — BFS Traversal + 5-Check Filter Pipeline

Takes a knowledge graph and a user, and produces the candidate set that user
should see. Traverses a DAG upward from the user's entry point, injects
hospital-wide safety nodes, then applies five sequential checks.

**Zero LLM. Zero runtime embeddings. Fully deterministic.**

Seven seeded users query the same 50-node graph and get seven different
answers, from one code path:

| User | Role | Ceiling | Department | Entry point | Final |
|---|---|---:|---|---|---:|
| Nurse Priya | VIEWER | L10 | ortho | Ortho Ward (L10) | 13 |
| Dr. Vikram | HOD | L4 | ortho | Ortho Dept (L5) | 22 |
| Dr. Ananya | EDITOR | L8 | medicine | Medicine General (L8) | 11 |
| Dr. Sharma | HOD | L4 | medicine | Medicine Dept (L5) | 15 |
| Pharmacist Ravi | VIEWER | L12 | pharmacy | Hospital (fallback) | 8 |
| Dr. Sunita | QUALITY | L6 | quality | Hospital (cross-dept) | 22 |
| Admin Suresh | ADMIN | L1 | admin | Hospital (cross-dept) | 42 |

Measured 1–6 ms per run against the 500 ms target, on the SQLite fallback.
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
   ├─ BFS Traversal ────────── upward through parent edges, plus a
   │                           department-scoped walk down; queue + visited set;
   │                           multi-parent safe; distance_from_entry recorded
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
| Tests | `unittest`, 98 tests, standard library only |

The React frontend is real (Vite + React 18 + Tailwind, source in
`frontend/src`). It has **not been built or linted in this environment** — see
*Known tradeoffs* before the demo.

---

## Setup

### 1. Supabase (the primary database)

1. Create a project at [supabase.com](https://supabase.com).
2. SQL Editor → run in order:
   - `supabase/schema.sql` — tables, indexes, cycle-rejection trigger
   - `supabase/seed.sql` — 50 nodes, 7 users, 20 tiers, 10 edges
   - `supabase/rls_policies.sql` — optional, checks 1–4 as Row-Level Security
3. Verify:
   ```sql
   SELECT COUNT(*) FROM knowledge_nodes;   -- 50
   SELECT COUNT(*) FROM users;             -- 7
   SELECT COUNT(*) FROM hierarchy_levels;  -- 20
   ```
4. Copy the connection string: Project Settings → Database → Connection
   string → URI.

### 2. Environment

```bash
cp .env.example .env
```

Set `SUPABASE_DB_URL` in `.env`. `DATABASE_BACKEND` defaults to `supabase`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_BACKEND` | `supabase` | `supabase` or `sqlite` |
| `SUPABASE_DB_URL` | — | PostgreSQL connection string |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | — | Supabase project API |
| `BRAHMO_ORG_ID` | `supra` | Tenant |
| `BRAHMO_DERIVABILITY_THRESHOLD` | `0.7` | Check 5 cutoff |
| `BRAHMO_PERMISSION_MODE` | `strict` | `strict` or `scope_aware` |

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

## Tests

```bash
python -m unittest discover -s backend/tests -t .
```

98 tests, no dependencies. They run against the SQLite fallback, so the
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
{ "user": "U-PRIYA", "zone2": true, "threshold": 0.7, "mode": "strict" }

// or a profile that exists in no database:
{ "role": "AUDITOR", "department": "audit", "ceiling": 3,
  "clearance": ["MNPI"], "name": "External Auditor" }
```

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
fetched. `supabase/rls_policies.sql` pushes the same four checks into
Row-Level Security as defence in depth — the answer to "what if someone
bypasses the API and queries the database directly?"

Check 5 is deliberately **not** in RLS: derivability is a relevance judgement,
not access control, and Postgres should not refuse an administrator a node
purely for being obvious.

**Nothing is hardcoded per user.** Role behaviour lives in a declarative table
(`backend/policy/role_policy.py`). There is no `if user == "Priya"` anywhere;
unknown roles fall through to a policy that grants nothing.

---

## Performance

- Permissions compile **once** per run into a dict — no per-node query, no N+1.
- BFS walks the hierarchy DAG (tens of tiers), not the knowledge nodes, so a
  user's traversal cost is independent of total graph size.
- Checks 1–4 are indexed SQL predicates; every one has a supporting index plus
  a composite covering the hot path.
- Derivability is a precomputed column — the scoring cost sits at ingest.
- Measured 1–6 ms per run across all seven users on the SQLite fallback. The
  dashboard displays the figure the backend reports, never a fabricated one.
  Supabase timing is not yet measured.

---

## Demo scenarios

1. **Nurse Priya** — full pipeline. 50 → BFS 20 → +Zone 2 30 → 13. The funnel
   shows compliance taking 5, permission 10, derivability 2.
2. **Dr. Vikram** — same graph, 22 nodes. Different entry point, and his HOD
   role clears his own department's MNPI: he sees `N-O11` (budget) but not
   `N-O12`, because every tag must clear, not any.
3. **Silent exclusion** — Priya's set has zero Cardiology, Paediatrics or
   Medicine nodes and no indication they exist. Then show `/admin/audit` to
   prove the trail exists on a separate operator endpoint.
4. **Zone 2** — toggle off: Priya drops 13 → 5 and loses all eight drug-safety
   globals including the Warfarin/NSAID rule. Toggle on. Note that two Zone 2
   nodes (`N-G04`, `N-G06`) are still removed by check 5, so injection widens
   the input to the sieve rather than punching through it.
5. **Surprise user** — type their profile into "Test an unseen profile". No
   code change, no database write.

---

## Known tradeoffs

- **The frontend has not been built.** `npm install` and `npm run build` have
  not been run against this source, and neither has ESLint. The module graph,
  imports and JSX nesting were checked statically. Run `npm install && npm run
  build` before relying on it.
- **Supabase has not been connected.** The schema, seed and RLS SQL are
  written and the PostgreSQL dialect is unit-tested, but no run has been made
  against a live Supabase instance. Every runtime figure quoted in this README
  came from the SQLite fallback.

- **Per-check timings are apportioned, not individually measured.** The five
  checks run as five progressive SQL statements; timing each separately would
  add round trips to report a number already under 2 ms in total.
- **RLS is provided but the application also filters.** Both layers enforce
  checks 1–4. The application path is what the demo exercises; RLS is defence
  in depth for direct database access.
- **The SQLite fallback denormalises `compliance_tags`** into a `required_tags`
  string because SQLite has no array type. PostgreSQL uses native `TEXT[]` with
  a GIN index. The predicate builder is dialect-aware; the rules are identical.
- **`strict` is the default permission mode** because it matches the brief's
  literal rule, but `scope_aware` is arguably the better production model. See
  Decision 4 in `docs/architecture.md`.
