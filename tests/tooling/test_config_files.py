"""config/sources.yaml and config/models.yaml obey ADR-010, ADR-009 and the owner's approvals.

These are checks on committed configuration, not on application code. They pin the
operating modes the owner approved on 2026-11-21, so that enabling a source, loosening a
mode or widening what may be sent to the model fails a test and cannot ride in unnoticed.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_PATH = REPO_ROOT / "config" / "sources.yaml"
MODELS_PATH = REPO_ROOT / "config" / "models.yaml"

# The owner's decision of 2026-11-21. Changing this table is changing that decision.
APPROVED_MODES = {
    "arxiv-cs-cl": "feed_summary",
    "google-deepmind-blog": "metadata_only",
    "google-research-blog": "metadata_only",
    "hugging-face-blog": "metadata_only",
    "simon-willison-entries": "metadata_only",
    "hacker-news": "metadata_only",
    "openai-news": "disabled",
    "mlflow-releases": "disabled",
    "anthropic-sdk-python-releases": "disabled",
}
MODES = {"feed_summary", "metadata_only", "disabled"}
KINDS = {"rss", "atom", "hn_api"}  # the adapters planned for M1; no others are approved
ROLES = {"primary", "vendor", "independent", "community", "aggregator"}
ACCESS = {"explicit", "interpretation", "uncertain"}
SUBMISSION = {"none", "title_and_summary"}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


SOURCES: list[dict[str, Any]] = load(SOURCES_PATH)["sources"]
MODELS = load(MODELS_PATH)
BY_ID = {source["id"]: source for source in SOURCES}
each_source = pytest.mark.parametrize("source", SOURCES, ids=[s["id"] for s in SOURCES])


# --- Sources -------------------------------------------------------------------------------


def test_the_catalogue_is_exactly_the_approved_selection_in_the_approved_modes() -> None:
    assert load(SOURCES_PATH)["schema"] == "sources.v1"
    assert len(SOURCES) == len(BY_ID), "source ids must be unique"
    assert {s["id"]: s["mode"] for s in SOURCES} == APPROVED_MODES


@each_source
def test_every_source_has_a_complete_record(source: dict[str, Any]) -> None:
    for key in (
        "id",
        "name",
        "kind",
        "url",
        "role",
        "enabled",
        "mode",
        "polling_interval_minutes",
        "rate_limit",
        "store",
        "model_submission",
        "retention_days",
        "excerpts_allowed",
        "attribution",
        "terms",
    ):
        assert key in source, f"{source.get('id')}: missing {key}"
    assert source["mode"] in MODES
    assert source["kind"] in KINDS
    assert source["role"] in ROLES
    assert source["model_submission"] in SUBMISSION
    assert isinstance(source["enabled"], bool)
    assert source["url"].startswith("https://")
    assert source["polling_interval_minutes"] >= 60
    assert source["rate_limit"]["max_connections"] == 1
    assert source["rate_limit"]["min_seconds_between_requests"] >= 1
    assert set(source["store"]) == {"metadata", "feed_summary", "body"}


@each_source
def test_every_terms_record_is_reviewed_approved_and_states_its_uncertainty(
    source: dict[str, Any],
) -> None:
    terms = source["terms"]
    assert isinstance(terms["reviewed_on"], datetime.date)
    assert isinstance(terms["approved_by_owner_on"], datetime.date)
    assert terms["approved_by_owner_on"] >= terms["reviewed_on"]
    assert terms["automated_access"] in ACCESS
    assert terms["urls"], "a terms record needs the pages that were read"
    assert all(url.startswith("https://") for url in terms["urls"])
    assert isinstance(terms["restrictions"], list)
    assert terms["restrictions"]
    assert isinstance(terms["uncertainties"], list)
    assert terms["uncertainties"], "say what remains uncertain, even if little"


@each_source
def test_enabled_and_mode_agree(source: dict[str, Any]) -> None:
    assert source["enabled"] is (source["mode"] != "disabled")


@each_source
def test_a_source_with_uncertain_automated_access_is_disabled(source: dict[str, Any]) -> None:
    if source["terms"]["automated_access"] == "uncertain":
        assert source["enabled"] is False
        assert source["mode"] == "disabled"
    if source["enabled"]:
        assert source["terms"]["automated_access"] in {"explicit", "interpretation"}


@each_source
def test_no_source_fetches_or_stores_article_bodies(source: dict[str, Any]) -> None:
    assert source["store"]["body"] is False
    assert "fetch_body" not in source or source["fetch_body"] is False
    assert source["mode"] != "body_enabled"


@each_source
def test_a_disabled_source_stores_and_submits_nothing(source: dict[str, Any]) -> None:
    if source["mode"] != "disabled":
        return
    assert source["store"] == {"metadata": False, "feed_summary": False, "body": False}
    assert source["model_submission"] == "none"
    assert source["excerpts_allowed"] is False


@each_source
def test_a_metadata_only_source_keeps_no_summary_and_submits_nothing(
    source: dict[str, Any],
) -> None:
    if source["mode"] != "metadata_only":
        return
    assert source["store"] == {"metadata": True, "feed_summary": False, "body": False}
    assert source["retention_days"]["feed_summary"] == 0
    assert source["excerpts_allowed"] is False
    # Access, storage and model submission are separate permissions. Where the right to
    # submit is unresolved, nothing is submitted, not even titles.
    assert source["model_submission"] == "none"


def test_only_arxiv_may_be_sent_to_the_model_and_on_an_explicit_basis() -> None:
    submitting = [s["id"] for s in SOURCES if s["model_submission"] != "none"]
    assert submitting == ["arxiv-cs-cl"]
    arxiv = BY_ID["arxiv-cs-cl"]
    assert arxiv["terms"]["automated_access"] == "explicit"
    assert arxiv["store"] == {"metadata": True, "feed_summary": True, "body": False}
    assert arxiv["url"] == "https://rss.arxiv.org/rss/cs.CL"


def test_arxiv_respects_its_stated_rate_limit() -> None:
    arxiv = BY_ID["arxiv-cs-cl"]
    assert arxiv["rate_limit"]["min_seconds_between_requests"] >= 3
    assert arxiv["rate_limit"]["max_connections"] == 1
    assert arxiv["polling_interval_minutes"] >= 1440


def test_simon_willison_uses_the_long_form_entries_feed() -> None:
    assert BY_ID["simon-willison-entries"]["url"] == "https://simonwillison.net/atom/entries/"


def test_hacker_news_uses_the_official_api_and_stores_no_usernames_or_comments() -> None:
    hn = BY_ID["hacker-news"]
    assert hn["kind"] == "hn_api"
    assert hn["url"] == "https://hacker-news.firebaseio.com/v0/"
    assert "by" not in hn["stored_fields"]
    assert "text" not in hn["stored_fields"]
    assert "kids" not in hn["stored_fields"]


def test_the_github_sources_are_disabled_and_no_new_adapter_is_introduced() -> None:
    for source_id in ("mlflow-releases", "anthropic-sdk-python-releases"):
        assert BY_ID[source_id]["enabled"] is False
    assert {s["kind"] for s in SOURCES} <= KINDS


# --- Models --------------------------------------------------------------------------------


def test_one_provider_and_the_two_approved_models() -> None:
    assert MODELS["schema"] == "models.v1"
    assert MODELS["provider"]["name"] == "anthropic"
    assert set(MODELS["models"]) == {"claude-haiku-5-5", "claude-sonnet-5-5"}
    assert MODELS["models"]["claude-haiku-5-5"]["tier"] == "inexpensive"
    assert MODELS["models"]["claude-sonnet-5-5"]["tier"] == "capable"


def test_prices_match_the_table_verified_in_the_rfc() -> None:
    haiku = MODELS["models"]["claude-haiku-5-5"]
    sonnet = MODELS["models"]["claude-sonnet-5-5"]
    assert haiku["prices"]["standard"] == {
        "input": 0.10,
        "output": 0.50,
        "cache_read": 0.01,
        "cache_write_5m": 0.125,
    }
    assert haiku["prices"]["long_prompt"] == {
        "input": 0.50,
        "output": 2.50,
        "cache_read": 0.05,
        "cache_write_5m": 0.625,
    }
    assert haiku["long_prompt_threshold_tokens"] == 100_000
    assert sonnet["prices"]["standard"] == {
        "input": 2.00,
        "output": 10.00,
        "cache_read": 0.10,
        "cache_write_5m": 2.50,
    }
    assert isinstance(MODELS["price_table"]["verified_on"], datetime.date)
    assert all(url.startswith("https://") for url in MODELS["price_table"]["sources"])


def test_the_rfc_states_the_same_prices() -> None:
    rfc = (REPO_ROOT / "docs" / "rfc" / "AI-Briefing-RFC-v0.3.md").read_text(encoding="utf-8")
    for fragment in (
        "$0.10 (prompts up to 100,000 tokens); $0.50 above",
        "$0.50 (prompts up to 100,000 tokens); $2.50 above",
        "| $2.00 |",
        "| $10.00 |",
    ):
        assert fragment in rfc, fragment


def test_every_task_uses_a_configured_model_and_sets_effort_explicitly() -> None:
    tasks = MODELS["tasks"]
    assert set(tasks) == {
        "screening",
        "assessment",
        "escalated_assessment",
        "baseline_digest",
        "concept_note",
    }
    for name, task in tasks.items():
        assert task["model"] in MODELS["models"], name
        assert task["effort"] in {"low", "medium", "high"}, name
    assert tasks["escalated_assessment"]["model"] == "claude-sonnet-5-5"
    assert all(
        task["model"] == "claude-haiku-5-5"
        for name, task in tasks.items()
        if name != "escalated_assessment"
    )


def test_the_budget_is_the_provisional_fifteen_dollars() -> None:
    budget = MODELS["budget"]
    assert budget["currency"] == "USD"
    assert budget["monthly_limit"] == 15.00
    assert budget["provisional"] is True
    assert budget["shed_order"][0] == "experimental_judges"
    assert budget["shed_order"][-1] == "screening"


@pytest.mark.parametrize("path", [SOURCES_PATH, MODELS_PATH], ids=["sources", "models"])
def test_configuration_holds_no_credential(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"sk-ant-[A-Za-z0-9_-]{8,}", text)
    assert not re.search(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*:\s*['\"]?[A-Za-z0-9_\-]{16,}", text
    )
    if path == MODELS_PATH:
        assert MODELS["provider"]["api_key_env"] == "ANTHROPIC_API_KEY"
        assert "api_key" not in MODELS["provider"]
