# Data Sources

## Summary

Every row in this project comes from the assessment's own Setup Guide. Nothing
was scraped, purchased, generated from a model, or taken from any real
clinical system. There is no patient data here, real or derived.

| Data | Rows | Source | File |
|---|---:|---|---|
| Organization | 1 | Setup Guide, "Seed Data — Organization + Hierarchy" | `backend/data/seed_data.py` |
| Hierarchy levels (DAG) | 20 | Setup Guide, same section | `backend/data/seed_data.py` |
| User profiles | 7 | Setup Guide, "Seed Data — 7 Users" | `backend/data/seed_data.py` |
| Knowledge nodes | 50 | Setup Guide, "Seed Data — 50 Knowledge Nodes" | `backend/data/seed_data.py` |
| Typed edges | 10 | Setup Guide, "Seed Data — Edges" | `backend/data/seed_data.py` |

`backend/data/seed_data.py` is the single source of truth.
`scripts/generate_sql.py` emits `supabase/seed.sql` from it, and
`SQLiteRepository.seed()` loads the same structures into SQLite, so the two
databases cannot drift.

## The clinical content is fictional

"Supra Multi-Specialty Hospital" is an invented organisation supplied by the
assessment. Patients Rajan, Padma and Aadhya are invented. Named clinicians
(Dr. Vikram, Dr. Sharma, Dr. Mehta) are invented. Budget figures, board
resolution numbers, vendor negotiations, the ATOM-2026 trial and the NABH
accreditation status are all invented.

The clinical statements — the Warfarin/NSAID interaction, penicillin
cross-reactivity rates, Morse Fall Scale thresholds, DVT prophylaxis dosing —
are broadly consistent with published practice, but they arrived as
**assessment fixtures and are treated as such**. They exist to exercise a
filtering pipeline. Nothing in this repository should be read as clinical
guidance, and no output of this system is a clinical recommendation.

This matters for one reason beyond good manners: the whole point of the
derivability check is that some of these statements are general knowledge and
some are organisation-specific. That distinction is only meaningful because
the organisation is fictional and self-consistent.

## Test fixtures are not seed data

`backend/tests/test_temporal_and_metadata.py` inserts three fixture nodes
(`N-TEST-EXPIRED`, `N-TEST-FUTURE`, `N-TEST-REPLACED`) and
`test_surprise_users.py` briefly creates an Oncology tier. These exist only
inside the test database and are removed or discarded when the test run ends.
They are needed because the supplied dataset contains no node with an expiry
date and only six departments, so the `valid_until` path and the
new-department path have nothing to exercise otherwise.

**None of these are added to `backend/data/seed_data.py`.** The assessment
dataset is used exactly as supplied: 50 nodes, 7 users, 20 tiers, 10 edges.

## Data I derived rather than copied

Three fields are computed, and it is worth being explicit about which:

**`required_tags`** (SQLite only) — a denormalisation of `compliance_tags`
into a `,MNPI,CONFIDENTIAL,` shaped string, so the compliance check stays a
SQL predicate on a store with no array type. PostgreSQL uses the native
`TEXT[]` with a GIN index and needs no equivalent.

**`hierarchy_level`** — copied from `hierarchy_levels.level_number` onto each
node at load time so the permission check is an indexed integer compare rather
than a join. A Postgres trigger keeps it in step; see `supabase/schema.sql`.

**Recomputed derivability scores** — `backend/derivability/scorer.py` produces
its own score for every node from the title and content. **These are not
written to the database and are not used by the pipeline.** Check 5 reads the
`derivability_score` shipped in the seed data, exactly as the FAQ specifies.
The scorer exists as a calibration harness: it demonstrates how the score
would be computed at ingest without an LLM, and reports where it disagrees
with the seeded labels. See `/api/derivability` and Decision 9 in
`architecture.md`.

## No external services

The pipeline makes no network calls of any kind. No LLM API, no embedding
service, no medical reference API, no telemetry. `test_pipeline.py` asserts
that no module under `backend/pipeline/` imports `openai`, `anthropic`,
`requests`, `httpx`, `urllib.request`, `transformers`,
`sentence_transformers`, `langchain` or `socket`.

The default SQLite store means the demo runs fully offline. The Supabase path
is the only thing that requires credentials, and those go in `.env`, which is
gitignored; `.env.example` carries placeholders only.

## Licensing

The seed content was supplied by Astroum AI as part of this assessment and
remains theirs. The pipeline implementation, schema, scorer, tests and
frontend in this repository are my own work, written for this assessment.
