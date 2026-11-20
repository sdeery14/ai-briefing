# ADR 005 — Education: a concept note in V1, a persistent curriculum in M6

**Status:** Proposed. The V1 part applies from M1. The curriculum part is a planned design, to be confirmed before M6.
**Date:** 2026-11-19 (revised for RFC v0.3)

## Context

The product vision combines industry intelligence with structured continuous education. v0.1 put the full curriculum in V1. The review found that it doubled V1's scope, had no decided content source, and could not record more than delivery without a feedback path. The owner's decision is to keep the vision, defer the engine, and keep a light educational element in V1.

## Decision

### V1: concept note

1. When one of the day's selected stories turns on a technical concept the reference audience may not know well, the briefing includes a short explanation (about 120 words) tied to that story.
2. It is optional. A day with no suitable concept has none.
3. It is labelled as background written by the model. It may cite the day's source documents by ID and contains no other links.
4. A normalised concept key is stored. The same concept is not repeated within 30 days.
5. No progress, prerequisite or mastery state exists in V1. Nothing is inferred about what the reader knows.

### M6: persistent curriculum (planned)

1. **Content.** Tracks, modules and lessons are versioned files. Each lesson has objectives, prerequisites, topic tags and canonical references. Lesson text is written once from those references, reviewed by the owner, and stored. It is not regenerated daily.
2. **Progress states**, none of which is inferred from an earlier one:

   | State | Evidence required |
   |---|---|
   | Scheduled | Selected for a briefing |
   | Delivered | Included in an exported briefing |
   | Acknowledged | The reader marked it read through the feedback path |
   | Self-rated | The reader reported confidence |
   | Checked | The reader answered a recall question on a later day |

   Sequence position advances on delivery. Understanding is claimed only from a check.
3. **News and learning.** Deterministic rules over shared topic tags. A matching current story is attached to the active lesson. A story matching a later lesson whose prerequisites are met may pull that lesson forward, at most once a week, after which the sequence resumes.
4. **Curriculum change.** New lessons arrive only through owner-reviewed changes. The system may report topics that recur in `major` and `practical` stories with no matching lesson. Concept keys accumulated since M1 are an input.
5. **Layers.** Shared knowledge (sources, stories, evidence, assessments) contains nothing about a reader. Progress and feedback are held per profile. Feedback never edits a shared assessment.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Full curriculum in V1 | Scope and missing content source |
| No educational element until M6 | Loses the product's second half for months and collects no signal about which concepts matter |
| Lessons generated fresh each day | Unreviewed, unsourced text in an evidence-first product |
| Inferring understanding from delivery | Not evidence |

## Consequences

V1 teaches opportunistically, not cumulatively. The concept note is model-written background and is labelled as such. The M6 design will be reviewed again before it is built.

## Acceptance checks (V1)

- A briefing with no qualifying concept has no concept note and still validates.
- A concept used within the previous 30 days is not selected again.
- The concept note contains no URL that is not a stored source document.
- The database contains no progress or mastery records.

## Revisit when

M6 begins, or feedback shows the concept note is not read.
