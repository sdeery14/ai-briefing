# Source terms records

The terms record for each of the nine sources in the initial selection, as required by ADR-010. The machine-readable form is `config/sources.yaml`; this page holds the reasoning and the pages that were read.

- **Reviewed:** 2026-11-21, from public terms and policy pages only. No source content was collected for this review.
- **Approved by the owner:** 2026-11-21, for personal, non-commercial use.
- **Widened by the owner:** 2026-11-23. Four sources may be read in full, and Hacker News metadata may be sent to the model. See "The decision of 2026-11-23".
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
- **Uncertain** — unresolved. The conservative option is taken, unless the owner has decided otherwise and the record says so.

The model provider's own terms apply to every source. Anthropic's commercial terms require the customer to warrant that it "has all rights and permissions required to submit Inputs". They state that Anthropic does not train on customer content, and its documentation says API inputs and outputs are deleted within 30 days by default. ([commercial terms](https://www.anthropic.com/legal/commercial-terms), [retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data))

## The decision of 2026-11-23

The first approval sent only arXiv text to the model. The owner judged that too narrow for the product: a briefing must be able to cite specific quotations and figures from the articles it reports on, which is what RFC §4 and ADR-004 describe.

No source's terms expressly grant the right to keep article text or to send it to a model. ADR-010 said that a source with unclear terms is metadata-only. [ADR-012](../adr/012-private-full-text-reading.md) amends that sentence: metadata-only stays the default, and the owner may move a source to full-text reading by a recorded decision when all of these hold:

1. Access is permitted: the terms do not prohibit automated reading of the pages concerned, and `robots.txt` allows it.
2. The text is stored only on the owner's machine and never enters the repository.
3. The text is purged within 90 days.
4. The text is sent to the model provider for analysis only, and the provider does not train on it.
5. Briefings show short attributed quotations and a link, never a reproduced article.
6. Use is personal and non-commercial.

The owner took that decision for the four sources below on 2026-11-23. Their terms remain silent or unclear on this use. The decision does not turn that silence into permission; it is a judgement taken under uncertainty, and an operating policy, not legal advice. The terms pages are as they were on 2026-11-21. Anyone else who runs this project makes that judgement for themselves.

Sources whose terms or `robots.txt` restrict automated **access** are unaffected and stay disabled.

## Summary

| Source | Mode | Access | Stored | Sent to model |
|---|---|---|---|---|
| arXiv `cs.CL` | Feed-summary | Explicit | Metadata and abstracts, indefinitely | Titles and abstracts |
| Google DeepMind blog | Full text | Explicit | Metadata; article text for 90 days | Article text |
| Google Research blog | Full text | Explicit | Metadata; article text for 90 days | Article text |
| Hugging Face blog | Full text | Interpretation | Metadata; article text for 90 days | Article text |
| Simon Willison (long-form entries) | Full text, from the feed | Interpretation | Metadata; article text for 90 days | Article text |
| Hacker News | Metadata-only | Interpretation | Item metadata, no usernames | Title, link and score |
| OpenAI News | Disabled | Uncertain | Nothing | Nothing |
| MLflow releases | Disabled | Uncertain | Nothing | Nothing |
| Anthropic SDK releases | Disabled | Uncertain | Nothing | Nothing |

"Metadata" means title, link, dates and identifiers. In metadata-only mode the summary or content a feed supplies is discarded when read, and no excerpt is used.

For a full-text source:

- An article page is fetched only from the source's own host, listed in `config/sources.yaml`. An item whose link points elsewhere stays metadata-only.
- The text is purged after 90 days. Its hash, the metadata and the short quotations used as evidence remain, so quote checks stay auditable.
- A briefing may quote at most 300 characters from one article.
- Article text never enters the repository, including test fixtures.

### What this means for M1

The model reads full articles from four sources and abstracts from arXiv, so assessments from those can cite verified quotations. A Hacker News item contributes its title, link and score; the page it links to is read only when that page belongs to a full-text source. A story known only from metadata is still capped at `watch` by the editorial policy.

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
- **Storage — by the owner's decision.** Neither blog states a content licence. The terms say "You may use Google's content as allowed by these terms" and grant no right to copy blog text. Article text is kept privately for 90 days under the decision of 2026-11-23.
- **Model submission — by the owner's decision.** Nothing in the terms addresses sending article text to a third-party model. Article text is submitted under the decision of 2026-11-23.
- **Body:** the article page, fetched only from `deepmind.google` or `research.google` respectively.
- **Retention:** metadata indefinitely; article text 90 days.
- **Attribution:** link to the original post. Do not alter Google branding or notices. Quotations of at most 300 characters.
- **Not read:** Google's service-specific terms and its generative AI prohibited-use policy.
- **Re-review trigger:** a change to either robots.txt.

### Hugging Face blog

- **Feed:** `https://huggingface.co/blog/feed.xml`
- **Pages read:** [terms of service](https://huggingface.co/terms-of-service) (effective 15 September 2022), [content policy](https://huggingface.co/content-policy) (effective 10 April 2025), [robots.txt](https://huggingface.co/robots.txt), the blog index.
- **Access — interpretation.** The terms have no clause on automated reading. robots.txt allows everything and the site publishes the feed. The content policy prohibits "excessive bulk activity".
- **Storage — by the owner's decision.** "You may not alter, reproduce, republish, license any of our proprietary materials, unless we expressly give you a written permission to do so." The blog mixes official and community posts; neither states a licence. Article text is kept privately for 90 days and never republished, under the decision of 2026-11-23. This is the record where the terms sit closest to the decision: a private working copy is a reproduction in the literal sense.
- **Model submission — by the owner's decision.** Not addressed by the terms. Article text is submitted under the decision of 2026-11-23.
- **Body:** the article page, fetched only from `huggingface.co`.
- **Retention:** metadata indefinitely; article text 90 days.
- **Attribution:** link to the original post. Quotations of at most 300 characters.
- **Not read:** individual post pages, which might carry their own licence.

### Simon Willison's Weblog

- **Feed:** `https://simonwillison.net/atom/entries/` (long-form entries only)
- **Pages read:** [about](https://simonwillison.net/about/), [robots.txt](https://simonwillison.net/robots.txt), the home page, and the header of two feeds.
- **Access — interpretation.** The about page offers Atom feeds for following the blog. robots.txt disallows only `/admin/` and `/search/`.
- **Storage — by the owner's decision.** No licence or terms are stated anywhere that was read; the footer is a bare copyright sign. Default copyright applies. The feed carries the full post, which is kept privately for 90 days under the decision of 2026-11-23.
- **Model submission — by the owner's decision.** Not addressed. Post text is submitted under the decision of 2026-11-23.
- **Body:** taken from the feed. No page is fetched.
- **Retention:** metadata indefinitely; post text 90 days.
- **Attribution:** link to the post and name the author. Quotations of at most 300 characters.
- **Simplest way to remove the remaining doubt:** ask the author. The author has not been asked.

### Hacker News

- **API:** `https://hacker-news.firebaseio.com/v0/`
- **Pages read:** [API README and licence](https://github.com/HackerNews/API), [Y Combinator terms](https://www.ycombinator.com/legal), [robots.txt](https://news.ycombinator.com/robots.txt), [FAQ](https://news.ycombinator.com/newsfaq.html)
- **Access — interpretation.** The README says "There is currently no rate limit" and states no terms for the data. The API is Y Combinator's own published route. Its host is not a Y Combinator subdomain.
- **Storage:** item id, title, link, score, comment count, time and type. Not the submitter's username, which is personal data the project has no use for, and not comment text.
- **Model submission — by the owner's decision.** Titles are written by users and often copy a third-party headline. The stored fields (title, link, score, comment count, time) may be sent to the model under the decision of 2026-11-23. Usernames and comment text are not stored, so they cannot be sent.
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
| 1 | May titles and links from metadata-only sources be sent to the model? | Settled on 2026-11-23: yes for Hacker News, the only enabled metadata-only source. |
| 2 | Full papers from arXiv | Not approved. Abstracts only. Full text would need PDF handling and a check of each paper's licence. |
| 3 | The Y Combinator terms clause on scraping | Unverified verbatim. Owner to read. |
| 4 | Permission from Simon Willison | Not requested. |
| 5 | OpenAI News | Disabled pending the owner's reading of the terms. |
| 6 | A GitHub API adapter | Not approved. Revisit in M5 on evidence of missed stories. |
| 7 | Pages not read (Google service-specific terms, OpenAI Service Terms, individual Hugging Face posts) | Listed in each record. |

## Re-review

Review a record again when the source changes its terms or robots.txt, when the mode is to be loosened, and otherwise at least once a year. Record the new date in `config/sources.yaml`.
