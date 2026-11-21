"""Decide what a round does next with a pull request, and count its fix rounds.

Used by the ``/round`` skill (``.claude/skills/round/SKILL.md``).

    uv run python scripts/round_outcome.py status 64
    uv run python scripts/round_outcome.py record-fix-round 64

``status`` reads the pull request once and prints one JSON object. Its ``action`` is one of:

- ``escalate``  A P0 finding from the reviewer or an allowed author, or the review threads
  could not be read so one cannot be ruled out. Stop the whole round and tell the owner.
  Do not fix anything first. This is checked before everything else: no other problem with
  the pull request can hide it.
- ``wait``      Checks or the review are still running.
- ``fix``       A required check failed or a finding is unanswered, and a fix round is left.
- ``resolve-conflicts``  The branch conflicts with the default branch.
- ``label``     Finished. ``outcome`` is ``ready-for-owner`` or ``needs-human``.
- ``none``      The pull request is closed.

Whenever ``stop_round`` is true the round ends, whatever the action says.

There is no action that merges. ``ready-for-owner`` means the owner can review and merge;
it is a label, not a permission. The result always carries ``"automatic_merge": false``.

``record-fix-round`` posts a marker comment on the pull request and refuses when the limit
is reached. Fix rounds are counted from those comments, so the count survives a restarted
session and does not depend on the agent's memory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

import merge_eligibility
import pr_wait
import review_threads
from round_lib import (
    COMMENT_MUTATION,
    PR_QUERY,
    Config,
    Gh,
    GhError,
    graphql,
    is_allowed_author,
    load_config,
    login_of,
    rest_pages,
    run_gh,
    with_retries,
)

MARKER = re.compile(r"<!-- round-fix-round:(\d+) -->")


class LimitReached(GhError):  # noqa: N818 - reads as a statement of fact
    """The pull request has already used every fix round it is allowed."""


class EscalationRequired(GhError):  # noqa: N818 - reads as a statement of fact
    """A P0 finding is open. Nothing is fixed until the owner has been told."""


READ_ERRORS = (GhError, KeyError, TypeError, ValueError)


def fix_rounds_used(comments: list[dict[str, Any]], config: Config) -> int:
    """How many fix rounds have been recorded, counting only allowed authors' markers."""
    rounds = {
        int(match.group(1))
        for comment in comments
        if is_allowed_author(login_of(comment.get("user")), config)
        for match in MARKER.finditer(str(comment.get("body") or ""))
    }
    return len(rounds)


def decide(
    snap: dict[str, Any],
    threads: list[dict[str, Any]],
    *,
    fix_rounds: int,
    max_fix_rounds: int,
    labels: tuple[str, str],
    protected: list[dict[str, str]] | None = None,
    threads_readable: bool = True,
) -> dict[str, Any]:
    """The next step for a pull request. Pure: no network, no side effects.

    A P0 from a trusted author is decided first, before the pull request's state, its
    checks, the review state or the fix-round budget are even looked at.
    """
    ready_label, needs_human_label = labels
    result: dict[str, Any] = {
        "pr": snap.get("pr"),
        "head": snap.get("head"),
        "action": "label",
        "outcome": None,
        "stop_round": False,
        "reasons": [],
        "notes": [],
        "fix_rounds_used": fix_rounds,
        "fix_rounds_allowed": max_fix_rounds,
        "automatic_merge": False,
        "merge": "owner-only",
    }

    def needs_human(reason: str, *, stop: bool = False, action: str = "label") -> dict[str, Any]:
        result.update(action=action, outcome=needs_human_label, stop_round=stop)
        result["reasons"].append(reason)
        return result

    critical = review_threads.critical_findings(threads)
    critical += [str(u) for u in snap.get("p0_findings") or [] if str(u) not in critical]
    if critical:
        return needs_human(
            "P0 finding: stop and escalate to the owner; do not attempt a fix "
            f"({', '.join(critical)})",
            stop=True,
            action="escalate",
        )
    unread = review_threads.incomplete_threads(threads)
    unread += [str(u) for u in snap.get("review_incomplete") or [] if str(u) not in unread]
    if unread:
        return needs_human(
            "not every comment on the unresolved review threads could be read, so a critical "
            "finding cannot be ruled out: stop the round and tell the owner "
            f"({', '.join(unread)})",
            stop=True,
            action="escalate",
        )
    if not threads_readable or snap.get("p0_unknown"):
        return needs_human(
            "the review threads could not be read, so a critical finding cannot be ruled out: "
            "stop the round and tell the owner",
            stop=True,
            action="escalate",
        )

    if snap.get("error") or snap.get("problems"):
        detail = snap.get("error") or "; ".join(snap.get("problems") or [])
        return needs_human(f"the pull request's state could not be trusted: {detail}")
    if snap.get("state") != "OPEN":
        result.update(action="none")
        result["notes"].append("merged by the owner" if snap.get("merged") else "closed")
        return result

    # Only the configured reviewer and allowed authors can direct the round. A thread from
    # anyone else is left alone and reported; it cannot send the agent off to "fix" things.
    outsiders = [t for t in threads if not (t.get("from_reviewer") or t.get("from_allowed_author"))]
    threads = [t for t in threads if t.get("from_reviewer") or t.get("from_allowed_author")]
    if outsiders:
        result["notes"].append(
            f"{len(outsiders)} unresolved thread(s) from other authors were not acted on; "
            "they still block merging until the owner deals with them"
        )

    if protected:
        categories = sorted({m["category"] for m in protected})
        result["notes"].append(
            "touches protected paths ("
            + ", ".join(categories)
            + "): needs the owner's close review"
        )
    if snap.get("protection") == "BEHIND":
        result["notes"].append("branch is behind the default branch; update before merging")

    codex = snap.get("codex")
    if pr_wait.reviewer_error(codex):
        message = codex.get("message") if codex else None
        return needs_human(f"the reviewer reported a problem: {message}")

    unanswered = [t for t in threads if not t.get("answered")]
    disputed = [t for t in threads if t.get("answered")]
    ci = snap.get("ci")
    failing = sorted(n for n, s in (snap.get("required_checks") or {}).items() if s == "fail")

    if ci == "fail" or unanswered:
        why = []
        if failing:
            why.append(f"required checks failed: {', '.join(failing)}")
        if unanswered:
            why.append(f"{len(unanswered)} review finding(s) have no response")
        if fix_rounds >= max_fix_rounds:
            return needs_human(
                f"fix-round limit of {max_fix_rounds} reached with work remaining: "
                + "; ".join(why)
            )
        result.update(action="fix")
        result["reasons"] = why
        return result

    if snap.get("conflicts") == "conflicting":
        result.update(action="resolve-conflicts")
        result["reasons"].append("the branch conflicts with the default branch")
        return result

    reviewed = (
        codex is not None and codex.get("for_head") is True and codex.get("status") == "completed"
    )
    if ci != "pass" or not reviewed:
        if snap.get("timeout"):
            waiting = []
            if ci != "pass":
                waiting.append(f"required checks are {ci}")
            if codex is None:
                waiting.append("the reviewer never responded")
            elif not reviewed:
                waiting.append("the review is not for the current head commit")
            return needs_human("timed out: " + "; ".join(waiting))
        result.update(action="wait")
        if ci != "pass":
            result["reasons"].append(f"required checks are {ci}")
        if not reviewed:
            stale = codex is not None and codex.get("stale")
            result["reasons"].append(
                "the review is for an earlier commit" if stale else "no completed review yet"
            )
        return result

    if disputed:
        return needs_human(
            f"{len(disputed)} review thread(s) were answered and left open for the owner to decide"
        )

    result.update(outcome=ready_label)
    result["reasons"].append("required checks passed and the review of the head commit is complete")
    return result


def changed_paths(gh: Gh, config: Config, number: int) -> list[str]:
    files = rest_pages(gh, f"repos/{config.repository}/pulls/{number}/files")
    paths: list[str] = []
    for item in files:
        paths.append(str(item["filename"]))
        if item.get("previous_filename"):
            paths.append(str(item["previous_filename"]))
    return paths


def status(gh: Gh, config: Config, number: int, *, timed_out: bool = False) -> dict[str, Any]:
    """Read the pull request and decide. A part that cannot be read never hides a P0.

    The review threads are read on their own, first. If the rest of the snapshot then
    fails, a P0 that was read still escalates; and if the threads themselves cannot be
    read, the round stops, because a critical finding cannot be ruled out.
    """
    threads: list[dict[str, Any]] = []
    threads_readable = True
    try:
        threads = review_threads.unresolved_threads(gh, config, number)
    except READ_ERRORS:
        threads_readable = False
    try:
        snap = pr_wait.snapshot(gh, config, number)
    except READ_ERRORS as error:
        snap = {"pr": number, "error": f"{type(error).__name__}: {str(error)[:200]}"}
    if timed_out:
        snap["timeout"] = True
    # If the count cannot be read, assume the budget is spent: no further fix round.
    fix_rounds = config.max_fix_rounds
    protected: list[dict[str, str]] | None = None
    try:
        comments = rest_pages(gh, f"repos/{config.repository}/issues/{number}/comments")
        fix_rounds = fix_rounds_used(comments, config)
        protected = [
            {"path": m.path, "category": m.category}
            for m in merge_eligibility.evaluate(changed_paths(gh, config, number)).protected
        ]
    except READ_ERRORS:
        pass
    result = decide(
        snap,
        threads,
        fix_rounds=fix_rounds,
        max_fix_rounds=config.max_fix_rounds,
        labels=(config.label_ready, config.label_needs_human),
        protected=protected,
        threads_readable=threads_readable,
    )
    result["protected_paths"] = protected
    result["conflicts"] = snap.get("conflicts")
    result["protection"] = snap.get("protection")
    result["required_checks"] = snap.get("required_checks")
    return result


def record_fix_round(gh: Gh, config: Config, number: int) -> str:
    """Record that a fix round is starting.

    Refuses once the limit has been used, and refuses while a P0 finding is open: a P0 is
    escalated, not fixed.
    """
    unresolved = review_threads.unresolved_threads(gh, config, number)
    if review_threads.critical_findings(unresolved):
        raise EscalationRequired(
            f"pull request {number} has an open P0 finding: stop the round and escalate "
            "to the owner; do not start a fix round"
        )
    if review_threads.incomplete_threads(unresolved):
        raise EscalationRequired(
            f"pull request {number} has review threads whose comments could not all be "
            "read, so a P0 cannot be ruled out: stop the round and tell the owner; do not "
            "start a fix round"
        )
    comments = rest_pages(gh, f"repos/{config.repository}/issues/{number}/comments")
    used = fix_rounds_used(comments, config)
    if used >= config.max_fix_rounds:
        raise LimitReached(
            f"pull request {number} has used all {config.max_fix_rounds} fix rounds; "
            f"label it {config.label_needs_human} and stop"
        )
    data = graphql(gh, PR_QUERY, owner=config.owner, name=config.name, number=number)
    pull = (data.get("repository") or {}).get("pullRequest")
    if not isinstance(pull, dict) or pull.get("state") != "OPEN":
        raise GhError(f"pull request {number} is not open")
    current = used + 1
    body = f"Fix round {current} of {config.max_fix_rounds}. <!-- round-fix-round:{current} -->"
    graphql(gh, COMMENT_MUTATION, subject=str(pull["id"]), body=body)
    return f"recorded fix round {current} of {config.max_fix_rounds}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    shower = sub.add_parser("status", help="print the next step as JSON")
    shower.add_argument("number", type=int)
    shower.add_argument(
        "--timed-out", action="store_true", help="the wait before this call timed out"
    )
    recorder = sub.add_parser("record-fix-round", help="record the start of a fix round")
    recorder.add_argument("number", type=int)
    args = parser.parse_args(argv)
    try:
        config = load_config()
        gh = with_retries(run_gh)
        if args.command == "record-fix-round":
            sys.stdout.write(record_fix_round(gh, config, args.number) + "\n")
            return 0
        result = status(gh, config, args.number, timed_out=args.timed_out)
    except (LimitReached, EscalationRequired) as error:
        sys.stderr.write(f"refused: {error}\n")
        return 4
    except (GhError, ValueError, KeyError, TypeError) as error:
        # Nothing could be established, so a critical finding cannot be ruled out.
        result = {
            "pr": args.number,
            "action": "escalate",
            "outcome": "needs-human",
            "stop_round": True,
            "reasons": [
                "could not read the pull request, so a critical finding cannot be ruled out; "
                f"stop the round and tell the owner: {type(error).__name__}: {error}"[:400]
            ],
            "automatic_merge": False,
            "merge": "owner-only",
        }
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        return 3
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
