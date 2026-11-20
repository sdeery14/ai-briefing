# ADR 003 — Hybrid scheduled discovery and bounded research

**Status:** Proposed

## Context

Curated monitoring is reliable but may miss new subjects. Open-ended agents can be expensive, unpredictable and hard to audit.

## Decision

Use feed/API adapters and cheap triage first, add bounded search discovery, then targeted AI research only for promising or disputed stories. Preserve source provenance and job costs.

## Consequences

Some breadth is sacrificed to strict budgets; adapters, query policies and source health become explicit responsibilities.

## Revisit when

A specific observed requirement or failure invalidates the current tradeoff. Changes to an accepted decision require a superseding ADR.
