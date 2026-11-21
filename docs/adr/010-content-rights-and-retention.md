# ADR 010 — Content rights and retention

**Status:** Accepted (owner, 2026-11-21)
**Date:** 2026-11-19 (new in RFC v0.3)

## Context

The system reads third-party content, stores some of it, quotes from it and is developed in a public repository. v0.1 stored observation payloads and relied on them for replay, but left retention undecided. The review found that this choice shapes the schema and the evaluation design, and that sources differ in what they permit.

This ADR sets a conservative operating policy. It is not legal advice.

## Decision

### What is stored and for how long

| Content | Stored | Retention |
|---|---|---|
| Source metadata: URL, title, author, dates, identifiers | Always | Indefinite |
| Summaries supplied by the source's feed, where its terms permit | When permitted | Indefinite |
| Fetched body text | Only from catalogued sources whose recorded terms permit it; private, on the host only | Up to 90 days, or less if the source entry says so |
| Evidence excerpts (the quotes in evidence items), within the source's excerpt limit | When permitted | Indefinite |
| Content hashes | Always | Indefinite |
| Model-call request payloads (they contain source text) | Private, on the host only | Same as bodies |
| Model-call responses and the system's own text | Always | Indefinite |

After the retention period, a scheduled job nulls body text and request payloads and records when it did so. Hashes, metadata and permitted excerpts remain, so integrity results stay auditable.

### Per-source record

Each catalogue entry records: the terms URL and the date they were reviewed; whether body fetching is permitted; body retention in days; the excerpt limit; rate limits; any attribution requirement; any other restriction. A source cannot be enabled without this. Catalogue changes require owner review (ADR-011).

Where terms are unclear, the source is treated as metadata-only.

### Access behaviour

Respect `robots.txt` and published rate limits. Identify the client with a generic user agent and no personal details. No scraping of pages behind a login or paywall.

### Output

Briefings contain the system's own summaries, short attributed excerpts within each source's limit, and links to originals. They never reproduce an article.

### The repository

The public repository never contains third-party article bodies, private data, credentials, local configuration or benchmark holdout labels. Test fixtures, recorded model responses and public evaluation cases are synthetic, written by the owner, or drawn from content whose licence permits redistribution, with the licence noted beside them.

### Consequences for replay

Re-running stored inputs through a new prompt is possible for 90 days on full text. Beyond that, only metadata, summaries and excerpts remain. Prospective evaluation (ADR-007) does not depend on long-term replay.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep all fetched text indefinitely | Best for replay; weakest position on terms; unnecessary once evaluation is prospective |
| Never fetch bodies | Safest; assessments would rest on summaries and the integrity check would have little to check |
| Decide per source informally | Unauditable, and easy for an agent or contributor to get wrong |

## Consequences

Some stories are assessed from metadata only and are capped by the editorial policy. The owner must review terms when adding a source and re-review periodically. Backups contain the same private text and follow the same retention.

## Acceptance checks

- A source without a completed terms record cannot be enabled.
- No body is stored for a source that does not permit it.
- After the purge job, no body text or request payload older than its retention period remains, and the corresponding hashes do.
- A CI check fails if a fixture directory contains a file not listed in the fixtures licence manifest.
- Exported excerpts do not exceed the source's excerpt limit.

## Revisit when

A source's terms change, the project gains users in other jurisdictions, or evaluation needs longer replay than 90 days.
