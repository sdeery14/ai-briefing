# AI Briefing — decisions that need the owner

**Status:** review input. Only items that cannot be settled from the documents or by a sensible default are listed. Each has my recommendation first. Finding numbers (F-nn) refer to [`architecture-review-v0.2.md`](architecture-review-v0.2.md).

Everything else in the review is a recommendation I would simply apply when revising the RFC and ADRs, unless you object.

| # | Decision | Recommendation | Needed before |
|---|---|---|---|
| D1 | Is the curriculum in V1? | Defer it | RFC revision |
| D2 | What role does the seed benchmark play, and how much labelling time will you commit? | Smoke test only; 15–20 minutes a week of prospective labelling | RFC revision |
| D3 | What source content is stored, for how long, and what may enter the public repository? | Metadata always; bodies for evidence only, time-limited; nothing third-party in the repository | M1 |
| D4 | Project licence | Apache-2.0 | First code commit |
| D5 | How do you give feedback on a briefing? | Email links to an HA webhook that writes event files | M2 design |
| D6 | Where does the full report live? | Inline in the email for V1 | M2 design |
| D7 | Host facts and storage for `homenvr` | SSD required; off-device backup | ADR-008 acceptance |
| D8 | Agent identity and merge authority | Separate bot identity with enforced protections | First `/round` |
| D9 | Model provider and monthly cost cap | One provider, two model tiers, a hard cap you choose | M1 |
| D10 | Community source for V1 | Hacker News only | M1 |

---

## D1. Is the curriculum in V1?

**Recommendation: defer.** Ship the intelligence briefing first and keep an optional `lesson` field in the contract.

| Option | Consequence |
|---|---|
| Defer (recommended) | V1 is roughly half the size. The 70/30 thesis is unproven for longer. The curriculum is designed later with a working feedback path and real usage behind it. |
| Minimal track in V1: about twenty hand-written lessons delivered in order | Tests whether you want a daily lesson at all. Costs authoring time now and still lacks any way to record more than delivery until D5 is built. |
| Full curriculum as proposed | Two products built at once. Requires answering RFC §12 item 7 (who writes and checks lesson content) immediately. Highest risk of an unread section. |

This is yours to decide because it is a statement about what the product is, not a technical tradeoff. (F-12)

## D2. Role of the seed benchmark and your labelling commitment

**Recommendation:** treat all 40 cards as a calibration aid and smoke test. Keep the 28 private ones private because it costs nothing, but use them at most once per milestone and build no tooling around them. Make prospective labelling the primary measure.

The real decision is your time. The prospective approach needs about 15 to 20 minutes a week: marking a sample of the week's assessed stories, noting what you saw elsewhere that the system missed, and a monthly look back at items it called major.

| Option | Consequence |
|---|---|
| Prospective labelling with a weekly commitment (recommended) | Trustworthy numbers accumulate slowly; a usable baseline after four to six weeks of operation. Until then, gates are deterministic only. |
| Adjudicate and expand the seed benchmark instead | Front-loaded effort and an early number, but the number is still subject to model hindsight and small-sample noise. I would not gate on it. |
| No regular labelling | Evaluation reduces to deterministic checks plus your impression of the email. Workable for a personal tool, but autonomous changes to prompts should then stay fully manual. |

(F-02)

## D3. Content storage, retention and what enters the public repository

**Recommendation:**

- Store feed-supplied metadata and summaries indefinitely.
- Fetch body text only for documents that pass screening. Keep it locally and privately. Purge it after a fixed period (I suggest 90 days) unless the document is cited as evidence, in which case keep the quoted spans and a content hash.
- Commit no third-party text to the repository. Public benchmark cases and fixtures are either your own writing or synthetic.
- Record each source's terms and rate limits next to its catalogue entry.

| Option | Consequence |
|---|---|
| Recommended posture | Replay with new prompts works for 90 days on full inputs and indefinitely on evidence. Storage stays small. Lowest exposure. |
| Metadata and summaries only, never fetch bodies | Simplest and safest. Assessments rest on summaries, so evidence quality drops and quote verification is weaker. |
| Keep everything indefinitely | Best for replay and backtesting. Largest storage, and the weakest position if any source's terms prohibit retention. |

I am not offering legal advice. This is a risk posture only you can set, and it changes the schema. (F-08)

## D4. Project licence

**Recommendation: Apache-2.0**, for its explicit patent grant and because it is compatible with the dependencies this project is likely to use.

| Option | Consequence |
|---|---|
| Apache-2.0 (recommended) | Permissive, patent grant, slightly more boilerplate. |
| MIT | Shortest and most familiar; no patent language. |
| AGPL-3.0 | Anyone offering it as a hosted service must publish changes. Discourages some contributors and reuse. |

The RFC already warns against inheriting ProjectBudget's licence by default. If `/round` helper scripts are copied from that project, confirm their licence permits it.

## D5. Feedback channel

**Recommendation:** links in the morning email call a Home Assistant webhook. HA writes one small JSON event file per click into a drop directory. AI Briefing ingests those files on its next run. This mirrors the export and keeps both systems out of each other's stores.

| Option | Consequence |
|---|---|
| HA webhook to drop directory (recommended) | One-tap feedback from the email. Requires a small change in the Home System repository and a decision on how the webhook is reached from your phone (local network only, or through whatever remote access HA already has). |
| CLI only | No cross-repository work. In practice feedback will be sparse, which undermines D2 and the curriculum. |
| Small authenticated web page served by AI Briefing | Richer input, including labelling. Adds a long-running service and an exposed port, both of which V1 excludes. |

(F-07)

## D6. Where the full report lives

**Recommendation:** put the full briefing inline in the email for V1 and drop the "link to the fuller report".

| Option | Consequence |
|---|---|
| Inline in the email (recommended) | Nothing to host. The email is longer. |
| Short section plus a link to a file served by Home Assistant | Keeps the email short. Files under HA's `www` folder are served without authentication, so this needs care. |
| Short section only; full report readable on the Pi | Simplest. The evidence trail, which is the product's main point, is not visible where you read. |

## D7. Host facts for `homenvr`

I need facts only you have, and one choice.

Facts to record:

1. How Home Assistant is installed (Home Assistant OS, Supervised, or Container on a general Linux host).
2. Whether the operating system is 64-bit.
3. Storage medium and free space; whether an SSD is attached.
4. Typical free memory and CPU load with current services.
5. The MLflow server version.

Choice: **where backups go.** Recommendation: a nightly SQLite snapshot copied to a different device (a NAS, another machine, or a cloud bucket), not to the Pi's own disk or its MinIO.

| Outcome | Consequence |
|---|---|
| General Linux host, 64-bit, SSD | The proposed container and systemd design stands. |
| Home Assistant OS | Host timers and arbitrary containers are not readily available. The design changes to an add-on or to running AI Briefing on another machine. |
| SD card only | I would not run a WAL-mode database there alongside the existing services. Add an SSD first. |

(F-13)

## D8. Agent identity and merge authority

**Recommendation:** the agent works through a separate bot account or GitHub App without admin rights. Protected paths require your review through CODEOWNERS and branch protection with administrator bypass disabled. A CI check, not the agent, decides whether a pull request is eligible for auto-merge.

| Option | Consequence |
|---|---|
| Separate identity with enforced protections (recommended) | "Requires owner approval" is real. One-time setup of an account or app and its token. |
| Agent uses your credentials, guarded by instructions in the skill | No setup. You cannot approve your own pull requests, so review rules either block everything or are bypassed, and nothing technical stops a merge to a protected path. |
| No auto-merge; you merge everything | Safest and slowest. Reasonable for M1 while the new protections are proven. |

Also yours to confirm: that the private answer key will be moved off any machine and account where Claude Code or Codex runs. (F-11)

## D9. Model provider and monthly cost cap

**Recommendation:** one provider, a small model for screening and a stronger model for assessment and writing, with a hard monthly cap enforced before each call. Choose the cap after the M0 spike measures real volume.

| Option | Consequence |
|---|---|
| One provider, two tiers, hard cap (recommended) | Predictable spend. When the cap is hit, the briefing degrades instead of overspending. |
| One strong model for everything | Simpler and higher quality on screening, at several times the cost on the highest-volume step. |
| Multiple providers from the start | Resilience to an outage, at the cost of maintaining two sets of prompts and structured-output behaviour. |

I have not quoted prices because they change and the volume is unmeasured. The number is yours.  (F-06)

## D10. Community source for V1

**Recommendation: Hacker News only**, through its public API, with search discovery deferred.

| Option | Consequence |
|---|---|
| Hacker News (recommended) | Public read-only API, no credentials, good coverage of engineering and tooling. Weaker on research chatter. |
| Reddit | Broader ML community coverage. Requires each installer's own credentials, and current terms restrict commercial use. Confirm the primary terms before choosing; my check relied on secondary sources. |
| None in V1 | Simplest. Discovery relies entirely on curated feeds, and popularity as a discovery signal is unavailable. |

---

## Status of the RFC's own open list (§12)

| RFC item | Disposition |
|---|---|
| 1. Licence and package name | D4. Package name is not blocking. |
| 2. Source catalogue and search provider | D10 for the community source; search provider deferred. The exact feed list can be drafted in M0 for your edit. |
| 3. HA integration format | Recommend the file handoff as proposed. No decision needed unless you disagree. |
| 4. Operational limits and Pi resources | D7. |
| 5. Benchmark adjudication | Replaced by D2. |
| 6. Retention policy and tracing overhead | D3; tracing overhead is covered by an M0 spike. |
| 7. Curriculum authoring | Deferred with D1. |
