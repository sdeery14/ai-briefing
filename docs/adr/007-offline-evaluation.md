# ADR 007 — Blind offline editorial benchmarking before live ranking

**Status:** Proposed

## Context

A language model can produce convincing but poor editorial judgments, and historical labels can leak future knowledge.

## Decision

Start with typed predictions and a reproducible offline harness. Keep private holdout labels outside agent/CI environments; use only evidence before each cutoff. Require human adjudication before fixed accuracy gates.

## Consequences

The seed 40-card set tests editorial classification, not discovery recall; future candidate-complete days and frozen snapshots will be separate test assets.

## Revisit when

A specific observed requirement or failure invalidates the current tradeoff. Changes to an accepted decision require a superseding ADR.
