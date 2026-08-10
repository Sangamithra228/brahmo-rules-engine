# BRAHMO Rules Engine — BFS Traversal + 5-Check Filter Pipeline

Takes a knowledge graph and a user, and produces the candidate set that user
should see. Traverses a DAG, injects hospital-wide safety nodes, then runs five
sequential checks that narrow the result down.

**Zero LLM. Zero embeddings at query time. Fully deterministic.**

Seven users query the same 50-node graph and get seven different answers:

| User | Role | Ceiling | Sees |
|---|---|---:|---:|
| Nurse Priya | VIEWER | L10 | 13 |
| Dr. Vikram | HOD | L4 | 22 |
| Dr. Ananya | EDITOR | L8 | 11 |
| Dr. Sharma | HOD | L4 | 15 |
| Pharmacist Ravi | VIEWER | L12 | 8 |
| Dr. Sunita (QA) | QUALITY | L6 | 22 |
| Admin Suresh | ADMIN | L1 | 42 |

Same code, same graph, same query path. 0.7–2 ms per run against a 500 ms
budget.

---

## Run it

```bash
python3 run_demo.py
# → http://localhost:8000
```

No `pip install`. No database credentials. No network. Python 3.11+ and the
standard library, because a demo that cannot fail on a missing dependency is
worth more than framework points.

Run the tests:

```bash
python3 -m unittest discover -s backend/tests -t .
# 66 tests
```

### The stack the brief specifies

FastAPI and Supabase are both implemented; SQLite and the stdlib server are
the defaults so the demo starts cold.

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

To point at Supabase: run `supabase/schema.sql`, then `supabase/seed.sql`,
then optionally `supabase/rls_policies.sql`; copy `.env.example` to `.env` and
fill in `SUPABASE_DB_URL`; and change one line in `backend/main.py`:

```python
from backend.repository.supabase_repo import SupabaseRepository
repo = SupabaseRepository()
```

`SupabaseRepository` implements the same interface, so nothing else changes.

---

## The pipeline

```
User row
  → Permission Compiler    O(1) {level: {can_read, can_write}} + clearance
  → Entry Point Resolver   department + ceiling → starting tier
  → BFS Traversal          up the DAG, plus a department-scoped walk down
  → Zone 2 Injection       global safety nodes added to the pool
  → Five Checks            ISOLATION → COMPLIANCE → PERMISSION →
                           TEMPORAL → DERIVABILITY   (progressive SQL)
  → Candidate Assembler    distance, zone, compression hint
```

Checks 1–4 execute as progressive SQL `WHERE` clauses. Stage *k* runs with
predicates 1..*k*, so the rows entering check *k+1* are exactly the rows that
survived check *k* — sequential by construction, evaluated by the database.
A node Priya may not see is never read on her behalf, which is the GAP 5
requirement.

`supabase/rls_policies.sql` pushes the same four checks into Row-Level
Security, so bypassing the API and querying Postgres directly returns the same
filtered rows.

---

## API

| Route | Purpose |
|---|---|
| `GET /` | Dashboard |
| `GET /health` | Node count, user count, `graph_acyclic`, `llm_calls: 0` |
| `GET /api/users` | The 7 profiles |
| `GET /api/hierarchy` | The 20-tier DAG |
| `GET /api/pipeline?user=U-PRIYA` | Run it |
| `GET /api/compare?users=A,B,C` | Side by side |
| `GET /api/audit?user=U-PRIYA` | Operator-only exclusion trail |
| `GET /api/derivability` | Offline scorer calibration report |

Options on `/api/pipeline` and `/api/compare`: `zone2=false`,
`threshold=0.5`, `mode=scope_aware`.

Run a profile that is not in the database — this is how the surprise-user test
is handled live, with nothing written to disk:

```
/api/pipeline?role=AUDITOR&department=audit&ceiling=3&clearance=MNPI&name=External+Auditor
```

The dashboard has the same thing under "Test an unseen profile".

---

## Demo script

**1. Priya — the core pipeline.** 50 → BFS 20 → +Zone 2 30 → 13. Walk the
sieve: compliance takes 5, permission takes 10, derivability takes 2. Her set
has zero Cardiology, zero Paediatrics, zero Medicine, zero MNPI, zero
superseded, zero derivable.

**2. Vikram — same graph, different person.** Switch the dropdown. 13 → 22.
His entry point moves to Ortho Dept (L5), his HOD role clears his own
department's MNPI. He sees `N-O11` (the budget). He does not see `N-O12` —
MNPI **and** CONFIDENTIAL needs admin clearance. Every tag must clear, not any.

**3. Silent exclusion.** Priya's response contains no removed count, no
placeholder, no 403. Then open `/api/audit?user=U-PRIYA` and show the trail
exists — on a separate operator endpoint, fetching ids and titles only, never
content.

**4. Zone 2 saves lives.** Toggle Zone 2 off. Priya drops 13 → 5 and loses all
eight drug-safety globals including the Warfarin/NSAID rule. Toggle on. That
gap is the argument.

**5. Innovation.** `/api/derivability`: the offline scorer, 96% agreement with
the seeded labels, and the two disagreements — `N-G04` and `N-G06` — where I
think the seed data is wrong and the nodes should be split. Detail in
Decision 9.

**6. Surprise user.** Take their profile, type it into the ad-hoc form, run.

---

## Layout

```
backend/
  data/seed_data.py          canonical seed — one source of truth
  policy/role_policy.py      declarative role table; no role logic in the pipeline
  pipeline/                  the six stages
  repository/                base interface + SQLite + Supabase
  derivability/scorer.py     offline heuristic scorer (innovation)
  tests/                     66 tests
  main.py                    FastAPI app
  server.py                  stdlib server (zero deps)
frontend/index.html          self-contained dashboard
supabase/                    schema.sql, seed.sql, rls_policies.sql
docs/architecture.md         every design decision, and the spec contradictions
docs/data_sources.md         provenance
```

---

## Notes on the brief

The specification contradicts itself in three places. All three are resolved
deliberately and documented in `docs/architecture.md` rather than papered over:

- **Zone 2 vs. the permission ceiling** (Decision 3). Applying
  `hierarchy_level >= ceiling` literally deletes every drug-safety node from
  Priya's session, which breaks Scenario 4 and inverts the opening story.
- **The ceiling vs. the sample output** (Decision 4). The sample candidate set
  shows Priya seeing an L8 node while her ceiling is L10. Both readings are
  implemented as modes; `strict` is the default.
- **Vikram's clearance** (Decision 5). His seeded clearance is empty, yet he
  is expected to see the MNPI budget node. Clearance is therefore compiled
  from role plus row, with a HOD's MNPI scoped to their own department.

Under these decisions Vikram lands on 22, matching the published figure
exactly; Priya lands on 13 against a published ~15 and Suresh on 42 against
~40, and both differences are arithmetic I can walk through node by node.
