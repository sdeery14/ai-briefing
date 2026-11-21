# Source terms records

The terms record for each of the nine sources in the initial selection, as required by ADR-010. The machine-readable form is `config/sources.yaml`; this page holds the reasoning and the pages that were read.

- **Reviewed:** 2026-11-21, from public terms and policy pages only. No source content was collected for this review.
- **Approved by the owner:** 2026-11-21, for personal, non-commercial use, in the operating modes below.
- **This is an operating policy, not legal advice.**

## How to read a record

Three permissions are kept apart, because having one does not give the others:

| Permission | Question |
|---|---|
| Access | May the feed or API be read automatically? |
| Storage | What may be kept in the database, and for how long? |
| Model submission | What may be sent to the model provider for analysis? |

Each conclusion is marked:

- **Explicit** — the terms say so.
- **Interpretation** — a reasonable reading that the terms do not state.
- **Uncertain** — unresolved. The conservative option is taken.

The model provider's own terms apply to every source. Anthropic's commercial terms require the customer to warrant that it "has all rights and permissions required to submit Inputs". They state that Anthropic does not train on customer content, and its documentation says API inputs and outputs are deleted within 30 days by default. So material is submitted only where the right to submit it is clear. ([commercial terms](https://www.anthropic.com/legal/commercial-terms), [retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data))

## Summary

| Source | Mode | Access | Stored | Sent to model |
|---|---|---|---|---|
| arXiv `cs.CL` | Feed-summary | Explicit | Metadata and abstracts, indefinitely | Titles and abstracts |
| Google DeepMind blog | Metadata-only | Explicit | Metadata | Nothing |
| Google Research blog | Metadata-only | Explicit | Metadata | Nothing |
| Hugging Face blog | Metadata-only | Interpretation | Metadata | Nothing |
| Simon Willison (long-form entries) | Metadata-only | Interpretation | Metadata | Nothing |
| Hacker News | Metadata-only | Interpretation | Item metadata, no usernames | Nothing |
| OpenAI News | Disabled | Uncertain | Nothing | Nothing |
| MLflow releases | Disabled | Uncertain | Nothing | Nothing |
| Anthropic SDK releases | Disabled | Uncertain | Nothing | Nothing |

"Metadata" means title, link, dates and identifiers. In metadata-only mode the summary or content a feed supplies is discarded when read, and no excerpt is used. No source is approved for fetching article bodies.

### What this means for M1

Only arXiv supplies text the model may read. The other five enabled sources contribute titles and links that the model never sees, so they cannot be screened or assessed by it. Under the editorial policy a metadata-only story cannot exceed `watch` in any case. How those items appear in a briefing is a decision for M1 (see "Open points").

## Records

### arXiv `cs.CL`

- **Feed:** `https://rss.arxiv.org/rss/cs.CL`
- **Pages read:** [API terms of use](https://info.arxiv.org/help/api/tou.html), [licences](https://info.arxiv.org/help/license/index.html), [RSS](https://info.arxiv.org/help/rss.html), [robots](https://info.arxiv.org/help/robots.html), [bulk data](https://info.arxiv.org/help/bulk_data.html)
- **Access — explicit.** The terms cover RSS by name: "make no more than one request every three seconds, and limit requests to a single connection at a time."
- **Storage — explicit.** "You are free to use descriptive metadata about arXiv e-prints under the terms of the Creative Commons Universal (CC0 1.0) Public Domain Declaration", and descriptive metadata "includes fields such as title, abstract, authors, identifiers, and classification terms". The terms permit users to "retrieve, store, transform, and share" it.
- **Bodies — not used.** Storing and serving e-print content is prohibited without the rights holder's permission. PDFs are never fetched.
- **Model submission — interpretation, on an explicit licence.** The terms do not mention AI tools. CC0 places no restriction on use.
- **Retention:** indefinite for metadata and abstracts.
- **Attribution:** none required. Link to the abstract page. Do not imply endorsement by arXiv.
- **Rate:** one fetch a day; the feed updates daily.
- **Uncertainty:** the RSS page calls feeds "intended primarily for human consumption" and names OAI-PMH as the preferred route for keeping a copy of metadata. One daily request is within the stated limits.

### Google DeepMind blog and Google Research blog

- **Feeds:** `https://deepmind.google/blog/rss.xml`, `https://research.google/blog/rss/`
- **Pages read:** [Google Terms of Service](https://policies.google.com/terms) (effective 30 July 2026), [DeepMind robots.txt](https://deepmind.google/robots.txt), [Research robots.txt](https://research.google/robots.txt), both blog index pages. Both footers link only to the Google terms and privacy policy.
- **Access — explicit, conditional.** The terms prohibit "using automated means to access content from any of our services in violation of the machine-readable instructions", such as "robots.txt files that disallow crawling, training, or other activities". Both robots.txt files allow everything for all agents.
- **Storage — uncertain beyond metadata.** Neither blog states a content licence. The terms say "You may use Google's content as allowed by these terms" and grant no right to copy blog text.
- **Model submission — uncertain.** Nothing addresses sending article text or titles to a third-party model. Nothing is submitted.
- **Retention:** metadata indefinitely; nothing else kept.
- **Attribution:** link to the original post. Do not alter Google branding or notices.
- **Not read:** Google's service-specific terms and its generative AI prohibited-use policy.
- **Re-review trigger:** a change to either robots.txt.

### Hugging Face blog

- **Feed:** `https://huggingface.co/blog/feed.xml`
- **Pages read:** [terms of service](https://huggingface.co/terms-of-service) (effective 15 September 2022), [content policy](https://huggingface.co/content-policy) (effective 10 April 2025), [robots.txt](https://huggingface.co/robots.txt), the blog index.
- **Access — interpretation.** The terms have no clause on automated reading. robots.txt allows everything and the site publishes the feed. The content policy prohibits "excessive bulk activity".
- **Storage — uncertain beyond metadata.** "You may not alter, reproduce, republish, license any of our proprietary materials, unless we expressly give you a written permission to do so." The blog mixes official and community posts; neither states a licence.
- **Model submission — uncertain.** Not addressed. Nothing is submitted.
- **Retention:** metadata indefinitely; nothing else kept.
- **Attribution:** link to the original post.
- **Not read:** individual post pages, which might carry their own licence.

### Simon Willison's Weblog

- **Feed:** `https://simonwillison.net/atom/entries/` (long-form entries only)
- **Pages read:** [about](https://simonwillison.net/about/), [robots.txt](https://simonwillison.net/robots.txt), the home page, and the header of two feeds.
- **Access — interpretation.** The about page offers Atom feeds for following the blog. robots.txt disallows only `/admin/` and `/search/`.
- **Storage — uncertain beyond metadata.** No licence or terms are stated anywhere that was read; the footer is a bare copyright sign. Default copyright applies. The feed carries full post HTML, which is discarded when read.
- **Model submission — uncertain.** Not addressed. Nothing is submitted.
- **Retention:** metadata indefinitely; nothing else kept.
- **Attribution:** link to the post and name the author.
- **Simplest way to resolve the uncertainty:** ask the author. He has not been asked.

### Hacker News

- **API:** `https://hacker-news.firebaseio.com/v0/`
- **Pages read:** [API README and licence](https://github.com/HackerNews/API), [Y Combinator terms](https://www.ycombinator.com/legal), [robots.txt](https://news.ycombinator.com/robots.txt), [FAQ](https://news.ycombinator.com/newsfaq.html)
- **Access — interpretation.** The README says "There is currently no rate limit" and states no terms for the data. The API is Y Combinator's own published route. Its host is not a Y Combinator subdomain.
- **Storage:** item id, title, link, score, comment count, time and type. Not the submitter's username, which is personal data the project has no use for, and not comment text.
- **Model submission — uncertain.** Titles are written by users and often copy a third-party headline. Nothing is submitted.
- **Retention:** metadata indefinitely.
- **Attribution:** link to the Hacker News item and to the linked page.
- **Rate:** self-imposed, at most one request a second on one connection.
- **Restrictions kept regardless:** the API only; never the HTML pages. Pages linked from Hacker News on hosts outside the catalogue are not fetched.
- **Unverified:** Y Combinator's terms cover "all subdomains" and reportedly prohibit "data mining, robots, scraping or similar data gathering or extraction methods". That clause came from a summary of a page that was only partly read. The owner should read it directly. The MIT licence on the API repository covers the repository, not the data.

### OpenAI News — disabled

- **Feed (not used):** `https://openai.com/news/rss.xml`
- **Pages read:** [terms of use](https://openai.com/policies/terms-of-use/) (effective 1 January 2026), [robots.txt](https://openai.com/robots.txt), the policies index, the sharing and publication policy, the brand page.
- **Access — uncertain.** The terms define Services to include "associated software applications and websites" and prohibit users from acting to "automatically or programmatically extract data or Output". Against that, the site publishes and links an RSS feed, and robots.txt allows everything.
- **Why disabled:** the wording of the terms and the existence of the feed point in different directions, and automated access is the one permission everything else depends on.
- **To enable later:** the owner accepts that reading a published feed is the intended use, in which case metadata-only is the defensible mode.
- **Not read:** OpenAI's Service Terms and its content-attribution page.

### MLflow releases and Anthropic SDK releases — disabled

- **Feeds (not used):** `https://github.com/mlflow/mlflow/releases.atom`, `https://github.com/anthropics/anthropic-sdk-python/releases.atom`
- **Pages read:** [GitHub terms of service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service), [acceptable use policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies), [robots.txt](https://github.com/robots.txt), and both repositories' licence files.
- **Access — uncertain for the Atom feeds.** GitHub's robots.txt has `Disallow: /*.atom$` for generic agents. The acceptable-use policy defines scraping as "extracting information from our Service via an automated process" and lists research and archival as the permitted purposes. It adds that "Scraping does not refer to the collection of information through our API."
- **Why disabled:** the sanctioned route is GitHub's REST API, which needs an adapter that has not been approved. No new adapter is introduced now.
- **Content:** both repositories are Apache-2.0. Neither that licence nor GitHub's terms says release notes fall under it.
- **Consequence:** there is no direct coverage of Anthropic announcements in the initial selection.
- **Disclosure:** on 2026-11-21, before robots.txt was checked, five GitHub release feeds were each fetched once to confirm they existed. Nothing from them was stored.

## Open points

These do not block the configuration. They are recorded so they are not lost.

| # | Point | Current handling |
|---|---|---|
| 1 | May titles and links from metadata-only sources be sent to the model? | No. They are never submitted. If the owner later decides titles are plain bibliographic facts that may be submitted, that is a change to `model_submission` for those sources. |
| 2 | How do metadata-only items appear in a briefing when the model has not seen them? | Undecided; an M1 question. The policy already caps them at `watch`. |
| 3 | The Y Combinator terms clause on scraping | Unverified verbatim. Owner to read. |
| 4 | Permission from Simon Willison | Not requested. |
| 5 | OpenAI News | Disabled pending the owner's reading of the terms. |
| 6 | A GitHub API adapter | Not approved. Revisit in M5 on evidence of missed stories. |
| 7 | Pages not read (Google service-specific terms, OpenAI Service Terms, individual Hugging Face posts) | Listed in each record. |

## Re-review

Review a record again when the source changes its terms or robots.txt, when the mode is to be loosened, and otherwise at least once a year. Record the new date in `config/sources.yaml`.
