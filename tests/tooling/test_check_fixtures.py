"""The fixtures licence manifest check (ADR-010, M1 issue 1.12)."""

from __future__ import annotations

from pathlib import Path

import pytest

import check_fixtures

ENTRY = """
[[fixtures]]
origin = "{origin}"
licence = "Apache-2.0"
note = "Invented for the tests."
files = [{files}]
"""


def tree(root: Path, files: list[str], manifest: str | None) -> Path:
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    if manifest is not None:
        (root / "tests").mkdir(exist_ok=True)
        (root / check_fixtures.MANIFEST).write_text(manifest, encoding="utf-8")
    return root


def entry(*files: str, origin: str = "synthetic") -> str:
    return ENTRY.format(origin=origin, files=", ".join(f'"{f}"' for f in files))


def test_this_repository_passes_its_own_check() -> None:
    assert check_fixtures.check() == []
    assert check_fixtures.main() == 0
    assert len(check_fixtures.fixture_files(check_fixtures.REPO_ROOT)) > 50


def test_a_fixture_file_the_manifest_does_not_list_fails_the_check(tmp_path: Path) -> None:
    listed = "tests/pipeline/recorded/01.json"
    root = tree(tmp_path, [listed, "tests/pipeline/recorded/02.json"], entry(listed))
    assert check_fixtures.check(root) == [
        "not listed in tests/FIXTURES.toml: tests/pipeline/recorded/02.json"
    ]
    # Listed, it passes.
    (root / check_fixtures.MANIFEST).write_text(
        entry(listed, "tests/pipeline/recorded/02.json"), encoding="utf-8"
    )
    assert check_fixtures.check(root) == []


def test_the_command_exits_nonzero_and_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tree(tmp_path, ["tests/x/article.txt"], entry("tests/x/other.txt"))
    monkeypatch.setattr(check_fixtures, "REPO_ROOT", root)
    monkeypatch.setattr(check_fixtures.check, "__defaults__", (root,))
    assert check_fixtures.main() == 1
    err = capsys.readouterr().err
    assert "not listed in tests/FIXTURES.toml: tests/x/article.txt" in err
    assert "listed but not present: tests/x/other.txt" in err
    assert "No third-party article text" in err


def test_ci_runs_the_check() -> None:
    workflow = (check_fixtures.REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv run --no-sync python scripts/check_fixtures.py" in workflow


def test_what_counts_as_a_fixture_file(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        [
            "tests/a/data.json",
            "tests/a/page.html",
            "tests/a/README.md",
            "tests/a/no_extension",
            "tests/a/test_code.py",
            "tests/a/__pycache__/test_code.cpython-312.pyc",
            "tests/.pytest_cache/v/cache/lastfailed",
            "evals/cases/case.json",
            "src/package/data.json",
            "docs/note.md",
        ],
        "",
    )
    assert check_fixtures.fixture_files(root) == [
        "evals/cases/case.json",
        "tests/a/README.md",
        "tests/a/data.json",
        "tests/a/no_extension",
        "tests/a/page.html",
    ]


def test_with_no_fixtures_no_manifest_is_needed_and_with_some_it_is(tmp_path: Path) -> None:
    assert check_fixtures.check(tree(tmp_path / "empty", ["tests/test_x.py"], None)) == []
    root = tree(tmp_path / "some", ["tests/a.json"], None)
    assert check_fixtures.check(root) == ["tests/FIXTURES.toml does not exist"]


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        ("not toml [", "cannot be read"),
        ("fixtures = 3", "must be a list of tables"),
        ("fixtures = [3]", "entry 1: not a table"),
        (entry("tests/a.json", origin="found-online"), "origin must be one of"),
        (entry("tests/a.json").replace('licence = "Apache-2.0"', 'licence = " "'), "licence"),
        (entry("tests/a.json").replace('note = "Invented for the tests."', ""), "note is missing"),
        (entry("tests/a.json", origin="licensed"), "says where it came from"),
        (entry("tests/a.json").replace('files = ["tests/a.json"]', "files = []"), "files"),
        (entry("tests/a.json", "tests/a.json"), "listed more than once: tests/a.json"),
        (entry("tests/a.json", "../outside.json"), "not a path under tests or evals"),
        (entry("tests/a.json", "/etc/passwd"), "not a path under tests or evals"),
        (entry("tests/a.json", "src/a.json"), "not a path under tests or evals"),
        (entry("tests/a.json", "tests//a.json"), "not a path under tests or evals"),
        (entry("tests/a.json", "tests/b.json"), "listed but not present: tests/b.json"),
    ],
)
def test_a_manifest_that_is_wrong_fails_the_check(
    tmp_path: Path, manifest: str, problem: str
) -> None:
    problems = check_fixtures.check(tree(tmp_path, ["tests/a.json"], manifest))
    assert any(problem in p for p in problems), problems


def test_a_licensed_fixture_with_its_source_passes(tmp_path: Path) -> None:
    manifest = entry("tests/a.json", origin="licensed").replace(
        'origin = "licensed"', 'origin = "licensed"\nsource = "https://example.org/data"'
    )
    assert check_fixtures.check(tree(tmp_path, ["tests/a.json"], manifest)) == []


def test_the_check_never_opens_a_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree(tmp_path, ["tests/a.json"], entry("tests/a.json"))
    real = Path.read_text
    opened: list[str] = []

    def reading(self: Path, *args: object, **kwargs: object) -> str:
        opened.append(self.name)
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", reading)
    assert check_fixtures.check(root) == []
    assert opened == ["FIXTURES.toml"]
