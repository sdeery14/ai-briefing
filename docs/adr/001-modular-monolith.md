# ADR 001 — Modular monolith, independent of Home Assistant

**Status:** Accepted (owner, 2026-11-21)
**Date:** 2026-11-19 (revised for RFC v0.3)

## Context

The engine should be usable by anyone with Python and an API key. The Raspberry Pi is an inexpensive first host, not a product dependency. The workload is a small daily batch: a few hundred documents, a few hundred model calls, one briefing.

## Decision

1. One Python package, run as short-lived CLI jobs. No long-running service, queue or broker.
2. Modules as listed in RFC §3.3. The `domain` module contains typed records and pure rules and imports no I/O library.
3. Database commits happen at application-service boundaries. Each stage reads rows in a known state and writes its result in one transaction.
4. The engine never imports Home Assistant code, never calls Home Assistant, and never sends email. Integration is by files (ADR-006).
5. Clock, HTTP transport and model client are injected.
6. Apache-2.0 licence.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Agent or workflow framework as the application skeleton | The pipeline is a fixed sequence; see ADR-009 |
| Separate services for collection, assessment and delivery | Adds deployment and failure modes with no scaling need |
| A Home Assistant add-on or custom integration | Makes Home Assistant a dependency and ties releases to it |

## Consequences

Simple deployment and tests. One process to reason about. Module boundaries are conventions enforced by an import check, not by process isolation.

## Acceptance checks

- A test fails if `domain` imports a network, database or filesystem library.
- A fresh clone installs and produces a briefing from recorded fixtures with no Home Assistant, MLflow or network.
- No module imports from a Home Assistant package.

## Revisit when

A second consumer needs concurrent access, or a stage's runtime no longer fits a scheduled job.
