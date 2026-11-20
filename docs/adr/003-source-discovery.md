# ADR 003 — Curated discovery first; search and research deferred

**Status:** Proposed
**Date:** 2026-11-19 (revised for RFC v0.3; previously "Hybrid scheduled discovery and bounded research")

## Context

v0.1 put three discovery mechanisms in V1: curated feeds, search-provider discovery and targeted research. The review found no evidence yet that curated sources are insufficient, no volume or cost model, and no stated way to group documents into stories.

## Decision

### Sources in V1

1. A curated catalogue of official and research sources read by RSS or Atom, including release feeds.
2. Hacker News through its public API, as a discovery and attention signal.
3. Reddit and other community sources, search-provider discovery and research-on-demand are deferred to M5. They are added only when coverage analysis in M4 shows a gap they would close.

Each catalogue entry records its source role, polling interval, rate limit, the URL of its terms, the date those terms were reviewed, whether body fetching is permitted, and its retention settings (ADR-010). A source is not enabled until this is filled in. Catalogue changes require owner review.

### Collection

- Conditional requests, per-source backoff and independent failure: one failing source does not fail the run.
- Source health is recorded and reported by `doctor`.

### Triage and screening

- Deterministic triage removes items that are already processed, outside the freshness window, malformed or from disabled sources. Low popularity never removes an item.
- An inexpensive model then screens titles and summaries in batches. Every outcome is stored with a reason.

### Body fetching

- Bodies are fetched only for items that pass screening, only from catalogued sources whose recorded terms permit it, and only by code. The model never selects a URL.
- A page linked from Hacker News whose host is not in the catalogue is kept as metadata only. Such a story cannot exceed `watch` under the editorial policy unless a catalogued source also covers it. Hosts that recur this way are reported as candidates for the catalogue.

### Story grouping

- **M1:** documents that share a canonical URL, or link to the same URL, form one story. This is deterministic and covers the common case of a post and its discussion thread.
- **M3:** for a new document, code shortlists recent open stories by full-text similarity within a time window. The model answers, for at most a few shortlisted stories, whether the document belongs to one of them. Code applies the answer.
- Every membership change is an append-only `StoryMembershipEvent` naming the rule or model call that decided it.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Search-provider discovery in V1 | Cost and terms unknown; no measured gap |
| Research loop in V1 | Needs assessment data to show where evidence was thin |
| Reddit as a community source | Requires per-installer credentials and has restrictive terms; Hacker News is sufficient to start |
| Embedding-based grouping | Adds a dependency and re-embedding cost; adopt only if the lexical shortlist misses too much |
| Fetching any page linked from a community item | Terms cannot be known for arbitrary hosts |

## Consequences

Some stories will be seen late or only as metadata. That is measured in M4 instead of being guessed at now. Maintaining the catalogue and its recorded terms is an ongoing owner task.

## Acceptance checks

- Re-collecting the same items creates no new documents.
- A simulated outage of one source leaves the others collected and the run successful.
- A feed item and a Hacker News item linking to it end up in one story.
- An item from an uncatalogued host has no stored body.
- Every screened item has a stored outcome and reason.

## Revisit when

M4 coverage analysis shows important stories that were never collected, or grouping errors that the lexical shortlist cannot fix.
