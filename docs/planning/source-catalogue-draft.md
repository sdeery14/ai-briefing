# Initial source catalogue — draft for owner approval

**Status:** Draft. **No source is enabled.** Nothing is collected until the owner approves each entry and its terms record is completed in `config/sources.yaml` (ADR-003, ADR-010). That file is created in M0, not in this pull request.

**Checked on:** 2026-11-21. "Verified" below means a fact was observed directly that day: the feed URL returned a parseable feed, or a terms page was read. Everything else needs the owner's review.

## How to read this

- **Role** is the source role used by the editorial policy (ADR-004): vendor, primary, independent, community or aggregator.
- **Frequency** is what the feed's recent dates showed, not a published schedule.
- **Proposed handling** is deliberately conservative. Unless terms have been read and recorded, a source is metadata plus whatever summary or content its own feed supplies, with no separate page fetch. Feed-supplied full text is treated as a body and kept for at most 90 days.
- Feed-supplied text is enough for M1. Most of these feeds carry a summary, abstract or release notes, which is what the assessor and the citation-integrity check work from.

## Core proposal (15 sources)

### Model providers and platforms

| # | Source | Purpose | Type and URL | Role | Frequency | Verified | Needs owner review |
|---|---|---|---|---|---|---|---|
| 1 | OpenAI News | Model, API and product announcements | RSS: `https://openai.com/news/rss.xml` | Vendor | Several a week; latest item 20 Nov 2026 | Feed live | Site terms. The feed mixes company news with technical releases, so screening must filter. |
| 2 | Google DeepMind blog | Research and model announcements | RSS: `https://deepmind.google/blog/rss.xml` | Vendor | A few a week; latest 18 Nov 2026 | Feed live | Site terms |
| 3 | Google Research blog | Research write-ups | RSS: `https://research.google/blog/rss/` | Vendor | A few a week; latest 20 Nov 2026 | Feed live | Site terms |
| 4 | Hugging Face blog | Open-model releases, tooling, tutorials | RSS: `https://huggingface.co/blog/feed.xml` | Vendor | Near daily; latest 20 Nov 2026 | Feed live | Site terms. High volume and mixed depth; may include community posts. |
| 5 | Anthropic SDK releases | Proxy for Anthropic API changes (see note A) | Atom: `https://github.com/anthropics/anthropic-sdk-python/releases.atom` | Vendor | Several a week; latest 20 Nov 2026 | Feed live | GitHub terms; whether this is an acceptable stand-in |

### Research

| # | Source | Purpose | Type and URL | Role | Frequency | Verified | Needs owner review |
|---|---|---|---|---|---|---|---|
| 6 | arXiv: cs.LG, cs.CL, cs.AI | New ML and AI papers | RSS: `https://rss.arxiv.org/rss/cs.LG+cs.CL+cs.AI` | Primary | Daily at midnight US Eastern; a single fetch of cs.LG alone returned 359 items | Feed live. Terms read: descriptive metadata, including abstracts, is CC0; at most one request every three seconds on one connection; do not store and serve e-print content. | Which categories. This is by far the largest source and the main driver of screening volume. |

### Engineering tools and frameworks

| # | Source | Purpose | Type and URL | Role | Frequency | Verified | Needs owner review |
|---|---|---|---|---|---|---|---|
| 7 | PyTorch releases | Core framework changes | Atom: `https://github.com/pytorch/pytorch/releases.atom` | Vendor | Feed showed entries dated 21 Nov 2026 | Feed live | GitHub terms; whether pre-release tags should be filtered |
| 8 | Transformers releases | Model library changes | Atom: `https://github.com/huggingface/transformers/releases.atom` | Vendor | Weekly or more; latest 21 Nov 2026 | Feed live | GitHub terms |
| 9 | vLLM releases | Inference serving | Atom: `https://github.com/vllm-project/vllm/releases.atom` | Vendor | Weekly; latest 18 Nov 2026 | Feed live | GitHub terms |
| 10 | MLflow releases | Tracking, tracing and evaluation tooling | Atom: `https://github.com/mlflow/mlflow/releases.atom` | Vendor | Weekly or more; latest 21 Nov 2026 | Feed live | GitHub terms |

Which repositories to follow is an editorial choice. These four match tools the owner is known to use; swap freely.

### Engineering analysis

| # | Source | Purpose | Type and URL | Role | Frequency | Verified | Needs owner review |
|---|---|---|---|---|---|---|---|
| 11 | Simon Willison's Weblog | Hands-on analysis of models and tools | Atom: `https://simonwillison.net/atom/everything/` | Independent | Many items a day (includes short link posts) | Feed live | Site terms; whether a narrower feed exists that carries only full posts |
| 12 | Import AI | Weekly research and policy digest with commentary | RSS: `https://importai.substack.com/feed` | Independent (also aggregates; see note B) | Weekly, Mondays | Feed live; carries full text and a copyright element | Substack and author terms; full-text retention |
| 13 | Ahead of AI | Long-form explanations of research and techniques | RSS: `https://magazine.sebastianraschka.com/feed` | Independent | About monthly; latest 15 Nov 2026 | Feed live; carries full text and a copyright element | Substack and author terms; whether some posts are subscriber-only |
| 14 | Lil'Log | Deep technical surveys | RSS: `https://lilianweng.github.io/index.xml` | Independent | Infrequent; latest 4 Jul 2026 | Feed live | Site terms |

### Community discovery

| # | Source | Purpose | Type and URL | Role | Frequency | Verified | Needs owner review |
|---|---|---|---|---|---|---|---|
| 15 | Hacker News | Attention signal and discovery of items outside the catalogue | Official API, base `https://hacker-news.firebaseio.com/v0/` (`topstories`, `beststories`, `item/<id>.json`) | Community | Continuous | API live, no authentication. The official README says "There is currently no rate limit." | The README states no terms for the data. Score threshold and polling interval. |

Hacker News items are metadata only: title, link, score and comment count. Linked pages on hosts outside the catalogue are not fetched (open question Q6).

## Optional additions

| Source | Purpose | Type and URL | Role | Frequency | Verified | Why optional |
|---|---|---|---|---|---|---|
| Mistral AI news | Model and platform announcements | RSS: `https://mistral.ai/news/rss` | Vendor | About weekly; latest 5 Nov 2026 | Feed live (served as plain text) | Adds a provider; lower volume |
| BAIR blog | Academic research write-ups | RSS: `https://bair.berkeley.edu/blog/feed.xml` | Primary | Infrequent; latest 9 Nov 2026 | Feed live | Low volume |
| Eugene Yan | Applied ML and LLM engineering patterns | RSS: `https://eugeneyan.com/rss/` | Independent | Infrequent; latest 19 Nov 2026 | Feed live | Low volume |

## Considered and not proposed

| Source | Reason |
|---|---|
| Anthropic news site | No feed found; two conventional feed paths returned 404 (note A) |
| Meta AI blog | No feed found at the conventional path (404) |
| Google "The Keyword" AI section | Feed is live, but it is largely product marketing and overlaps sources 2 and 3 |
| Microsoft Research blog | Feed is live; broad research scope beyond AI engineering |
| Latent Space | Feed is live; daily commentary at high volume |
| The Gradient | Feed is live; three posts since late 2024 |
| Chip Huyen's blog | Feed is live; no post since January 2025 |
| Reddit, X | Deferred by decision (ADR-003) |

## Notes

**A. Anthropic coverage.** The chosen model provider has no announcement feed that I could find, and M1 reads only RSS, Atom and the Hacker News API. Source 5 is a partial stand-in. Major Anthropic announcements will usually also arrive through Hacker News and Import AI, but as community or secondary coverage they are capped at `watch` by the editorial policy. Options for the owner: accept this until M5, or add a small page-based adapter for provider announcement pages as a separate, reviewed decision.

**B. Digests and corroboration.** Import AI reports on other people's work. When it covers a paper or release, corroboration should count the underlying source, not the digest. Until source-role rules are complete in M3, treat it as independent commentary and do not let it alone raise a story above `watch`.

**C. Volume.** arXiv dominates. One category returned 359 items in a single fetch; the three together will be higher. This sets the size of the screening step and is the first thing M1 measures. Each screening request should stay under 100,000 input tokens, because the inexpensive model's price is five times higher above that threshold (RFC §7).

**D. Terms.** Only arXiv's API terms and the Hacker News API README were read. For every other source the terms record is empty and must be completed by the owner before the source is enabled. Where terms are unclear the source stays metadata-only (ADR-010).

## What the owner is asked to do

1. Strike, swap or add sources. The list is an editorial choice.
2. For each source kept, read its terms and fill in the record: terms URL, date reviewed, whether body or full-text storage is permitted, retention, excerpt limit.
3. Decide the Anthropic coverage question in note A.
4. Approve. The approved list becomes `config/sources.yaml` in M0, with every source disabled until its record is complete.
