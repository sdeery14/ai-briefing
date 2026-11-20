# ADR 008 — Scheduled Raspberry Pi jobs with bounded privileges

**Status:** Proposed

## Context

The home Pi shares resources with multiple services and may host Frigate later; arbitrary model or network activity creates operational and security risk.

## Decision

Use short-lived scheduled container CLI jobs with explicit concurrency, budget, storage and network bounds. Treat internet content as data, not instructions. Keep secrets and HA permissions outside the research engine.

## Consequences

Requires CPU/memory/storage headroom validation, clear error/fallback policy, online SQLite backup and guarded deployment review.

## Revisit when

A specific observed requirement or failure invalidates the current tradeoff. Changes to an accepted decision require a superseding ADR.
