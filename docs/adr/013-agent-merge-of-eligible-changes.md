# ADR 013 — The development round merges eligible changes

**Status:** Accepted (owner, 2026-11-25). The owner authorised this change explicitly and asked for it to be implemented; it takes effect when the owner merges the pull request that adds this record.
**Date:** 2026-11-25
**Amends:** [ADR-011](011-development-workflow-and-merge-authority.md). It replaces Phase A's rule that the owner merges every pull request, and removes Phase B's preconditions of a separate agent identity and an isolated environment. Everything else in ADR-011 stands: the protected paths, the input allowlist, P0 escalation, the two-fix-round limit, the review workflow.

## Context

ADR-011 Phase A has the owner merge every pull request. Phase B allows automatic merging only after a separate GitHub identity for the agent, an environment without the owner's credentials, and required code-owner review all exist.

In the first days of M1 the owner was asked to merge each pull request by hand, including a three-line quoting fix. The owner approved a detailed architecture first in order to stay out of routine development until there is a working version to test, apart from steps only the owner can do. The owner considered the separate identity and declined it as too much machinery for a personal project.

The owner's ProjectBudget repository already runs a `/round` skill that merges automatically. The owner asked for the same behaviour here, reusing that approach and keeping the implementation as simple as possible.

This is a deliberate trade of a safeguard for speed, taken by the owner with the risk stated below.

## Decision

### The round merges a pull request when every one of these holds

1. All required checks have passed on the head commit.
2. The review bot, verified as the configured reviewer, has completed a review of that same head commit.
3. Every review thread is resolved. A thread the agent disputes is left open, so it blocks the merge.
4. The pull request does not carry the `needs-human` label. A P0 finding, a disputed finding, a timeout or a spent fix budget puts that label on, and only the owner takes it off.
5. No changed file is on an owner-only path (below), and the list of changed files is known to be complete.
6. GitHub reports the pull request's merge state as clean: no conflict, branch up to date, nothing blocked by the ruleset.
7. It was worked from an issue the owner authorised, within the two-fix-round limit.

If any condition fails, or anything about the pull request cannot be read, it is not merged. It is left for the owner with the reason stated.

### How a merge is made

- The round runs `gh pr merge <pr> --auto --squash --delete-branch`, as the ProjectBudget round does, with one addition: `--match-head-commit <sha>` names the commit that was checked and reviewed, so GitHub refuses the merge if the branch has moved.
- It runs that command only through `scripts/round_outcome.py merge <pr>`, which first reads the pull request afresh and refuses unless every condition above holds at that moment.
- It runs the command only on a pull request GitHub already reports as clean, so the merge happens at once. The round then waits until GitHub reports the pull request merged before starting any issue that depends on it.
- If the merge does not complete within the wait, the round switches auto-merge off again for that pull request and reports it. Nothing is left armed to merge later under conditions nobody checked. This is stricter than ProjectBudget, which leaves a pull request armed.
- A P0 finding discovered by that last check stops the whole round, exactly as at any other point.

### A branch behind `main`

The ruleset requires a branch to be up to date. When a pull request is eligible in every other respect but behind `main`, the round merges `main` into the branch (never a force push), pushes, asks for a fresh review, and waits for the checks and the review of the new commit. Only then is it merged. This does not count as a fix round.

ProjectBudget updates an armed pull request and lets it merge when its checks pass, without a review of the new commit. This project does not arm first, because condition 2 requires a review of the exact commit that is merged.

### Owner-only paths

A pull request that touches any of these is never merged by the round. It is left for the owner, labelled `ready-for-owner`, with the paths named.

| Category | Paths | Origin |
|---|---|---|
| Decisions | `docs/adr/**`, `docs/rfc/**` | ProjectBudget's exception for decision records, extended to the RFC |
| Workflows | `.github/**` | ProjectBudget's exception for workflows |
| Migrations | `migrations/**` | ProjectBudget's exception |
| Dependencies | `pyproject.toml` | ProjectBudget's exception for dependency changes. Any change to the file counts, since the round decides from file names |
| Evaluation | `src/ai_briefing/evaluation/**`, `evals/**` | This project: the owner's evaluation decisions |
| Models, budget, sources | `config/**` | This project: source approvals, model choice and spend |
| Deployment | `deploy/**`, container and Compose files | This project: deployment is the owner's to authorise |
| Agent workflow | `.claude/**`, `scripts/**`, `AGENTS.md`, `CLAUDE.md`, `CODEOWNERS` | This project: the agent must not be able to loosen its own controls, including this rule |

The first four are ProjectBudget's exceptions, as the owner asked. ProjectBudget's fifth, released sections of `CHANGELOG.md`, has no counterpart: this project has no changelog. The last four were not in ProjectBudget's list. They are kept because they are the decisions the owner reserved when handing over routine development (source approvals, evaluation, deployment) and the controls themselves. They are rarely touched by M1 issues. The owner can remove any of them by editing the list in `scripts/merge_eligibility.py`.

The remaining ADR-011 protected paths (`uv.lock`, `schemas/**`, prompts, editorial policy, golden files and recorded responses) stay protected: a change is declared in the pull request and reviewed with care. The round may merge it.

### What stays with the owner

Merging any owner-only change; accepting ADRs; approving sources and changes to their modes; model and budget configuration; credentials and paid API calls unless an issue says otherwise; repository settings; releases and deployment; and every pull request labelled `needs-human`.

The round never pushes to `main`, never force-pushes, never bypasses a protection and never changes a GitHub setting.

## Risk accepted

The agent acts with the owner's GitHub rights. Nothing technical stops it from merging by another route; ADR-011 said so and required a separate identity before any automatic merge. That protection is not in place. What remains:

- The ruleset on `main` has no bypass and applies to the owner's account too: a pull request with a failing required check or an unresolved review thread cannot be merged by anyone.
- The review bot is independent of the agent. The agent's scripts refuse to resolve a P0 thread, a thread the owner opened, or one whose comments could not all be read.
- The scripts can run one merge command only, a squash of a named commit, and only after re-checking every condition.
- Development runs offline against synthetic fixtures, so little untrusted content reaches the agent while it works.
- Nothing is deployed from this repository, and a squash merge can be reverted.

The main cost: prompts, editorial policy, schemas and lock-file changes can now merge without the owner reading them. The owner will judge prompts and policy by the briefings they produce and by the 14-day comparison, not by reading each change.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep ADR-011 Phase A | The owner merges every routine change, which is the involvement the owner set out to avoid |
| ADR-011 Phase B in full (separate identity, isolated environment, required code-owner review) | The strongest option. Declined by the owner as too complicated for a personal project; it remains the right step if the project gains users or contributors |
| Arm auto-merge early and let GitHub merge when checks pass, as ProjectBudget does | GitHub checks the required checks and the threads, not that the review covers the final commit. A branch updated after review could merge unreviewed |
| Let the agent merge everything that passes | The agent could then change its own rules, the checks, source approvals and spend |
| ProjectBudget's four exceptions and nothing more | Would let the round merge changes to source approvals, the budget and its own merge rule. The owner can still choose this by shortening the list |

## Consequences

- M1 can proceed through its issues without the owner, stopping at owner-only changes and at `needs-human`.
- **Several M1 issues will still wait for the owner**, because they add a dependency (`pyproject.toml`) or a migration: 1.2, 1.3, 1.4 and 1.5 at least. That follows from carrying over ProjectBudget's exceptions. If it proves too much, the owner can drop `pyproject.toml` from the list.
- A defect in a prompt or policy can reach `main` unread. It is caught, if at all, by the review bot, the tests and the owner's use of the product.
- `.github/CODEOWNERS` now lists the owner-only paths. It still enforces nothing unless the owner turns on code-owner review.
- ADR-011's validation that depends on the owner being the only merger no longer applies; its Phase B demonstration is replaced by the tests named below.

## Acceptance checks

- The merge command refuses, and sends nothing, for a pull request that touches an owner-only path; carries `needs-human`; has a failing or pending required check; lacks a completed review of its head commit by the configured reviewer; has an unresolved thread; is behind, conflicting, blocked, draft or closed; or whose files, labels, threads or state could not be read.
- A P0 found by the merge command's own check stops the round.
- The merge command returns only when GitHub reports the pull request merged, and switches auto-merge off if it does not.
- A pull request that is eligible but behind `main` is updated and re-reviewed, not merged.
- With `merge_authority` set to `owner-only`, no outcome permits a merge.
- The only merge the scripts can run is `gh pr merge --auto --squash --delete-branch` with the expected head commit named. Any variation is refused.
- A test pins the owner-only paths, so removing one fails until the owner changes this decision.

## Revisit when

The project gains users or outside contributors; anything is deployed from this repository; a merged change is found that the owner would have refused; the review bot stops reviewing or becomes unreliable; too many pull requests wait on the dependency or migration exception; or the owner sets up a separate agent identity, at which point ADR-011 Phase B's stronger controls should replace this record.
