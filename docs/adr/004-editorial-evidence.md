# ADR 004 — Evidence records and a deterministic editorial policy

**Status:** Proposed
**Date:** 2026-11-19 (revised for RFC v0.3)

## Context

Popularity and confident writing are poor guides to importance. v0.1 asked one model output for scores, a class, a placement and a merge decision, and treated evidence as a list of document IDs. The review found that citations could not be verified, that corroboration was undefined, and that the single output mixed decisions that belong to different parts of the system.

## Decision

### Three separate steps

| Step | Performed by | Output |
|---|---|---|
| Assessment | Model | Claims, evidence, dimension scores, uncertainty, suggested class, draft text |
| Policy | Code | Final class, ceiling and reasons, eligibility |
| Selection | Code | Which stories appear, in what order (ADR-006, RFC §6.5) |

Merging is a grouping decision (ADR-003). Placement is a selection decision. Neither is part of the assessment.

### Assessment

- Five dimensions scored 0 to 4: impact, evidence, novelty, professional relevance, maturity. Each level has a written anchor. Relevance is judged for one stated reference audience.
- The dimensions are not combined into a single weighted number.
- The schema puts claims and evidence before scores and the suggested class.
- A standard assessment uses the inexpensive model. Code escalates a story to the capable model once when the policy marks it as potentially `major` or its uncertainty is high, budget permitting.

### Evidence

- The model cites only observation IDs present in its input and never outputs a URL. URLs shown to the reader are resolved from stored documents.
- Each supporting citation includes a verbatim quote.
- Each citation becomes an `EvidenceItem` with two independent fields:
  - **Integrity status**, set by code: the ID was in the input, the quote occurs in the stored text after whitespace and Unicode normalisation, and the observation predates the assessment.
  - **Support label**, initially `unreviewed`: whether the quote actually supports the claim. Only a person, or later a calibrated judge, sets this.
- An item that fails integrity is recorded and excluded from support.

**A verified quote proves that the source contains those words. It does not prove the claim, and it does not prove the quote supports the claim.** The system never presents integrity as verification of truth.

### Source roles and corroboration

Each document has a role: primary, vendor, independent, community or aggregator. Independent corroboration counts distinct primary or independent sources. Several documents repeating one announcement count once.

### Policy

Classes are `major`, `practical`, `watch` and `low`. The final class is the lower of the suggested class and a ceiling computed from evidence facts. The starting rules are in RFC §6.2. They are versioned code in a protected path and change only with owner review.

### Reassessment and repetition

- Reassess when the input set changes, or the prompt, rubric or model changes for an open story.
- Re-decide, without a model call, when the policy version changes.
- A briefed story is eligible again only when its final class changed or new primary or independent evidence arrived.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Let the model set the final class | Persuasive source text can then promote a story; no rule is auditable |
| A weighted score | Hides which dimension drove the outcome and invites tuning to a number |
| Free-form citations with URLs | Allows invented or unsupported links |
| An LLM judge for groundedness instead of the integrity check | Costlier and less reliable for the part that code can check exactly |
| Treating a verified quote as a verified claim | Overstates what was checked |

## Consequences

More structure in the prompt and schema. Policy rules need maintenance and will sometimes hold back a story that deserved more. That is the intended bias for an evidence-first product, and it is measured in M4.

## Acceptance checks

- An assessment citing an ID that was not in its input is rejected.
- A quote absent from the stored observation is marked failed and does not count as support.
- A story supported only by vendor sources making a comparative claim does not exceed `watch`, whatever the model suggested.
- Changing the policy version produces new decisions without new model calls.
- Every URL in an exported briefing matches a stored document.
- Reports show integrity results and human support labels as separate figures.

## Revisit when

Owner labels show the policy ceilings are systematically too strict or too loose, or the dimension scores prove too noisy to be useful.
