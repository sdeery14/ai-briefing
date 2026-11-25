# ADR 011 — Development workflow and merge authority

**Status:** Accepted (owner, 2026-11-21)
**Date:** 2026-11-19 (new in RFC v0.3)

> **Amended on 2026-11-25 by [ADR-013](013-agent-merge-of-eligible-changes.md), at the owner's direction.**
> The owner authorised automatic merging without the separate GitHub identity and isolated environment that Phase B below requires. Read this record with these changes:
>
> - **Phase A's rule that the owner merges every pull request no longer applies.** The `/round` workflow merges a pull request itself when its required checks pass, the review of its head commit is complete, every finding is resolved, and it touches no owner-only path.
> - **Phase B's preconditions 1 to 4 and 6 are not required.** Precondition 5, the input allowlist, stays.
> - **The owner-only paths are listed in ADR-013.** They are a subset of the protected paths in this record. The other protected paths stay protected: a change to one is declared and reviewed with care, but the round may merge it.
> - Unchanged: the protected-path list, the input allowlist, P0 escalation, the two-fix-round limit, the review workflow, and the rule against pushing to `main`, force-pushing, bypassing protections or changing settings.
>
> The text below is kept as accepted on 2026-11-21, for the reasoning and for the risk it describes, which ADR-013 accepts.

## Context

ProjectBudget was built with Claude Code implementing milestone issues through a `/round` skill and Codex reviewing each pull request. The owner wants the same workflow here, with stronger enforcement.

Facts read from the ProjectBudget repository and its GitHub settings on 2026-11-19:

| Fact | Implication here |
|---|---|
| `/round` lives in `.claude/skills/round/SKILL.md` and uses `scripts/pr_wait.py` and `scripts/review_threads.py` | These can be copied; both repositories are Apache-2.0 and have the same owner |
| The skill's limits ("never arm auto-merge on a PR that changes …") are instructions in the skill text | The agent decides its own eligibility |
| Branch protection requires status checks on an up-to-date branch, resolved conversations and linear history | Good base to reproduce |
| Protection is not enforced for administrators; no review is required; there is no CODEOWNERS file | Nothing technical requires the owner's approval on any path |
| The skill runs with the session's `gh` credentials, which are the owner's | The agent acts with the owner's rights, including administrator bypass |
| The skill resolves Codex review threads itself after fixing them | "Conversations resolved" is not an independent control |
| The skill reads every issue's body and comments | In a public repository, text from any account can reach the agent |
| `pr_wait.py` reads required checks from the classic branch-protection API and waits for a state block from the Codex bot | Must be adapted if rulesets are used |

AI Briefing adds two risks ProjectBudget did not have: prompts, rubrics and evaluation assets whose quiet alteration would change the product's behaviour without failing a test, and a private benchmark answer key.

## Decision

### Phase A: human merge (from M0 until the owner enables Phase B)

1. `/round` is ported without a merge step. For each issue it implements, opens a pull request, waits for CI and the Codex review, fixes findings for at most two rounds, and labels the result `ready-for-owner` or `needs-human`.
2. The owner merges every pull request.
3. A repository ruleset on `main` requires a pull request, the required status checks on an up-to-date branch, resolved conversations and linear history, and blocks force pushes and deletion.
4. CODEOWNERS assigns the protected paths to the owner.
5. A CI job computes merge eligibility and reports it. In Phase A it is informational.

Residual risk, stated plainly: while the agent runs under the owner's credentials on the owner's machine, nothing technical prevents it from merging. Phase A relies on the skill having no merge step and on the skill itself being a protected path. Phase B removes that reliance.

### Phase B: automatic merge of eligible changes

Automatic merging is enabled only after all of the following exist and have been demonstrated with test pull requests:

1. **Agent identity.** The agent acts through a separate GitHub App or machine account with write access, no administrator role and no place on any bypass list.
2. **Environment.** Rounds run where the owner's GitHub credentials are not available to the agent.
3. **Code-owner review.** The ruleset requires code-owner approval for protected paths. Only the owner can bypass.
4. **Eligibility check.** A required status check, computed by CI from the list of changed files, passes only when no protected path is touched and no golden or recorded output changed. The workflow that computes it reads the file list through the API, runs no code from the pull request, and is itself on a protected path.
5. **Input allowlist.** The skill acts only on issues and comments authored by the owner or the review bot.
6. **Demonstration.** A test pull request from the agent identity touching a protected path cannot be merged by that identity. One touching only unprotected paths merges once checks pass.

The owner enables Phase B by a reviewed change to the skill's configuration.

### Protected paths

Changes to these always need the owner's approval, in both phases:

| Category | Paths |
|---|---|
| Decisions | `docs/rfc/**`, `docs/adr/**` |
| Evaluation | `src/ai_briefing/evaluation/**`, `evals/**`, golden files and recorded responses under `tests/` |
| Prompts and editorial policy | `src/ai_briefing/prompts/**`, `src/ai_briefing/editorial/policy/**` |
| Models, budget, sources | `config/**` |
| Contracts and migrations | `schemas/**`, `migrations/**` |
| Workflows | `.github/**` |
| Dependencies | `pyproject.toml`, `uv.lock` |
| Deployment | `deploy/**`, container and Compose files |
| Agent workflow | `.claude/**`, `scripts/**`, `AGENTS.md`, `CLAUDE.md`, `CODEOWNERS` |

Eligible for automatic merge in Phase B: domain logic with tests, source adapters behind an existing protocol with recorded fixtures, renderers, how-to documentation, and refactors that leave replay output unchanged.

Most quality-relevant work (prompts, rubrics, policy) is therefore human-reviewed by design. Autonomous rounds are for plumbing.

### Hard limits on the agent, in both phases

Never push to `main`, force-push, tag, release, publish or deploy. Never change repository settings, rulesets or secrets. Never touch the Pi or the Home System repository. Never dispute a review finding past two fix rounds; label and move on.

### Review

1. Codex reviews every pull request, guided by a review section in `AGENTS.md` written for this project. Beyond code quality it flags: label-like fields in public data, loosened assertions, changed expected outputs, prompt or policy changes outside a labelled pull request, third-party text in fixtures, and anything that lets model output reach a network call.
2. A thread the agent disputes stays open for the owner.

### CI and secrets

1. Tier 0 (ADR-007) runs on every pull request with no secrets and no network.
2. Model API keys exist only in a protected environment used by the owner-started Tier 1 workflow. That workflow never runs for forks.
3. No workflow triggered by `pull_request_target` checks out or executes pull-request code.

### The private answer key

It is not stored on any machine or account where Claude Code or Codex runs, and never appears in the repository, issues, pull requests, CI, logs or MLflow. Any use is by the owner alone, and the results are not given to agents.

### Porting

Copy the skill and both scripts into this repository; nothing references ProjectBudget at run time. Move project-specific values (milestone names, check names, reviewer login, protected globs, allowlist) into one configuration file. Remove ProjectBudget-specific steps (changelog handling, browser checks). Adapt `pr_wait.py` to read required checks from the ruleset.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Reuse `/round` unchanged with automatic merge | Limits are instructions; the agent holds the owner's rights |
| Human merge permanently | Safe but gives up most of the workflow's value for low-risk changes |
| Automatic merge now, protections later | The protections are what make it safe |
| Rely on the agent's own judgement of which paths are sensitive | The party being constrained should not compute the constraint |

## Consequences

Development is slower in Phase A. Setting up the agent identity and an isolated environment is real work and is deferred until the owner wants Phase B. The owner reviews every prompt, policy, evaluation and dependency change indefinitely.

## Acceptance checks

- In Phase A, the skill contains no merge command, and a pull request cannot merge with a failing required check.
- The eligibility job reports "not eligible" for a pull request touching each protected category.
- A pull request that changes only a golden file is reported "not eligible".
- An issue opened by a non-allowlisted account is skipped by the skill.
- Before Phase B: the two demonstration pull requests behave as described in point 6.

## Revisit when

A second maintainer joins, external contributions begin, or the review bot's behaviour changes.
