"""Merge eligibility: every ADR-011 protected category is detected, and nothing else is."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import merge_eligibility as me

REPO_ROOT = Path(__file__).resolve().parents[2]

# One or more example paths per protected category. Every category in the policy must
# appear here; test_every_category_has_an_example enforces that.
PROTECTED_EXAMPLES: dict[str, list[str]] = {
    "decisions": [
        "docs/rfc/AI-Briefing-RFC-v0.3.md",
        "docs/adr/011-development-workflow-and-merge-authority.md",
        "docs/adr/README.md",
    ],
    "evaluation": [
        "src/ai_briefing/evaluation/metrics.py",
        "src/ai_briefing/evaluation/judges/groundedness.py",
        "evals/public_cases.jsonl",
        "tests/golden/briefing.json",
        "tests/briefings/golden/2026-11-19.json",
        "tests/recorded/assess_story.json",
        "tests/llm/recorded/screening/batch_1.json",
    ],
    "prompts-and-editorial-policy": [
        "src/ai_briefing/prompts/assess.md",
        "src/ai_briefing/editorial/policy/ceilings.py",
    ],
    "models-budget-sources": ["config/models.yaml", "config/sources.yaml"],
    "contracts-and-migrations": [
        "schemas/daily_briefing.v1.json",
        "migrations/versions/0001_initial.py",
    ],
    "workflows": [
        ".github/workflows/ci.yml",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
    ],
    "dependencies": ["pyproject.toml", "uv.lock"],
    "deployment": [
        "deploy/systemd/ai-briefing-collect.timer",
        "Dockerfile",
        "Dockerfile.arm64",
        "deploy/Dockerfile",
        ".dockerignore",
        "compose.yaml",
        "compose.override.yml",
        "docker-compose.yml",
        "docker/docker-compose.prod.yaml",
    ],
    "agent-workflow": [
        ".claude/skills/round/SKILL.md",
        ".claude/settings.json",
        "scripts/merge_eligibility.py",
        "scripts/offline_guard.py",
        "AGENTS.md",
        "CLAUDE.md",
        "CODEOWNERS",
    ],
}

UNPROTECTED_EXAMPLES = [
    "README.md",
    "SECURITY.md",
    "LICENSE",
    "docs/planning/milestones.md",
    "docs/operations/repository-safeguards.md",
    "docs/reviews/v0.3-open-questions.md",
    "src/ai_briefing/domain/models.py",
    "src/ai_briefing/sources/rss.py",
    "src/ai_briefing/editorial/assessment.py",
    "src/ai_briefing/editorial/policy.md.bak/notes.txt",
    "src/ai_briefing/briefings/render.py",
    "tests/conftest.py",
    "tests/tooling/test_merge_eligibility.py",
    "tests/sources/fixtures/feed.xml",
    "tests/golden_rules_test.py",
    "tests/recorded.py",
    "docs/adr-notes.md",
    "configuration/notes.md",
    "my-scripts/tool.py",
    "pyproject.toml.example",
    "docs/compose-guide.md",
]


def test_every_category_has_an_example() -> None:
    assert set(PROTECTED_EXAMPLES) == {category for category, _ in me.PROTECTED}


@pytest.mark.parametrize(
    ("category", "path"),
    [(category, path) for category, paths in PROTECTED_EXAMPLES.items() for path in paths],
)
def test_protected_path_is_detected(category: str, path: str) -> None:
    match = me.match_path(path)
    assert match is not None, f"{path} should be protected"
    assert match.category == category
    result = me.evaluate([path])
    assert result.eligible is False
    assert result.categories == (category,)


@pytest.mark.parametrize("path", UNPROTECTED_EXAMPLES)
def test_unprotected_path_is_eligible(path: str) -> None:
    assert me.match_path(path) is None
    result = me.evaluate([path])
    assert result.eligible is True
    assert result.protected == ()
    assert result.reasons == ()


def test_every_pattern_is_exercised_by_an_example() -> None:
    hit = {
        match.pattern
        for paths in PROTECTED_EXAMPLES.values()
        for path in paths
        if (match := me.match_path(path)) is not None
    }
    declared = {pattern for _, patterns in me.PROTECTED for pattern in patterns}
    assert hit == declared


def test_one_protected_file_makes_a_mixed_change_ineligible() -> None:
    result = me.evaluate(["README.md", "src/ai_briefing/domain/models.py", "uv.lock"])
    assert result.eligible is False
    assert [m.path for m in result.protected] == ["uv.lock"]
    assert result.changed_file_count == 3


def test_several_categories_are_all_reported() -> None:
    result = me.evaluate(["AGENTS.md", "config/models.yaml", "docs/adr/001-x.md"])
    assert result.categories == ("agent-workflow", "decisions", "models-budget-sources")


@pytest.mark.parametrize(
    "path",
    ["agents.md", "CLAUDE.MD", "PyProject.toml", ".GitHub/workflows/ci.yml", "dockerfile"],
)
def test_matching_ignores_case(path: str) -> None:
    assert me.match_path(path) is not None


@pytest.mark.parametrize("path", ["./AGENTS.md", "/AGENTS.md", "docs\\adr\\001-x.md"])
def test_paths_are_normalised_before_matching(path: str) -> None:
    assert me.match_path(path) is not None


def test_single_star_does_not_cross_directories() -> None:
    assert me.pattern_to_regex("a/*.md").fullmatch("a/b.md")
    assert not me.pattern_to_regex("a/*.md").fullmatch("a/b/c.md")
    assert me.pattern_to_regex("a/**").fullmatch("a/b/c.md")
    assert not me.pattern_to_regex("a/**").fullmatch("ab/c.md")


def test_empty_file_list_is_not_eligible() -> None:
    result = me.evaluate([])
    assert result.eligible is False
    assert result.reasons == ("no changed files were supplied",)


def test_incomplete_file_list_is_not_eligible() -> None:
    result = me.evaluate(["README.md"], complete=False, expected_count=5000)
    assert result.eligible is False
    assert result.complete is False
    assert "could not be confirmed complete" in result.reasons[0]


def test_result_is_single_line_json_with_the_expected_fields() -> None:
    result = me.evaluate(["AGENTS.md"], pull_request=7, head_sha="abc123")
    text = result.to_json()
    assert "\n" not in text
    data = json.loads(text)
    assert data["schema"] == "merge_eligibility.v1"
    assert data["phase"] == "report-only"
    assert data["eligible"] is False
    assert data["pull_request"] == 7
    assert data["head_sha"] == "abc123"
    assert data["protected"] == [
        {"path": "AGENTS.md", "category": "agent-workflow", "pattern": "AGENTS.md"}
    ]


def test_hostile_file_name_cannot_break_out_of_the_outputs() -> None:
    hostile = "scripts/x`\n| injected | row |\neligible=true\n<script>.py"
    result = me.evaluate([hostile])
    assert result.eligible is False
    assert "\n" not in result.to_json()
    summary = me.summary_markdown(result)
    row = next(line for line in summary.splitlines() if line.startswith("| `scripts/x"))
    assert "<script>" not in summary
    assert "eligible=true" not in [line.strip() for line in summary.splitlines()]
    assert row.count("|") == 5


def test_summary_states_that_the_report_is_informational() -> None:
    blocked = me.summary_markdown(me.evaluate(["uv.lock"]))
    assert "Not eligible for automatic merge" in blocked
    assert "informational and blocks nothing" in blocked
    assert "this workflow never merges anything" in blocked
    assert "`uv.lock`" in blocked
    clear = me.summary_markdown(me.evaluate(["README.md"]))
    assert "**Eligible:**" in clear


# --- GitHub API retrieval, with a fake transport (no network) ---------------------------


def fake_api(files: list[dict[str, Any]], *, reported: int | None = None) -> me.Fetch:
    def get(url: str) -> Any:
        if url.endswith("/pulls/12"):
            count = len(files) if reported is None else reported
            return {"changed_files": count, "head": {"sha": "deadbeef"}}
        page = int(re.search(r"[?&]page=(\d+)", url).group(1))  # type: ignore[union-attr]
        start = (page - 1) * me.PAGE_SIZE
        return files[start : start + me.PAGE_SIZE]

    return get


def test_changed_files_follows_pagination() -> None:
    files = [{"filename": f"src/ai_briefing/domain/m{i}.py"} for i in range(250)]
    paths, complete, expected, head = me.changed_files("o/r", 12, fake_api(files))
    assert len(paths) == 250
    assert complete is True
    assert expected == 250
    assert head == "deadbeef"


def test_a_protected_file_on_a_later_page_is_found() -> None:
    files = [{"filename": f"docs/planning/n{i}.md"} for i in range(230)]
    files.append({"filename": ".github/workflows/ci.yml"})
    paths, complete, expected, _ = me.changed_files("o/r", 12, fake_api(files))
    result = me.evaluate(paths, complete=complete, expected_count=expected)
    assert result.eligible is False
    assert result.categories == ("workflows",)


def test_renaming_a_file_out_of_a_protected_path_is_detected() -> None:
    files = [{"filename": "docs/notes/old-policy.py", "previous_filename": "config/models.yaml"}]
    paths, complete, expected, _ = me.changed_files("o/r", 12, fake_api(files))
    result = me.evaluate(paths, complete=complete, expected_count=expected)
    assert result.eligible is False
    assert result.categories == ("models-budget-sources",)
    assert result.changed_file_count == 1


def test_a_short_file_list_is_reported_incomplete() -> None:
    files = [{"filename": "README.md"}]
    paths, complete, expected, _ = me.changed_files("o/r", 12, fake_api(files, reported=4))
    assert complete is False
    assert me.evaluate(paths, complete=complete, expected_count=expected).eligible is False


def test_a_list_at_the_api_limit_is_reported_incomplete() -> None:
    files = [{"filename": f"docs/planning/n{i}.md"} for i in range(me.API_FILE_LIMIT)]
    _, complete, _, _ = me.changed_files("o/r", 12, fake_api(files))
    assert complete is False


@pytest.mark.parametrize("repo", ["", "owner", "a/b/c", "owner/name?x=1", "../etc/passwd"])
def test_malformed_repository_names_are_refused(repo: str) -> None:
    with pytest.raises(ValueError, match="owner/name"):
        me.changed_files(repo, 12, fake_api([]))


def test_api_client_refuses_urls_outside_github() -> None:
    get = me._github_get("not-a-real-token")
    with pytest.raises(ValueError, match="outside the GitHub API"):
        get("https://example.com/repos/o/r/pulls/1")


# --- Command line ------------------------------------------------------------------------


def test_cli_reads_a_file_list_and_writes_all_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = tmp_path / "changed.txt"
    listing.write_text("README.md\nconfig/sources.yaml\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    code = me.main(
        ["--files-from", str(listing), "--summary", str(summary), "--github-output", str(output)]
    )
    assert code == 0  # report only: an ineligible result is not a failure
    printed = json.loads(capsys.readouterr().out)
    assert printed["eligible"] is False
    assert "Not eligible" in summary.read_text(encoding="utf-8")
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "eligible=false"
    assert lines[1].startswith("result={")
    assert len(lines) == 2


def test_cli_without_a_token_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code = me.main(["--repo", "o/r", "--pr", "12"])
    assert code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["eligible"] is False
    assert printed["complete"] is False


# --- CODEOWNERS stays in step with the policy -------------------------------------------


def test_codeowners_file_matches_the_policy() -> None:
    on_disk = (REPO_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert on_disk.replace("\r\n", "\n") == me.codeowners_text()


def test_codeowners_assigns_every_rule_to_the_owner() -> None:
    rules = [
        line.split()
        for line in me.codeowners_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert len(rules) == sum(len(patterns) for _, patterns in me.OWNER_ONLY)
    assert all(owners == ["@sdeery14"] for _, *owners in rules)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("docs/rfc/**", "/docs/rfc/"),
        ("tests/**/golden/**", "/tests/**/golden/"),
        ("pyproject.toml", "/pyproject.toml"),
        ("**/Dockerfile*", "Dockerfile*"),
        ("**/compose*.yaml", "compose*.yaml"),
    ],
)
def test_codeowners_pattern_spelling(pattern: str, expected: str) -> None:
    assert me.codeowners_pattern(pattern) == expected


def test_policy_matches_the_table_in_agents_md() -> None:
    """Every path written in the AGENTS.md protected-path table is covered by the policy."""
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    table = text.split("| Category | Paths |", 1)[1].split("\n\n", 1)[0]
    listed = re.findall(r"`([^`]+)`", table)
    assert listed, "no paths found in the AGENTS.md table"
    for entry in listed:
        probe = entry.replace("**", "example/file.txt")
        if entry == "tests/":
            probe = "tests/golden/example.json"
        assert me.match_path(probe) is not None, f"{entry} in AGENTS.md is not covered"


@pytest.mark.parametrize(
    "path",
    ["scripts/a\nb.py", "docs/adr/x\r\ny.md", "config/\n", ".github/workflows/a\tb.yml"],
)
def test_control_characters_in_a_file_name_do_not_evade_matching(path: str) -> None:
    assert me.match_path(path) is not None
    assert me.evaluate([path]).eligible is False


# --- ADR-013: owner-only paths ------------------------------------------------------------


def test_every_owner_only_pattern_is_also_a_protected_pattern() -> None:
    protected = {p for _, patterns in me.PROTECTED for p in patterns}
    assert protected >= me.OWNER_ONLY_PATTERNS
    # What the round may merge although it is protected: the lock file, contracts,
    # prompts and policy, and golden and recorded test files.
    assert protected - me.OWNER_ONLY_PATTERNS == {
        "uv.lock",
        "schemas/**",
        "src/ai_briefing/prompts/**",
        "src/ai_briefing/editorial/policy/**",
        "tests/**/golden/**",
        "tests/**/recorded/**",
    }


@pytest.mark.parametrize(
    "path",
    [
        "docs/adr/013-agent-merge.md",
        "docs/rfc/AI-Briefing-RFC-v0.3.md",
        "pyproject.toml",
        "migrations/versions/0001_first.py",
        "migrations/env.py",
        "config/sources.yaml",
        "config/models.yaml",
        ".github/workflows/ci.yml",
        ".github/CODEOWNERS",
        ".claude/skills/round/config.json",
        ".claude/skills/round/SKILL.md",
        "scripts/round_outcome.py",
        "scripts/merge_eligibility.py",
        "AGENTS.md",
        "agents.MD",
        "CLAUDE.md",
        "deploy/compose.yml",
        "Dockerfile",
        "src/ai_briefing/evaluation/metrics.py",
        "evals/cases/one.json",
    ],
)
def test_an_owner_only_path_can_never_be_merged_by_the_round(path: str) -> None:
    result = me.evaluate([path, "src/ai_briefing/domain/records.py"])
    assert [m.path for m in result.owner_only] == [path]
    assert result.agent_may_merge is False


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "schemas/daily_briefing.v1.schema.json",
        "src/ai_briefing/prompts/screening.md",
        "src/ai_briefing/editorial/policy/rules.py",
        "tests/llm/recorded/screening.json",
        "tests/briefings/golden/day.md",
    ],
)
def test_other_protected_paths_are_reported_but_do_not_prevent_the_round_merging(path: str) -> None:
    result = me.evaluate([path])
    assert [m.path for m in result.protected] == [path]
    assert result.owner_only == ()
    assert result.eligible is False  # still reported as touching a protected path
    assert result.agent_may_merge is True


def test_unprotected_code_may_be_merged_by_the_round() -> None:
    result = me.evaluate(["src/ai_briefing/sources/fetcher.py", "tests/sources/test_fetcher.py"])
    assert result.eligible is True
    assert result.agent_may_merge is True


def test_an_uncertain_file_list_can_never_be_merged_by_the_round() -> None:
    assert me.evaluate([]).agent_may_merge is False
    assert me.evaluate(["src/x.py"], complete=False).agent_may_merge is False
    assert me.evaluate(["src/x.py"], expected_count=0).agent_may_merge is False
    assert me.failure("could not read").agent_may_merge is False


def test_the_summary_marks_owner_only_paths() -> None:
    summary = me.summary_markdown(me.evaluate(["config/sources.yaml", "uv.lock"]))
    assert "**Owner-only:** 1 changed file(s)" in summary
    assert "| `config/sources.yaml` | models-budget-sources | `config/**` | yes |" in summary
    assert "| `uv.lock` | dependencies | `uv.lock` | no |" in summary


@pytest.mark.parametrize(
    ("path", "first_protected_category"),
    [
        ("src/ai_briefing/prompts/Dockerfile", "prompts-and-editorial-policy"),
        ("tests/golden/Dockerfile", "evaluation"),
        ("tests/llm/recorded/compose.yml", "evaluation"),
        ("schemas/docker-compose.yaml", "contracts-and-migrations"),
        ("src/ai_briefing/editorial/policy/Dockerfile.dev", "prompts-and-editorial-policy"),
    ],
)
def test_a_path_under_two_protected_patterns_is_owner_only_if_either_is(
    path: str, first_protected_category: str
) -> None:
    # The first protected pattern a path matches may be one the round can merge. The
    # owner-only check must not stop there.
    result = me.evaluate([path])
    assert [m.category for m in result.protected] == [first_protected_category]
    assert [(m.path, m.category) for m in result.owner_only] == [(path, "deployment")]
    assert first_protected_category not in me.PROJECTBUDGET_EXCEPTIONS
    assert result.agent_may_merge is False
    row = next(line for line in me.summary_markdown(result).splitlines() if path in line)
    assert row.endswith("| yes |")


def test_every_path_is_checked_against_every_owner_only_pattern() -> None:
    for _, patterns in me.OWNER_ONLY:
        for pattern in patterns:
            example = pattern.replace("**/", "nested/dir/").replace("/**", "/x/y.txt")
            example = example.replace("*", "")
            assert me.match_owner_only(example) is not None, pattern
            assert me.evaluate([example]).agent_may_merge is False, pattern
    assert me.match_owner_only("src/ai_briefing/sources/fetcher.py") is None
    assert me.match_owner_only("uv.lock") is None


def test_the_projectbudget_exceptions_are_carried_over() -> None:
    # ProjectBudget's round never arms a merge on decision records, workflows, migrations
    # or dependency changes. The same four are owner-only here.
    owner_only = dict(me.OWNER_ONLY)
    assert me.PROJECTBUDGET_EXCEPTIONS == ("decisions", "workflows", "migrations", "dependencies")
    assert "docs/adr/**" in owner_only["decisions"]
    assert owner_only["workflows"] == (".github/**",)
    assert owner_only["migrations"] == ("migrations/**",)
    assert owner_only["dependencies"] == ("pyproject.toml",)
    for path in ("docs/adr/x.md", ".github/workflows/ci.yml", "migrations/x.py", "pyproject.toml"):
        assert me.evaluate([path]).agent_may_merge is False, path
