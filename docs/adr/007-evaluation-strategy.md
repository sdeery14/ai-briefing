# ADR 007 — Evaluation strategy: deterministic gates and prospective evaluation

**Status:** Proposed
**Date:** 2026-11-19 (revised for RFC v0.3; previously "Blind offline editorial benchmarking before live ranking". Absorbs the evaluation content of v0.1 ADR-009.)

## Context

A green test suite does not show that editorial judgement is good. v0.1 planned to establish quality with a 40-case historical benchmark (12 public labels, 28 private) before any live ranking, and to calibrate five LLM judges.

The independent review found that the benchmark cannot do this:

- With 28 cases, an observed 71% accuracy has a 95% interval of roughly 53% to 85%.
- Labels come from one author and were written with knowledge of outcomes.
- Cases were selected because they were memorable.
- A current model may know how historical stories turned out, which an evidence cutoff does not prevent.
- A small holdout stops being blind after a few uses.

The owner accepts this criticism.

## Decision

### 1. Layers and what each may be used for

| Layer | Used for | Not used for |
|---|---|---|
| Deterministic tests | Hard CI gates | Judging editorial quality |
| Replay of recorded model responses | Regression gates on everything downstream of the model | Showing a prompt change helped |
| 40-case benchmark | Rubric calibration and a smoke test for new prompts | Any gate or accuracy claim |
| Prospective owner feedback and labels | The primary quality measure | Discovery recall |
| Blind comparison with the baseline digest | Whether the pipeline beats a single prompt; comparing variants | Explaining why |
| Reference-set comparison | Discovery recall by stage | Absolute recall |
| LLM judges | Diagnosis | Gating, until promoted under point 6 |

### 2. Deterministic checks are the hard gates

Schema validity, deduplication, idempotent re-runs, date and time-zone logic, citation integrity, policy ceilings, budget enforcement, network-policy tests, and replay of recorded responses. These run offline with no secrets on every pull request.

### 3. Prospective evaluation is primary

Each new day is a case that the prompts and models could not have seen. The owner commits about 15 to 20 minutes a week:

- Per-item feedback from the email (ADR-006).
- A weekly labelled sample of assessed stories, labelled before looking at the system's class where practical.
- A weekly note of important stories seen elsewhere that the system missed.
- A revisit at 30 and 90 days of items that were classed `major` or led a briefing.

Decision-time labels and later revisions are stored separately. The first answers "was this a reasonable call then"; the second answers "did it turn out to matter".

### 4. Blind comparison against the baseline

The single-prompt digest runs on the same day's collected items. The owner is shown both briefings unlabelled, in random order, and records a preference. This runs daily in M1 and on a weekly sample afterwards. The baseline stays as a permanent arm.

### 5. The benchmark

All 40 cases are a calibration aid and smoke test. The 28 private labels stay private because that costs nothing, are used rarely, and have no tooling built around them. The answer key is never stored on a machine or account where a coding agent runs, and never enters the repository, CI, prompts, logs or MLflow.

### 6. LLM judges

Judges may be built early for diagnosis. Their outputs are stored and reported as diagnostic, never as a gate. A judge becomes authoritative for a specific check only when:

- its agreement with owner labels has been measured on a stated sample and reported with an interval, and
- the owner approves the change through review of the gating configuration.

Agreement is re-measured whenever the judge's model or rubric changes.

### 7. Reporting rules

- Every metric is reported with its sample size and an uncertainty interval.
- Run-to-run variability is measured by assessing the same inputs several times. The resulting disagreement rate is the noise band; differences inside it are not treated as changes.
- **Citation integrity** (checked by code) and **semantic support** (does the quote support the claim, judged by a person on a sample) are reported as separate figures and never merged.
- No accuracy threshold is set until a trustworthy baseline exists.

### 8. Measures

| Question | Measure |
|---|---|
| Is the briefing useful? | Per-item feedback; blind preference against the baseline |
| Are `major` calls right? | Precision of `major` on prospective labels and at the 30- and 90-day revisit |
| Is hype kept out? | `overhyped` feedback rate; items that failed the revisit; vendor-only items reaching above `watch` (must be zero) |
| Is evidence sound? | Integrity failure rate (code); support rate on a labelled sample (person) |
| Is anything important missed? | For each reference story: collected, grouped, assessed at `watch` or above, briefed; loss at each stage; time to first seen |

### 9. Gating tiers

| Tier | When | Contents | Effect |
|---|---|---|---|
| 0 | Every pull request; offline; no secrets | Point 2 | Required |
| 1 | Started by the owner; uses an API key in a protected environment; never on forks | Live-model run on the public development set, repeated, compared with the main-branch result and the noise band | Informs the owner's review of prompt, model, rubric or policy changes |
| 2 | Weekly, by the owner | Prospective metrics, recall analysis, any private check | Sets priorities; results are not given to coding agents |

### 10. Independence from tooling

Evaluation is plain Python in the `evaluation` module. It reads the operational database or a snapshot and writes a versioned JSON result file. It has no MLflow dependency. Logging a result file to an MLflow experiment for comparison is optional (ADR-009).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Adjudicate and expand the historical benchmark | Does not fix sample size, selection bias or model hindsight |
| Gate on LLM judges from the start | Circular for editorial quality; unmeasured reliability |
| MLflow evaluation and scorers as the evaluation framework | Couples correctness checks to optional infrastructure |
| No structured evaluation | No protection while agents change the code |

## Consequences

Trustworthy numbers arrive slowly: a first baseline after several weeks of operation. Until then, gates are deterministic only and prompt changes rely on owner review. The approach depends on the owner's weekly time and on the feedback path working.

## Acceptance checks

- Tier 0 runs to completion with networking disabled and no credentials.
- A scan of public evaluation data finds no private-label fields.
- Every figure in an evaluation result file has a sample size and an interval.
- A judge's score cannot change a gate outcome unless the gating configuration, a protected file, names it.
- Integrity and support appear as separate fields in results.

## Revisit when

Prospective labels are numerous enough to set thresholds, a judge meets the promotion conditions, or the weekly time commitment proves unsustainable.
