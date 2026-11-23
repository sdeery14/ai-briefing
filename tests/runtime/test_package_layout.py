"""The package has the modules RFC §3.3 names for M1, and importing them does nothing."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ai_briefing

# RFC v0.3 §3.3, less `feedback` and `evaluation`, which arrive with the issues that need them.
MODULES = ("domain", "sources", "stories", "editorial", "briefings", "llm", "storage", "runtime")

# Imports every module in a fresh interpreter with an audit hook that fails on any network
# call, subprocess, database connection, or file opened for writing. Reading the modules'
# own source files is how an import works and is allowed.
PROBE = """
import importlib, sys

FORBIDDEN = ("socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "sqlite3.",
             "urllib.", "http.", "ftplib.", "smtplib.", "webbrowser.")

def hook(event, args):
    if event.startswith(FORBIDDEN):
        raise RuntimeError("import performed I/O: " + event)
    if event == "open":
        mode = args[1]
        flags = args[2] or 0
        writing = isinstance(mode, str) and any(c in mode for c in "wax+")
        if writing or flags & 0x3:  # O_WRONLY or O_RDWR
            raise RuntimeError("import opened a file for writing: %r" % (args[0],))

names = sys.argv[1:]
sys.addaudithook(hook)
for name in names:
    importlib.import_module(name)
sys.stdout.write("imported %d" % len(names))
"""


def test_the_m1_module_packages_exist() -> None:
    root = Path(ai_briefing.__file__).parent
    present = {p.name for p in root.iterdir() if (p / "__init__.py").is_file()}
    assert set(MODULES) <= present
    assert present <= {*MODULES, "feedback", "evaluation", "prompts"}, (
        "a module outside RFC §3.3 was added"
    )


@pytest.mark.parametrize("name", MODULES)
def test_each_module_package_imports_and_says_what_it_owns(name: str) -> None:
    module = importlib.import_module(f"ai_briefing.{name}")
    assert module.__doc__, f"ai_briefing.{name} needs a docstring saying what it owns"


def test_importing_the_package_performs_no_io() -> None:
    names = ["ai_briefing", *(f"ai_briefing.{name}" for name in MODULES), "ai_briefing.runtime.cli"]
    result = subprocess.run(  # noqa: S603 - a fixed command: this interpreter and the probe above
        [sys.executable, "-c", PROBE, *names],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"imported {len(names)}"


def test_the_probe_does_catch_io() -> None:
    # Without this, a probe that never fails would make the test above meaningless.
    writer = "import tempfile\ntempfile.TemporaryFile().close()\n"
    result = subprocess.run(  # noqa: S603 - a fixed command: this interpreter and the probe above
        [sys.executable, "-c", PROBE.replace("for name in names:", writer + "for name in names:")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "opened a file for writing" in result.stderr
