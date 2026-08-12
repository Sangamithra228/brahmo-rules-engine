# Architecture — BFS Traversal + 5-Check Filter Pipeline

## The shape of it

```
User row
   │
   ├─ 1. Permission Compiler ──── O(1) {level: {can_read, can_write}} + clearance set
   │                              compiled ONCE per session
   ├─ 2. Entry Point Resolver ─── department + ceiling → the DAG tier to start from
   │
   ├─ 3. BFS Traversal ────────── up the parent edges, plus a department-scoped
   │                              walk down; visited set; shortest distances
   ├─ 4. Zone 2 Injection ─────── global safety nodes added to the candidate pool
   │                              (after BFS, before the checks)
   │
   ├─ 5. Five Sequential Checks ─ ISOLATION → COMPLIANCE → PERMISSION →
   │                              TEMPORAL → DERIVABILITY, as progressive
   │                              SQL WHERE clauses
   │
   └─ 6. Candidate Assembler ──── annotate: distance, zone, compression hint
                                  → the contract for the Composition Agent
```

Zero LLM calls. Zero embeddings at query time. Zero randomness. `test_pipeline.py`
asserts the output is byte-identical across runs and that no module under
`backend/pipeline/` imports a model client or a network library.

---

## Results

| User | Role | Ceiling | Entry | BFS | +Zone 2 | Final |
|---|---|---:|---|---:|---:|---:|
| Nurse Priya | VIEWER | L10 | Ortho Ward (L10) | 20 | 30 | **13** |
| Dr. Vikram | HOD | L4 | Ortho Dept (L5) | 20 | 30 | **22** |
| Dr. Ananya | EDITOR | L8 | Medicine General (L8) | 13 | 23 | **11** |
| Dr. Sharma | HOD | L4 | Medicine Dept (L5) | 13 | 23 | **15** |
| Pharmacist Ravi | VIEWER | L12 | Hospital (fallback) | 3 | 13 | **8** |
| Dr. Sunita (QA) | QUALITY | L6 | Hospital (fallback, cross-dept) | 50 | 50 | **22** |
| Admin Suresh | ADMIN | L1 | Hospital (fallback, cross-dept) | 50 | 50 | **42** |

Seven users, seven different candidate sets, one graph, one code path.
Pipeline time is 0.7–2 ms against a 500 ms budget.

The setup guide's expected figures are ~15 / ~22 / ~40 for Priya / Vikram /
Suresh. Vikram matches exactly. Priya lands at 13 and Suresh at 42; the
reasons are Decisions 3 and 4 below, and both are arithmetic I can walk
through node by node.

---

## Decision 1 — BFS direction is up, plus a department-scoped walk down

Pure upward traversal from Ortho Ward reaches Ortho General → Ortho Dept →
Clinical Division → Hospital. That is five tiers and it misses the TKR Unit
and the Post-TKR Protocol Area, which are siblings under Ortho Dept rather
than ancestors of the ward. It also misses Priya's own patients, who sit
*below* her at L12.

But an unrestricted walk down from Clinical Division would hand her
Cardiology, Paediatrics and ICU, which is the exact failure the assessment
is about.

So: **ascend freely through department-less tiers and your own department;
descend only into tiers owned by your own department.** Department isolation
becomes a structural property of the traversal, enforced before any check
runs, rather than something check 1 has to clean up afterwards.

This yields 20 reachable nodes for Priya, which is the "~20" the setup guide
predicts.

## Decision 2 — a multi-parent node is not a bridge between departments

Post-TKR Protocol Area has `parent_ids = [Ortho, Surgery]`. The visited set
handles the obvious part: it is enqueued from both paths but processed once,
at its shortest distance.

The subtler part is what happens *above* it. Naive upward traversal walks
from Post-TKR into Surgery Department, and Priya has just acquired another
department's tier through a shared child. On this seed data nothing leaks
(Surgery has no nodes), but the general case is a real privilege-escalation
path: co-own one node with a department and inherit its whole subtree.

The rule is therefore: ascend into department-less tiers and your own
department; refuse a parent belonging to a foreign department. Refusals are
recorded on `TraversalResult.blocked_foreign_parents` and surfaced in the demo
notes, so the containment is visible rather than implicit.

This answers "which department's ceiling applies to a multi-parent node?" —
neither. The node is reachable from both, and reachability through it confers
nothing about the co-parent.

## Decision 3 — Zone 2 is exempt from the permission ceiling

The setup guide's rule for check 3 is `hierarchy_level >= ceiling_level`, and
the Zone 2 notes say injected nodes may still be excluded by the ceiling.
Applied literally to Priya those two statements delete every drug-safety
constraint she has: the global nodes live at HL-GLOBAL (L3), her ceiling is
L10, and 3 is not >= 10. Scenario 4 — "Zone 2 saves lives" — would have
nothing to show, and the opening story about a nurse needing the
Warfarin/NSAID rule inverts.

The resolution is that a Zone 2 node's hierarchy position records **where it
was authored, not who may read it**. A hospital-wide safety rule is published
at the root *to everyone*; that is what "global" means. Zone 2 is therefore
exempt from the ceiling, and only from the ceiling — it still passes through
isolation, compliance, temporal and derivability. The proof that it is an
exemption rather than a hole: `N-G04` (0.75) and `N-G06` (0.80) are Zone 2
nodes and are still removed by check 5, and `test_zone2_nodes_still_pass_
through_all_five_checks` asserts it.

This is a flag (`RolePolicy.zone2_bypasses_ceiling`), not a hardcode.

## Decision 4 — the permission check has two modes, and the spec supports both

Here is the sharpest contradiction in the brief, stated plainly.

- The AI starter prompt says a VIEWER can read levels `>= ceiling`. Priya's
  ceiling is 10.
- The sample candidate set for Priya contains `N-O02` (Paracetamol
  First-Line Post-TKR), which sits at **L8**.
- The mock UI also shows her "Post-op vitals q15min first 4hrs" — `N-O01`, at
  **L5**.

Under the literal rule, both are invisible to her. Under a rule permissive
enough to include them, the ceiling stops constraining her at all, because
BFS has already restricted her to her own branch.

Rather than pick silently, both are implemented:

**`strict` (default).** The ceiling applies to every node's own tier. Priya
gets 13: her ward, her patients, and the globals. Department protocols at L5
and L8 are above her ceiling.

**`scope_aware`.** BFS has already proved a tier sits inside the user's own
branch, so the ceiling does not re-litigate it; it still bites on tiers reached
by a cross-department fallback walk. Priya gets 21, including `N-O01` and
`N-O02`.

`strict` is the default because it matches the stated rule and lands closest
to the published counts. But I think `scope_aware` is the better production
model, and the reason is visible in the data: `N-O01` (post-op vitals
monitoring, importance 0.94) and `N-O06` (DVT prophylaxis, 0.93) are
*department-level records of ward-level clinical practice*. A nurse who
cannot see the DVT prophylaxis protocol cannot do her job safely. The real
defect is the modelling — those nodes describe hospital-wide clinical safety
and should be Zone 2, not Zone 1 at L5. A ceiling is the right tool for
withholding a budget spreadsheet and the wrong tool for withholding a
prophylaxis protocol.

Switch with `?mode=scope_aware` or the dropdown in the UI.

## Decision 5 — compliance clearance is derived from role, not just the row

The setup guide gives Vikram `compliance_clearance = '{}'`, and simultaneously
expects him to see `N-O11` (the MNPI budget node) but not `N-O12`
(MNPI + CONFIDENTIAL). With an empty clearance array he sees neither.

So clearance is compiled from two sources: whatever is on the user row, plus
whatever the role policy grants implicitly. A HOD implicitly clears MNPI —
**scoped to their own department**, because a head of Orthopaedics has no
business in Cardiology's trial data. An admin clears everything. An auditor
clears MNPI across departments.

A node is withheld unless the user clears **every** tag it carries, not any —
which is what separates `N-O11` from `N-O12` and produces exactly the
behaviour the guide describes. Vikram lands on 22, the published figure.

Unknown roles fall through to `DEFAULT_POLICY`, which grants nothing. Fail
closed: `test_unknown_role_is_not_granted_privilege` sends in
`CHIEF_WIZARD` at ceiling 1 and asserts they get no MNPI.

## Decision 6 — check order, and why sequential is not a formality

Ordered by blast radius, not by cost:

1. **Isolation** — a cross-tenant row must not be evaluated by any later rule.
2. **Compliance** — legal exposure. An MNPI node should be gone before
   anything reasons about org structure.
3. **Permission** — organisational authority.
4. **Temporal** — correctness. A superseded protocol is worse than no protocol.
5. **Derivability** — relevance, and the only one that is a quality judgement
   rather than a security one. It runs last because it is the only check whose
   failure is merely wasteful.

On this dataset, running them in parallel would produce the same final set.
The order still matters for two reasons. Every check would otherwise evaluate
rows it has no business reading — check 3 would compute permission on nodes
compliance had already condemned. And the audit trail would attribute
exclusions to the wrong rule: `N-A01` would be recorded as "above your
ceiling" when the truthful, legally relevant answer is "MNPI, and you are not
cleared". Order encodes intent, and the audit log is where that intent has to
survive.

## Decision 7 — the checks run in SQL (GAP 5)

The alternative is fetching all 50 nodes into Python and filtering there.
That fails: restricted content has already crossed the network boundary, and
discarding it afterwards is politeness rather than access control.

`Repository.run_checks` ANDs the predicates progressively. Stage *k* runs with
predicates 1..*k*, so the row set entering check *k+1* is literally the row set
that survived check *k* — sequential by construction — and every stage is
evaluated by the database. Only the final survivors have their content read.

Funnel counts come from `COUNT(*)` per stage, so the numbers on screen are the
database's own count, not Python's bookkeeping.

`supabase/rls_policies.sql` pushes checks 1–4 into Row-Level Security as
defence in depth. That is the answer to "what if someone bypasses the API and
queries the database directly?" — they get the same filtered rows, because the
policy is on the table.

Check 5 is deliberately **not** in RLS. Derivability is a relevance judgement,
not access control; enforcing it at the database level would mean Postgres
refuses to show an administrator a node purely because it is obvious. Security
checks belong in RLS, quality checks belong in the pipeline.

## Decision 8 — silent exclusion is a property of the response shape

`PipelineResult` has two serialisers. `to_public_dict()` returns the candidate
set and the funnel and nothing else: no removed count, no placeholder rows, no
403, no "3 nodes restricted". `to_audit_dict()` explains every exclusion and
is reachable only via `/api/audit`, which is operator-gated.

They are separate methods rather than one method with a flag, because a flag
is one careless `if` away from leaking. `test_public_response_reveals_nothing_
about_exclusions` greps the serialised response for "denied", "restricted",
"hidden", "redacted" and friends.

Audit mode fetches node **ids and titles only**, never content — so even the
operator trail does not become a back door to the material itself.

## Decision 9 — derivability without an LLM

The problem: "Paracetamol is an analgesic" is derivable; "Supra uses
Paracetamol 650mg QDS as first-line post-TKR pain" is not. Both are about
paracetamol, so topic does not separate them.

What separates them is whether the sentence contains anything that could only
be true *at this organisation*. A general-knowledge statement appears in a
textbook unchanged. An organisational statement carries a fingerprint: a
hospital name, a named clinician, a rupee figure, a local incident, a policy
verb, a named patient, a versioned local document.

`backend/derivability/scorer.py` scores from a 0.50 baseline using two
opposing signal families — definitional/textbook phrasing pushes up,
organisational fingerprints push down. It runs as a **batch pre-computation at
ingest**, never in the request path, which is what keeps the engine honest
about being zero-LLM and inside its latency budget. At query time check 5 is
one indexed numeric compare.

Calibration against the seeded scores: **96% agreement** on which side of the
0.7 threshold each of the 50 nodes falls — and that is the only thing check 5
consumes. The scorer explains itself (`Explanation.generic_hits` /
`specific_hits`), so any score can be interrogated.

The two disagreements are worth more than the agreements:

- **N-G04** (Hand Hygiene) — seeded 0.75, computed 0.10.
- **N-G06** (Patient Identification) — seeded 0.80, computed 0.36.

Both are seeded as derivable, and the WHO 5-moment framework genuinely is
general knowledge. But both nodes also carry Supra's own numbers — "Supra
target: 95%. Current: 88%" — which no model knows. My scorer sees the local
metric and marks them organisational. **I think these nodes are doing two jobs
and should be split**: the protocol is derivable, the compliance figure is
not. That is a data-modelling finding, surfaced by the scorer disagreeing with
its own training labels, which is the useful thing a calibration harness does.

An embedding-based scorer would be a strict improvement on recall and is
compatible with the constraint, provided it stays a batch job. Noted as future
work rather than built, because it would need a medical reference corpus to be
better than the heuristic rather than merely more impressive.

## Decision 10 — cycle prevention at three layers

The graph is declared acyclic, so a cycle is a bug, not a case to tolerate.

1. **Runtime**: the visited set means BFS terminates on a cyclic graph rather
   than looping. `test_bfs_terminates_on_a_cyclic_graph` injects a real cycle
   and proves the traversal halts.
2. **Load time**: `detect_cycles()` runs an iterative three-colour DFS over the
   parent graph — iterative rather than recursive so a deep graph cannot blow
   the stack. `/health` reports `graph_acyclic`.
3. **Write time**: `would_create_cycle(child, new_parent)` rejects the edge
   before insert, and `supabase/schema.sql` carries the same guard as a
   Postgres trigger using a recursive CTE. Rejecting at the door beats
   detecting at query time.

---

## Scaling to 15,000 nodes across 12 hospitals

Nothing in the hot path is proportional to total graph size.

- **BFS** walks the *hierarchy DAG* (tens of tiers), not the knowledge nodes.
  Priya's traversal touches 8 tiers whether the estate holds 842 nodes or
  15,000. Adding hospitals adds branches she never enters.
- **Checks 1–4** are indexed SQL predicates. Every one has a supporting index,
  plus a composite on `(org_id, hierarchy_level, status, derivability_score)`
  covering the hot path. They scale with the index, not the table.
- **Check 5** is a pre-computed column. The scoring cost moves to ingest, where
  it is amortised, and stays out of the request.
- **Permission compilation** is O(15) — fifteen tiers — regardless of anything.

The thing that would need attention first is not the query but the candidate
*level* list: a cross-department admin at 12 hospitals produces a large
`IN (...)`. The fix is to push traversal into the database as a recursive CTE
so the level set never round-trips, which keeps the whole pipeline one query.
Multi-tenancy would move from a `WHERE` clause to partitioning on `org_id`.

## What I did not build, on purpose

- **The Composition Agent.** The brief ends at the candidate set; that is the
  contract boundary.
- **Authentication.** A dropdown, as instructed.
- **A node editor.** The graph is static for this assessment.
- **Embedding-based derivability.** Compatible with the constraints as a batch
  job, but it needs a reference corpus to beat the heuristic.

## Known gaps

- **Frontend is vanilla HTML/CSS/JS, not React + Tailwind.** Deliberate: it is
  one self-contained file with no build step and no CDN, so it cannot fail
  mid-demo because a network request timed out. The tradeoff is real and the
  port is mechanical — the API is plain JSON and the components map one to one.
- **Default store is SQLite, not Supabase.** `SupabaseRepository` implements
  the same interface and `supabase/` holds schema, seed and RLS policies. The
  swap is one line in `backend/main.py`. SQLite is the default so the demo
  starts with zero installs and zero credentials.
- **Per-check timings are apportioned, not individually measured.** The five
  checks execute as five progressive SQL statements; timing each separately
  would mean five extra round trips to report a number that is already under
  2 ms in total.
