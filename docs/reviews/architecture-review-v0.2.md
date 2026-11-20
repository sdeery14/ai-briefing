# AI Briefing — independent architecture review of packet v0.2

**Reviewed:** `ai-briefing-architecture-v0.2.zip` (README, RFC v0.1, ADRs 001–009, M1 issue plan, review prompt)
**Review date:** 2026-11-19
**Status of this document:** review input only. Nothing in the RFC or ADRs has been modified or accepted.

Companion files: [`proposed-revisions.md`](proposed-revisions.md) (specific changes and alternatives) and [`open-decisions.md`](open-decisions.md) (what needs the owner).

---

## 1. Executive summary

The foundations are sound and I would not reopen them: one Python modular monolith, SQLite, scheduled short-lived jobs, plain-Python orchestration, cloud LLM calls, a file handoff to Home Assistant, and MLflow as an optional backend. The packet is also unusually honest about what its benchmark cannot prove.

The plan is not ready to implement as sequenced, for two reasons.

1. **Value is validated last.** The first readable briefing appears in M5 and the first real morning email in M6. M1 through M4 build an evaluator, a knowledge base, a research loop and a curriculum before anyone has learned whether the briefing is worth reading. The single largest risk for this product is "the briefing is no better than the newsletters I already get", and the plan defers that test the longest.
2. **The evaluation plan rests on a benchmark that cannot carry it.** Forty single-author, hindsight-selected cards with unfrozen sources cannot rank prompts or models against each other, and M1 is built around scoring them. A 28-case holdout gives a 95% interval of roughly 53% to 85% around an observed 71% accuracy. Historical cases are also contaminated in a way an `as_of` cutoff on evidence does not fix: the model being tested may already know how the story turned out.

Beyond those two, there are a dozen design gaps that should be closed before the ADRs they touch are accepted. The most consequential: story grouping has no stated mechanism, evidence is not a first-class record so citations cannot be verified, there is no channel for the owner to give feedback, volume and cost are unmodelled, and the `/round` guardrails are described as instructions rather than enforced mechanisms.

**Recommendation:** spend a short revision pass on the documents (days, not weeks), run three small spikes, then start with a walking skeleton that produces a real daily briefing in the first milestone. Build the evaluation system from the data that skeleton generates.

---

## 2. The architecture as I understand it

- **Product.** A self-hosted service for one data scientist or AI engineer that collects AI/ML/software sources through the day, groups them into stories, judges which matter on evidence rather than popularity, and publishes a five-minute morning briefing of three to five developments plus one curriculum lesson.
- **Pipeline.** Source adapters (RSS/Atom, GitHub releases, one community source, optional search) produce candidates. These are normalised, deduplicated, clustered into stories, filtered by deterministic triage, assessed by an LLM on five 0–4 dimensions with a class and a coverage action, optionally researched under a budget and reassessed, then selected and composed into a versioned JSON briefing with Markdown and HTML renderings.
- **State.** SQLite via SQLAlchemy and Alembic, one writer. Thirteen logical entities covering sources, documents and their observations, stories, append-only assessments, research runs, curriculum, progress, briefings, feedback and job runs.
- **Runtime.** A container or `uv` install on the Home System Pi, driven by host systemd timers. Collection about every three hours, a briefing ready by 06:30 local, exported atomically to a read-only mount.
- **Integration.** Home Assistant keeps ownership of recipients, personal context and sending. It reads the exported JSON at 07:00 and omits the section if the file is missing, invalid or stale.
- **Evaluation and observability.** A deterministic offline evaluator over a 40-card seed benchmark (12 public labels, 28 private), planned LLM judges calibrated against human labels, and optional MLflow tracing across every stage.
- **Workflow.** Claude Code implements milestone issues through an adapted `/round` skill, Codex reviews pull requests, and a list of sensitive paths requires owner approval.

---

## 3. Strengths worth preserving

| Decision | Why it should survive revision |
|---|---|
| Modular monolith, CLI jobs, no queue or broker (ADR-001, ADR-008) | The workload is a small daily batch. Short-lived processes cost nothing when idle and fail in isolation. |
| Plain-Python orchestration (ADR-009 §1) | The pipeline is a fixed sequence with one bounded loop, and SQLite rows already act as checkpoints. See section 6. |
| Append-only assessments and immutable briefings (ADR-002) | This is what makes auditing and later evaluation possible. |
| Separate `published_at` and `first_seen_at`, never guessing dates | Correct, and commonly got wrong. |
| "Popularity is a discovery signal, not proof of impact" and the vendor-blog rule (RFC §4) | These are the product's actual differentiators. They should become enforceable rules, not just prompt wording. |
| Briefing as a data product; HA reads a file and owns sending (ADR-006) | Clean failure isolation. The existing email keeps working whatever AI Briefing does. |
| MLflow optional, never on the success path (ADR-009 §2) | Right boundary. I recommend narrowing what is traced, not changing the boundary. |
| No fixed accuracy thresholds before a baseline exists (ADR-009 §7) | Correct, and it should be kept under pressure to "have a number". |
| Personal feedback kept separate from shared factual evidence (RFC §5) | This is the right seam for future personalisation. |
| Explicit non-goals list (RFC §2) | Long and specific. Keep adding to it. |

---

## 4. Findings ranked by severity

Severity scale:

- **P0** — resolve before any implementation starts.
- **P1** — resolve before the affected milestone; the related ADR should not be accepted unchanged.
- **P2** — should fix; cheap now, expensive later.
- **P3** — minor.

### P0

**F-01. The product is not validated until M5/M6.**
RFC §11 orders the work as evaluator, intake, editorial, learning, composition, deployment. Every milestone before M5 produces infrastructure whose requirements are guesses about what a good briefing needs. Concrete failure case: after M4 the owner reads the first composed briefing, finds it reads like a weaker version of an existing newsletter, and discovers that the clustering, research and curriculum machinery did not address the real problem (for example source selection or writing quality).
There is also no baseline to beat. A single prompt summarising a dozen good feeds is a one-day build. The architecture is only justified if it clearly beats that.
*Recommendation:* make the first milestone a walking skeleton that emits a real briefing daily, include the trivial single-prompt digest as a permanent baseline, and move Pi and HA delivery to the second milestone so the briefing is used in its real channel early. Revised sequence in `proposed-revisions.md` §4.

**F-02. The seed benchmark cannot measure the ranking engine, and M1 is built around it.**
Taking the packet's own description (40 cards, 12 public, 28 holdout, provisional single-author labels, `source_text_frozen` false):

- *Statistical power.* With 28 cases, one case is 3.6 points of accuracy. An observed 20/28 has a 95% Wilson interval of about 53% to 85%. If the four classes are roughly balanced (the class distribution is not in the packet, so this is an assumption), the holdout has about seven `major` cases and major recall moves 14 points per case. Macro-F1 and per-dimension MAE on this sample cannot distinguish two reasonable prompts.
- *Label validity.* One author wrote the labels and, as far as the packet shows, also wrote the rubric. Agreement with those labels measures agreement with that author on that day. Per-dimension scores on a 0–4 scale are the least reliable part; adjacent-score disagreement between careful humans is normal.
- *Selection bias.* "Historically selected" cards were chosen because they were memorable. The benchmark over-represents clear cases and under-represents the dull, ambiguous middle that dominates real daily volume, which is where a ranking engine earns or loses its value.
- *Hindsight in the labels.* Labels written after outcomes are known encode the outcome. A model that scored a later-vindicated paper as `watch` at the time may have been right given the evidence then.
- *Hindsight in the model.* This is not addressed anywhere in the packet. An `as_of` cutoff restricts the evidence supplied, but the LLM's training data may post-date the event. It can then "predict" significance from memory. Historical replay with a current model systematically overstates quality, and no fixture discipline fixes that.
- *Holdout erosion.* Each time a private score influences a decision, information about the labels leaks into the design. With 28 cases and repeated autonomous rounds, the holdout stops being blind after a handful of looks, even if nobody ever sees a label.
- *Scope.* As ADR-007 already says, a pre-selected list cannot measure discovery. It also cannot measure composition, repetition handling or usefulness.

*Recommendation:* reclassify the seed set as a rubric-calibration aid and regression smoke test. Stop investing in blind-holdout machinery for it. Make the primary evaluation prospective: every new day is a test case the model and prompts could not have seen, labelled by the owner before outcomes are known and revisited later. Details in section 7.

### P1

**F-03. Story grouping has no stated mechanism, and it is the hardest technical problem in the design.**
RFC §2 requires "multi-document story grouping, including updates to an existing story". RFC §5 excludes embeddings and vector search. Canonical URLs and content hashes only catch syndicated copies. Nothing in the packet says how a vendor blog post, the arXiv paper, a Hacker News thread and three news articles become one story, or how a later benchmark result is recognised as an update to it rather than a new story.
Two further gaps follow. `Story.normalized subject` has no defined author or stability. And story membership is mutable while assessments are immutable: after a merge or a corrected mis-cluster, an old assessment refers to a story whose contents have changed, so "what did the assessor see?" is unanswerable.
*Recommendation:* run a spike on one week of real captured feed data before ADR-002/003 are accepted. My preferred design is lexical shortlist (SQLite FTS5 over titles and summaries, limited to a recent time window) followed by an LLM yes/no match against at most a few candidates, with every membership change recorded as an append-only event. Make each assessment record the exact observation IDs it was given.

**F-04. Evidence is not a first-class record, so citations cannot be verified.**
In RFC §5, evidence is a list of "cited document IDs" on the assessment, and the briefing contract carries `source_urls`. Failure cases: the model cites a real document that does not support the claim; the model writes a plausible URL that was never collected; a vendor's performance claim is cited as if independently confirmed. The RFC says validation will "forbid fabricated evidence" but describes no way to detect it.
*Recommendation:* three cheap structural rules. (a) The model may only reference documents by the IDs it was given; URLs in output are always resolved from the database, never taken from model text. (b) Each supporting citation carries a short verbatim quote, and code checks that the quote appears in the stored observation. (c) Each story document has a source role (primary, vendor, independent reporting, community discussion, aggregator), and corroboration counts independent sources, not documents. With these, "no hallucinated citations" is true by construction and most of what a groundedness judge would be asked is checked deterministically.

**F-05. The assessment output mixes four different decisions.**
RFC §4 step 5 asks a single assessment for dimension scores, a class, and a coverage action from `lead`, `brief`, `watchlist`, `skip`, `merge`. But `merge` is a clustering decision. `lead` versus `brief` depends on what else happened that day and what was already covered, which a per-story assessment cannot know. `skip` and `watchlist` follow from the class. RFC §6 says classification is "reasoned using policy rules" without saying whether the model or code applies them.
*Recommendation:* the model produces claims, evidence and anchored dimension scores. Deterministic policy code derives the class ceiling (for example, weak evidence cannot be `major`). Composition, in code, decides placement. Remove `merge` from the action vocabulary. This also means the seed benchmark's action labels measure something the assessor should not be deciding.

**F-06. Volume and cost are not modelled.**
The RFC sets no monthly budget and no expected volume. Paper feeds alone can deliver hundreds of items per weekday (my estimate; it should be measured). The deterministic triage in RFC §4 step 4 removes seen, out-of-scope and malformed items, which will not reduce that volume much, and the RFC forbids discarding on low social traction. As written, most items reach the paid assessment step.
*Recommendation:* add an explicit cheap-model screening tier between deterministic triage and full assessment, state a hard monthly cap enforced before each call from a persisted ledger, and measure real volume in the spike.

**F-07. There is no feedback channel.**
Journey step 5 (RFC §1) is "give feedback or inspect what was missed", and there is a `Feedback` entity, but V1 has no UI, the email is sent by Home Assistant, and no reply path exists. A CLI on the Pi will not be used at 07:05. Evaluation of usefulness, curriculum progress and any future personalisation all depend on this input.
*Recommendation:* mirror the export with an inbound drop directory. Links in the email hit a Home Assistant webhook, HA writes a small JSON event file, AI Briefing ingests it on its next run. Neither side reads the other's store.

**F-08. Content rights and retention are unresolved, yet the data model and replay depend on them.**
`DocumentObservation` stores payloads, replay needs them kept, the project is open source, and RFC §12 item 6 leaves retention open. Specific risks:

- Fetching and keeping full article text is a different legal posture from keeping feed-supplied metadata. The RFC does not say which is intended.
- Community sources vary. arXiv's API terms place descriptive metadata under CC0 and ask clients to respect rate limits. Reddit's current terms restrict commercial use and require each user's own credentials, which is awkward for a tool others will install. X is effectively unavailable.
- Public benchmark cases and test fixtures must not contain third-party text.

*Recommendation:* decide a retention posture before M2 (my proposal is in `open-decisions.md` D3), and add an ADR for it. I am not giving legal advice; the point is that the choice changes the schema.

**F-09. The judge plan is larger than the labelled data can support.**
ADR-009 §4 proposes LLM judges for groundedness, editorial discrimination, uncertainty calibration, composition quality and curriculum continuity. Each needs its own human-labelled calibration set with enough negatives to estimate agreement. Twelve public labels cannot calibrate one judge, let alone five. A judge for "editorial discrimination" is also circular: it is the same kind of model as the assessor, with correlated blind spots toward confident, well-written hype.
*Recommendation:* no LLM judges in V1 gates. After F-04, groundedness is mostly deterministic. Introduce at most one narrow judge (claim-supported-by-quote) once there are on the order of a hundred owner-labelled examples, and report its agreement with humans alongside every score it produces.

**F-10. Observability is over-scoped and duplicates the database.**
ADR-009 §3 instruments every stage with spans and a correlation chain. But `JobRun` and `EditorialAssessment` already persist versions, counts, cost and errors. Two records of the same facts will drift. Specific technical concerns, checked against current MLflow documentation:

- The Pi should use the `mlflow-tracing` package (documented at about 5 MB) and not full `mlflow` (documented at about 1 GB). `mlflow.genai.evaluate` needs the full package, so evaluation runs belong on the development machine.
- Trace export is asynchronous by default in open-source MLflow, with retries up to a documented default of 500 seconds. A short-lived CLI job must flush before exit and must bound that wait, or "completes with MLflow down" becomes "hangs for eight minutes then loses the trace".
- The client must be compatible with whatever MLflow version `homenvr` runs. That version is not stated in the packet.
- The Home System MLflow store is reachable from the development workstation. This Claude Code workspace has MLflow trace-retrieval skills installed, so anything logged there should be assumed readable by the coding agent. ADR-009 §6 forbids holdout data in an "agent-accessible trace store"; in practice that describes this store.

*Recommendation:* make SQLite and structured JSON logs the system of record, add one `LLMCall` record per model call, and limit MLflow to an optional thin wrapper around model calls and the job root. Section 8 gives the full comparison with LangSmith and Langfuse.

**F-11. The `/round` guardrails are instructions, not mechanisms.**
The M1 plan lists paths that "require owner approval". I could not inspect ProjectBudget's `/round` skill, so the following are risks to check, not confirmed defects.

- If the agent uses the owner's GitHub credentials, its pull requests are authored by the owner. GitHub does not let an author approve their own pull request, so "owner review required" cannot be enforced by branch protection, and the agent holds the owner's merge rights.
- The agent is asked not to touch thresholds and rubrics, but the evaluation harness, golden files and CI workflows are also code it can edit. An agent under pressure to turn a check green can weaken the check.
- In a public repository, issue text and pull-request comments are prompt input. An issue filed by a stranger in the milestone is an injection path into an agent that can merge.
- The answer key was described as a "download". If it sits on the same machine and user account as Claude Code, it is inside the agent's reach regardless of what the repository contains. I have not looked for it.

*Recommendation:* a separate bot identity, CODEOWNERS plus branch protection on protected paths, a CI job (not the agent) that decides auto-merge eligibility from the diff, an author allowlist for issues and comments the skill will act on, and the private key kept off the development machine. Matrix in `proposed-revisions.md` §5.

**F-12. The curriculum is the largest unvalidated scope item and has no content source.**
ADR-005 specifies structure (tracks, modules, prerequisites) but RFC §12 item 7 leaves open who writes lessons. In an evidence-first product, an LLM-written lesson with no source behind it is the least-evidenced thing on the page. Thirty percent of five minutes is about 300 words, which limits what a "lesson" can be. And without F-07, even exposure cannot be recorded reliably, because Home Assistant sends the email.
*Recommendation:* defer the curriculum until the intelligence half has been used daily for a few weeks. Keep `lesson` as an optional field in the contract. Section 9 describes the model I would build when it returns.

**F-13. Raspberry Pi assumptions are unverified, and some are prerequisites.**
The RFC rightly says to measure headroom, but several unknowns decide the deployment design itself:

- How Home Assistant is installed. If it is Home Assistant OS, host systemd timers and arbitrary containers are not straightforwardly available. The presence of PostgreSQL and MinIO suggests a general Linux host, but the packet does not say.
- Whether the OS is 64-bit, which an ARM64 container requires.
- Storage medium. SQLite in WAL mode on an SD card shared with Home Assistant's recorder and PostgreSQL is a wear and corruption risk. The RFC says "prefer" an SSD; I would make it a requirement.
- Where backups go. A backup on the same device, including the MinIO instance on the same Pi, does not survive the failures that matter.

*Recommendation:* a one-page host inventory before ADR-008 is accepted. The workload itself is light: network-bound, a few hundred megabytes of memory, minutes of CPU per day. Frigate, if it arrives, is the real threat to headroom, not this.

**F-14. The fetcher runs on the home-automation host.**
RFC §10 lists SSRF protections; given the host, they deserve acceptance tests and priority. A feed entry or redirect pointing at `homeassistant.local`, a LAN address, or the MLflow and MinIO ports must be refused after DNS resolution and on every redirect hop. The RFC also mentions "LLM tools restricted to read-only research functions", which implies a tool-calling loop.
*Recommendation:* no model-driven tool calling in V1. The model proposes search queries as structured output; code executes them against an allowlisted search API and fetches only result URLs that pass the same network policy. The model never chooses an arbitrary URL to fetch.

### P2

| ID | Finding | Recommendation |
|---|---|---|
| F-15 | "Reproducible" is undefined (M5 acceptance; RFC §11). LLM output is not bit-reproducible and model versions are retired. | Define two levels: *re-render* (same briefing from stored decisions, exact) and *re-run* (same inputs through a new prompt or model, compared statistically). Persist raw model responses so re-render never needs the model. |
| F-16 | The diagram shows an assess/research cycle with no stated bound, and V1 includes both search discovery and targeted research. | One research round per story per day in V1. Defer broad search discovery until miss analysis shows curated sources are insufficient. |
| F-17 | "LLM providers implement narrow protocols" could become a generic chat abstraction. | Define the protocol at task level (`assess(story_packet) -> Assessment`), implement one provider with its native schema-constrained output, validate with Pydantic, allow one bounded retry. No second provider or routing library until needed. |
| F-18 | "Job locks/lease semantics" invites stale-lease bugs. | Use an OS file lock (`flock`) on a single host; the kernel releases it on crash. Keep idempotency keys in `JobRun`. |
| F-19 | The briefing contract has gaps: `status` and `confidence` are not enumerated, `lesson` is required by the example, there is no degraded state, no published JSON Schema, and "a link to the fuller report" has nowhere to point since V1 has no web UI. | Enumerate `ready`, `degraded`, `empty`. Make `lesson` optional. Publish the schema file and a contract fixture for the consumer. Ship a pre-rendered HTML fragment so HA does not template stories. Decide where the full report lives (see D6). |
| F-20 | Corroboration is undefined. Five articles repeating one press release look like five sources. | Covered by the source-role rule in F-04. |
| F-21 | "Professional relevance" is audience-relative but stored in a global assessment; `LearningProgress` already has a profile ID. | Fix one audience persona in the rubric for V1 and say so. Personalise later by re-ranking at composition, not by re-assessing. Keep a single default profile. |
| F-22 | No degraded path if the model provider is down before 06:30. | Compose from already-assessed stories with `status: degraded` and a retry window. The HA fallback then becomes the second line of defence, not the first. |
| F-23 | Run-to-run variance of assessments is unmeasured, so no later comparison can be interpreted. | Before any prompt comparison, assess the same inputs several times and record the disagreement rate. This sets the noise band used in gating. |

### P3

| ID | Finding |
|---|---|
| F-24 | ADRs 001–008 are a few sentences each with identical "Revisit when" text. They record no alternatives considered and no acceptance checks. ADR-009 is the model to follow. |
| F-25 | ADR-007 and ADR-009 both govern evaluation. Merge the evaluation content into one ADR and leave ADR-009 for orchestration and observability. |
| F-26 | Several acceptance criteria are untestable as worded: "consistent decisions", "defensible report", "progress coherently". |
| F-27 | The packet is v0.2 but the RFC inside is v0.1. Align the naming. |
| F-28 | Alembic on SQLite needs batch mode for most `ALTER TABLE` operations. Worth a line in ADR-002 so the first migration sets it up. |
| F-29 | The packet zip sits untracked in the repository root. Decide whether to commit the extracted documents under `docs/` or ignore the zip. I left it untouched. |

---

## 5. Product design and MVP scope

**Is the problem compelling?** For the owner, yes: a personal, auditable, self-hosted briefing with honest uncertainty. For a wider audience it is unproven, because free curated AI newsletters already exist. The differentiators that cannot be had elsewhere are the evidence trail, the uncertainty labelling, the repetition and update handling, and (later) the cumulative curriculum. V1 should be judged on exactly those.

**Is the MVP too broad?** Yes. V1 as listed contains three discovery mechanisms, clustering, a research loop, a curriculum, three renderers, an evaluation harness, tracing and a deployment. I would cut V1 to: curated feeds plus Hacker News, grouping, one assessment pass with verified citations, deterministic composition, Markdown and JSON output, the HA handoff, and a feedback path. Research-on-demand follows when the data shows which stories needed it.

**Are intelligence and education separated?** In the module layout, yes. In the plan, no: they share V1, the briefing contract requires a lesson, and the 70/30 split is in the product thesis. They are different products with different risks. Intelligence fails by being wrong or late; education fails by being shallow or unread. Ship intelligence first.

**Is infrastructure being built ahead of validation?** Yes (F-01). The evaluator, the tracing boundary and the holdout process are all scheduled before a briefing exists.

---

## 6. AI engineering and orchestration

**Plain Python versus LangChain or LangGraph.** I tried to argue for LangGraph and could not. Its real offerings are durable checkpoints, resumable branching and human interrupts. Here, every stage is a query for rows in a given state followed by an idempotent write, so the database is the checkpoint and a re-run is the resume. There are no human interrupts in a cron batch. LangChain's provider wrappers would sit between the code and native structured output, which is the feature this design depends on most. The decision in ADR-009 §1 is right. The "revisit when" condition should be tightened to one concrete trigger: research needing more than one model-directed step.

**Where code should decide instead of the model.**

| Decision | Owner |
|---|---|
| URL canonicalisation, exact duplicate detection, scope filters | Code |
| Shortlisting candidate stories for a new document | Code (lexical search and time window) |
| Confirming a document belongs to a shortlisted story | Model, constrained to yes/no plus story ID |
| Extracting claims, quoting support, scoring dimensions against anchored descriptions | Model |
| Verifying quotes exist, cited IDs were supplied, evidence predates `as_of` | Code |
| Class ceiling from evidence facts (source roles, corroboration count) | Code |
| Whether a story needs reassessment (input set or versions changed) | Code |
| Whether to research, and how many queries | Code, from class and uncertainty thresholds |
| Selection, ordering, diversity, repetition against past briefings | Code |
| Headline and "why it matters" prose | Model, with stored output |
| Next lesson, interruption, resumption | Code |
| Budget enforcement, dates, time zones, rendering | Code |

**Structured outputs.** Use the provider's schema-constrained output, validate with Pydantic, retry once on failure, and store the raw response. Order schema fields so claims and evidence come before scores and class; a model that states its verdict first tends to rationalise it. Give every score level a written anchor. Expect scores to cluster in the middle of the range and treat per-dimension values as diagnostics, not as gates.

**Prompt injection.** With no tool calling (F-14) and ID-only citations (F-04), the remaining injection risk is integrity: source text written to persuade the assessor ("this is a major breakthrough"). The deterministic class ceiling is the main defence, because a single vendor source cannot reach `major` however it is worded. Rendered output must escape all model and source text.

---

## 7. Evaluation: what can be trusted and how to measure it

### Principle

Use time as the holdout. A day's news did not exist when the prompt and model were frozen, so it cannot have leaked, been memorised, or been labelled with hindsight. This addresses label leakage, model contamination and holdout erosion together, which no amount of process around a static 28-case file can.

### What each layer can and cannot tell you

| Layer | Trustworthy for | Not trustworthy for |
|---|---|---|
| Deterministic tests on fixtures | Schema, deduplication, idempotency, date logic, citation integrity, budget enforcement, policy ceilings | Any judgement of editorial quality |
| Replay of recorded model responses | Regressions in everything downstream of the model, at zero cost | Whether a prompt change helped |
| Seed benchmark, public cases | Rubric wording, obvious breakage, a smoke test for new prompts | Comparing two reasonable prompts; accuracy claims |
| Seed benchmark, private cases | A rare sanity check | Anything used repeatedly |
| Prospective owner labels | Classification quality on real volume, precision of `major`, hype false positives | Discovery (the owner only sees what was collected) |
| Reference-set comparison | Discovery recall, by stage | Absolute recall; references have their own biases |
| Blind pairwise briefing comparison | Usefulness; whether variant A beats variant B | Why |
| LLM judge | Scaling a narrow, already-validated human check | Editorial significance; anything it has not been calibrated on |

### Measuring the four things asked about

**Discovery recall.** True recall is unknowable, so measure it against a pooled reference. Each week, assemble important stories from two or three external curated lists plus anything the owner noticed elsewhere. For each, record how far it got: collected, grouped, assessed at `watch` or above, included in a briefing. Report loss per stage and time-to-first-seen. This separates "we never saw it" from "we saw it and ranked it low", which the packet correctly says matters.

**Hype false positives.** Two measures. At decision time, the owner marks briefing items as overhyped through the feedback channel. At 30 and 90 days, revisit every item that was classed `major` or led a briefing and ask whether it held up. The retrospective precision of `major` is the single number that best reflects the product promise. A deterministic companion check: no item reaches `major` on vendor-only evidence.

**Evidence quality.** Deterministic first: every cited ID was in the input, every quote is found in the stored observation, every observation predates `as_of`, and independent-source count is computed from source roles. Target for the first three is zero violations, enforced as a hard gate. Only "does this quote actually support this claim" needs judgement, sampled by the owner at first and by a calibrated judge later.

**Briefing usefulness.** With one reader, ground truth is the reader. Collect per-item useful/not-useful and a weekly "what did I miss". For comparing pipeline variants, generate two briefings for the same day and have the owner pick the better one without knowing which is which. Pairwise preference is more reliable than absolute ratings and needs far fewer samples. Always include the trivial single-prompt digest as one arm until the pipeline beats it consistently.

### Leakage, bias and calibration controls

- Label before looking at the system's output where possible, or the system anchors the label.
- Freeze labels at decision time and record later revisions separately. The first is "was this a reasonable call then", the second is "did it turn out to matter". Both are useful and they are different.
- Record every look at private results. Budget them (for example, once per milestone exit).
- Keep a judge's agreement rate with human labels next to every score it emits, with the sample size. Re-measure whenever the judge model or rubric changes.
- Never let a judge and the assessor be the only two opinions on a quality question.

### How results should gate autonomous rounds

| Tier | Runs | Contents | Effect |
|---|---|---|---|
| 0 | Every pull request, offline, no secrets | Unit tests, schema checks, leak check on public data, replay of recorded responses, evidence and policy tripwires | Hard gate. Zero tolerance on tripwires. |
| 1 | Owner-triggered or on labelled pull requests, with an API key in a protected environment; never on forks | Live-model run on the public development set, repeated, compared with the main-branch baseline and the measured noise band | Required for prompt, model or rubric changes. Advisory to the owner, who decides. |
| 2 | Weekly, on the owner's machine or the Pi | Prospective metrics, reference-set recall, any private check | Informs priorities. Never read by the agent. |

A pull request that changes expected outputs, recorded responses, evaluation code or thresholds is not eligible for auto-merge, whatever its test status.

---

## 8. Observability: MLflow, LangSmith, Langfuse or custom

Facts checked against vendor documentation on the review date; see section 12.

| Option | Fit for this project |
|---|---|
| **MLflow (existing server)** | Already running and familiar. A small tracing-only client exists. Evaluation and judge tooling exist but need the full package. Works without any orchestration framework. Costs: version coupling to the Home System server, flush handling in short-lived jobs, and a store shared with another project. |
| **Langfuse, self-hosted** | Not viable on this host. Current self-hosting requires ClickHouse, Redis or Valkey, blob storage and PostgreSQL, with documented minimums of 8 GiB for ClickHouse alone and 4 GiB each for the web and worker containers. |
| **Langfuse Cloud** | Technically fine and framework-independent, but adds an external account and sends trace content off the host for no capability the project needs yet. |
| **LangSmith** | Self-hosting is restricted to the Enterprise plan, so in practice this is SaaS. Works without LangChain. Same external-dependency objection, plus default trace retention measured in days. |
| **Custom only** (SQLite rows and JSON logs) | Enough to operate and debug a daily batch of a few hundred model calls. No trace UI, no experiment comparison. |

**Recommended simplest architecture.**

1. *System of record, always on:* `JobRun`, `LLMCall` and `EditorialAssessment` rows in SQLite, plus structured JSON logs. `LLMCall` holds prompt hash, model ID, token counts, cost, latency, status and a reference to the stored request and response. This alone satisfies every ADR-009 acceptance check about recoverability.
2. *Optional view:* a `Tracer` protocol with a no-op default and an MLflow implementation of a few dozen lines, wrapping model calls and the job root only. Deterministic stages are covered by `JobRun` counts and logs; they do not need spans.
3. *Evaluation output:* the runner writes a portable JSON result file. Logging that file and its headline metrics to an MLflow experiment is an optional last step, useful for comparing prompt versions on the development machine.
4. *Deferred:* MLflow datasets, built-in judges and judge alignment, until there are enough human labels to use them honestly. Drop the abstract "backend portability" goal in ADR-009 §8; the no-op protocol already provides it.

**Is observability decoupled from behaviour?** In intent, yes. Three things would make it true in practice: nothing in application logic reads from MLflow; export has a short bounded timeout and an explicit flush at job end; and a test runs the full pipeline with the tracking URI pointing at a closed port.

---

## 9. Curriculum and personalisation

When the curriculum returns after deferral, I would build it as follows.

**Content.** Tracks, modules and lessons are versioned files in the repository. Each lesson lists objectives, prerequisites, topic tags and canonical references (documentation, papers, textbook sections). Lesson text is generated once from those references, reviewed through a pull request, and stored. It is not regenerated daily. This keeps the evidence-first promise on the education side.

**Progression.** Record distinct states and never infer a later one from an earlier one:

| State | Evidence |
|---|---|
| Scheduled | Selected for a briefing |
| Delivered | Included in an exported briefing (the most the engine can know alone) |
| Acknowledged | The reader clicked "read" or similar through the feedback channel |
| Self-rated | The reader reported confidence |
| Checked | The reader answered a retrieval question about it on a later day |

Position in the sequence advances on delivery. Anything called understanding is set only by a check. A one-question recall prompt in the next day's briefing is the cheapest honest test, and it doubles as spaced review.

**How news should influence learning.** Use deterministic rules over shared topic tags. If a major story matches the active lesson, attach it as an "in the news" link. If it matches a later lesson whose prerequisites are met, pull that lesson forward, at most once a week, then resume. News should change curriculum *content* only through human-reviewed changes: a monthly report of topics that recur in `major` and `practical` stories with no matching lesson, with a persistence requirement of several weeks so the curriculum does not chase hype.

**Independent knowledge base and future personalisation.** Keep two layers. The shared layer holds sources, documents, stories, evidence and assessments for a stated reference audience; it contains nothing about any reader. The profile layer holds feedback, progress, topic weights and briefing selection. Personalisation is a re-ranking at composition time over shared assessments, with the breadth budget the RFC already describes. Feedback never edits a shared assessment. This is consistent with the RFC; it should be stated as an invariant in ADR-005.

---

## 10. Deployment, operations and Home Assistant

- **Resources.** The job is network-bound and small. Set container memory and CPU limits anyway so a parsing bug cannot starve Home Assistant. Keep full `mlflow` out of the runtime image.
- **Storage.** Feed metadata and summaries for a few hundred documents a day is on the order of a gigabyte a year. Retained full text would be roughly ten times that. Both figures are my estimates and both are manageable on an SSD; neither belongs on an SD card.
- **SQLite.** WAL mode on a local bind mount, foreign keys on, a busy timeout, one writer. `VACUUM INTO` or the backup API for snapshots, copied off the device. Test a restore before the first real use, not at release.
- **Scheduling.** systemd timers with `Persistent=true` and an explicit time zone. Work backwards from 07:00: final collection and assessment around 05:00, composition at 06:15, a retry window to 06:45.
- **Idempotency.** Collection is keyed on source and external ID. Assessment is keyed on story, input-set hash, prompt version and model. A briefing is keyed on local date; regeneration creates a new version only when forced. Export is an atomic rename.
- **Failure.** One source failing does not fail the run (already in the RFC). Provider outage produces a degraded briefing (F-22). A crashed job releases its file lock and the next timer picks up unprocessed rows.
- **Home Assistant.** The file contract is right. Add the published schema, a consumer fixture, a pre-rendered fragment, and the inbound feedback directory. The consumer lives in another repository that I have not seen, so how it reads and validates JSON is unverified.
- **Existing MLflow, PostgreSQL and MinIO.** Use MLflow as an optional trace sink only. Do not put AI Briefing's primary data in the Home System's PostgreSQL or its backups in the Pi's MinIO; both would create exactly the dependency ADR-001 rules out.
- **Image builds.** Build the ARM64 image in CI and pull it on the Pi manually. No runner on the Pi.

---

## 11. Development workflow

Covered in F-11 and in `proposed-revisions.md` §5. In brief:

- Reuse the `/round` pattern by parameterising it (repository, milestone, check names, reviewer identity, protected paths) and vendoring its helper scripts into this repository, not by referencing ProjectBudget.
- Enforce protections in GitHub, not in the prompt.
- Safe to auto-merge: domain logic with tests, adapters behind existing protocols using recorded fixtures, renderers, non-decision documentation, refactors that leave replay outputs unchanged.
- Always human: everything already listed in RFC §10, plus evaluation code and data, golden files and recorded responses, CI workflows, CODEOWNERS, the `/round` skill and its configuration, agent settings, and the briefing schema.
- Expect that most quality-relevant work (prompts, rubrics, policy) will be human-in-the-loop by design. Autonomous rounds are for plumbing.
- The M1 issues are well sized. Their content should change (F-01, F-02).

---

## 12. What I verified and what I assumed

**Checked against current documentation**

- MLflow provides a tracing-only package with a much smaller footprint than full `mlflow`; trace logging is asynchronous by default in open-source MLflow, drops traces when its queue is full, and retries failed exports up to a default timeout. [MLflow lightweight tracing SDK](https://mlflow.org/docs/latest/genai/tracing/lightweight-sdk/), [MLflow production tracing](https://mlflow.org/docs/latest/genai/tracing/prod-tracing/)
- MLflow offers custom judges and human-feedback alignment; the default alignment method has changed between releases. [MLflow scorer concepts](https://mlflow.org/docs/latest/genai/concepts/scorers/)
- Self-hosted Langfuse requires ClickHouse, Redis or Valkey, blob storage and PostgreSQL, with the minimums quoted in section 8. [Langfuse production checklist](https://langfuse.com/resources/engineering/self-hosted-langfuse-production-checklist)
- LangSmith self-hosting is limited to the Enterprise plan. [LangSmith platform setup](https://docs.langchain.com/langsmith/platform-setup)
- arXiv API metadata is offered under CC0 and clients must respect rate limits. [arXiv API terms of use](https://info.arxiv.org/help/api/tou.html)

**Not verified; treat as assumptions**

- The contents, class balance and field layout of the editorial benchmark. I did not have it and did not look for it.
- The ProjectBudget `/round` skill, `pr_wait.py` and Codex configuration.
- Everything about `homenvr`: OS, Home Assistant install type, storage, free memory, MLflow server version.
- The Home System `morning-briefing-email` implementation and how it would read a JSON file.
- Daily item volume from any source, and all storage and cost estimates derived from it.
- Reddit's and Hacker News's current terms. Search results on Reddit came from secondary sources; check the primary terms before choosing a community adapter.
- MLflow's OpenTelemetry export behaviour, which I did not confirm.

---

## 13. Is the project ready for implementation?

**No, not as sequenced. Yes, after a short and well-defined revision.**

The technology choices are sound and no re-architecture is needed. What needs to change is the order of work, the role of the benchmark, and a handful of data-model and guardrail details that are cheap to fix on paper and expensive to fix in code.

Conditions I would set before the first `/round`:

1. Owner decisions D1 through D10 in `open-decisions.md` are made.
2. The RFC milestone plan is replaced by a skeleton-first sequence.
3. ADR-007 and ADR-009 are rewritten around prospective evaluation and a narrowed MLflow role.
4. The data model gains evidence records, assessment input snapshots, story membership history and an `LLMCall` record.
5. Three spikes are complete: one week of captured feed data with a story-grouping trial and a volume and cost measurement; the MLflow client on the Pi with the server stopped; a host inventory.
6. Branch protection, a bot identity and the auto-merge eligibility check exist before any unattended merge.

None of these is large. Together they are perhaps a week of part-time work, and they replace several weeks of building things in the wrong order.
