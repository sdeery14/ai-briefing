# ADR 001 — Modular monolith independent of Home Assistant

**Status:** Proposed

## Context

The intelligence engine should be shareable and runnable without the existing Home System; the Raspberry Pi is initially an inexpensive host, not a product dependency.

## Decision

Use a Python modular monolith with CLI entrypoints and narrow adapters. The engine never imports Home Assistant components or sends personal email.

## Consequences

Simple deployment and tests; integration belongs to a small independent adapter. Additional service boundaries can emerge from demonstrated demand.

## Revisit when

A specific observed requirement or failure invalidates the current tradeoff. Changes to an accepted decision require a superseding ADR.
