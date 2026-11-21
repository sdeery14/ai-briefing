# Source catalogue — approved initial selection and future options

**Status:** The owner approved nine sources as the **initial editorial selection** on 2026-11-21. That is approval of which sources to follow. It is **not** permission to fetch or retain content.

**No source is enabled.** Under ADR-010, each source needs its own terms record, reviewed and approved by the owner, before it is switched on in `config/sources.yaml`. That file is created in M0. A publicly reachable feed is not treated as permission to store what it serves.

**Checked on:** 2026-11-21. "Verified" means a fact was observed directly that day: the feed URL returned a parseable feed, or a terms page was read.

## Approved initial selection

| # | Source | Purpose | Type and URL | Role | Terms status |
|---|---|---|---|---|---|
| 1 | OpenAI News | Model, API and product announcements | RSS: `https://openai.com/news/rss.xml` | Vendor | Not reviewed. Owner review required. |
| 2 | Google DeepMind blog | Research and model announcements | RSS: `https://deepmind.google/blog/rss.xml` | Vendor | Not reviewed. Owner review required. |
| 3 | Google Research blog | Research write-ups | RSS: `https://research.google/blog/rss/` | Vendor | Not reviewed. Owner review required. |
| 4 | Hugging Face blog | Open-model releases, tooling, tutorials | RSS: `https://huggingface.co/blog/feed.xml` | Vendor | Not reviewed. Owner review required. |
| 5 | arXiv, `cs.CL` only | New papers in computation and language | RSS: `https://rss.arxiv.org/rss/cs.CL` | Primary | **API terms read 2026-11-21** (summary below). Owner approval of the record still required. |
| 6 | MLflow releases | Tracking, tracing and evaluation tooling | Atom: `https://github.com/mlflow/mlflow/releases.atom` | Vendor | Not reviewed (GitHub terms; the project's licence for release notes). Owner review required. |
| 7 | Simon Willison's Weblog | Hands-on analysis of models and tools | Atom: `https://simonwillison.net/atom/everything/` | Independent | Not reviewed. Owner review required. |
| 8 | Hacker News | Attention signal and discovery of items outside the catalogue | Official API, base `https://hacker-news.firebaseio.com/v0/` | Community | **API README read 2026-11-21.** It states no terms for the data. Owner review required. |
| 9 | Anthropic SDK releases | Partial stand-in for Anthropic announcements | Atom: `https://github.com/anthropics/anthropic-sdk-python/releases.atom` | Vendor | Not reviewed (GitHub terms; the project's licence for release notes). Owner review required. |

All nine feed or API URLs were live on 2026-11-21. The arXiv URL shown is the single-category form of the address that was tested; the `cs.CL` feed itself answered that day but was empty because it was a Saturday.

### What has actually been reviewed

| Source | What was read | What it says |
|---|---|---|
| arXiv | Terms of Use for arXiv APIs | Descriptive metadata, which the terms define as including title, abstract, authors, identifiers and classification, is offered under CC0. At most one request every three seconds, on a single connection, across all machines under one's control. Do not store and serve e-print content (PDFs, source) from one's own servers. Do not present the project as endorsed by arXiv. |
| Hacker News | The official API README | No authentication. "There is currently no rate limit." The README gives no terms for use of the data. |
| The other seven | Nothing | Terms, permitted storage and retention are unknown. |

No permission has been assumed for any source. Where terms are unclear after review, the source stays metadata-only (ADR-010).

### Handling until a terms record is approved

- The source stays disabled. Nothing is collected from it.
- When enabled, the default is metadata plus whatever summary or content the source's own feed supplies, with no separate page fetch. Feed-supplied full text is treated as a body and kept for at most 90 days.
- Hacker News items are metadata only: title, link, score and comment count. Linked pages on hosts outside the catalogue are not fetched (open question Q6).

### Terms record to complete for each source

Terms URL; date reviewed; whether storing the feed's summary or content is permitted; whether a separate body fetch is permitted; retention in days; excerpt limit; rate limit; attribution or other restrictions.

### Known limitations of this selection

**Anthropic coverage is partial.** Anthropic has no announcement feed that was found (two conventional feed paths returned 404), and M1 reads only RSS, Atom and the Hacker News API. SDK releases show API changes, not model or policy announcements. Major Anthropic news will usually also arrive through Hacker News or independent commentary, where the editorial policy caps it at `watch`. This is accepted for now. No custom scraper is built. Discovery is revisited in M5 on evidence of stories that were actually missed.

**arXiv is limited to `cs.CL`.** This is to control volume. A single fetch of `cs.LG` alone returned 359 items; `cs.CL` volume was not measured, because the feed was empty on the day of the check. Further categories can be enabled after M1 measures collection volume and relevance.

**Mixed feeds.** OpenAI News and the Hugging Face blog mix technical releases with company and community posts, and Simon Willison's feed includes many short link posts each day. Screening has to filter these. Whether a narrower feed exists for the last one was not checked.

**Volume and price threshold.** Each screening request should stay under 100,000 input tokens, because the inexpensive model's price is five times higher above that threshold (RFC §7).

## Future options

Not part of the initial selection. Kept here so they can be added later through an owner-reviewed catalogue change. Feed URLs were live on 2026-11-21; no terms were reviewed.

| Source | Purpose | Type and URL | Role | Observed frequency |
|---|---|---|---|---|
| arXiv `cs.LG`, `cs.AI` | Wider research coverage | RSS: `https://rss.arxiv.org/rss/cs.LG+cs.CL+cs.AI` (combined form) | Primary | Daily; high volume |
| PyTorch releases | Core framework changes | Atom: `https://github.com/pytorch/pytorch/releases.atom` | Vendor | Frequent; may include pre-release tags |
| Transformers releases | Model library changes | Atom: `https://github.com/huggingface/transformers/releases.atom` | Vendor | Weekly or more |
| vLLM releases | Inference serving | Atom: `https://github.com/vllm-project/vllm/releases.atom` | Vendor | Weekly |
| Import AI | Weekly research and policy digest | RSS: `https://importai.substack.com/feed` | Independent; also aggregates | Weekly. Full text in feed. |
| Ahead of AI | Long-form explanations of research | RSS: `https://magazine.sebastianraschka.com/feed` | Independent | About monthly. Full text in feed. |
| Lil'Log | Deep technical surveys | RSS: `https://lilianweng.github.io/index.xml` | Independent | Infrequent |
| Mistral AI news | Model and platform announcements | RSS: `https://mistral.ai/news/rss` | Vendor | About weekly |
| BAIR blog | Academic research write-ups | RSS: `https://bair.berkeley.edu/blog/feed.xml` | Primary | Infrequent |
| Eugene Yan | Applied ML and LLM engineering patterns | RSS: `https://eugeneyan.com/rss/` | Independent | Infrequent |

A digest such as Import AI reports on other people's work. If it is added, corroboration should count the underlying source, not the digest.

## Considered and not proposed

| Source | Reason |
|---|---|
| Anthropic news site | No feed found |
| Meta AI blog | No feed found at the conventional path |
| Google "The Keyword" AI section | Largely product marketing; overlaps the DeepMind and Research blogs |
| Microsoft Research blog | Broad research scope beyond AI engineering |
| Latent Space | Daily commentary at high volume |
| The Gradient | Three posts since late 2024 |
| Chip Huyen's blog | No post since January 2025 |
| Reddit, X | Deferred by decision (ADR-003) |

## Next steps

1. Owner: review the terms of each of the nine sources and complete its record. arXiv is the furthest along.
2. M0: the approved selection becomes `config/sources.yaml`, every entry disabled.
3. A source is enabled, one at a time, by an owner-reviewed change once its record is complete. M1 can produce its first briefing with any subset that has been enabled.
