# ADR 014 — One further fix round for a small, valid finding

**Status:** Accepted (owner, 2026-11-27). The owner agreed the rule and asked for it to be implemented (issue #44); it takes effect when the owner merges the pull request that adds this record.
**Date:** 2026-11-27
**Amends:** [ADR-011](011-development-workflow-and-merge-authority.md), as amended by [ADR-013](013-agent-merge-of-eligible-changes.md). It changes one thing: what happens when a pull request has used its two fix rounds and review findings remain. Everything else in both records stands.

## Context

ADR-011 limits a pull request to two fix rounds. After that the round labels it `needs-human` and moves on. The limit exists so the agent does not loop on a pull request that is not converging, and does not argue with a reviewer indefinitely.

Twice in M1 (pull requests #31 and #43) the limit was reached with one review finding left that was valid, small to fix and outside every protected path. Each time the round stopped and the owner's answer was to make the fix. The stop cost a round trip and the `needs-human` label, which only the owner removes, so the owner also had to merge by hand.

The owner approved a detailed architecture in order to stay out of routine development. A decision with one sensible answer should not need the owner.

## Decision

### One further fix round

After two fix rounds, the agent may take **one further fix round** without asking, when every one of these holds:

1. Every remaining finding is tagged P1, P2 or P3.
2. The agent agrees that every remaining finding is valid. It disputes none.
3. The fix is small.
4. The fix touches no protected path, whether or not the pull request already touches one.
5. No required check is failing. The further round is for review findings, not for a pull request whose checks the earlier rounds left broken.

If any condition fails, the pull request is labelled `needs-human` as before.

### What does not change

- A P0 finding stops the round and is escalated. It is never fixed by the agent, in any round.
- A finding the agent disputes is answered with evidence and left open for the owner.
- After the further round there is no other. If findings remain or a check fails, the pull request is labelled `needs-human`.
- Updating a branch from `main` and resolving a conflict are still not fix rounds.
- The configuration may lower the two-round limit and may not raise it. If it is lowered, the further round is not offered.
- The merge conditions of ADR-013 are unchanged, except that condition 7's "within the two-fix-round limit" now reads "within the fix rounds this record allows". A pull request that is clean after the further round is merged by the round like any other.

### Who checks what

- **The scripts** check what can be read from the pull request: the two ordinary rounds are used and the further one is not; no P0; no disputed thread; no failing required check. `round_outcome.py status` then answers `fix-further`, and `record-fix-round --further` records the round once and refuses a second.
- **The agent** judges conditions 2, 3 and 4: that the findings are valid, the fix is small, and it stays outside the protected paths. "Small" has no line count. It means a contained correction to the code under review with its test, not a redesign. When in doubt, the agent stops.
- **The record** is a comment on the pull request saying the further round was taken under this ADR. The round's summary to the owner names every pull request that used it.

## Risk accepted

The agent decides for itself that a third round is warranted, using a judgement ("small", "valid") that no script checks. It could talk itself into a larger change. What bounds this: the round is one, not open-ended; the fix is reviewed by the review bot like any other commit, and nothing merges without a completed review of the final commit with every thread resolved; protected paths are excluded; and the comment on the pull request shows the owner each time it happened.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep the two-round limit | The owner is asked to confirm fixes that have one sensible answer, and then merges by hand |
| Raise the limit to three for every case | A third round would also be spent on failing checks and on pull requests that are not converging, which is what the limit is for |
| A line limit on the fix, checked by a script | Possible, and the owner may add one. A count is a poor measure of risk: three lines in the wrong place matter more than forty lines of test. The review of the final commit is the real check |
| Let the owner authorise each extra round in a comment | That is the present practice and the cost this record removes |

## Consequences

- Fewer pull requests stop at `needs-human` for a small fix. Those that do stop have a P0, a dispute, a failing check, a protected path, or have not converged in three rounds.
- A pull request can now be merged by the round after three fix rounds.
- `AGENTS.md`, `CLAUDE.md` and the `/round` skill state the rule. ADR-011's sentences on the two-round limit are read with this record.

## Acceptance checks

- With two rounds used, passing checks and unanswered findings, `status` answers `fix-further` and names the conditions the agent must judge.
- It answers `needs-human` instead when a required check is failing, a finding is disputed, the further round is already used, the count of rounds cannot be read, or the configured limit is below two.
- A P0 is escalated before any of this is considered.
- `record-fix-round` without `--further` still refuses a third round. With it, the round is recorded once, only straight after the second, and not over a dispute or a P0.

## Revisit when

A further round produces a change the owner would have refused; further rounds become common, which would mean issues are too large or reviews too late; or the owner wants a measurable limit on the size of the fix.
