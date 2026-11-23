"""``schemas/daily_briefing.v1.schema.json`` accepts and rejects the example documents as
their manifest labels them (RFC §8.2, ADR-006).

The examples are published for the consumer to test against, so each is a plain document
and its label lives in ``manifest.json`` beside them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ai_briefing.domain.enums import BriefingStatus, Confidence, EditorialClass, SourceRole

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas" / "daily_briefing.v1.schema.json"
EXAMPLES = Path(__file__).parent / "daily_briefing_v1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


SCHEMA: dict[str, Any] = read_json(SCHEMA_PATH)
MANIFEST: dict[str, Any] = read_json(EXAMPLES / "manifest.json")
VALIDATOR = Draft202012Validator(SCHEMA)


def failures(document: Any) -> set[tuple[str, str]]:
    """Every (location, keyword) the document breaks."""
    return {
        ("".join(f"/{part}" for part in error.absolute_path), str(error.validator))
        for error in VALIDATOR.iter_errors(document)
    }


def test_the_schema_is_itself_valid_and_closed() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["properties"]["schema_version"] == {"const": "daily_briefing.v1"}
    objects = [SCHEMA, *(d for d in SCHEMA["$defs"].values() if d.get("type") == "object")]
    assert len(objects) == 5
    assert all(o["additionalProperties"] is False for o in objects)


def test_every_string_and_list_has_a_maximum() -> None:
    unbounded: list[str] = []

    def walk(node: Any, where: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "string" and "maxLength" not in node:
                unbounded.append(where)
            if node.get("type") == "array" and "maxItems" not in node:
                unbounded.append(where)
            for key, value in node.items():
                walk(value, f"{where}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}/{index}")

    walk(SCHEMA, "")
    assert unbounded == []


def test_the_manifest_lists_exactly_the_example_files() -> None:
    listed = [entry["file"] for entry in MANIFEST["valid"] + MANIFEST["invalid"]]
    assert len(listed) == len(set(listed))
    on_disk = {p.relative_to(EXAMPLES).as_posix() for p in EXAMPLES.rglob("*.json")}
    assert set(listed) | {"manifest.json"} == on_disk
    assert all(entry["file"].startswith("valid/") for entry in MANIFEST["valid"])
    assert all(entry["file"].startswith("invalid/") for entry in MANIFEST["invalid"])
    assert all(entry["shows"].strip() for entry in MANIFEST["valid"] + MANIFEST["invalid"])
    assert MANIFEST["schema"] == SCHEMA_PATH.relative_to(REPO_ROOT).as_posix()


@pytest.mark.parametrize("entry", MANIFEST["valid"], ids=lambda e: e["file"])
def test_a_valid_example_validates(entry: dict[str, str]) -> None:
    assert failures(read_json(EXAMPLES / entry["file"])) == set()


@pytest.mark.parametrize("entry", MANIFEST["invalid"], ids=lambda e: e["file"])
def test_an_invalid_example_fails_for_its_stated_reason(entry: dict[str, str]) -> None:
    found = failures(read_json(EXAMPLES / entry["file"]))
    assert (entry["at"], entry["keyword"]) in found, f"{entry['shows']} Got: {sorted(found)}"


@pytest.mark.parametrize("entry", MANIFEST["invalid"], ids=lambda e: e["file"])
def test_an_invalid_example_breaks_one_rule_only(entry: dict[str, str]) -> None:
    # Each example isolates one rule, so a consumer can tell which rule it is testing.
    assert failures(read_json(EXAMPLES / entry["file"])) == {(entry["at"], entry["keyword"])}


def test_the_examples_cover_every_status_and_stay_synthetic() -> None:
    statuses = {read_json(EXAMPLES / e["file"])["status"] for e in MANIFEST["valid"]}
    assert statuses == {s.value for s in BriefingStatus}
    for path in EXAMPLES.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        hosts = {part.split("/")[2] for part in text.split('"') if part.startswith("http")}
        assert hosts <= {"example.org", "example.com", "example.net"}, path.name


def test_the_schema_enumerations_match_the_domain() -> None:
    story = SCHEMA["$defs"]["story"]["properties"]
    assert set(SCHEMA["properties"]["status"]["enum"]) == {s.value for s in BriefingStatus}
    assert set(story["confidence"]["enum"]) == {c.value for c in Confidence}
    roles = SCHEMA["$defs"]["evidence"]["properties"]["source_role"]["enum"]
    assert set(roles) == {r.value for r in SourceRole}
    # Stories carry the two classes that are shown as stories. Watch items have their own
    # list and low items are not shown.
    assert set(story["class"]["enum"]) == {
        EditorialClass.MAJOR.value,
        EditorialClass.PRACTICAL.value,
    }
    assert SCHEMA["properties"]["stories"]["maxItems"] == 5


def test_the_rfc_example_validates() -> None:
    rfc = (REPO_ROOT / "docs" / "rfc" / "AI-Briefing-RFC-v0.3.md").read_text(encoding="utf-8")
    start = rfc.index('{\n  "schema_version": "daily_briefing.v1"')
    example = json.loads(rfc[start : rfc.index("\n```", start)])
    assert failures(example) == set()
