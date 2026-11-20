# ADR 002 — SQLite with provenance and immutable editorial history

**Status:** Proposed

## Context

A collection system must track revisions, deduplicated stories, time-based decisions and prior briefings. Pi resources favor a single local store.

## Decision

Use SQLite with migrations and one logical writer. Preserve source-document observations, story relationships, versioned assessments and briefing versions; add query-level interfaces for future retrieval.

## Consequences

No PostgreSQL dependency; write concurrency remains limited; WAL-aware backup and restore testing are mandatory.

## Revisit when

A specific observed requirement or failure invalidates the current tradeoff. Changes to an accepted decision require a superseding ADR.
