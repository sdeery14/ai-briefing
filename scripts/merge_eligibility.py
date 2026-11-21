"""Report whether a pull request touches a protected path (ADR-011).

The protected paths below are the table in ADR-011, written as patterns. This script is
the single source for them: ``.github/CODEOWNERS`` is generated from the same list and a
test fails if the two drift apart.

In ADR-011 Phase A the result is informational. A pull request that touches a protected
path is reported as not eligible for a future automatic merge; nothing here blocks the
owner from merging it. The script never merges anything.

It reads the changed-file list from the GitHub API and runs no code from the pull request.
File names are untrusted input: they are matched and printed, never executed or evaluated.

    python3 scripts/merge_eligibility.py --repo owner/name --pr 12       # GITHUB_TOKEN in env
    python3 scripts/merge_eligibility.py --files-from changed.txt        # offline, one path per line
    python3 scripts/merge_eligibility.py --print-codeowners              # the generated CODEOWNERS

Standard library only, so the workflow needs no dependency install.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "merge_eligibility.v1"
PHASE = "A-report-only"
OWNER = "@sdeery14"
API_ROOT = "https://api.github.com"

# GitHub returns at most 3000 files for a pull request. A list that long cannot be
# trusted to be complete, so it is treated as indeterminate.
API_FILE_LIMIT = 3000
PAGE_SIZE = 100

# ADR-011 protected paths. ``**`` crosses directories, ``*`` does not.
# Golden files live in a ``golden/`` directory and recorded model responses in a
# ``recorded/`` directory, anywhere under ``tests/``.
PROTECTED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("decisions", ("docs/rfc/**", "docs/adr/**")),
    (
        "evaluation",
        (
            "src/ai_briefing/evaluation/**",
            "evals/**",
            "tests/**/golden/**",
            "tests/**/recorded/**",
        ),
    ),
    (
        "prompts-and-editorial-policy",
        ("src/ai_briefing/prompts/**", "src/ai_briefing/editorial/policy/**"),
    ),
    ("models-budget-sources", ("config/**",)),
    ("contracts-and-migrations", ("schemas/**", "migrations/**")),
    ("workflows", (".github/**",)),
    ("dependencies", ("pyproject.toml", "uv.lock")),
    (
        "deployment",
        (
            "deploy/**",
            "**/Dockerfile*",
            "**/.dockerignore",
            "**/compose*.yml",
            "**/compose*.yaml",
            "**/docker-compose*.yml",
            "**/docker-compose*.yaml",
        ),
    ),
    (
        "agent-workflow",
        (".claude/**", "scripts/**", "AGENTS.md", "CLAUDE.md", "CODEOWNERS"),
    ),
)

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class Match:
    path: str
    category: str
    pattern: str


@dataclass(frozen=True)
class Result:
    eligible: bool
    complete: bool
    changed_file_count: int
    protected: tuple[Match, ...]
    reasons: tuple[str, ...]
    pull_request: int | None = None
    head_sha: str | None = None
    schema: str = SCHEMA
    phase: str = PHASE
    categories: tuple[str, ...] = field(default=())

    def to_json(self) -> str:
        """One line of JSON. ``json.dumps`` escapes newlines, so it is safe in a step output."""
        return json.dumps(asdict(self), sort_keys=True)


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a protected-path pattern into an anchored, case-insensitive regex."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    # Case-insensitive on purpose: "agents.MD" should not slip past "AGENTS.md".
    # DOTALL so a file name containing a newline cannot slip past "**".
    return re.compile("".join(out), re.IGNORECASE | re.DOTALL)


_COMPILED: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (category, pattern, pattern_to_regex(pattern))
    for category, patterns in PROTECTED
    for pattern in patterns
)


def normalise(path: str) -> str:
    """Forward slashes, no leading ``./`` or ``/``. Nothing else is rewritten."""
    cleaned = path.replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def match_path(path: str) -> Match | None:
    """The first protected pattern the path falls under, if any."""
    candidate = normalise(path)
    for category, pattern, regex in _COMPILED:
        if regex.fullmatch(candidate):
            return Match(path=path, category=category, pattern=pattern)
    return None


def evaluate(
    paths: Sequence[str],
    *,
    complete: bool = True,
    expected_count: int | None = None,
    pull_request: int | None = None,
    head_sha: str | None = None,
) -> Result:
    """Decide eligibility from a changed-file list. Anything uncertain is not eligible."""
    unique = sorted(set(paths))
    protected = tuple(m for m in (match_path(p) for p in unique) if m is not None)
    reasons: list[str] = []
    if not complete:
        reasons.append("the changed-file list could not be confirmed complete")
    if expected_count is not None and expected_count == 0:
        reasons.append("the pull request reports no changed files")
    elif not unique:
        reasons.append("no changed files were supplied")
    if protected:
        reasons.append(f"{len(protected)} changed file(s) are on protected paths")
    categories = tuple(sorted({m.category for m in protected}))
    return Result(
        eligible=not reasons,
        complete=complete,
        changed_file_count=expected_count if expected_count is not None else len(unique),
        protected=protected,
        reasons=tuple(reasons),
        pull_request=pull_request,
        head_sha=head_sha,
        categories=categories,
    )


def failure(reason: str, *, pull_request: int | None = None) -> Result:
    """The result when the list could not be retrieved at all."""
    return Result(
        eligible=False,
        complete=False,
        changed_file_count=0,
        protected=(),
        reasons=(reason,),
        pull_request=pull_request,
    )


# --- GitHub API -----------------------------------------------------------------------

Fetch = Callable[[str], Any]


def _github_get(token: str) -> Fetch:
    def get(url: str) -> Any:
        if not url.startswith(API_ROOT + "/"):
            raise ValueError("refusing to request a URL outside the GitHub API")
        request = urllib.request.Request(  # noqa: S310 - fixed https host, checked above
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "merge-eligibility",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)

    return get


def changed_files(repo: str, number: int, get: Fetch) -> tuple[list[str], bool, int, str | None]:
    """Every path the pull request touches, whether the list is complete, the count and head.

    A renamed file contributes both names: moving a file out of a protected path is a
    change to that path.
    """
    if not _REPO.fullmatch(repo):
        raise ValueError("repository must look like owner/name")
    pull = get(f"{API_ROOT}/repos/{repo}/pulls/{number}")
    expected = int(pull["changed_files"])
    head_sha = str(pull["head"]["sha"])
    paths: list[str] = []
    entries = 0
    page = 1
    while entries < expected and entries < API_FILE_LIMIT:
        batch = get(
            f"{API_ROOT}/repos/{repo}/pulls/{number}/files?per_page={PAGE_SIZE}&page={page}"
        )
        if not batch:
            break
        for item in batch:
            entries += 1
            paths.append(str(item["filename"]))
            previous = item.get("previous_filename")
            if previous:
                paths.append(str(previous))
        page += 1
    complete = entries == expected and expected < API_FILE_LIMIT
    return paths, complete, expected, head_sha


# --- Output ---------------------------------------------------------------------------


def _shown(path: str) -> str:
    """A path made safe to print inside Markdown code formatting."""
    cleaned = "".join(ch if ch.isprintable() and ch not in "`|<>" else "?" for ch in path)
    return cleaned if len(cleaned) <= 200 else cleaned[:197] + "..."


def summary_markdown(result: Result, *, limit: int = 50) -> str:
    lines = ["## Merge eligibility (report only)", ""]
    if result.eligible:
        lines.append("**Eligible:** no protected path is touched.")
    else:
        lines.append("**Not eligible for automatic merge.**")
    lines += [
        "",
        "ADR-011 Phase A: this report is informational. It does not block the owner from "
        "merging, and nothing merges automatically.",
        "",
        f"- Changed files: {result.changed_file_count}",
        f"- File list complete: {'yes' if result.complete else 'no'}",
    ]
    for reason in result.reasons:
        lines.append(f"- Reason: {reason}")
    if result.protected:
        lines += ["", "| Protected path touched | Category | Rule |", "|---|---|---|"]
        for match in result.protected[:limit]:
            lines.append(f"| `{_shown(match.path)}` | {match.category} | `{match.pattern}` |")
        if len(result.protected) > limit:
            lines.append(f"| ... and {len(result.protected) - limit} more | | |")
    return "\n".join(lines) + "\n"


def codeowners_pattern(pattern: str) -> str:
    """The CODEOWNERS spelling of a protected-path pattern."""
    if pattern.startswith("**/"):
        return pattern[3:]  # unanchored: matches at any depth
    if pattern.endswith("/**"):
        return "/" + pattern[:-2]  # a directory and everything under it
    return "/" + pattern


def codeowners_text() -> str:
    lines = [
        "# Generated from scripts/merge_eligibility.py. Do not edit by hand:",
        "#   python3 scripts/merge_eligibility.py --print-codeowners > .github/CODEOWNERS",
        "#",
        "# These are the protected paths in ADR-011. A change to any of them needs the",
        "# owner's review. This file only names the owner; a repository ruleset has to",
        "# require code-owner review for that to be enforced.",
        "",
    ]
    for category, patterns in PROTECTED:
        lines.append(f"# {category}")
        width = max(len(codeowners_pattern(p)) for p in patterns)
        for pattern in patterns:
            lines.append(f"{codeowners_pattern(pattern).ljust(width)}  {OWNER}")
        lines.append("")
    return "\n".join(lines)


def _append(path: str | None, text: str) -> None:
    if path:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--repo", help="owner/name")
    parser.add_argument("--pr", type=int, help="pull request number")
    parser.add_argument("--files-from", help="read changed paths from a file, one per line")
    parser.add_argument("--summary", help="append a Markdown summary to this file")
    parser.add_argument("--github-output", help="append step outputs to this file")
    parser.add_argument("--print-codeowners", action="store_true")
    args = parser.parse_args(argv)

    if args.print_codeowners:
        sys.stdout.write(codeowners_text())
        return 0

    exit_code = 0
    if args.files_from:
        text = Path(args.files_from).read_text(encoding="utf-8")
        result = evaluate([line for line in text.splitlines() if line.strip()])
    elif args.repo and args.pr is not None:
        token = os.environ.get("GITHUB_TOKEN", "")
        try:
            if not token:
                raise ValueError("GITHUB_TOKEN is not set")
            paths, complete, expected, head = changed_files(args.repo, args.pr, _github_get(token))
            result = evaluate(
                paths,
                complete=complete,
                expected_count=expected,
                pull_request=args.pr,
                head_sha=head,
            )
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as error:
            result = failure(
                f"could not read the changed-file list: {type(error).__name__}",
                pull_request=args.pr,
            )
            exit_code = 1
    else:
        parser.error("give --repo and --pr, or --files-from, or --print-codeowners")

    sys.stdout.write(result.to_json() + "\n")
    _append(args.summary, summary_markdown(result))
    _append(
        args.github_output,
        f"eligible={'true' if result.eligible else 'false'}\nresult={result.to_json()}\n",
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
