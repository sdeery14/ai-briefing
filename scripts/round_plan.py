"""Work out which issues in a milestone a round may take on, without changing anything.

Used by the ``/round`` skill (``.claude/skills/round/SKILL.md``). It only reads.

    uv run python scripts/round_plan.py --milestone "M1 Working briefing"
    uv run python scripts/round_plan.py --milestone "M1 Working briefing" --only 12,14
    uv run python scripts/round_plan.py --milestone "M1 Working briefing" --fixture plan.json

What makes an issue workable:

- It is open, in the named milestone, and **written by an author on the allowlist** in the
  round configuration. Putting an issue in a milestone needs write access, and the owner
  starts the round by naming the milestone; those two together are the authorisation.
- It carries none of the configured skip labels.
- It states what "done" means, under a ``Done when`` heading or line.
- Everything it depends on is closed. Dependencies are written in the issue body as a
  line ``Depends on: #12, #14``.

Text from anyone else never becomes instructions. An issue by another author is listed as
skipped with no body. Comments by other authors are counted and dropped; their text is not
included in the plan at all.

``--fixture`` reads GitHub's answers from a JSON file instead of the network, for a dry run
or a test. Exit code 0 always means "a plan was produced", never "work may be merged".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from round_lib import (
    Config,
    Gh,
    GhError,
    is_allowed_author,
    load_config,
    login_of,
    rest_pages,
    run_gh,
    slug,
    with_retries,
)

DEPENDS = re.compile(r"^\s*depends on\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
ISSUE_REF = re.compile(r"#(\d+)")
DONE_WHEN = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?done[- ]when\b", re.IGNORECASE | re.MULTILINE)
ADR_REF = re.compile(r"\bADR-0?(\d{1,3})\b", re.IGNORECASE)


def fixture_gh(data: dict[str, Any]) -> Gh:
    """Answer the REST calls this script makes from a dictionary of path to response."""
    routes: dict[str, Any] = data.get("routes") or {}

    def gh(args: Sequence[str]) -> Any:
        path = args[1]
        base, _, query = path.partition("?")
        page = re.search(r"(?:^|&)page=(\d+)", query)
        key = re.sub(r"(?:^|&)(?:per_page|page)=\d+", "", query).strip("&")
        route = f"{base}?{key}" if key else base
        if route not in routes:
            raise GhError(f"fixture has no answer for {route}")
        value = routes[route]
        if isinstance(value, list) and page:
            start = (int(page.group(1)) - 1) * 100
            return value[start : start + 100]
        return value

    return gh


def find_milestone(gh: Gh, config: Config, title: str) -> dict[str, Any]:
    milestones = rest_pages(gh, f"repos/{config.repository}/milestones?state=open")
    matches = [m for m in milestones if m.get("title") == title]
    if len(matches) != 1:
        available = sorted(str(m.get("title")) for m in milestones)
        raise GhError(f"no single open milestone titled {title!r}; open milestones: {available}")
    return dict(matches[0])


def dependencies(body: str) -> list[int]:
    numbers: list[int] = []
    for line in DEPENDS.findall(body):
        numbers.extend(int(n) for n in ISSUE_REF.findall(line))
    return sorted(set(numbers))


def plan_issue(gh: Gh, config: Config, issue: dict[str, Any]) -> dict[str, Any]:
    """One issue's place in the plan: ready, blocked, or skipped, with the reasons."""
    number = int(issue["number"])
    author = login_of(issue.get("user"))
    labels = sorted(str(label.get("name")) for label in issue.get("labels") or [])
    entry: dict[str, Any] = {
        "number": number,
        "author": author,
        "labels": labels,
        "status": "skipped",
        "reasons": [],
    }
    if not is_allowed_author(author, config):
        # Nothing an unlisted author wrote is carried into the plan, not even the title.
        entry["reasons"].append("author is not on the allowlist; not authorised work")
        return entry

    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    entry.update(
        title=title,
        branch=config.branch_format.format(number=number, slug=slug(title)),
        adrs=sorted({f"ADR-{int(n):03d}" for n in ADR_REF.findall(body)}),
        depends_on=dependencies(body),
        instructions=body,
    )
    skip = sorted(set(labels) & config.skip_labels)
    if skip:
        entry["reasons"].append(f"labelled {', '.join(skip)}")
        return entry

    comments = rest_pages(gh, f"repos/{config.repository}/issues/{number}/comments")
    trusted = [c for c in comments if is_allowed_author(login_of(c.get("user")), config)]
    entry["owner_comments"] = [str(c.get("body") or "") for c in trusted]
    entry["ignored_comments"] = len(comments) - len(trusted)

    blockers: list[str] = []
    if not DONE_WHEN.search(body):
        blockers.append("no 'Done when' statement; ask the owner what done means")
    for dependency in entry["depends_on"]:
        other = gh(["api", f"repos/{config.repository}/issues/{dependency}"])
        state = other.get("state") if isinstance(other, dict) else None
        if state != "closed":
            blockers.append(f"depends on #{dependency}, which is not closed")
        elif isinstance(other, dict) and other.get("state_reason") == "not_planned":
            blockers.append(f"depends on #{dependency}, which was closed as not planned")
    if blockers:
        entry["status"] = "blocked"
        entry["reasons"] = blockers
    else:
        entry["status"] = "ready"
    return entry


def build_plan(
    gh: Gh, config: Config, milestone_title: str, only: Sequence[int] | None = None
) -> dict[str, Any]:
    if not re.search(config.milestone_title_pattern, milestone_title):
        raise GhError(
            f"{milestone_title!r} does not look like a project milestone "
            f"(pattern {config.milestone_title_pattern})"
        )
    milestone = find_milestone(gh, config, milestone_title)
    items = rest_pages(
        gh, f"repos/{config.repository}/issues?milestone={milestone['number']}&state=open"
    )
    issues = [i for i in items if "pull_request" not in i]
    if only:
        issues = [i for i in issues if int(i["number"]) in set(only)]
    entries = [plan_issue(gh, config, i) for i in sorted(issues, key=lambda i: int(i["number"]))]
    return {
        "schema": "round_plan.v1",
        "repository": config.repository,
        "milestone": milestone_title,
        "merge": "agent-when-eligible" if config.agent_may_merge else "owner-only",
        "automatic_merge": config.agent_may_merge,
        "max_fix_rounds": config.max_fix_rounds,
        "ready": [e["number"] for e in entries if e["status"] == "ready"],
        "blocked": [e["number"] for e in entries if e["status"] == "blocked"],
        "skipped": [e["number"] for e in entries if e["status"] == "skipped"],
        "issues": entries,
    }


def render(plan: dict[str, Any]) -> str:
    lines = [
        f"Round plan for milestone {plan['milestone']!r} ({plan['repository']})",
        (
            "The round merges a pull request only when every ADR-013 condition holds; "
            "the owner merges the rest."
            if plan.get("automatic_merge")
            else "The round opens pull requests and stops. Only the owner merges."
        ),
        "",
    ]
    for entry in plan["issues"]:
        heading = f"#{entry['number']} [{entry['status']}]"
        if "title" in entry:
            heading += f" {entry['title']}"
        lines.append(heading)
        if entry["status"] == "ready":
            lines.append(f"    branch: {entry['branch']}")
            lines.append(f"    ADRs named: {', '.join(entry['adrs']) or 'none'}")
            depends = ", ".join(f"#{n}" for n in entry["depends_on"]) or "none"
            lines.append(f"    depends on: {depends} (all closed)")
            if entry.get("ignored_comments"):
                lines.append(
                    f"    ignored {entry['ignored_comments']} comment(s) from other authors"
                )
        for reason in entry["reasons"]:
            lines.append(f"    - {reason}")
    lines += [
        "",
        f"ready: {plan['ready']}  blocked: {plan['blocked']}  skipped: {plan['skipped']}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--milestone", required=True, help="exact milestone title")
    parser.add_argument("--only", help="comma-separated issue numbers")
    parser.add_argument("--fixture", help="read GitHub's answers from this JSON file")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args(argv)
    try:
        config = load_config()
        if args.fixture:
            gh = fixture_gh(json.loads(Path(args.fixture).read_text(encoding="utf-8")))
        else:
            gh = with_retries(run_gh)
        only = [int(n) for n in args.only.split(",")] if args.only else None
        plan = build_plan(gh, config, args.milestone, only)
    except (GhError, ValueError, KeyError, TypeError, OSError) as error:
        sys.stderr.write(f"error: {type(error).__name__}: {str(error)[:300]}\n")
        return 3
    sys.stdout.write(json.dumps(plan, indent=2) + "\n" if args.json else render(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
