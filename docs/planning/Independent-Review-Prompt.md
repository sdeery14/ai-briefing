# Independent architecture-review prompt for Claude Code

Review the attached **proposed** AI Briefing RFC v0.1 and all proposed ADRs as an independent senior software architect, ML evaluation engineer and security reviewer. **Do not implement anything yet.** Challenge the plan rather than agreeing by default.

Specifically:

1. Does the MVP provide a valuable complete user journey without overbuilding collection, clustering, research, curriculum or Home Assistant integration?
2. Are the service boundaries and logical data model adequate for provenance, document revisions, multi-source stories, immutable assessments, temporal cutoffs, idempotent scheduled jobs and future sharing?
3. Do the classification and evidence policies actually distinguish significance from virality, marketing, novelty and adoption? Where could the model hallucinate citations or infer too much from promotional evidence?
4. Can the 40-case seed benchmark support the conclusions claimed? Find label leakage, source-snapshot gaps, replay contamination, poor negative coverage, unadjudicated labels and misaligned quality gates.
5. Are the Raspberry Pi 4B deployment, SQLite locking, file-based HA handoff and fallback safe and operable alongside Home Assistant, MLflow/PostgreSQL/MinIO and possible future Frigate?
6. Are source acquisition, SSRF defenses, robots/ToS, prompt injection, secrets, observability, historical content rights and backup/restore appropriately bounded?
7. Which decisions should be reversed, deferred, or tested with a spike before being enshrined in an Accepted ADR?
8. Is the proposed ADR-009 stack (plain Python orchestration, optional MLflow observability, custom scorers with MLflow GenAI integration) justified versus LangSmith, Langfuse, or LangGraph? Check trace portability, judge calibration, separation of production/offline eval, ARM64 overhead, and leakage of sensitive/holdout data.
9. How should the existing ProjectBudget `/round` skill and Codex PR workflow be adapted without exposing holdout labels or permitting automated changes to editorial policy and deployment permissions?

Produce: (a) blocking architectural concerns with concrete failure cases, (b) recommended changes, (c) clear alternatives and tradeoffs, (d) revised milestone sequencing, (e) explicit open decisions for the owner. Reference RFC/ADR sections and distinguish observations from assumptions. Do not create a repo, run code, contact external services, modify the benchmark, or merge PRs.
