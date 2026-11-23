"""Shared pieces of the ``/round`` workflow (ADR-011, as amended by ADR-013).

Everything project-specific comes from one file, ``.claude/skills/round/config.json``.
The protected-path policy is not repeated there: it is ``scripts/merge_eligibility.py``.

These scripts talk to GitHub only through :func:`run_gh`, which refuses any call that is
not on a short list: plain ``GET`` requests, two read queries and four write mutations
(reply to a review thread, resolve one, comment on a pull request, and squash-merge a
pull request at one exact commit). The merge mutation is sent from one place only,
``round_outcome.merge``, after it has re-checked every condition in ADR-013. There is no
code path here that can enable auto-merge, push, or change a setting.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / ".claude" / "skills" / "round" / "config.json"

# ADR-011: at most two fix rounds. The configuration may lower this, never raise it.
HARD_MAX_FIX_ROUNDS = 2

# ADR-013: who merges.
OWNER_ONLY = "owner-only"
AGENT_WHEN_ELIGIBLE = "agent-when-eligible"
MERGE_AUTHORITIES = frozenset({OWNER_ONLY, AGENT_WHEN_ELIGIBLE})

# A finding's severity is the badge the reviewer puts on it, or a tag at the very start
# of the comment. A "P0" that only appears later in the text is the finding talking about
# severities, not its own severity.
SEVERITY_BADGE = re.compile(r"!\[(P[0-3]) Badge\]")
SEVERITY_LEADING = re.compile(r"^[\s*_`#>\[(-]*(P[0-3])\b")
ESCALATE = "P0"

Gh = Callable[[Sequence[str]], Any]


class ConfigError(ValueError):
    """The round configuration is missing, malformed, or asks for something not allowed."""


class GhError(RuntimeError):
    """GitHub could not be read, or answered with something unusable."""


class ForbiddenCommand(GhError):  # noqa: N818 - reads as a statement of fact
    """A script tried to make a GitHub call that the round workflow never makes."""


@dataclass(frozen=True)
class Config:
    repository: str
    default_branch: str
    allowed_authors: frozenset[str]
    reviewer_login: str
    state_marker: str
    review_request: str
    required_checks: tuple[str, ...]
    informational_checks: tuple[str, ...]
    timeout_minutes: float
    poll_seconds: float
    max_fix_rounds: int
    label_ready: str
    label_needs_human: str
    skip_labels: frozenset[str]
    branch_format: str
    milestone_title_pattern: str
    agent_may_merge: bool = False

    @property
    def owner(self) -> str:
        return self.repository.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.repository.split("/", 1)[1]


def _require(data: dict[str, Any], key: str, kind: type) -> Any:
    value = data.get(key)
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise ConfigError(f"round config: '{key}' must be a {kind.__name__}")
    return value


def parse_config(data: dict[str, Any]) -> Config:
    if data.get("schema") != "round_config.v1":
        raise ConfigError("round config: unknown schema")
    # ADR-013: "owner-only" means the round never merges. "agent-when-eligible" lets it
    # merge a pull request that meets every ADR-013 condition. Nothing else is accepted,
    # and this file is itself an owner-only path.
    merge_authority = data.get("merge_authority")
    if merge_authority not in MERGE_AUTHORITIES:
        raise ConfigError(
            "round config: merge_authority must be 'owner-only' or 'agent-when-eligible'"
        )
    repository = _require(data, "repository", str)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ConfigError("round config: repository must look like owner/name")
    authors = _require(data, "allowed_authors", list)
    if not authors or not all(isinstance(a, str) and a.strip() for a in authors):
        raise ConfigError("round config: allowed_authors must be a non-empty list of logins")
    reviewer = _require(data, "reviewer", dict)
    wait = _require(data, "wait", dict)
    labels = _require(data, "labels", dict)
    max_fix_rounds = _require(data, "max_fix_rounds", int)
    if not 0 <= max_fix_rounds <= HARD_MAX_FIX_ROUNDS:
        raise ConfigError(f"round config: max_fix_rounds must be 0 to {HARD_MAX_FIX_ROUNDS}")
    required = _require(data, "required_checks", list)
    if not required or not all(isinstance(c, str) and c for c in required):
        raise ConfigError("round config: required_checks must be a non-empty list of names")
    timeout = wait.get("timeout_minutes")
    poll = wait.get("poll_seconds")
    if not isinstance(timeout, int | float) or not isinstance(poll, int | float):
        raise ConfigError("round config: wait.timeout_minutes and wait.poll_seconds are numbers")
    if timeout <= 0 or poll <= 0:
        raise ConfigError("round config: wait values must be positive")
    reviewer_login = _require(reviewer, "login", str)
    if reviewer_login.lower() in {a.lower() for a in authors}:
        raise ConfigError("round config: the reviewer must not be an allowed instruction author")
    return Config(
        repository=repository,
        default_branch=_require(data, "default_branch", str),
        allowed_authors=frozenset(a.strip().lower() for a in authors),
        reviewer_login=reviewer_login,
        state_marker=_require(reviewer, "state_marker", str),
        review_request=_require(reviewer, "request_comment", str),
        required_checks=tuple(required),
        informational_checks=tuple(data.get("informational_checks", [])),
        timeout_minutes=float(timeout),
        poll_seconds=float(poll),
        max_fix_rounds=max_fix_rounds,
        label_ready=_require(labels, "ready", str),
        label_needs_human=_require(labels, "needs_human", str),
        skip_labels=frozenset(labels.get("skip", [])),
        branch_format=_require(data, "branch_format", str),
        milestone_title_pattern=_require(data, "milestone_title_pattern", str),
        agent_may_merge=merge_authority == AGENT_WHEN_ELIGIBLE,
    )


def load_config(path: Path | None = None) -> Config:
    target = path or CONFIG_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"round config: cannot read {target.name}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("round config: top level must be an object")
    return parse_config(data)


# --- Authors and severities -----------------------------------------------------------


def is_allowed_author(login: object, config: Config) -> bool:
    """True only for a login on the allowlist. Anything missing or odd is not allowed."""
    return isinstance(login, str) and login.strip().lower() in config.allowed_authors


def node_is_reviewer(node: object, config: Config) -> bool:
    """True when a GitHub ``user`` or ``author`` object is the configured reviewer app.

    GitHub spells an app's account two ways. REST gives ``name[bot]`` with
    ``"type": "Bot"``; GraphQL gives ``name`` with ``"__typename": "Bot"``. Both must say
    it is a bot, so an ordinary user account with a similar name is never accepted.
    """
    if not isinstance(node, dict):
        return False
    login = node.get("login")
    kind = node.get("__typename") or node.get("type")
    if not isinstance(login, str) or kind != "Bot":
        return False
    return login in {config.reviewer_login, config.reviewer_login.removesuffix("[bot]")}


def severity_of(body: str) -> str | None:
    """A finding's own severity: its badge, else a tag that opens the comment, else none."""
    badge = SEVERITY_BADGE.search(body)
    if badge:
        return badge.group(1)
    leading = SEVERITY_LEADING.match(body)
    return leading.group(1) if leading else None


def slug(title: str, limit: int = 40) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return text[:limit].rstrip("-") or "work"


# --- GitHub access --------------------------------------------------------------------

PR_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      id number state isDraft merged mergeable mergeStateStatus headRefOid baseRefName
      author { login }
      commits(last: 1) {
        nodes {
          commit {
            oid
            statusCheckRollup {
              contexts(first: 100) {
                pageInfo { hasNextPage }
                nodes {
                  __typename
                  ... on CheckRun {
                    name status conclusion isRequired(pullRequestNumber: $number)
                  }
                  ... on StatusContext {
                    context state isRequired(pullRequestNumber: $number)
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved isOutdated path line originalLine
          comments(first: 50) {
            pageInfo { hasNextPage }
            nodes { author { __typename login } body url createdAt }
          }
        }
      }
    }
  }
}
"""

REPLY_MUTATION = """
mutation($thread: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $thread, body: $body}) {
    comment { url }
  }
}
"""

RESOLVE_MUTATION = """
mutation($thread: ID!) {
  resolveReviewThread(input: {threadId: $thread}) { thread { isResolved } }
}
"""

COMMENT_MUTATION = """
mutation($subject: ID!, $body: String!) {
  addComment(input: {subjectId: $subject, body: $body}) { commentEdge { node { url } } }
}
"""

# Squash-merge one pull request, and only if its head is still the commit that was
# checked and reviewed. GitHub refuses the merge if the head has moved, if a required
# check is failing, or if a review thread is unresolved (the ruleset on main).
MERGE_MUTATION = """
mutation($pull: ID!, $head: GitObjectID!) {
  mergePullRequest(input: {pullRequestId: $pull, expectedHeadOid: $head, mergeMethod: SQUASH}) {
    pullRequest { number merged mergeCommit { oid } }
  }
}
"""

ALLOWED_GRAPHQL = frozenset(
    {PR_QUERY, THREADS_QUERY, REPLY_MUTATION, RESOLVE_MUTATION, COMMENT_MUTATION, MERGE_MUTATION}
)


def check_allowed(args: Sequence[str]) -> None:
    """Refuse any GitHub call the round workflow does not make.

    Allowed: ``gh api <path>`` as a plain GET with no extra flags, and ``gh api graphql``
    with one of the six documents above.
    """
    if len(args) < 2 or args[0] != "api":
        raise ForbiddenCommand("only 'gh api' calls are made by the round scripts")
    if args[1] == "graphql":
        queries = [a for a in args[2:] if a.startswith("query=")]
        if len(queries) != 1 or queries[0][len("query=") :] not in ALLOWED_GRAPHQL:
            raise ForbiddenCommand("that GraphQL document is not one the round scripts use")
        flags = [a for a in args[2:] if a.startswith("-")]
        if any(flag not in {"-f", "-F"} for flag in flags):
            raise ForbiddenCommand("unexpected flag on a GraphQL call")
        return
    if len(args) != 2 or args[1].startswith("-") or any(c.isspace() for c in args[1]):
        raise ForbiddenCommand("REST calls are GET only, with no flags")
    if not args[1].startswith("repos/"):
        raise ForbiddenCommand("REST calls are limited to repository resources")


def run_gh(args: Sequence[str]) -> Any:
    """Run ``gh`` and parse its JSON. Raises :class:`GhError` instead of guessing."""
    check_allowed(args)
    try:
        completed = subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GhError(f"gh could not be run: {type(error).__name__}") from error
    if completed.returncode != 0:
        raise GhError(f"gh failed: {completed.stderr.strip()[:300]}")
    try:
        payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    except json.JSONDecodeError as error:
        raise GhError("gh returned something that is not JSON") from error
    if isinstance(payload, dict) and payload.get("errors"):
        raise GhError(f"GitHub reported errors: {str(payload['errors'])[:300]}")
    return payload


def with_retries(gh: Gh, attempts: int = 3, pause: float = 2.0) -> Gh:
    """Retry transient failures. A forbidden call is never retried."""

    def call(args: Sequence[str]) -> Any:
        last: GhError | None = None
        for attempt in range(attempts):
            try:
                return gh(args)
            except ForbiddenCommand:
                raise
            except GhError as error:
                last = error
                if attempt + 1 < attempts:
                    time.sleep(pause)
        raise last if last else GhError("gh failed")

    return call


def graphql(gh: Gh, query: str, **variables: str | int) -> Any:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    payload = gh(args)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise GhError("GraphQL response had no data")
    return payload["data"]


def rest_pages(gh: Gh, path: str, limit_pages: int = 50) -> list[Any]:
    """Every item of a paginated REST list. Raises if the end is not reached."""
    items: list[Any] = []
    joiner = "&" if "?" in path else "?"
    for page in range(1, limit_pages + 1):
        batch = gh(["api", f"{path}{joiner}per_page=100&page={page}"])
        if not isinstance(batch, list):
            raise GhError(f"expected a list from {path}")
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise GhError(f"{path} did not end within {limit_pages} pages")


def login_of(node: object) -> str | None:
    """The login in a GitHub ``user`` or ``author`` object, or ``None``."""
    if isinstance(node, dict):
        value = node.get("login")
        return value if isinstance(value, str) else None
    return None
