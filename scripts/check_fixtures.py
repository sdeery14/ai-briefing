"""Check that every fixture file is listed in the fixtures licence manifest (ADR-010).

    uv run python scripts/check_fixtures.py

The public repository holds no third-party article text. Fixtures, recorded model
responses and evaluation cases are synthetic, written by the owner, or under a licence
that permits redistribution, and the manifest says which, file by file. This check fails
when a fixture directory holds a file the manifest does not list, so a new fixture cannot
arrive without someone stating where it came from.

A fixture file is any file under ``tests/`` or ``evals/`` that is not Python source. The
manifest is ``tests/FIXTURES.toml``:

    [[fixtures]]
    origin = "synthetic"          # synthetic, owner or licensed
    licence = "Apache-2.0"
    note = "What these are and how they were made."
    source = "https://..."        # required when origin is "licensed"
    files = ["tests/pipeline/recorded/01_screening.json"]

The check reads file names only. It never opens a fixture.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "tests/FIXTURES.toml"
ROOTS = ("tests", "evals")
ORIGINS = ("synthetic", "owner", "licensed")
SKIPPED_DIRECTORIES = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
CODE_SUFFIXES = frozenset({".py", ".pyc"})


def fixture_files(root: Path) -> list[str]:
    """Every fixture file under the fixture roots, as repository-relative POSIX paths."""
    found = []
    for name in ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(root)
            if not path.is_file() or SKIPPED_DIRECTORIES.intersection(relative.parts):
                continue
            if path.suffix in CODE_SUFFIXES or relative.as_posix() == MANIFEST:
                continue
            found.append(relative.as_posix())
    return sorted(found)


def _listed(entry: object, number: int, problems: list[str]) -> list[str]:
    """The files one manifest entry lists, after checking the entry says what it must."""
    where = f"entry {number}"
    if not isinstance(entry, dict):
        problems.append(f"{where}: not a table")
        return []
    origin = entry.get("origin")
    if origin not in ORIGINS:
        problems.append(f"{where}: origin must be one of {', '.join(ORIGINS)}")
    for field in ("licence", "note"):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{where}: {field} is missing")
    if origin == "licensed":
        source = entry.get("source")
        if not isinstance(source, str) or not source.strip():
            problems.append(f"{where}: a licensed fixture says where it came from (source)")
    files = entry.get("files")
    if not isinstance(files, list) or not files:
        problems.append(f"{where}: files is missing or empty")
        return []
    listed = []
    for item in files:
        path = PurePosixPath(item) if isinstance(item, str) else None
        if (
            path is None
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in str(item)
            or path.parts[:1] not in [(root,) for root in ROOTS]
            or path.as_posix() != item
        ):
            problems.append(f"{where}: not a path under {' or '.join(ROOTS)}: {item!r}")
            continue
        listed.append(item)
    return listed


def check(root: Path = REPO_ROOT) -> list[str]:
    """Everything wrong with the manifest and the fixture directories. Empty means sound."""
    manifest = root / MANIFEST
    present = fixture_files(root)
    if not manifest.is_file():
        return [f"{MANIFEST} does not exist"] if present else []
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        return [f"{MANIFEST} cannot be read: {error}"]
    entries = data.get("fixtures", [])
    if not isinstance(entries, list):
        return [f"{MANIFEST}: fixtures must be a list of tables"]
    problems: list[str] = []
    listed: list[str] = []
    for number, entry in enumerate(entries, start=1):
        listed += _listed(entry, number, problems)
    seen: set[str] = set()
    for path in listed:
        if path in seen:
            problems.append(f"listed more than once: {path}")
        seen.add(path)
    problems += [f"not listed in {MANIFEST}: {path}" for path in present if path not in seen]
    here = set(present)
    problems += [f"listed but not present: {path}" for path in sorted(seen - here)]
    return problems


def main() -> int:
    problems = check()
    if problems:
        sys.stderr.write("fixtures licence manifest check failed:\n")
        for problem in problems:
            sys.stderr.write(f"  {problem}\n")
        sys.stderr.write(
            f"Every fixture file is listed in {MANIFEST} with its origin and licence "
            "(ADR-010). No third-party article text belongs in the repository.\n"
        )
        return 1
    sys.stdout.write(f"fixtures: {len(fixture_files(REPO_ROOT))} files, all listed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
