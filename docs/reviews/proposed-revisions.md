# AI Briefing — proposed revisions to RFC v0.1 and ADRs 001–009

**Status:** suggestions only. No RFC or ADR text has been changed. Finding numbers (F-nn) refer to [`architecture-review-v0.2.md`](architecture-review-v0.2.md); decision numbers (D-n) refer to [`open-decisions.md`](open-decisions.md).

Contents:

1. RFC revisions, by section
2. ADR revisions
3. Alternative architectures and tradeoffs
4. Revised milestone sequence
5. Development workflow design
6. Items that can safely be deferred

---

## 1. RFC revisions

### §1 Product thesis

- Add a named baseline: "a single-prompt digest of the starter feeds". State that the pipeline must beat it in blind owner comparison, and that it remains a permanent evaluation arm (F-01).
- Change the target journey so step 3 does not require a lesson. Describe the 70/30 split as the eventual target once the curriculum ships (F-12, D1).
- Make step 5 concrete by naming the feedback mechanism chosen in D5 (F-07).

### §2 V1 scope

Move out of V1:

| Item | Reason | Returns when |
|---|---|---|
| Curriculum, progress tracking, lesson selection | F-12 | Briefings have been in daily use for some weeks |
| Search-provider discovery | F-16 | Miss analysis shows curated sources are insufficient |
| Research-on-demand | F-16 | Assessment data shows which stories were under-evidenced |
| HTML renderer beyond an email fragment | Not needed without a UI | A consumer needs it |
| LLM judges | F-09 | About a hundred owner labels exist |
| MLflow datasets and judge alignment | F-10 | Same |

Add to V1:

- A feedback ingestion path (F-07).
- A cheap-model screening tier and a hard monthly cost cap (F-06).
- Verified citations: ID-only references and quote checks (F-04).

### §3 Architecture

- Replace the diagram's assess/research cycle with a bounded step: at most one research round per story per day (F-16).
- Remove `research` and `learning` from the V1 module table; keep the names reserved.
- In the `editorial` row, split responsibilities into *assessment* (model output: claims, evidence, scores) and *policy* (code: class ceilings, reassessment triggers). Move ranking and placement to `briefings` (F-05).
- Add to `runtime`: the `LLMCall` log and the cost ledger.
- CLI: add `feedback ingest`, `eval run`, and `backup`. Drop `research` for now.

### §4 Information lifecycle

- **Step 2 (Normalize).** State exactly what is stored per observation: feed-supplied metadata and summary always; fetched body text only under the retention policy in D3.
- **Step 3 (Cluster).** Specify the mechanism chosen after the spike (section 3.1). Require that every membership change is an append-only event.
- **Step 4 (Triage).** Add a second tier: a cheap-model relevance screen on title and summary, with its own recorded decisions so missed items can be audited. Keep the rule that low traction alone never discards.
- **Step 5 (Evaluate).** The model returns claims, each with document ID, verbatim quote and support type, then anchored scores and an uncertainty note. Class is derived by policy code within a ceiling. Remove the coverage action from the assessment (F-05).
- **Step 7 (Publish).** Define "material update" deterministically: a story is eligible again only if its class changed or a new primary or independent evidence item arrived since it was last briefed.
- **Step 8 (Reevaluate).** Define the trigger: the input-set hash, prompt version, rubric version or model changed. Otherwise the existing assessment stands.

### §5 Data model

Proposed changes to the logical model:

| Change | Entity | Detail | Finding |
|---|---|---|---|
| Add | `AssessmentInput` | assessment ID, observation ID. The exact inputs shown to the model, plus a hash on the assessment. | F-03, F-15 |
| Add | `EvidenceItem` | assessment ID, claim text, observation ID, verbatim quote, support type (supports, contradicts, context), verified flag | F-04 |
| Add | `LLMCall` | job run ID, purpose, prompt hash, model ID, tokens in and out, cost, latency, status, reference to stored request and response | F-10 |
| Add | `StoryMembershipEvent` | story ID, document ID, action (add, remove, merge-in), reason, decided by (rule or model call ID), timestamp. `StoryDocument` becomes the current-state view. | F-03 |
| Add field | `StoryDocument` or `SourceDocument` | source role: primary, vendor, independent, community, aggregator | F-04, F-20 |
| Add field | `Story` | `merged_into_id`; a defined lifecycle (open, dormant, closed); `last_briefed_assessment_id` | F-03 |
| Add | `ScreeningDecision` | document ID, tier, outcome, reason, model call ID | F-06 |
| Change | `EditorialAssessment` | remove action; add input hash; add `class_ceiling_reason`; idempotency key on (story, input hash, prompt version, model) | F-05 |
| Change | `Briefing` | add status enum; add profile ID with a single default | F-19, F-21 |
| Defer | `ResearchRun`, `LearningTrack`, `Module`, `Lesson`, `LearningProgress` | Not in V1 | F-12, F-16 |
| Keep | `Feedback` | Add event ID for idempotent ingestion and a source field | F-07 |

Prompts are versioned files in the repository identified by content hash. They do not need a table.

Add a note that Alembic must run in batch mode on SQLite (F-28).

### §6 Editorial and learning policy

- Add written anchors for each level of each dimension. Until they exist, per-dimension agreement cannot be interpreted.
- State the fixed reference audience for "professional relevance" (F-21).
- Add an explicit ceiling table, for example: vendor-only evidence caps the class at `watch` for comparative performance claims and at `practical` for the existence of a release. The exact rules are the owner's editorial policy; the point is that they are code.
- Move the learning policy paragraph to a deferred section.

### §7 Briefing contract

- Enumerate `status`: `ready`, `degraded`, `empty`. Enumerate `confidence`.
- Make `lesson` optional.
- Replace `source_urls` with a list of evidence entries: URL, title, source role. URLs are resolved from stored documents only.
- Add an optional pre-rendered HTML fragment and plain-text fallback, so the consumer does not template content.
- Publish `schemas/daily_briefing.v1.json` and a set of valid and invalid fixtures for the consumer's tests.
- Specify staleness precisely: the consumer accepts a file only if `local_date` equals today in the stated time zone and `status` is not `empty`.
- Resolve where "the fuller report" lives (D6).
- Add the inbound feedback contract: directory, file naming, event schema, idempotency by event ID.

### §8 Scheduling, deployment, resilience

- Replace "job locks/lease semantics" with a single OS file lock (F-18).
- Require SSD storage and an off-device backup target, pending D7 (F-13).
- Add the degraded-briefing path and the timing budget working back from 07:00 (F-22).
- Add container memory and CPU limits as defaults.
- Add network policy for the fetcher: deny private, loopback and link-local ranges after resolution and on every redirect; where the container runtime allows it, run on a network with no LAN route (F-14).
- State that the runtime image contains the tracing-only MLflow client, not full MLflow (F-10).

### §9 Evaluation and observability

Rewrite around the following structure (F-02, F-09, F-10):

1. System of record is SQLite and JSON logs. MLflow is an optional view of model calls.
2. Evaluation layers and what each can support, as in the review's section 7.
3. Prospective labelling is the primary quality measure. The seed benchmark is a calibration aid and smoke test.
4. Three gating tiers. Tripwires are hard gates; quality scores are advisory until a baseline and noise band exist.
5. No LLM judge in a gate until its agreement with human labels has been measured on a stated sample.
6. Measure run-to-run variance before any comparison (F-23).

Remove the M1 metrics list (macro-F1, per-dimension MAE and so on) as acceptance criteria. Keep them as report fields, shown with their sample sizes.

### §10 Security

- Add: no model-driven tool calling in V1 (F-14).
- Add: model output never supplies URLs; all rendered text is escaped (F-04).
- Add: `/round` acts only on issues and comments from allowlisted authors (F-11).
- Add: the private answer key is not stored on any machine or account where a coding agent runs (F-11).
- Extend the owner-review list with evaluation code and data, recorded responses, golden files, CODEOWNERS, the `/round` skill and agent settings.

### §11 Milestones

Replace with the sequence in section 4 below. Reword untestable criteria (F-26).

### §12 Open decisions

Replace with the list in `open-decisions.md`. Items 3 and 5 of the current list are resolved by recommendation here (file handoff stays; adjudication is replaced by prospective labelling).

---

## 2. ADR revisions

General: bring ADRs 001–008 up to the standard of ADR-009 by adding "alternatives considered", "acceptance checks", and a specific "revisit when" (F-24).

| ADR | Proposed change |
|---|---|
| **001 Modular monolith** | Accept with additions. Record alternatives (framework-based agent, separate services). Add an import-boundary check as an acceptance test: the domain package imports no I/O library. |
| **002 Persistence** | Add the entities in section 1 §5. State what an observation stores and reference the retention ADR. Replace "one logical writer" with the file-lock rule. Add Alembic batch mode, SSD requirement, off-device backup and a restore test before first use. Acceptance check: re-running any job twice produces no new rows. |
| **003 Hybrid discovery** | Narrow V1 to curated feeds plus one community source. Move search discovery and research to a later ADR that is written when miss data exists. Add the two-tier triage and the story-grouping mechanism chosen after the spike. Add a per-source record of terms, rate limits and permitted storage. |
| **004 Editorial evidence** | Separate model assessment from code policy and from composition. Add evidence records, ID-only citation, quote verification, source roles and independent-source counting. Add level anchors. Remove `merge` and placement from the assessment vocabulary. Acceptance check: an assessment citing an ID it was not given, or a quote not present in the observation, is rejected. |
| **005 Learning curriculum** | Mark as deferred. When revived: reviewed lesson content grounded in listed references; the five progression states; deterministic news-influence rules; the shared-layer and profile-layer invariant. |
| **006 Briefing consumer** | Accept with the contract additions in section 1 §7 and the inbound feedback directory. Record the rejected alternative (localhost HTTP) and why. |
| **007 Offline evaluation** | Retitle to "Evaluation strategy" and absorb the evaluation half of ADR-009. Replace "blind offline benchmarking before live ranking" with "deterministic gates now; prospective evaluation from live operation". Reclassify the seed benchmark. Define the tiers, the look budget for private data, and the rule that changes to evaluation assets need owner review. |
| **008 Pi operations and security** | Add the host inventory as a precondition. Add resource limits, the network policy, the no-tool-calling rule, the timing budget, the degraded path and the off-device backup. |
| **009 Observability and evaluations** | Reduce to orchestration and observability. Keep items 1, 2 and 6. Replace item 3 with "instrument model calls and job roots; deterministic stages are covered by job records". Replace item 4 and 5 with a pointer to ADR-007. Drop item 8's portability goal in favour of the no-op tracer protocol. Add: tracing-only client on the Pi, explicit flush with a bounded timeout, a test with the server unreachable, and a statement that the Home System MLflow store is agent-accessible. Tighten "revisit when" to: research requires more than one model-directed step. |
| **New: content rights and retention** | Records D3: what is stored, for how long, what may appear in the public repository, per-source terms. |
| **New: development workflow and merge authority** | Records D8 and section 5 below. |

---

## 3. Alternative architectures and tradeoffs

### 3.1 Story grouping

| Option | For | Against |
|---|---|---|
| A. URL and hash only; let the composer merge near-duplicates in the day's shortlist | Trivial. Enough for a first briefing. | No persistent stories, so no update tracking or repetition control across days. |
| **B. Lexical shortlist (FTS5, time window) then model yes/no match** (preferred) | No new dependency. Decisions are recorded and auditable. Cost is bounded by the shortlist size. | Lexical recall can miss differently-worded coverage. Needs the spike to confirm. |
| C. Embeddings via API, stored in SQLite, cosine shortlist then model confirmation | Better recall on paraphrase. | Adds a provider dependency and a re-embedding cost on model change; the RFC excluded it. |
| D. Local embedding model on the Pi | No per-call cost. | Memory and CPU on a shared host; conflicts with ADR-008. |

Use A in the walking skeleton, B from the trust-layer milestone, and move to C only if the spike or miss analysis shows B's shortlist recall is inadequate. Whichever is chosen, membership events and assessment input snapshots are required.

### 3.2 Evaluation strategy

| Option | For | Against |
|---|---|---|
| As proposed: blind holdout on the seed set, adjudicate, then set thresholds | Feels rigorous; available now. | F-02 in full. Adjudicating 40 cards does not fix sample size or model hindsight. |
| **Prospective labelling plus deterministic gates** (preferred) | Immune to leakage and contamination. Measures the real distribution. Produces calibration data for a later judge. | Needs the owner's time every week and a working feedback path. Slow to accumulate. |
| Judge-first: calibrate LLM judges and gate on them | Scales without owner time. | Circular for editorial quality (F-09). Hides errors behind a number. |
| No formal evaluation; rely on reading the briefing | Cheapest. | No protection during autonomous rounds; regressions surface as a vague sense that it got worse. |

### 3.3 Observability

| Option | For | Against |
|---|---|---|
| As proposed: MLflow spans across all stages | Full trace view of each run. | Duplicates job records; more code on every stage; flush and version risks (F-10). |
| **SQLite record plus optional MLflow on model calls** (preferred) | One source of truth. MLflow outage is a non-event. Small client. | The MLflow UI shows model calls, not the whole pipeline. |
| No MLflow in V1 | Simplest. | Loses side-by-side prompt comparison, which the owner already knows how to use. |
| Langfuse or LangSmith cloud | Good trace and prompt tooling. | External account and data egress; a second observability system beside the existing one. |

### 3.4 Curriculum

| Option | For | Against |
|---|---|---|
| As proposed: full curriculum in V1 | Delivers the whole thesis. | F-12. Doubles V1 scope with no content source decided. |
| **Defer; reserve the contract field** (preferred) | Halves V1. Lets feedback infrastructure exist first. | The product is "just" a briefing for a while. |
| Minimal: one hand-written track of about twenty lessons, delivered in order | Tests whether a daily lesson is wanted at all, cheaply. | Still needs authoring time now. |

The minimal option is a reasonable first step once the curriculum returns.

### 3.5 Deployment form

| Option | For | Against |
|---|---|---|
| **Container run by systemd timers** (as proposed) | Isolated dependencies; resource limits; same image elsewhere. | Needs a container runtime and ARM64 builds. Depends on D7. |
| `uv` virtual environment run by systemd timers | Fewer moving parts; faster start. | Shares the host Python toolchain; weaker isolation next to Home Assistant. |
| Run on a different machine and write the export over the network | Removes all Pi constraints. | Breaks the same-host file handoff; adds a transport. |

Keep the container, and document the `uv` path as the portable install for other users.

---

## 4. Revised milestone sequence

Each milestone ends with something the owner uses or decides. Evaluation assets are built from data the earlier milestones produce.

| Milestone | Deliverable | Exit criterion |
|---|---|---|
| **M0 — Decisions and spikes** (owner-led, no `/round`) | D1–D10 decided. Revised RFC and ADRs accepted. Host inventory. One week of raw feed capture with volume, cost and grouping measurements. MLflow client tested on the Pi with the server stopped. Repository protections and bot identity in place. | Written results for each spike; ADRs marked Accepted by the owner. |
| **M1 — Walking skeleton** (development machine) | Package, CI and Tier 0 checks. Minimal schema with job and model-call records. RSS/Atom and Hacker News adapters. URL and hash deduplication. Screening tier. One assessment pass with ID-only citations. Deterministic selection. Markdown and JSON briefing. The single-prompt baseline digest. | A briefing and a baseline digest are produced daily for two weeks from one command. The owner records a preference each day. Re-running a day creates no duplicate rows. |
| **M2 — Delivery and feedback** | Container and timers on the Pi. Backup and tested restore. Atomic export. HA reader in the Home System repository. Feedback drop directory and ingestion. Degraded path. | The 07:00 email includes the section on healthy days and omits it on a forced failure. A feedback click appears in the database. A restore from the off-device backup succeeds. |
| **M3 — Trust layer** | Persistent stories with membership events. Evidence items and quote verification. Source roles and policy ceilings. Assessment input snapshots and reassessment triggers. Repetition and update rules. Recorded-response replay in CI. | Zero citation-integrity violations over two weeks of live runs. A fixture day with a syndicated duplicate, a real update and a vendor-only claim is handled as specified. |
| **M4 — Evaluation from live data** | Weekly labelling routine and tooling. Reference-set recall funnel. 30- and 90-day revisit of `major` items. Variance measurement. Tier 1 workflow. Seed benchmark wired in as a smoke test. | A first baseline report exists with sample sizes and a noise band. The owner has compared at least one prompt change through Tier 1. |
| **M5 — Coverage** | More sources and GitHub releases, chosen from miss analysis. Research-on-demand with one bounded round, if the data supports it. | Measured improvement in the recall funnel or in under-evidenced stories, beyond the noise band. |
| **M6 — Curriculum** | Per the revived ADR-005, starting with the minimal option. | Lessons are delivered in order for two weeks, recall checks are answered through the feedback path, and no state is inferred beyond its evidence. |

Sizing: M1 is the largest and should be about eight to ten issues of the size the current M1 plan uses. From the current M1 list, keep issues 1, 2, 4 and a reduced 6. Fold issue 3 into M4, issue 5 into the assessor protocol in M1, and replace issue 7 with a short document in M0.

---

## 5. Development workflow design

I have not seen ProjectBudget's `/round` skill. The following describes the target; compare it against what exists.

### 5.1 Porting `/round`

- Put the skill and its helper scripts in this repository. Do not reference another repository at run time.
- Move every project-specific value to one configuration file: repository, milestone naming, required check names, reviewer bot login, protected path globs, merge method, the author allowlist.
- Review the helper scripts for hard-coded paths, check names and label names. Confirm their licence allows copying into a repository whose licence may differ (D4).
- The skill must never create tags, releases or deployments, and must never touch the Pi.

### 5.2 Enforcement by mechanism

| Control | Mechanism |
|---|---|
| Owner approval on protected paths | CODEOWNERS plus a branch protection rule requiring code-owner review, with administrator bypass disabled |
| Agent cannot approve or bypass | Agent uses a separate bot account or GitHub App with write but not admin rights |
| Auto-merge eligibility | A CI job computes it from the diff and sets a status check. The skill merges only when that check passes. The agent cannot set it. |
| Injection through issues and comments | The skill reads only issues and comments whose author is on the allowlist |
| Secrets | Model API keys live in a protected environment used only by the owner-triggered Tier 1 workflow. No `pull_request_target` workflow checks out pull-request code. |
| Holdout | Not on the development machine. Any private scoring happens elsewhere and returns nothing to the agent's workspace. |

### 5.3 Merge matrix

| Change | Auto-merge after green Tier 0 and resolved Codex findings | Owner approval |
|---|---|---|
| Domain logic and its tests | Yes | |
| Source adapters behind an existing protocol, with recorded fixtures | Yes | |
| Renderers and templates | Yes | |
| README and how-to documentation | Yes | |
| Refactors with unchanged replay output | Yes | |
| Prompts, rubrics, level anchors, policy ceiling rules | | Yes, with a Tier 1 report |
| Model or provider selection, budgets | | Yes, with a Tier 1 report |
| Evaluation code, metrics, datasets, golden files, recorded responses | | Yes |
| Briefing schema and feedback schema | | Yes |
| Migrations | | Yes |
| Dependencies and lock file | | Yes |
| Source catalogue and network policy | | Yes |
| CI workflows, CODEOWNERS, `/round` skill and configuration, agent settings | | Yes |
| RFC, ADRs, review documents | | Yes |
| Deployment, scheduling, HA integration | | Yes |

### 5.4 Offline evaluation in CI

- **Tier 0** runs on every pull request with no network and no secrets, and should finish in a couple of minutes. It includes replaying recorded model responses through everything downstream of the model and asserting the tripwires: schema validity, citation integrity, policy ceilings, budget enforcement, idempotent re-run.
- **Recorded responses** are captured by the owner from real runs, scrubbed, and committed as protected fixtures. They must be synthetic or built from content that is safe to publish (D3).
- **Tier 1** is started by the owner or by a label only the owner can apply. It posts a comparison with the main-branch baseline, including the number of cases and the noise band. It informs the owner's review; it is not a required check.
- Codex should be asked to flag any diff that changes expected outputs, loosens an assertion, or adds label-like fields to public data.

---

## 6. Items that can safely be deferred

| Item | Why it can wait |
|---|---|
| Curriculum and progress model | Independent of briefing quality; needs the feedback path first |
| Search-provider discovery | Needs miss data to justify provider cost and terms |
| Research-on-demand | Needs assessment data to show where evidence was thin |
| LLM judges | Need labels that do not exist yet |
| MLflow evaluation datasets and judge alignment | Same |
| Full-pipeline tracing spans | Job records cover it |
| Second model provider or a routing layer | No current need |
| Embeddings and vector search | Only if lexical shortlisting proves inadequate |
| Multi-profile personalisation | One user; keep the profile ID column and nothing else |
| Full HTML report and any web UI | No consumer |
| Authenticated HTTP API for consumers | No remote consumer |
| Frozen historical source corpus for backtesting | Superseded by prospective evaluation; revisit only if a specific question needs it |
| Blind-holdout tooling and leak audits | The seed set is no longer a gate |
| Packaging for PyPI, public documentation site | After the owner has used it for a month |
