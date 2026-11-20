# ADR 009 — AI engineering, observability, and evaluation stack

**Status:** Proposed for owner and independent architecture review  
**Date:** 2026-11-19

## Context

AI Briefing runs deterministic collection, source inspection, LLM-based editorial analysis, and briefing composition. A green software test does not demonstrate high-quality editorial decisions. The initial runtime is the `homenvr` Raspberry Pi, which already hosts an MLflow tracking server backed by PostgreSQL and MinIO. The application must be usable on other machines and must not become dependent on that server. The owner has experience with MLflow and custom deterministic/LLM evaluation pipelines in the Home System project.

LangChain/LangGraph are orchestration tools, whereas LangSmith, Langfuse, and MLflow provide overlapping but different tracing/evaluation capabilities. Introducing an orchestration framework solely for observability or agent branding would add avoidable complexity.

## Decision

1. **Orchestration stays plain Python in V1.** Use explicit, bounded services/jobs and typed input/output contracts. Do not require LangChain, LangGraph, or an autonomous multi-agent framework. Reassess LangGraph only if actual workflows require durable stateful branching, resumption, human interrupts, or complex tool-mediated research loops.
2. **MLflow is the default optional observability backend.** Reuse the existing Home System MLflow installation where available, with separately named AI Briefing experiments and correlation metadata. The domain layer, job completion, and structured local logs must work when the tracking server is unavailable. Prefer the lightweight MLflow client footprint on the Pi; verify package and runtime overhead on ARM64.
3. **Instrument the whole pipeline, not just model calls.** Trace or log collection, normalization, clustering, editorial assessment, bounded research, composition, publishing, and the evaluation runner. Maintain a `run_id`/`story_id`/`assessment_id` correlation chain. Capture model identifier, prompt/rubric/config version, duration, token counts, approximate cost, retries, and error classification. Use minimal referenced evidence, not full source dumps, in default tracing.
4. **Own domain-specific evaluators; reuse platform capabilities.** Implement deterministic checks for schema, duplicate/merge rules, allowed-as-of evidence, source-link integrity, cost/budget constraints and reproducibility. Implement typed LLM-as-judge rubrics for groundedness, editorial discrimination, uncertainty calibration, composition quality and curriculum continuity. Use MLflow GenAI evaluation/datasets/experiments where they reduce glue, without making correctness or offline execution depend on MLflow.
5. **Calibrate judges independently.** Pin judge model IDs, rubric prompts, and versions; record the judge's decisions and trace separately. Test judge/human agreement and review disagreements. LLM-judge agreement is not independent factual verification. Deterministic tripwires always take precedence over positive judge scores.
6. **Separate offline and production evaluation.** Offline benchmark execution must work without network calls and may not require credentials or MLflow. Production jobs may emit sampled quality assessments and traces under explicit budgets. The private holdout answer key, raw individual holdout scores, sensitive user context and API keys must not enter the repository, CI, coding-agent context, or any shared/agent-accessible trace store.
7. **Observe before optimizing.** Initial quality metrics have no arbitrary pass thresholds. Establish human-adjudicated baselines and document allowed tolerances before enforcing editorial regression gates. Code/schema/security checks can gate merges immediately; changes to judge criteria, evaluation thresholds, source permissions, prompts, models and deployment configuration require owner review.
8. **Backend portability remains a boundary.** Keep core evaluation results in versioned, portable typed records so LangSmith, Langfuse, OpenTelemetry, or a different tracking backend can be evaluated later. Do not build a custom tracing UI or duplicate a full experiment-tracking platform in V1.

## Consequences

- Reuses existing infrastructure, minimizes the number of services on the Pi, and retains inspectable research/evaluation runs.
- Adds thin instrumentation and adapter boundaries plus discipline around trace payload privacy and benchmark leakage.
- Sacrifices some ready-made agent orchestration and LangSmith-specific UX in return for a simpler, independently testable pipeline.
- Custom code is limited to AI Briefing-specific rubrics, data validation, and evaluation reports—not general-purpose tracing, storage or experiment UI.

## Acceptance checks

- A full simulated collection → evaluation → briefing run produces correlated local job records and, with MLflow enabled, browsable stage traces.
- The same run completes with MLflow down; the failure is logged and no business result is lost.
- An offline evaluation passes with no model API access and no tracking server.
- A deterministic citation/evidence failure cannot be overridden by a high LLM-judge score.
- Prompt, model, rubric and application commit versions can be recovered for any persisted editorial assessment.
- Holdout labels and user secrets are absent from code, CI artifacts, model prompts and exported traces.

## Revisit when

The real research workflow proves to require durable agent orchestration, MLflow creates measured maintenance/performance problems on ARM64, or a short trace/evaluation UX comparison demonstrates a material benefit from another backend.
