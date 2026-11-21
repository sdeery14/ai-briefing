"""Wait for a pull request's required checks and its Codex review, then print one JSON line.

Used by the ``/round`` skill (``.claude/skills/round/SKILL.md``). Needs an authenticated
GitHub CLI (``gh``). It only reads; it cannot merge, and it has no mode that waits for a
merge, because in ADR-011 Phase A the owner merges.

    uv run python scripts/pr_wait.py 64          # wait until settled or timed out
    uv run python scripts/pr_wait.py 64 --once   # one snapshot, no waiting

Exit code 0: the wait ended with an answer. 2: timed out. 3: GitHub could not be read, or
the configuration disagrees with the repository's ruleset. A non-zero exit never means
"passed".

What it reports, and where each fact comes from:

- **Required checks** are read from the ruleset that applies to the default branch, and
  compared with the names in the round configuration. A difference is an error, not a guess.
- Each required check is ``pass``, ``fail``, ``pending`` or ``missing`` (not reported for
  this commit at all).
- **conflicts** is GitHub's ``mergeable`` field: only whether the branch merges cleanly.
- **protection** is GitHub's ``mergeStateStatus``: whether the branch rules are satisfied.
  The two are different and are never combined.
- **codex** is the review state the configured reviewer account publishes, and counts only
  when it names the pull request's current head commit.

The merge-eligibility report is listed under ``informational``. It is not a required check
and a green result there gives no permission to merge.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from typing import Any

from round_lib import (
    PR_QUERY,
    Config,
    Gh,
    GhError,
    graphql,
    load_config,
    login_of,
    node_is_reviewer,
    rest_pages,
    run_gh,
    with_retries,
)

PASSING = {"SUCCESS", "NEUTRAL", "SKIPPED"}
CONFLICTS = {"MERGEABLE": "none", "CONFLICTING": "conflicting"}
_RANK = {"fail": 3, "pending": 2, "pass": 1}


def ruleset_required_checks(gh: Gh, config: Config) -> list[str]:
    """The status checks the active rules require on the default branch."""
    rules = gh(["api", f"repos/{config.repository}/rules/branches/{config.default_branch}"])
    if not isinstance(rules, list):
        raise GhError("could not read the rules for the default branch")
    names: list[str] = []
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
            for check in (rule.get("parameters") or {}).get("required_status_checks") or []:
                names.append(str(check["context"]))
    return names


def check_states(nodes: list[dict[str, Any]]) -> tuple[dict[str, str], set[str]]:
    """Map each check's name to ``pass``, ``fail`` or ``pending``; and which GitHub requires.

    If a name appears more than once, the worst state wins.
    """
    states: dict[str, str] = {}
    required: set[str] = set()
    for node in nodes:
        if node.get("__typename") == "StatusContext":
            name = str(node.get("context") or "?")
            raw = node.get("state")
            state = (
                "pass"
                if raw == "SUCCESS"
                else "pending"
                if raw in {"PENDING", "EXPECTED"}
                else "fail"
            )
        else:
            name = str(node.get("name") or "?")
            if node.get("status") != "COMPLETED":
                state = "pending"
            else:
                state = "pass" if node.get("conclusion") in PASSING else "fail"
        if _RANK[state] > _RANK.get(states.get(name, ""), 0):
            states[name] = state
        if node.get("isRequired"):
            required.add(name)
    return states, required


def required_states(states: dict[str, str], required: list[str]) -> dict[str, str]:
    return {name: states.get(name, "missing") for name in required}


def ci_verdict(required: dict[str, str]) -> str:
    """``fail`` if any required check failed; ``pass`` only when every one passed."""
    values = set(required.values())
    if not required:
        return "missing"
    if "fail" in values:
        return "fail"
    if values == {"pass"}:
        return "pass"
    return "missing" if values <= {"pass", "missing"} else "pending"


def head_arrived_at(gh: Gh, config: Config, head: str) -> str:
    """When the head commit reached GitHub: the creation of its first check suite.

    A commit's own dates say when it was made, not when it was pushed. A notice the
    reviewer posted before the push is about the previous head.
    """
    suites = gh(["api", f"repos/{config.repository}/commits/{head}/check-suites"]) or {}
    created = [
        str(s["created_at"])
        for s in (suites.get("check_suites") if isinstance(suites, dict) else None) or []
        if s.get("created_at")
    ]
    return min(created) if created else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def codex_state(
    comments: list[dict[str, Any]], config: Config, head: str, head_arrived: str
) -> dict[str, Any] | None:
    """The reviewer's response that applies to the pull request now, or ``None``.

    Only comments from the configured reviewer account are read. The review state is the
    JSON block the reviewer embeds after its state marker. A notice without that block
    (a quota message, a request to set up an environment) counts only when it is newer
    than the head's arrival, and never overrides a state for the head itself.
    """
    pattern = re.compile(re.escape(config.state_marker) + r" (\{.*?\}) -->", re.S)
    latest: dict[str, Any] | None = None
    for comment in comments:
        if not node_is_reviewer(comment.get("user"), config):
            continue
        body = str(comment.get("body") or "")
        match = pattern.search(body)
        if match:
            try:
                review = json.loads(match.group(1)).get("code_review")
            except (json.JSONDecodeError, AttributeError):
                review = None
            if isinstance(review, dict):
                latest = review
            else:
                latest = {"status": "error", "message": "unreadable review state"}
        elif str(comment.get("created_at") or "") >= head_arrived and (
            latest is None or latest.get("commit_sha") != head
        ):
            latest = {"status": "error", "message": body.strip()[:300]}
    if latest is None:
        return None
    commit = latest.get("commit_sha")
    return {
        "status": latest.get("status"),
        "message": latest.get("message"),
        "commit": commit,
        "for_head": commit == head,
        "stale": commit is not None and commit != head,
        "findings": latest.get("has_any_findings"),
        "unresolved": latest.get("has_unresolved_findings"),
    }


def snapshot(gh: Gh, config: Config, number: int) -> dict[str, Any]:
    """Everything the round needs to know about the pull request, read once."""
    ruleset = ruleset_required_checks(gh, config)
    data = graphql(gh, PR_QUERY, owner=config.owner, name=config.name, number=number)
    pull = (data.get("repository") or {}).get("pullRequest")
    if not isinstance(pull, dict):
        raise GhError(f"pull request {number} was not found")
    head = str(pull["headRefOid"])
    commits = ((pull.get("commits") or {}).get("nodes")) or []
    commit = (commits[-1].get("commit") if commits else None) or {}
    if commit.get("oid") not in (None, head):
        raise GhError("the check results are for a different commit than the head")
    contexts = ((commit.get("statusCheckRollup") or {}).get("contexts")) or {}
    complete = not (contexts.get("pageInfo") or {}).get("hasNextPage", False)
    states, github_required = check_states(contexts.get("nodes") or [])

    problems: list[str] = []
    if sorted(ruleset) != sorted(config.required_checks):
        problems.append(
            "the ruleset's required checks differ from the round configuration: "
            f"ruleset {sorted(ruleset)}, configuration {sorted(config.required_checks)}"
        )
    if not complete:
        problems.append("more checks exist than were read")
    unexpected = github_required - set(ruleset)
    if unexpected:
        problems.append(f"GitHub marks other checks as required: {sorted(unexpected)}")

    required = required_states(states, ruleset)
    comments = rest_pages(gh, f"repos/{config.repository}/issues/{number}/comments")
    codex = codex_state(comments, config, head, head_arrived_at(gh, config, head))
    return {
        "pr": number,
        "head": head,
        "base": pull.get("baseRefName"),
        "state": pull.get("state"),
        "merged": bool(pull.get("merged")),
        "draft": bool(pull.get("isDraft")),
        "author": login_of(pull.get("author")),
        "conflicts": CONFLICTS.get(str(pull.get("mergeable")), "unknown"),
        "protection": pull.get("mergeStateStatus"),
        "required_checks": required,
        "ci": "error" if problems else ci_verdict(required),
        "informational": {
            name: states.get(name, "missing") for name in config.informational_checks
        },
        "other_checks": {
            name: state
            for name, state in states.items()
            if name not in required and name not in config.informational_checks
        },
        "codex": codex,
        "problems": problems,
        "automatic_merge": False,
        "merge": "owner-only",
    }


def settled(snap: dict[str, Any]) -> bool:
    """True when waiting longer will not change what the round should do next."""
    if snap["state"] != "OPEN" or snap["problems"]:
        return True
    if snap["ci"] == "fail":
        return True
    codex = snap["codex"]
    if codex is not None and codex["status"] == "error":
        return True
    reviewed = codex is not None and codex["for_head"] and codex["status"] == "completed"
    return snap["ci"] == "pass" and reviewed


def wait(
    gh: Gh,
    config: Config,
    number: int,
    *,
    timeout_minutes: float,
    poll_seconds: float,
    once: bool = False,
    sleep: Any = time.sleep,
    clock: Any = time.monotonic,
) -> tuple[dict[str, Any], int]:
    deadline = clock() + timeout_minutes * 60
    while True:
        snap = snapshot(gh, config, number)
        if snap["problems"]:
            return snap, 3
        if settled(snap) or once:
            return snap, 0
        if clock() >= deadline:
            snap["timeout"] = True
            return snap, 2
        sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("number", type=int, help="pull request number")
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    parser.add_argument("--timeout-minutes", type=float)
    parser.add_argument("--poll-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        config = load_config()
        snap, code = wait(
            with_retries(run_gh),
            config,
            args.number,
            timeout_minutes=args.timeout_minutes or config.timeout_minutes,
            poll_seconds=args.poll_seconds or config.poll_seconds,
            once=args.once,
        )
    except (GhError, ValueError, KeyError, TypeError) as error:
        snap = {
            "pr": args.number,
            "error": f"{type(error).__name__}: {str(error)[:300]}",
            "ci": "error",
            "automatic_merge": False,
            "merge": "owner-only",
        }
        code = 3
    sys.stdout.write(json.dumps(snap) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
