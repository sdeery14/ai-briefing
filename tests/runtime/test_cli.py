"""The ``ai-briefing`` command exists, is installed, and describes itself."""

from __future__ import annotations

import subprocess
import sysconfig
from importlib.metadata import entry_points, version
from pathlib import Path

import pytest

from ai_briefing import __version__
from ai_briefing.runtime import cli


def installed_script() -> Path:
    scripts = Path(sysconfig.get_path("scripts"))
    matches = [p for p in scripts.iterdir() if p.stem == "ai-briefing"]
    assert matches, f"no ai-briefing script in {scripts}; run `uv sync --locked --group dev`"
    return matches[0]


def run_installed(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - a fixed command: the project's own entry point
        [str(installed_script()), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_the_console_script_is_registered_and_points_at_the_cli() -> None:
    (script,) = entry_points(group="console_scripts", name="ai-briefing")
    assert script.value == "ai_briefing.runtime.cli:main"
    assert script.load() is cli.main


def test_help_exits_zero_through_the_installed_entry_point() -> None:
    result = run_installed("--help")
    assert result.returncode == 0, result.stderr
    assert "usage: ai-briefing" in result.stdout
    assert result.stderr == ""


def test_version_exits_zero_through_the_installed_entry_point() -> None:
    result = run_installed("--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"ai-briefing {__version__}"


def test_the_reported_version_is_the_installed_package_version() -> None:
    assert __version__ == version("ai-briefing")


def test_a_bare_invocation_shows_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "usage: ai-briefing" in capsys.readouterr().out


def test_an_unknown_argument_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--no-such-option"])
    assert raised.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
