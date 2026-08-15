# BRAHMO Rules Engine — BFS Traversal + 5-Check Filter Pipeline

A deterministic healthcare knowledge access engine that takes a knowledge graph and a user profile, traverses the DAG upward from the user's entry point, injects hospital-wide safety nodes, and applies five sequential checks to produce the final candidate set.

**Zero LLM. Zero runtime embeddings. Fully deterministic.**

## Overview

The pipeline:

1. Resolves the user's entry point from department and hierarchy ceiling.
2. Traverses the knowledge hierarchy upward using BFS.
3. Injects globally relevant Zone 2 nodes.
4. Applies five sequential filtering checks.
5. Returns only nodes that survive all five checks.

The five checks are:

1. **Isolation**
2. **Compliance**
3. **Permission**
4. **Temporal**
5. **Derivability**

No LLM is involved anywhere in this decision pipeline.

## Seeded Users

| User | Role | Ceiling | Department | Entry Point | Final |
|---|---|---:|---|---|---:|
| Nurse Priya | VIEWER | L10 | ortho | Ortho Ward (L10) | 11 |
| Dr. Vikram | HOD | L4 | ortho | Ortho Dept (L5) | 13 |
| Dr. Ananya | EDITOR | L8 | medicine | Medicine General (L8) | 9 |
| Dr. Sharma | HOD | L4 | medicine | Medicine Dept (L5) | 12 |
| Pharmacist Ravi | VIEWER | L12 | pharmacy | Hospital (org-wide off) | 8 |
| Dr. Sunita | QUALITY | L6 | quality | Hospital (org-wide) | 22 |
| Admin Suresh | ADMIN | L1 | admin | Hospital (org-wide) | 42 |

## Architecture

```text
User Profile
     │
     ├── Permission Compiler
     ├── Entry Point Resolver
     ├── BFS Traversal
     │       └── FIFO queue + visited set + multi-parent safe
     ├── Zone 2 Injection
     ├── Check 1 — ISOLATION
     ├── Check 2 — COMPLIANCE
     ├── Check 3 — PERMISSION
     ├── Check 4 — TEMPORAL
     ├── Check 5 — DERIVABILITY
     └── Candidate Set
```

The five checks are sequential. Each check receives the output of the previous check.

Detailed architectural reasoning is documented in `docs/architecture.md`.

## BFS Traversal

The hierarchy is represented as a Directed Acyclic Graph.

Traversal starts from the user's resolved entry point and moves upward through `parent_ids`.

The implementation uses:

- FIFO queue
- visited set
- multi-parent traversal
- cycle protection
- `distance_from_entry`

## Zone 2 Injection

Zone 2 represents globally relevant hospital-wide knowledge. Zone 2 nodes are injected before the five checks and still pass through all five checks.

```text
BFS
  ↓
Zone 2 Injection
  ↓
Isolation
  ↓
Compliance
  ↓
Permission
  ↓
Temporal
  ↓
Derivability
```

## Five Sequential Checks

### 1. Isolation

Ensures the node belongs to the same organization/tenant as the user.

```text
org_id = user.org_id
```

### 2. Compliance

Checks whether the user's clearance satisfies the node's required compliance tags. Unknown roles are handled fail-closed.

### 3. Permission

Uses compiled role permissions and hierarchy ceiling, avoiding an N+1 permission query pattern.

### 4. Temporal

Checks `status`, `superseded_by`, and `valid_until` so expired or superseded knowledge is excluded.

### 5. Derivability

Uses a precomputed derivability score compared against `BRAHMO_DERIVABILITY_THRESHOLD`.

Default:

```text
0.7
```

Derivability is treated as a relevance check rather than an access-control mechanism.

## Database Query Design

The optimized Supabase/PostgreSQL pipeline keeps the five checks sequential while reducing database round trips.

```text
pool
 ↓
c1_isolation
 ↓
c2_compliance
 ↓
c3_permission
 ↓
c4_temporal
 ↓
c5_derivability
 ↓
final survivors
```

The optimized main pipeline uses two database round trips:

```text
1. Fetch user/profile
2. Execute the combined pipeline statement
```

## Content Protection / GAP 5

The check chain operates on node metadata. Node `content` and `title` are not needed to perform the five checks.

Only nodes surviving all five checks have their final payload joined/fetched.

```text
metadata
   ↓
five checks
   ↓
survivor IDs
   ↓
final content join
   ↓
candidate response
```

## Silent Exclusion

Excluded nodes are simply absent from the public pipeline response. The public response does not expose removed node counts, restricted placeholders, or exclusion reasons.

An operator-only audit endpoint is available separately:

```text
GET /admin/audit
```

## Security Model

### Multi-tenant isolation

The pipeline enforces organization-level isolation. Tests include a rival tenant to verify cross-tenant nodes never enter a user's final candidate set.

### Fail-closed roles

Role behaviour is defined declaratively in `backend/policy/role_policy.py`. Unknown roles fall through to a restrictive policy.

### Admin API protection

For non-local deployment, configure:

```text
BRAHMO_ADMIN_TOKEN
```

and provide:

```text
X-Admin-Token
```

### Error handling

Unhandled application errors are returned as generic internal server errors rather than exposing database details, file paths, SQL fragments, or potentially sensitive row information.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Database | Supabase / PostgreSQL |
| Offline fallback | SQLite |
| Frontend | React 18 |
| Build tool | Vite |
| Styling | Tailwind CSS |
| Testing | Python `unittest` |
| API | REST / FastAPI |
| Database driver | psycopg |
| Pipeline | Deterministic rules engine |

## Repository Structure

```text
brahmo-rules-engine/
├── backend/
│   ├── api.py
│   ├── config.py
│   ├── main.py
│   ├── derivability/
│   ├── models/
│   ├── pipeline/
│   ├── policy/
│   ├── repository/
│   └── tests/
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── scripts/
│   ├── benchmark_pipeline.py
│   ├── generate_sql.py
│   └── verify_supabase.py
├── supabase/
│   ├── schema.sql
│   ├── seed.sql
│   └── rls_policies.sql
├── docs/
│   └── architecture.md
├── data_sources.md
├── requirements.txt
├── run_demo.py
├── .env.example
└── README.md
```

## Setup

### 1. Create the Supabase database

Run these files in order in the Supabase SQL Editor:

```text
1. supabase/schema.sql
2. supabase/seed.sql
3. supabase/rls_policies.sql
```

Expected dataset:

```text
50 knowledge nodes
7 users
20 hierarchy tiers
10 edges
```

### 2. Environment Configuration

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Configure:

```text
DATABASE_BACKEND=supabase
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key
SUPABASE_DB_URL=postgresql://postgres.your-project-ref:YOUR_DATABASE_PASSWORD@aws-0-your-region.pooler.supabase.com:5432/postgres
BRAHMO_ORG_ID=supra
BRAHMO_DERIVABILITY_THRESHOLD=0.7
BRAHMO_PERMISSION_MODE=strict
```

**Never commit the real `.env` file.**

### 3. Verify Supabase

```bash
pip install "psycopg[binary]"
python scripts/verify_supabase.py
```

The script checks connectivity, dataset counts, and one pipeline execution for each seeded user.

### 4. Backend

```bash
python -m venv venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source venv/bin/activate
```

Install:

```bash
pip install -r requirements.txt
```

Run:

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

Backend:

`http://localhost:8000`

### 5. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend:

`http://localhost:5173`

### 6. Production Frontend Build

```bash
cd frontend
npm run lint
npm run build
```

### 7. SQLite Fallback

PowerShell:

```powershell
$env:DATABASE_BACKEND="sqlite"
python run_demo.py
```

Linux/macOS:

```bash
DATABASE_BACKEND=sqlite python run_demo.py
```

SQLite is an explicit opt-in fallback.

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Health/status information |
| GET | `/users` | List seeded users |
| GET | `/users/{user_id}` | Retrieve one user |
| GET | `/hierarchy` | Retrieve hierarchy |
| POST | `/pipeline/run` | Execute the rules pipeline |
| GET | `/pipeline/compare?users=A,B,C` | Compare multiple users |
| GET | `/pipeline/{run_id}` | Replay a completed run |
| GET | `/admin/audit?user=...` | Operator exclusion audit |
| GET | `/admin/derivability` | Derivability calibration report |

## Running the Pipeline

Seeded user example:

```json
{
  "user": "U-PRIYA",
  "zone2": true
}
```

Unseen user example:

```json
{
  "role": "AUDITOR",
  "department": "audit",
  "ceiling": 3,
  "clearance": ["MNPI"],
  "name": "External Auditor"
}
```

The pipeline is profile-driven rather than hardcoded to the seven seeded users.

## Testing

Run:

```bash
python -m unittest discover -s backend/tests -t .
```

Current result:

```text
155 tests
OK
```

Important coverage includes BFS traversal, permissions, five-check ordering, determinism, unseen users, temporal metadata, API/configuration, derivability, isolation/Zone 2, and single-query/check-chain behaviour.

## Frontend Verification

```bash
npm run lint
```

Result:

```text
ESLint clean
0 problems
```

Production build:

```bash
npm run build
```

Result:

```text
Vite production build successful
```

## Supabase Verification Results

Latest live Supabase verification:

```text
Knowledge nodes:   50
Users:              7
Hierarchy tiers:   20
```

| User | Entry Point | BFS | Final | Time |
|---|---|---:|---:|---:|
| Admin Suresh | HL-01 | 50 | 42 | 124.60 ms |
| Dr. Sharma | HL-05-MED | 10 | 12 | 43.36 ms |
| Dr. Vikram | HL-05-ORTHO | 11 | 13 | 44.33 ms |
| Dr. Sunita | HL-01 | 50 | 22 | 51.91 ms |
| Dr. Ananya | HL-08-MED-GEN | 11 | 9 | 50.23 ms |
| Nurse Priya | HL-10-ORTHO-W | 15 | 11 | 43.24 ms |
| Pharmacist Ravi | HL-01 | 3 | 8 | 41.79 ms |

## Performance Benchmark

Run:

```bash
python scripts/benchmark_pipeline.py --runs 10
```

Latest Supabase benchmark:

| User | Median |
|---|---:|
| Admin Suresh | 48.1 ms |
| Dr. Sharma | 41.7 ms |
| Dr. Vikram | 40.1 ms |
| Dr. Sunita | 43.5 ms |
| Dr. Ananya | 42.9 ms |
| Nurse Priya | 43.1 ms |
| Pharmacist Ravi | 47.7 ms |

```text
Slowest median: 48.1 ms
Target:         500 ms
Status:         PASS
```

The optimized main pipeline uses two database round trips and keeps the five checks sequential inside the SQL pipeline.

## Performance Optimization

The optimized implementation collapses the main pipeline into a single combined SQL statement after the user lookup.

The five checks remain visible as chained CTEs:

```text
c1_isolation
    ↓
c2_compliance
    ↓
c3_permission
    ↓
c4_temporal
    ↓
c5_derivability
```

This preserves the requirement that Check N receives the output of Check N-1 while reducing network latency.

## Demo Scenarios

### 1. Nurse Priya

Demonstrates:

```text
BFS 15 → Zone 2 25 → Final 11
```

### 2. Dr. Vikram

Demonstrates a different entry point, HOD permissions, department-specific clearance, and a different candidate set from the same graph.

### 3. Silent Exclusion

Run the pipeline as Nurse Priya. Restricted knowledge is absent from the public response. The operator audit endpoint can separately demonstrate the exclusion trail.

### 4. Zone 2

Toggle Zone 2 off and on to demonstrate that globally relevant nodes are injected but still pass all five checks.

### 5. Surprise / Unseen User

Use the `AUDITOR` example above to demonstrate profile-driven evaluation without a database write or code change.

## Verification Status

| Item | Status |
|---|---|
| Backend test suite | **155 passing** |
| Pipeline behaviour | **Verified** |
| Silent exclusion | **Verified** |
| Unseen user behaviour | **Verified** |
| Frontend lint | **Passing** |
| Frontend production build | **Passing** |
| Supabase connection | **Verified** |
| Knowledge nodes | **50** |
| Users | **7** |
| Hierarchy tiers | **20** |
| Supabase pipeline verification | **Passed for all 7 seeded users** |
| Supabase benchmark | **48.1 ms slowest median** |
| 500 ms performance budget | **PASS** |
| Schema / seed / RLS | **Applied to Supabase** |
| RLS policies | **Present in live Supabase instance** |

## Data Sources

Clinical/healthcare knowledge used by the assessment dataset is documented in:

`data_sources.md`

Seed SQL is in:

`supabase/seed.sql`

## Known Tradeoffs and Assessment Decisions

### Upward-only BFS

The implementation follows the assessment wording that traversal moves upward through the DAG. Detailed reasoning is documented in `docs/architecture.md`.

### RLS

RLS policies are included and applied to the Supabase instance as defense in depth.

They cover isolation, compliance, permission, and temporal access.

The application pipeline remains the primary deterministic filtering layer. The RLS compliance policy is deliberately simpler than the application's department-scoped HOD clearance logic, so RLS is a security floor rather than an exact mirror of every application-level rule.

### Derivability and RLS

Derivability is intentionally not included as an RLS access-control rule.

```text
RLS
  → access control

Derivability
  → relevance filtering
```

### SQLite compliance representation

SQLite does not provide PostgreSQL's native array type. The SQLite fallback therefore represents compliance tags differently while the PostgreSQL implementation uses the appropriate PostgreSQL representation. The rules and logical filtering behaviour remain consistent.

## Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_BACKEND` | `supabase` or `sqlite` |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Publishable/anon key |
| `SUPABASE_DB_URL` | PostgreSQL connection string |
| `BRAHMO_ORG_ID` | Organization/tenant |
| `BRAHMO_DERIVABILITY_THRESHOLD` | Check 5 threshold |
| `BRAHMO_PERMISSION_MODE` | Permission mode |
| `BRAHMO_ADMIN_TOKEN` | Optional admin API token |
| `BRAHMO_CORS_ORIGINS` | Allowed browser origins |

Never commit real credentials. The repository contains `.env.example`; the real `.env` is gitignored.

## No LLM in the Rules Engine

The assessment requires deterministic rule evaluation.

This implementation uses:

```text
NO LLM
NO runtime embeddings
NO probabilistic access decisions
NO per-user hardcoded rules
```

Every candidate decision is produced by deterministic traversal, metadata, permissions, compliance, temporal rules, and derivability thresholds.

## Final Summary

BRAHMO Rules Engine provides a deterministic pipeline for assembling organization-aware healthcare knowledge context.

The implementation provides:

- upward DAG traversal
- BFS with multi-parent protection
- Zone 2 global-node injection
- five sequential checks
- tenant isolation
- compliance filtering
- hierarchy permissions
- temporal validity
- derivability filtering
- silent exclusion
- operator audit
- PostgreSQL/Supabase support
- SQLite fallback
- optimized SQL execution
- unseen-user support
- React/Vite dashboard
- automated backend tests
- frontend lint/build verification
- live Supabase verification

Current validation:

```text
155 backend tests          PASS
Supabase connectivity      PASS
50 knowledge nodes         PASS
7 seeded users             PASS
20 hierarchy tiers         PASS
7-user pipeline check      PASS
Frontend lint              PASS
Frontend production build  PASS
Slowest benchmark median   48.1 ms
Performance target         500 ms
```

The repository is intended to be run locally with the supplied configuration and dataset, with all real credentials supplied through the ignored `.env` file.
