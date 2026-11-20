# AI Briefing — milestone plan and issue breakdown

**Status:** Proposed, with [RFC v0.3](../rfc/AI-Briefing-RFC-v0.3.md). Replaces the v0.2 "M1 — Foundation & offline editorial evaluation" plan.

Do not create GitHub issues or run `/round` until the owner accepts the RFC and ADRs.

## Principles

- Each milestone ends with something the owner can observe or use.
- One issue and one pull request per independently testable unit, with a done-when the owner can check.
- M0 and M1 are broken down to issues here. Later milestones list scope and exit criteria; their issues are written when the milestone starts, using what the earlier ones taught.
- All pull requests are merged by the owner until ADR-011 Phase B is enabled.

## Sequence

| Milestone | Delivers | Depends on |
|---|---|---|
| M0 | Decisions, repository safeguards, catalogue, provider setup | Owner acceptance |
| M1 | A daily briefing and a baseline digest on the development machine | M0 items marked "before M1" |
| M2 | Pi deployment, morning email, feedback, backup and restore | M1; host verification |
| M3 | Story grouping, corroboration, full policy, reassessment | M1 data; M2 running |
| M4 | Prospective evaluation and quality improvement | M2 feedback path; several weeks of data |
| M5 | Expanded discovery and targeted research | Gaps measured in M4 |
| M6 | Persistent curriculum and progress | M2 feedback path; M4 findings |

---

## M0 — Decisions, safeguards and minimal preparation

Target: about a week of part-time work. M0 is finished when the "before M1" items are done. It is not a place for open-ended investigation.

### Required before M1

| # | Item | Who | Done when |
|---|---|---|---|
| 0.1 | Accept, amend or reject RFC v0.3 and ADRs 001–011 | Owner | ADR statuses updated by the owner |
| 0.2 | Answer open questions Q3 (provider and model identifiers) and Q7 (initial sources) | Owner | Recorded in `v0.3-open-questions.md` or the config files |
| 0.3 | Licence and project files: Apache-2.0 `LICENSE`, `NOTICE`, `SECURITY.md`, README | Agent, owner review | Files merged |
| 0.4 | `AGENTS.md` and `CLAUDE.md`: project rules, commands, and the Codex review section from ADR-011 | Agent, owner review | Files merged; Codex follows them on a test pull request |
| 0.5 | Repository protections: ruleset on `main`, CODEOWNERS for protected paths, secret scanning | Owner | A test pull request with a failing check cannot merge |
| 0.6 | CI skeleton: lint, types, tests, a guard that fails tests on network access, the merge-eligibility job in report mode | Agent, owner review | Eligibility job reports correctly for one protected and one unprotected test change |
| 0.7 | Port `/round` without a merge step, with its two helper scripts and a configuration file | Agent, owner review | A dry run lists a test milestone's issues and plan; the skill contains no merge command |
| 0.8 | Source catalogue v0 in `config/sources.yaml` with roles, terms URLs, review dates, fetch and retention settings | Agent drafts, owner reviews each entry | Every enabled source has a completed record |
| 0.9 | Provider account for AI Briefing with its own key and a provider-side spend limit; `config/models.yaml` with model identifiers and price table | Owner | A one-line smoke call succeeds from the development machine |
| 0.10 | Confirm the private benchmark answer key is not on any machine or account where a coding agent runs | Owner | Owner's confirmation recorded |

### Gate M2, not M1 (start in M0, may finish during M1)

| # | Item | Who | Done when |
|---|---|---|---|
| 0.11 | Host inventory per ADR-008: OS and architecture as installed, storage medium and free space, memory and CPU over a day, MLflow server version | Owner | A short record in `docs/operations/` |
| 0.12 | Check that the lightweight MLflow tracing client can log to the running server, and that a job completes with the server stopped | Owner with agent-prepared script | Result recorded; client version range chosen |
| 0.13 | Choose the off-device backup destination (Q2) and, if needed, reliable storage for the data directory (Q1) | Owner | Decision recorded |

### Experiments that belong in M1, not M0

These need the M1 collector running on real sources, so doing them earlier would mean building a throwaway.

- Daily volume per source and tokens and cost per stage.
- A story-grouping trial on a week of captured data, to confirm the M3 design.
- A first look at run-to-run variability of assessments.

---

## M1 — Working daily briefing and baseline

**Goal:** an actual, readable daily AI briefing from real sources on the development machine, next to a deliberately simple single-prompt digest.

**Not in M1:** the Pi, Home Assistant, feedback files, topic-based grouping, source-role corroboration rules, escalation, MLflow, judges, the benchmark harness.

### Issues

| # | Issue | Done when |
|---|---|---|
| 1.1 | Package and CLI skeleton | `ai-briefing --help` works from a clean clone; CI is green |
| 1.2 | Domain types and contracts: typed records and enumerations; `daily_briefing.v1` JSON Schema with valid and invalid fixtures | The import-boundary test passes; fixtures validate or fail as labelled |
| 1.3 | Storage: schema and first migration for the M1 entities; SQLite settings; file lock; `JobRun` with idempotency keys | Upgrade and downgrade pass; running a job twice with one key adds no rows |
| 1.4 | Fetcher and network policy; source catalogue loader; RSS and Atom adapter with conditional requests | Private-address and redirect tests pass; re-collecting recorded feeds adds no documents; one failing source does not fail the run |
| 1.5 | Hacker News adapter; canonical URLs; exact deduplication; link-based story grouping with membership events | A feed item and a Hacker News item linking to it form one story; an uncatalogued host has no stored body |
| 1.6 | Model client: one provider, structured output, `LLMCall` log, price table, budget pre-check, recorded-response replay mode | A call that would exceed the cap is refused and recorded; the pipeline runs in CI from recorded responses with no key |
| 1.7 | Screening and standard assessment with ID-only citations, assessment input snapshots, evidence items and the integrity check | A citation to an ID not in the input is rejected; a quote not in the stored text is marked failed |
| 1.8 | Policy v0 and deterministic selection: ceilings for no verified evidence, metadata-only and community-only stories; freshness; repetition; title-similarity suppression | Table-driven tests cover each rule; a failed evidence item never supports a briefing item |
| 1.9 | Composition, concept note, Markdown and JSON rendering, atomic export | Output validates against the schema; every URL matches a stored document; a concept is not repeated within 30 days |
| 1.10 | Baseline digest and blind comparison: `baseline generate`, `compare`, `ComparisonJudgment` | Two unlabelled briefings are shown in random order; the choice and the hidden order are stored |
| 1.11 | Operations: structured JSON logs, `doctor`, `budget status`, retention purge, no-op tracer protocol, fixtures licence manifest check | After the purge, no body older than its retention remains and hashes do; CI fails on an unlisted fixture file |

Issues 1.7 to 1.10 include prompts and policy, which are protected paths. They are reviewed by the owner in any phase.

### Acceptance criteria

All are observable without reading code.

1. From a clean clone with no network and no API key, one command sequence produces a schema-valid briefing from recorded fixtures. CI runs this.
2. On the development machine with real sources, a pipeline briefing and a baseline digest are stored for **14 consecutive days**.
3. Each of those days has a recorded blind preference.
4. Re-running any day's jobs adds no rows.
5. A query for briefing URLs that do not match a stored document returns nothing.
6. A query for briefing items supported by a failed evidence item returns nothing.
7. A query for stored bodies from sources that do not permit fetching returns nothing.
8. Month-to-date spend is under the cap and `budget status` agrees with the sum of recorded calls.
9. The network-policy tests pass.

### M1 exit report

A short written report, by the owner with agent help:

- Items per day per source; tokens and cost per stage; projected monthly cost against $15.
- Preference tally against the baseline, with the count and an interval.
- Observed failure types (duplicates, misgrouped stories, weak evidence, misses the owner noticed).
- Result of the grouping trial and the variability check.
- A recommendation: proceed to M2, or simplify first if the baseline is preferred.

---

## M2 — Pi deployment, email delivery, feedback and recovery

**Goal:** the briefing arrives in the existing 07:00 email, feedback flows back, and the data survives a disk failure.

**Gate:** items 0.11 to 0.13 complete; data directory not on the boot microSD.

Scope:

- ARM64 container image built in CI; Compose project; systemd timer units; resource limits; deployment guide.
- Host preflight checks in `doctor`.
- Backup command, off-device copy, documented and tested restore.
- Export directory, dated archive, staleness semantics.
- Degraded and budget-exhausted behaviour from RFC §7.
- `feedback_event.v1` schema, fixtures and ingestion.
- MLflow tracer implementation, with the unreachable-server test.
- Consumer guide and contract fixtures for the Home System.
- In the Home System repository, by the owner: read and render the briefing section; the authenticated feedback page; the two directory mounts.

Exit criteria:

1. On seven consecutive healthy days, the 07:00 email contains the full briefing with source links.
2. With the export file removed, corrupted, or dated yesterday, the email is sent with its existing content only.
3. Opening the feedback link records nothing. Pressing a control records one event, which appears as one row after ingestion.
4. A restore from the off-device backup onto a clean directory passes `doctor`.
5. A job with tracing enabled completes with the MLflow server stopped.
6. The container stays within its memory limit for a week.

---

## M3 — Story grouping, evidence and editorial policy

**Goal:** stories persist and update correctly, and the policy enforces the evidence-first promise.

Scope:

- Lexical shortlist and constrained model match for grouping; merge and correction handling.
- Source roles applied to documents; independent corroboration count; full ceiling rules from RFC §6.2.
- Escalation to the capable model under budget.
- Reassessment and re-decision triggers; material-update rule for repeat coverage.
- Provenance view: from a briefing item to its decision, assessment, inputs and evidence.

Exit criteria:

1. A scripted fixture day containing a syndicated duplicate, a genuine update to an earlier story, a vendor-only performance claim and a metadata-only community item produces the specified briefing.
2. Over 14 live days, no briefing item is supported by a failed evidence item and no vendor-only comparative claim exceeds `watch`.
3. After a merge, earlier assessments still resolve to the observations they saw.
4. Changing the policy version re-decides open stories with no model calls.

---

## M4 — Prospective evaluation and quality improvement

**Goal:** a trustworthy baseline with stated uncertainty, and a way to tell whether a change helped.

Scope:

- Weekly labelling worksheet: sampling, blind presentation, import.
- Reference-set comparison and the recall funnel.
- 30- and 90-day revisit of `major` and lead items.
- Run-to-run variability measurement and the noise band.
- Evaluation result file format; optional logging to MLflow.
- Tier 1 workflow, started by the owner.
- The 12 public benchmark cases wired in as a smoke test. The private cases stay outside the repository and are used only by the owner (ADR-007 §5).
- Experimental judges, diagnostic only, with agreement reporting.

Exit criteria:

1. A baseline report exists in which every figure has a sample size and an interval.
2. Integrity failure rate and human-labelled support rate are reported separately.
3. One prompt or policy change has been compared against the baseline through Tier 1, and the owner decided using the noise band.
4. Any judge output is marked diagnostic and shown with its measured agreement and sample size.

---

## M5 — Expanded discovery and targeted research

**Starts only if** M4 shows important stories that were never collected, or stories that stayed at `watch` for lack of evidence that existed elsewhere.

Candidate scope, chosen from the measured gap: more curated sources; another community source; search-provider discovery; one bounded research step in which the model proposes queries, code runs them against an allowlisted API, and the story is reassessed once.

Exit criterion: the targeted measure (recall at a named stage, or the share of under-evidenced stories) improves by more than the noise band, within the budget.

Each addition needs its own ADR or an amendment to ADR-003.

---

## M6 — Persistent curriculum and progress

**Starts when** the briefing is in daily use, the feedback path works, and ADR-005's curriculum design has been re-reviewed.

Scope: one hand-reviewed track delivered in order; the five progress states; a next-day recall check through the feedback path; deterministic news-to-lesson rules; a periodic report of recurring concepts with no lesson, seeded by concept keys stored since M1.

Exit criteria:

1. Lessons are delivered in order for 14 days and resume correctly after an interruption.
2. No progress state is recorded without its required evidence.
3. Recall checks are answered through the feedback path and stored.
