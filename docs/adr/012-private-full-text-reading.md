# ADR 012 — Private full-text reading where terms are silent

**Status:** Accepted (owner, 2026-11-23)
**Date:** 2026-11-23
**Amends:** [ADR-010](010-content-rights-and-retention.md), one sentence under "Per-source record". Everything else in ADR-010 stands.

## Context

ADR-010 allows article bodies "only from catalogued sources whose recorded terms permit it", and adds: "Where terms are unclear, the source is treated as metadata-only."

The terms review of 2026-11-21 found that only arXiv states what may be done with its content. The other enabled sources publish feeds and allow crawling in `robots.txt`, but their terms neither grant nor refuse the right to keep a private copy of an article or to send it to a model for analysis. Under ADR-010 as written, every one of them is metadata-only, and the model reads nothing but arXiv abstracts.

That defeats the product. RFC §4 and ADR-004 rest on assessments that cite quotations verified against stored text. ADR-010 itself rejected "never fetch bodies" because "assessments would rest on summaries and the integrity check would have little to check". With the rule applied strictly, that rejected alternative is what the system would do.

The uncertainty has two different kinds, which ADR-010 did not separate:

- **Access:** whether the pages may be read automatically at all. This is governed by the source's terms and `robots.txt`.
- **Use:** what may be done privately with text that was permissibly read. Most sources say nothing.

This ADR sets an operating policy. It is not legal advice.

## Decision

The sentence in ADR-010, "Where terms are unclear, the source is treated as metadata-only", is replaced by the following.

**Metadata-only remains the default where terms are unclear.** A source may be moved to full-text reading only by a decision of the owner, recorded in that source's terms record, and only when all of these hold:

1. **Access is permitted.** The source's terms do not prohibit automated reading of the pages concerned, and `robots.txt` allows it. A source whose automated access is uncertain or refused stays disabled or metadata-only. This ADR does not relax that.
2. **The text is private.** It is stored only on the owner's host and in its backups, and never enters the repository.
3. **Retention is bounded.** The text and the model-call request payloads that contain it are purged within 90 days, as ADR-010 already requires.
4. **Model submission is for analysis only**, to a provider whose terms state that it does not train on the content.
5. **Output never reproduces an article.** A briefing shows the system's own text, short attributed quotations within the source's recorded limit, and a link to the original.
6. **Use is personal and non-commercial.**

The terms record for such a source must:

- say that the terms are silent or unclear, and quote any sentence that bears on the question;
- give the date of the owner's decision;
- name the hosts an article page may be fetched from; a link to any other host stays metadata-only;
- state the body retention and the quotation limit.

A terms record must not describe unclear terms as permission. It records a decision taken under uncertainty.

**Express refusal still wins.** Where a source's terms prohibit automated access, copying for private use, or submission to AI systems, the source is not read in full, whatever the owner's preference.

Nothing else in ADR-010 changes: the retention table, the purge, the access behaviour, the rules for output and for the repository.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep ADR-010 as written | Only arXiv abstracts reach the model; the evidence design in ADR-004 has almost nothing to verify |
| Ask each publisher for permission first | The right long-term answer for some sources; too slow to be a precondition for a personal tool, and most will not reply. It stays open as a way to remove doubt |
| Treat silence as permission, with no conditions | Unauditable, and it would extend to redistribution and commercial use, which are different questions |
| Use only sources with open licences | Would remove most of the sources the owner selected |
| Send text to the model but store none of it | Quotations could not be verified later, which breaks the integrity check and the audit trail |

## Consequences

- The owner carries a judgement the source's terms do not settle. The terms records say so in plain words.
- Anyone else who runs this project must make the same judgement for themselves. The public configuration reflects the owner's decision, not a general permission.
- A source that later publishes terms refusing this use must be moved back to metadata-only, and its stored text purged, without waiting for the retention period.
- Re-review of each record at least once a year, as ADR-010 requires, now matters more.
- The conditions assume personal, non-commercial use. If the project gains other users, sends briefings to other people, or becomes commercial, this ADR must be revisited before that happens.

## Acceptance checks

- Every source in full-text mode has a terms record that states the terms are silent or unclear, the date of the owner's decision, the permitted hosts, the body retention and the quotation limit.
- No source whose automated access is recorded as uncertain is enabled.
- A test pins the set of full-text sources, so adding one fails until the owner's decision is recorded.
- Body retention for a full-text source never exceeds 90 days.
- No article page is fetched from a host that is not listed for its source.

## Revisit when

A source changes its terms or `robots.txt`; a publisher objects; the project gains users other than the owner or any commercial use; briefings are sent to other people; or the model provider's terms on training or retention change.
