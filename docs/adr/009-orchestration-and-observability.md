# ADR 009 — Plain-Python orchestration, one provider, and narrow observability

**Status:** Proposed
**Date:** 2026-11-19 (revised for RFC v0.3; previously "AI engineering, observability, and evaluation stack". Evaluation content moved to ADR-007.)

## Context

v0.1 proposed plain-Python orchestration with MLflow spans on every pipeline stage, MLflow evaluation tooling and a portability layer for other backends. The review agreed with the orchestration choice and found the observability design over-scoped: it duplicated what the database already records, and it carried risks for short-lived jobs.

The Home System's own notes record that exporting traces inline blocked its event loop and had to be moved to a worker thread. Its MLflow server image is unpinned, so the running version is not known from the repository.

## Decision

### Orchestration

1. Plain Python. No LangChain, LangGraph or agent framework.
2. Control flow is code. Each stage is a query for rows in a given state followed by an idempotent write, so the database is the checkpoint and re-running is the resume.
3. The model has no tools. It never selects a URL and cannot trigger a network request or any other action.
4. Escalation is a single bounded step decided by code. There is no loop directed by the model.

### Model provider

1. One provider. The interface is defined per task, for example `assess(story_packet) -> Assessment`, not as a generic chat abstraction.
2. The provider's schema-constrained output is used, validated with Pydantic, with one bounded retry. The raw response is stored.
3. Two tiers: an inexpensive model for screening, standard assessment, the baseline digest and the concept note; a capable model for escalated assessments.
4. Model identifiers, the price table and budgets are in `config/models.yaml`, a protected file.
5. No routing library and no second provider until a concrete need exists.

### Cost control

1. A provisional budget of $15 per calendar month, enforced in the `llm` module.
2. Before each call, the maximum possible cost is estimated. A call that would exceed the remaining monthly budget or the day's allowance is refused and the refusal recorded.
3. Actual usage is recorded after each call.
4. Shedding order and degraded behaviour are defined in RFC §7.

### Observability

1. **System of record:** SQLite. `JobRun` records each job. `LLMCall` records every model call: purpose, prompt identifier and hash, provider, model, token counts, estimated cost, price table version, latency, status, retries, and references to the stored request and response.
2. **Logs:** structured JSON, one event per line, carrying job and entity identifiers.
3. **Prompts** are files in the repository identified by content hash.
4. **Tracing is optional.** A `Tracer` protocol has a no-op default. The MLflow implementation wraps model calls, job roots and a small number of important operations (composition, export). Deterministic stages are covered by job records and logs and are not traced individually.
5. **Client.** The lightweight MLflow tracing package is used in the runtime image, where it is compatible with the server. Full MLflow is not installed on the Pi.
6. **Failure behaviour.** Nothing in application logic reads from MLflow. Export has a short bounded timeout and an explicit flush at job end. A job with tracing enabled and the server unreachable completes normally.
7. **Content.** Traces carry identifiers and metadata by default, not article text. Private labels and credentials never enter a trace. The Home System MLflow store is reachable from development machines and is treated as readable by coding agents.
8. **Experiment tracking.** Evaluation result files (ADR-007) may be logged to MLflow from the development machine for comparison. Evaluation logic does not depend on it.

## Alternatives considered

| Alternative | Assessment |
|---|---|
| LangGraph | Offers durable checkpoints, resumable branching and human interrupts. The database already provides the first two for a batch job, and there are no interrupts. |
| LangChain provider wrappers | Sit between the code and native structured output, which this design depends on |
| MLflow spans on every stage | Duplicates `JobRun`; more code on every stage |
| No MLflow | Simplest, but loses a trace view the owner already uses |
| Langfuse, self-hosted | Requires ClickHouse, Redis, blob storage and PostgreSQL, with documented memory minimums well beyond this host |
| Langfuse Cloud or LangSmith | An external account and data leaving the host, for no capability needed yet. LangSmith self-hosting is limited to its Enterprise plan. |
| A backend-portability layer | The no-op protocol already keeps the backend replaceable |

## Consequences

The MLflow UI shows model calls and job roots, not the whole pipeline. The database is where a run is explained. The price table must be kept current by hand.

## Acceptance checks

- A full run with tracing disabled leaves complete `JobRun` and `LLMCall` records.
- The same run with tracing enabled and the tracking URI pointing at a closed port finishes within a bounded extra time and loses no business result.
- For any stored assessment, the prompt hash, model identifier, application version and cost can be recovered from the database alone.
- A call that would exceed the budget is not sent, and a refused-call record exists.
- No code path lets model output cause a network request.
- The runtime image does not contain the full MLflow package.

## Revisit when

A workflow needs more than one model-directed step, the tracing client proves incompatible with the server or troublesome on ARM64, or measured cost shows the budget or tiering is wrong.
