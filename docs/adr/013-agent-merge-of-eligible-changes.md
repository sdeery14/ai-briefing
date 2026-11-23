# ADR 013 — The development agent merges eligible changes

**Status:** Accepted by the owner by merging the pull request that adds this record (2026-11-23). The owner decided the rule on 2026-11-23; this record does not exist on `main` unless the owner merged it.
**Date:** 2026-11-23
**Amends:** [ADR-011](011-development-workflow-and-merge-authority.md). It replaces Phase A's rule that the owner merges every pull request, and the preconditions of Phase B. Everything else in ADR-011 stands: the protected paths, the input allowlist, the fix-round limit, the review workflow.

## Context

ADR-011 Phase A has the owner merge every pull request. Phase B allows automatic merging only after a separate GitHub identity for the agent, an environment without the owner's credentials, and required code-owner review all exist.

In the first days of M1 the owner was asked to merge each pull request by hand, including a three-line quoting fix. The owner's intent in approving a detailed architecture first was to stay out of routine development until there is a working version to test, apart from steps only the owner can do. The owner considered setting up the separate identity and declined it as too much machinery for a personal project at this stage.

This is a deliberate trade of a safeguard for speed, taken by the owner with the risk stated below.

## Decision

### The round may merge a pull request when every one of these holds

1. All required checks have passed on the head commit.
2. The review bot has completed a review of that same head commit.
3. Every review thread is resolved. A thread the agent disputes is left open, so it blocks the merge.
4. The pull request does not carry the `needs-human` label. A P0 finding, a disputed finding, a timeout or a spent fix budget puts that label on, and only the owner takes it off.
5. No changed file is on an owner-only path (below), and the list of changed files is known to be complete.
6. GitHub reports the pull request's merge state as clean: no conflict, branch up to date, nothing blocked by the ruleset.
7. It was worked from an issue the owner authorised, within the two-fix-round limit.

If any condition fails, or cannot be read, the pull request is left for the owner with the reason stated.

### Owner-only paths

A pull request that touches any of these is merged by the owner and by nobody else.

| Category | Paths | Why |
|---|---|---|
| Decisions | `docs/rfc/**`, `docs/adr/**` | The owner's architectural decisions |
| Evaluation | `src/ai_briefing/evaluation/**`, `evals/**` | The owner's evaluation decisions |
| Models, budget, sources | `config/**` | Source approvals, model choice and spend |
| Workflows | `.github/**` | CI, the checks themselves |
| Deployment | `deploy/**`, container and Compose files | Deployment is the owner's to authorise |
| Agent workflow | `.claude/**`, `scripts/**`, `AGENTS.md`, `CLAUDE.md`, `CODEOWNERS` | The agent must not be able to loosen its own controls, including this rule |

The other ADR-011 protected paths (dependencies, `schemas/**`, `migrations/**`, prompts, editorial policy, golden files and recorded responses) stay protected: a change is declared in the pull request and reviewed with care. They no longer require the owner to merge.

### How a merge is made

- Only through `scripts/round_outcome.py merge <pr>`. It reads the pull request afresh, refuses unless every condition holds at that moment, and squash-merges the exact commit that was checked and reviewed. If the branch has moved, GitHub refuses the merge.
- Never by `gh pr merge`, the web interface, a direct API call, or auto-merge. Auto-merge stays off in the repository.
- The scripts that decide and perform the merge are on an owner-only path. So is the configuration value that switches agent merging on (`merge_authority` in the round configuration); setting it back to `owner-only` restores ADR-011 Phase A.

### What stays with the owner

Merging any owner-only change; accepting ADRs; approving sources and changes to their modes; model and budget configuration; credentials and paid API calls unless an issue says otherwise; repository settings; releases and deployment; and every pull request labelled `needs-human`.

## Risk accepted

The agent acts with the owner's GitHub rights. Nothing technical stops it from merging by another route; ADR-011 said so and required a separate identity before any automatic merge. That protection is not in place. What remains:

- The ruleset on `main` has no bypass and applies to the owner's account too: a pull request with a failing required check or an unresolved review thread cannot be merged by anyone.
- The review bot is independent of the agent. The agent's scripts refuse to resolve a P0 thread, a thread the owner opened, or one whose comments could not all be read.
- The merge command re-checks every condition and can send one merge document only: a squash of a named commit.
- Development runs offline against synthetic fixtures, so little untrusted content reaches the agent while it works.
- Nothing is deployed from this repository, and a squash merge can be reverted.

The main cost: prompts, editorial policy, dependencies and migrations can now merge without the owner reading them. The owner will judge prompts and policy by the briefings they produce and by the 14-day comparison, not by reading each change.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep ADR-011 Phase A | The owner merges every routine change, which is the involvement the owner set out to avoid |
| ADR-011 Phase B in full (separate identity, isolated environment, required code-owner review) | The strongest option. Declined by the owner for now as too complicated for a personal project; it remains the right step if the project gains users or contributors |
| GitHub auto-merge | Arms a merge that happens later, when the conditions may no longer be what was checked; the explicit command merges one known commit |
| Let the agent merge everything that passes | The agent could then change its own rules, the checks, source approvals and spend |
| Owner-only for all ADR-011 protected paths | Nearly every M1 issue adds a dependency, a schema, a migration or a prompt, so little would merge without the owner |

## Consequences

- M1 can proceed through its issues without the owner, stopping at owner-only changes and at `needs-human`.
- A defect in a prompt or policy can reach `main` unread. It is caught, if at all, by the review bot, the tests and the owner's use of the product.
- `.github/CODEOWNERS` now lists the owner-only paths. It still enforces nothing unless the owner turns on code-owner review.
- The validation in ADR-011 that depends on the owner being the only merger no longer applies; its Phase B demonstration is replaced by the tests named below.

## Acceptance checks

- The merge command refuses, and sends nothing, for a pull request that touches an owner-only path; carries `needs-human`; has a failing or pending required check; lacks a completed review of its head commit; has an unresolved thread; is behind, conflicting, blocked, draft or closed; or whose files, labels, threads or state could not be read.
- With `merge_authority` set to `owner-only`, no outcome permits a merge.
- The only merge document the scripts can send is a squash that names the expected head commit, and it is sent from one place.
- A test pins which protected paths are owner-only, so moving one out fails until the owner changes this decision.

## Revisit when

The project gains users or outside contributors; anything is deployed from this repository; a merged change is found that the owner would have refused; the review bot stops reviewing or becomes unreliable; or the owner sets up a separate agent identity, at which point ADR-011 Phase B's stronger controls should replace this record.
