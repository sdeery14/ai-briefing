# M1 — Foundation & offline editorial evaluation (proposed)

Do not create GitHub issues or run `/round` until the RFC and ADRs are reviewed and accepted. One issue/PR per independently testable unit, with explicit acceptance criteria. Do not make a single broad "build the app" issue.

1. **Packaging, typing, CI.** `uv`-managed Python package and CLI entrypoint; Ruff, strict mypy, pytest, CI; no runtime network calls in tests. `ai-briefing --help` works from clean checkout.
2. **Domain schemas.** Pydantic/typed models for candidate cards, evidence references, evaluation inputs, ordinal scores, dispositions and coverage actions. Reject missing citations or scores outside 0–4. No external side effects.
3. **Offline evaluator.** Read public case JSONL and prediction JSONL; emit deterministic JSON summary (macro-F1, major recall, false-promotion rate, action/merge metrics, per-dimension MAE); explicit handling of missing/duplicate IDs and zero denominators.
4. **Test fixtures and time travel.** Fake clock and transport; `as_of` cutoff enforced; test that future-dated evidence is not ingested into the evaluation; tests cannot call live model APIs.
5. **Evaluation provider boundary.** Protocol for editorial judgment; deterministic baseline/rule-based stub plus injectable LLM adapter interface. The LLM adapter implementation may be a later issue; do not optimize against private holdout labels.
6. **Optional observability boundary.** Structured event/trace interface with no-op fallback when MLflow is unavailable. Verify correlation IDs, trace redaction and offline operation; implementation must not start a tracking server for tests.
7. **Blind benchmark process.** Documentation and one owner-run command for private scoring outside the repository/agent workspace. Public calibration labels OK; private labels prohibited in artifacts, CI and trace exports. Audit published package fields for accidental leakage.

### `round` adaptation, before any unattended merges

Reuse the ProjectBudget orchestration *pattern* rather than blindly copying project paths/commands. Transfer `pr_wait.py`, review-thread control and issue/PR conventions after review of licensing and cross-repository assumptions. All decisions and high-risk files require owner approval: `docs/adr/**`, `docs/rfc/**`, DB migrations, dependencies, GitHub workflows, security/network/policy config, grading thresholds, model prompts/rubrics, deployment/email paths. No tags or releases from `/round`. The PR reviewer checks for evidence leakage and rubric changes as well as code quality. Do not let the implementation agent see the holdout answer key or private scoring logs.

### M1 exit review

- All seven issues have independently testable done-when criteria and no public secrets or private labels.
- Fresh clone runs all checks offline; dependency installation only requires package registries.
- Baseline editorial prediction can be scored against calibration labels, and private scoring is possible outside agent access.
- No benchmark thresholds are chosen until provisional labels have been adjudicated and a baseline measured.
