# ADR 006 — Versioned briefing data product with read-only Home Assistant consumer

**Status:** Proposed

## Context

The existing 7am HA email already integrates calendar, GitHub, Alfred persona and Resend. Replacing it couples unrelated domains and risks delivery outages.

## Decision

Generate versioned daily JSON and renderers. Initially publish atomically to a read-only shared host mount. HA reads/validates it and retains full responsibility for sending; stale/missing results are silently omitted with diagnostics.

## Consequences

A local shared filesystem is simpler than an API on one host; remote consumers later require a separate authenticated transport.

## Revisit when

A specific observed requirement or failure invalidates the current tradeoff. Changes to an accepted decision require a superseding ADR.
