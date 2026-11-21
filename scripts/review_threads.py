"""List a pull request's unresolved review threads, or reply to one and resolve it.

Used by the ``/round`` skill (``.claude/skills/round/SKILL.md``). Needs an authenticated
GitHub CLI (``gh``).

    uv run python scripts/review_threads.py list 64
    uv run python scripts/review_threads.py resolve 64 PRRT_kwDO... --reply "Fixed in abc1234: ..."
    uv run python scripts/review_threads.py resolve 64 PRRT_kwDO... --reply "Not changing: ..." --keep-open

``list`` prints a JSON array. Each thread carries its id, path, line, whether the diff has
moved on from it, the author of the first comment and whether that is the configured
reviewer, the severity tag (``P0`` to ``P3``) if the body has one, the number of replies,
whether an allowed author has already answered it, and the comment URL.

``resolve`` will not close every thread:

- A ``P0`` thread is never resolved here. It is escalated to the owner.
- A thread opened by anyone other than the configured reviewer is never resolved here.
  The owner's own comments are for the owner to close.
- ``--keep-open`` posts the reply and leaves the thread open. Use it for any finding you
  dispute, so the owner decides.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from round_lib import (
    ESCALATE,
    REPLY_MUTATION,
    RESOLVE_MUTATION,
    THREADS_QUERY,
    Config,
    Gh,
    GhError,
    graphql,
    is_allowed_author,
    load_config,
    login_of,
    node_is_reviewer,
    run_gh,
    severity_of,
    with_retries,
)


class Refused(GhError):  # noqa: N818 - reads as a statement of fact
    """The thread is one this script must leave for the owner."""


def all_threads(gh: Gh, config: Config, number: int) -> list[dict[str, Any]]:
    """Every review thread on the pull request, following the cursors to the end."""
    threads: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(100):
        variables: dict[str, str | int] = {
            "owner": config.owner,
            "name": config.name,
            "number": number,
        }
        if cursor is not None:
            variables["after"] = cursor
        pull = (graphql(gh, THREADS_QUERY, **variables).get("repository") or {}).get("pullRequest")
        if not isinstance(pull, dict):
            raise GhError(f"pull request {number} was not found")
        connection = pull["reviewThreads"]
        threads.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            return threads
        cursor = connection["pageInfo"]["endCursor"]
    raise GhError("review threads did not end within 100 pages")


def _trusted(author: object, config: Config) -> bool:
    """The configured reviewer or an allowed author. Nobody else can raise a P0."""
    return node_is_reviewer(author, config) or is_allowed_author(login_of(author), config)


def critical_findings(threads: list[dict[str, Any]]) -> list[str]:
    """Where the unresolved P0 findings from trusted authors are, given described threads."""
    return [str(t.get("url") or t["id"]) for t in threads if t.get("p0")]


def describe(thread: dict[str, Any], config: Config) -> dict[str, Any]:
    comments = (thread.get("comments") or {}).get("nodes") or []
    first = comments[0] if comments else {}
    body = str(first.get("body") or "")
    author = login_of(first.get("author"))
    replies = comments[1:]
    return {
        "id": thread["id"],
        "path": thread.get("path"),
        "line": thread.get("line") or thread.get("originalLine"),
        "outdated": bool(thread.get("isOutdated")),
        "author": author,
        "from_reviewer": node_is_reviewer(first.get("author"), config),
        "from_allowed_author": is_allowed_author(author, config),
        "severity": severity_of(body),
        # A P0 counts wherever a trusted author raises it in the thread: as the opening
        # finding, or as a reply that escalates someone else's thread.
        "p0": any(
            severity_of(str(c.get("body") or "")) == ESCALATE and _trusted(c.get("author"), config)
            for c in comments
        ),
        "body": body,
        "replies": len(replies),
        "answered": any(is_allowed_author(login_of(r.get("author")), config) for r in replies),
        "url": first.get("url"),
    }


def unresolved_threads(gh: Gh, config: Config, number: int) -> list[dict[str, Any]]:
    return [
        describe(thread, config)
        for thread in all_threads(gh, config, number)
        if not thread.get("isResolved")
    ]


def resolve(
    gh: Gh, config: Config, number: int, thread_id: str, reply: str, *, keep_open: bool
) -> str:
    """Reply to a thread and, when permitted, resolve it. Returns what was done."""
    if not reply.strip():
        raise Refused("a reply saying what changed, or why nothing did, is required")
    matches = [t for t in unresolved_threads(gh, config, number) if t["id"] == thread_id]
    if not matches:
        raise Refused(f"{thread_id} is not an unresolved thread on pull request {number}")
    thread = matches[0]
    if not keep_open:
        if thread["p0"]:
            raise Refused("a P0 thread is escalated to the owner, not resolved here")
        if not thread["from_reviewer"]:
            raise Refused(
                "only threads opened by the configured reviewer are resolved here; "
                "reply with --keep-open and leave this one for the owner"
            )
    graphql(gh, REPLY_MUTATION, thread=thread_id, body=reply)
    if keep_open:
        return f"{thread_id}: replied, left open for the owner"
    graphql(gh, RESOLVE_MUTATION, thread=thread_id)
    return f"{thread_id}: replied and resolved"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lister = sub.add_parser("list", help="print the unresolved threads as JSON")
    lister.add_argument("number", type=int)
    resolver = sub.add_parser("resolve", help="reply to a thread and mark it resolved")
    resolver.add_argument("number", type=int)
    resolver.add_argument("thread_id")
    resolver.add_argument("--reply", required=True, help="what changed, or why nothing did")
    resolver.add_argument(
        "--keep-open", action="store_true", help="post the reply but leave the thread open"
    )
    args = parser.parse_args(argv)
    try:
        config = load_config()
        gh = with_retries(run_gh)
        if args.command == "list":
            threads = unresolved_threads(gh, config, args.number)
            sys.stdout.write(json.dumps(threads, indent=2) + "\n")
            return 0
        message = resolve(
            gh, config, args.number, args.thread_id, args.reply, keep_open=args.keep_open
        )
    except Refused as error:
        sys.stderr.write(f"refused: {error}\n")
        return 4
    except (GhError, ValueError, KeyError, TypeError) as error:
        sys.stderr.write(f"error: {type(error).__name__}: {str(error)[:300]}\n")
        return 3
    sys.stdout.write(message + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
