"""The ``domain`` module is pure: it imports no I/O library, directly or through another
project module (RFC §3.3, AGENTS.md).

The check is an allowlist over the import statements in every file under ``domain``. The
only project package ``domain`` may import is itself, so nothing can reach an I/O library
by way of another module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ai_briefing.domain

DOMAIN_DIR = Path(ai_briefing.domain.__file__).parent

# Pure standard-library modules and the one validation library. Adding a name here is a
# decision: it must do no database, network, filesystem or model-provider work.
ALLOWED = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "itertools",
        "re",
        "types",
        "typing",
        "unicodedata",
        "annotated_types",
        "pydantic",
        "typing_extensions",
        "ai_briefing.domain",
    }
)


def is_allowed(module: str) -> bool:
    return any(module == name or module.startswith(name + ".") for name in ALLOWED)


def imported_modules(source: str, package: str) -> list[str]:
    """Every module a piece of source imports, with relative imports made absolute."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                found.append(f"{base}.{node.module}" if node.module else base)
            elif node.module:
                found.append(node.module)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name | ast.Attribute)
            and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
            in {"__import__", "import_module"}
        ):
            found.append("<dynamic import>")
    return found


def violations(source: str, package: str = "ai_briefing.domain") -> list[str]:
    return sorted({m for m in imported_modules(source, package) if not is_allowed(m)})


def domain_files() -> list[Path]:
    files = sorted(DOMAIN_DIR.rglob("*.py"))
    assert len(files) >= 3, "expected the domain package's modules"
    return files


@pytest.mark.parametrize("path", domain_files(), ids=lambda p: p.relative_to(DOMAIN_DIR).as_posix())
def test_a_domain_file_imports_only_pure_modules(path: Path) -> None:
    relative = path.relative_to(DOMAIN_DIR).with_suffix("")
    package = ".".join(["ai_briefing", "domain", *relative.parts[:-1]])
    assert violations(path.read_text(encoding="utf-8"), package) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import sqlite3", ["sqlite3"]),
        ("import os.path", ["os.path"]),
        ("from pathlib import Path", ["pathlib"]),
        ("import httpx, json", ["httpx", "json"]),
        ("from urllib.request import urlopen", ["urllib.request"]),
        ("import anthropic", ["anthropic"]),
        ("from sqlalchemy.orm import Session", ["sqlalchemy.orm"]),
        ("from ai_briefing.storage import repositories", ["ai_briefing.storage"]),
        ("from ai_briefing import storage", ["ai_briefing"]),
        ("from .. import storage", ["ai_briefing"]),
        ("from ..llm import client", ["ai_briefing.llm"]),
        ("import importlib\nimportlib.import_module('socket')", ["<dynamic import>", "importlib"]),
        ("__import__('socket')", ["<dynamic import>"]),
        ("def f():\n    import socket", ["socket"]),
    ],
)
def test_the_check_catches_io_and_other_project_modules(source: str, expected: list[str]) -> None:
    assert violations(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "from __future__ import annotations",
        "from datetime import UTC, datetime",
        "from pydantic import BaseModel",
        "from ai_briefing.domain.enums import SourceMode",
        "from . import enums",
        "from .enums import SourceMode",
    ],
)
def test_the_check_allows_pure_imports(source: str) -> None:
    assert violations(source) == []
