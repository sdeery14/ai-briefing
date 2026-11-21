# ADR 002 — SQLite as the system of record, with append-only history

**Status:** Accepted (owner, 2026-11-21)
**Date:** 2026-11-19 (revised for RFC v0.3)

## Context

The system must explain every briefing item: which documents were seen, what the model was shown, what it said, what the policy decided and why. It runs on a shared, modest host. The independent review found that the v0.1 model could not answer "what did the assessor see?" after a story changed, and that evidence was not a record at all.

## Decision

1. **SQLite**, accessed through SQLAlchemy, migrated with Alembic in batch mode. It is the operational system of record for data, job history and model-call history.
2. **Entities** are those in RFC §5. The additions since v0.1 are `ScreeningDecision`, `StoryMembershipEvent`, `AssessmentInput`, `EvidenceItem`, `EditorialDecision`, `ConceptNote`, `ComparisonJudgment` and `LLMCall`.
3. **Append-only history.** Observations, membership events, assessments, evidence items, decisions and briefing versions are never updated or deleted, with one exception: body text is nulled by the retention job (ADR-010), leaving the hash.
4. **Assessment input snapshot.** Every assessment records the observation IDs it was given and a hash of that set.
5. **Model output and policy output are separate records.** `EditorialAssessment` is what the model returned. `EditorialDecision` is what the policy concluded from it.
6. **Idempotency.** Documents are unique on source and external ID. Assessments are unique on story, input hash, prompt hash and model ID. Briefings are unique on local date, variant and version. Feedback is unique on event ID. `JobRun` carries an idempotency key.
7. **One writer.** An OS file lock (`flock`) around each job. No database lease table.
8. **Settings.** WAL mode, foreign keys on, a busy timeout. Timestamps in UTC; briefings also store local date and time zone.
9. **Storage and backup.** The database lives on reliable persistent storage, not on boot microSD (ADR-008). Snapshots use `VACUUM INTO` or the online backup API and are copied off the device.

## Alternatives considered

| Alternative | Why not |
|---|---|
| The Home System's existing PostgreSQL | Creates the dependency ADR-001 rules out |
| Mutable story and assessment rows | Loses the audit trail that evaluation depends on |
| Event sourcing throughout | More machinery than a single-writer batch needs; a current-state table plus an event log for membership is enough |
| A database lease with heartbeats | Stale-lease handling for no benefit on one host |

## Consequences

Write concurrency is limited to one job at a time, which the schedule already assumes. History grows without bound except for bodies; at the expected volume this is on the order of a gigabyte a year (an estimate to be confirmed in M1).

## Acceptance checks

- Running any job twice with the same idempotency key creates no new rows.
- For any briefing item, a query returns the decision, the assessment, the exact observations shown to the model, and the evidence items with their integrity status.
- After a story merge, earlier assessments still resolve to the observations they saw.
- A snapshot taken while a job is running restores to a consistent database.
- The first migration applies and downgrades cleanly on SQLite.

## Revisit when

A second writer is needed, the database exceeds what a nightly snapshot can copy comfortably, or query needs outgrow relational filters and full-text search.
