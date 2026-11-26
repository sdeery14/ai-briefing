"""The domain's enumerations and ``Source`` record agree with the committed configuration.

If a value is added to ``config/sources.yaml`` or ``config/models.yaml`` without the
matching enumeration member, or the other way round, one of these fails.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest
import yaml

from ai_briefing.domain.enums import (
    AutomatedAccess,
    BodySource,
    Effort,
    ModelSubmission,
    ModelTask,
    ModelTier,
    SourceKind,
    SourceMode,
    SourceRole,
)
from ai_briefing.domain.records import Source

REPO_ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((REPO_ROOT / "config" / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


SOURCES: list[dict[str, Any]] = load("sources.yaml")["sources"]
MODELS = load("models.yaml")


def values(enum: type[StrEnum]) -> set[str]:
    return {member.value for member in enum}


def test_every_source_value_in_the_catalogue_is_a_known_member() -> None:
    assert {s["kind"] for s in SOURCES} <= values(SourceKind)
    assert {s["role"] for s in SOURCES} <= values(SourceRole)
    assert {s["mode"] for s in SOURCES} <= values(SourceMode)
    assert {s["model_submission"] for s in SOURCES} <= values(ModelSubmission)
    assert {s["terms"]["automated_access"] for s in SOURCES} <= values(AutomatedAccess)
    assert {s["body"]["source"] for s in SOURCES if "body" in s} <= values(BodySource)


def test_the_catalogue_uses_every_mode_and_submission_value() -> None:
    # The catalogue's header comment documents these values; a member the catalogue never
    # uses would be undocumented there.
    assert {s["mode"] for s in SOURCES} == values(SourceMode)
    assert {s["model_submission"] for s in SOURCES} == values(ModelSubmission)
    assert {s["kind"] for s in SOURCES} == values(SourceKind)


def test_the_documented_values_in_the_catalogue_header_match() -> None:
    header = (REPO_ROOT / "config" / "sources.yaml").read_text(encoding="utf-8")
    assert "none | metadata | title_and_summary | full_text" in header
    assert " | ".join(m.value for m in ModelSubmission) == (
        "none | metadata | title_and_summary | full_text"
    )
    assert "explicit | interpretation | uncertain" in header
    assert " | ".join(m.value for m in AutomatedAccess) == "explicit | interpretation | uncertain"


@pytest.mark.parametrize("entry", SOURCES, ids=[s["id"] for s in SOURCES])
def test_every_catalogue_entry_is_a_valid_source_record(entry: dict[str, Any]) -> None:
    source = Source.model_validate(entry)
    assert source.id == entry["id"]
    assert source.mode.value == entry["mode"]
    assert source.model_submission.value == entry["model_submission"]
    assert source.enabled is entry["enabled"]
    if "body" in entry:
        assert source.body is not None
        assert list(source.body.hosts) == entry["body"]["hosts"]


def test_model_tasks_tiers_and_efforts_match_the_model_configuration() -> None:
    assert set(MODELS["tasks"]) == values(ModelTask)
    assert {m["tier"] for m in MODELS["models"].values()} == values(ModelTier)
    efforts = {t["effort"] for t in MODELS["tasks"].values()}
    efforts |= {m["default_effort"] for m in MODELS["models"].values()}
    assert efforts == values(Effort)


def test_every_shed_step_but_the_experimental_one_is_a_model_task() -> None:
    shed = MODELS["budget"]["shed_order"]
    assert set(shed) - {"experimental_judges"} == values(ModelTask)
