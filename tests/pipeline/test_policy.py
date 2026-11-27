"""Policy v0 as a table, and the selection rules that use it (M1 issue 1.10; RFC §6.2, §6.3,
§6.5; ADR-004). One case per rule and per ceiling, with the boundaries."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine

from ai_briefing.briefings import compose as composing
from ai_briefing.briefings.compose import MAX_STORIES, compose
from ai_briefing.domain.enums import EditorialClass, SourceRole
from ai_briefing.editorial.policy import v0 as policy
from ai_briefing.llm.config import ModelsConfig

from .conftest import (
    CATALOGUE,
    FEEDS,
    HASH,
    NOW,
    PAPERS,
    SOUND,
    FakeTransport,
    ScriptedBackend,
    _rss,
)
from .conftest import run_day as run
from .test_first_briefing import table
from .test_rules import assessed, built

MAJOR, PRACTICAL, WATCH, LOW = (
    EditorialClass.MAJOR,
    EditorialClass.PRACTICAL,
    EditorialClass.WATCH,
    EditorialClass.LOW,
)
P, V, I, C, A = (  # noqa: E741 - I is the independent role, beside its four neighbours
    ("p", SourceRole.PRIMARY),
    ("v", SourceRole.VENDOR),
    ("i", SourceRole.INDEPENDENT),
    ("c", SourceRole.COMMUNITY),
    ("a", SourceRole.AGGREGATOR),
)

# --- Ceilings ---------------------------------------------------------------------------------

# verified quotations, has text, roles -> the ceiling and every reason for it
CEILING_CASES: list[tuple[str, int, bool, tuple[Any, ...], EditorialClass, tuple[str, ...]]] = [
    ("nothing caps a supported story with text", 1, True, (P,), MAJOR, ()),
    ("many verified quotations change nothing", 9, True, (P, I), MAJOR, ()),
    ("no verified evidence", 0, True, (P,), WATCH, (policy.NO_VERIFIED_EVIDENCE,)),
    ("one verified quotation is enough", 1, True, (V,), MAJOR, ()),
    ("metadata only", 1, False, (P,), WATCH, (policy.METADATA_ONLY,)),
    ("community only", 1, True, (C,), WATCH, (policy.COMMUNITY_ONLY,)),
    ("aggregator only", 1, True, (A,), WATCH, (policy.COMMUNITY_ONLY,)),
    ("community and aggregator only", 1, True, (C, A), WATCH, (policy.COMMUNITY_ONLY,)),
    ("community with a primary source is not community only", 1, True, (C, P), MAJOR, ()),
    ("community with a vendor is not community only", 1, True, (A, V), MAJOR, ()),
    ("a story with no documents is not called community only", 1, True, (), MAJOR, ()),
    (
        "every reason that applies is recorded",
        0,
        False,
        (C,),
        WATCH,
        (policy.NO_VERIFIED_EVIDENCE, policy.METADATA_ONLY, policy.COMMUNITY_ONLY),
    ),
]


@pytest.mark.parametrize(
    ("verified", "has_text", "roles", "ceiling", "reasons"),
    [case[1:] for case in CEILING_CASES],
    ids=[case[0] for case in CEILING_CASES],
)
@pytest.mark.parametrize("suggested", list(EditorialClass))
def test_the_ceiling_table(
    suggested: EditorialClass,
    verified: int,
    has_text: bool,
    roles: tuple[tuple[str, SourceRole], ...],
    ceiling: EditorialClass,
    reasons: tuple[str, ...],
) -> None:
    verdict = policy.decide(
        suggested,
        verified_supporting_evidence=verified,
        has_source_text=has_text,
        source_roles=roles,
    )
    assert verdict.ceiling is ceiling
    assert verdict.ceiling_reasons == reasons
    # The lower of the two, so a ceiling never raises a class.
    assert verdict.final_class is (suggested if suggested.rank <= ceiling.rank else ceiling)
    assert verdict.eligible is (verdict.final_class is not LOW)


def test_every_ceiling_in_the_table_has_a_case() -> None:
    covered = {reason for case in CEILING_CASES for reason in case[5]}
    assert covered == {rule.reason for rule in policy.CEILINGS}
    assert len({rule.reason for rule in policy.CEILINGS}) == len(policy.CEILINGS) == 3


def test_the_rules_carry_a_version_and_the_window_is_three_days() -> None:
    assert policy.POLICY_VERSION == "v0.2"
    assert timedelta(hours=72) == policy.FRESHNESS


# --- Repetition, as a rule --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("briefed", "current", "new_evidence", "why"),
    [
        (PRACTICAL, PRACTICAL, False, None),
        (WATCH, WATCH, False, None),
        (MAJOR, MAJOR, False, None),
        (WATCH, PRACTICAL, False, policy.CLASS_CHANGED),
        (PRACTICAL, WATCH, False, policy.CLASS_CHANGED),
        (PRACTICAL, MAJOR, False, policy.CLASS_CHANGED),
        (PRACTICAL, PRACTICAL, True, policy.NEW_EVIDENCE),
        (WATCH, WATCH, True, policy.NEW_EVIDENCE),
        (WATCH, MAJOR, True, policy.CLASS_CHANGED),
    ],
)
def test_a_briefed_story_returns_only_with_a_material_update(
    briefed: EditorialClass, current: EditorialClass, new_evidence: bool, why: str | None
) -> None:
    assert (
        policy.may_appear_again(
            briefed_class=briefed, current_class=current, new_independent_evidence=new_evidence
        )
        == why
    )


@pytest.mark.parametrize(
    ("role", "cited", "already_shown", "new"),
    [
        (SourceRole.PRIMARY, 1, {1}, False),  # the same observation the reader was given
        (SourceRole.PRIMARY, 1, {2}, True),
        (SourceRole.PRIMARY, 1, set(), True),
        (SourceRole.INDEPENDENT, 1, {2}, True),
        (SourceRole.VENDOR, 1, {2}, False),
        (SourceRole.COMMUNITY, 1, {2}, False),
        (SourceRole.AGGREGATOR, 1, {2}, False),
    ],
)
def test_new_evidence_is_an_observation_the_reader_was_not_given_from_a_source_that_counts(
    role: SourceRole, cited: int, already_shown: set[int], new: bool
) -> None:
    item = assessed(1, PRACTICAL)  # its one verified quotation cites observation 1
    assert {e.observation_id for e in item.evidence} == {cited}
    # The role is that of the source that was quoted, whatever the story is known by.
    assert composing._new_evidence(item, frozenset(already_shown), lambda _id: role) is new


def test_evidence_that_failed_its_check_is_not_new_evidence() -> None:
    item = assessed(1, WATCH, verified=0)
    assert composing._new_evidence(item, frozenset(), lambda _id: SourceRole.PRIMARY) is False


# "full" in full-width letters, which NFKC folds to the ordinary ones.
FULL_WIDTH = "".join(chr(ord(letter) + 0xFEE0) for letter in "full")

# --- Near-duplicate titles ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "similar"),
    [
        ("Library version 2 released", "Library version 2 released", True),
        ("Library version 2 released", "LIBRARY  Version 2: released!", True),
        (FULL_WIDTH + " width title words here", "full width title words here", True),
        # Four of five distinct words shared: 0.8, on the line.
        ("alpha beta gamma delta", "alpha beta gamma delta epsilon", True),
        # Four of six: under it.
        ("alpha beta gamma delta zeta", "alpha beta gamma delta epsilon", False),
        ("Library version 2 released", "Library version 3 released", False),
        # Short titles must match exactly: three shared words of four prove little.
        ("GPT five released", "GPT five released today", False),
        ("Release notes", "release NOTES", True),
        ("A sound paper on retrieval", "A minor note on formatting", False),
        ("", "", False),
        ("!!!", "???", False),
        ("Something", "", False),
    ],
)
def test_near_duplicate_titles(first: str, second: str, similar: bool) -> None:
    assert policy.similar_titles(first, second) is similar
    assert policy.similar_titles(second, first) is similar


def test_of_two_near_duplicates_the_better_one_is_kept() -> None:
    title = "Vendor releases version two of its library"
    weaker = assessed(1, PRACTICAL, scores=(2, 2, 2, 2, 2), title=title)
    stronger = assessed(2, PRACTICAL, scores=(3, 2, 2, 2, 2), title=title + "!")
    other = assessed(3, PRACTICAL, title="A different story about evaluation methods")
    content = built([weaker, stronger, other])
    assert [s["story_id"] for s in content["stories"]] == ["s-2", "s-3"]


def test_a_watch_item_repeating_a_storys_headline_is_dropped() -> None:
    title = "Researchers publish a new benchmark for agents"
    story = assessed(1, PRACTICAL, title=title)
    echo = assessed(2, WATCH, title=title.upper())
    distinct = assessed(3, WATCH, title="An unrelated note about tokenisers and speed")
    content = built([echo, story, distinct])
    assert [s["story_id"] for s in content["stories"]] == ["s-1"]
    assert [w["headline"] for w in content["watchlist"]] == ["Headline 3"]


def test_a_story_that_did_not_make_the_cut_suppresses_nothing() -> None:
    # Six stories for five places. The sixth is not shown, so its near-duplicate on the
    # watch list has nothing to repeat and stays.
    top = [
        assessed(n, PRACTICAL, scores=(3, 3, 3, 3, 3), title=f"Distinct headline number {n} here")
        for n in range(1, MAX_STORIES + 1)
    ]
    sixth = assessed(6, PRACTICAL, title="The sixth story of a busy day")
    echo = assessed(7, WATCH, title="The sixth story of a busy day")
    content = built([*top, sixth, echo])
    assert len(content["stories"]) == MAX_STORIES
    assert "s-6" not in [s["story_id"] for s in content["stories"]]
    assert [w["headline"] for w in content["watchlist"]] == ["Headline 7"]


# --- Repetition and re-deciding, through the pipeline -------------------------------------------

DAY_TWO = date(2026, 11, 20)
# The synthetic day without the paper whose assessment is rejected for an invented
# citation: that one is assessed afresh every run, which is not what is being tested here.
SETTLED = {
    PAPERS.url: _rss(
        "papers.example.org",
        ("p-sound", "A sound paper on retrieval", f"<p>{SOUND}</p>"),
        ("p-hype", "A paper that claims a great deal", "<p>This changes everything.</p>"),
        ("p-low", "[low] A minor note on formatting", "<p>A note about code formatting.</p>"),
    )
}
LATER = NOW + timedelta(hours=25)


def brief(engine: Engine, day: date, now: datetime) -> dict[str, Any]:
    with engine.begin() as connection:
        composed = compose(
            connection, CATALOGUE, local_date=day, timezone="UTC", configuration_hash=HASH, now=now
        )
    return composed.briefing.document()


def shown(content: dict[str, Any]) -> list[str]:
    return [s["headline"] for s in content["stories"]] + [
        w["headline"] for w in content["watchlist"]
    ]


def reasons(engine: Engine, content: dict[str, Any]) -> list[str]:
    briefings = {row["id"]: row for row in table(engine, "briefings")}
    return [
        row["inclusion_reason"]
        for row in table(engine, "briefing_items")
        if briefings[row["briefing_id"]]["content_hash"] == composing.stable_hash(content)
    ]


def test_a_story_already_briefed_does_not_reappear_the_next_day(
    engine: Engine, config: ModelsConfig
) -> None:
    run(engine, config, ScriptedBackend(), FakeTransport(SETTLED))
    first = brief(engine, date(2026, 11, 19), NOW)
    assert len(first["stories"]) == 2
    assert first["watchlist"]
    # The next day nothing has changed. Every item is still inside the freshness window,
    # and none of them is news twice.
    backend = ScriptedBackend()
    run(engine, config, backend, FakeTransport(SETTLED), day="2026-11-20", now=LATER)
    second = brief(engine, DAY_TWO, LATER)
    assert shown(second) == []
    assert second["status"] == "empty"
    assert backend.requests == []


def test_recomposing_a_day_is_not_repetition(engine: Engine, config: ModelsConfig) -> None:
    run(engine, config, ScriptedBackend(), FakeTransport())
    first = brief(engine, date(2026, 11, 19), NOW)
    again = brief(engine, date(2026, 11, 19), NOW + timedelta(hours=1))
    # The day's own earlier version does not bar its stories from the day.
    assert shown(again) == shown(first) != []
    assert len(table(engine, "briefings")) == 1


def test_a_briefed_story_reappears_when_new_primary_evidence_arrives(
    engine: Engine, config: ModelsConfig
) -> None:
    run(engine, config, ScriptedBackend(), FakeTransport())
    first = brief(engine, date(2026, 11, 19), NOW)
    assert "A sound paper on retrieval" in shown(first)
    # The paper's abstract is revised. It is the same document, observed again.
    revised = FEEDS[PAPERS.url].replace(
        SOUND.encode(), (SOUND + " A fourth dataset confirms the result.").encode()
    )
    assert revised != FEEDS[PAPERS.url]
    run(
        engine,
        config,
        ScriptedBackend(),
        FakeTransport({PAPERS.url: revised}),
        day="2026-11-20",
        now=LATER,
    )
    second = brief(engine, DAY_TWO, LATER)
    assert shown(second) == ["A sound paper on retrieval"]
    (reason,) = reasons(engine, second)
    assert (
        reason == f"class practical, ranked 1 of the day; briefed before, and {policy.NEW_EVIDENCE}"
    )
    # And once it has been briefed again, it does not come back a third time.
    third_time = LATER + timedelta(hours=12)
    assert shown(brief(engine, date(2026, 11, 21), third_time)) == []


def test_a_new_policy_version_redecides_without_a_model_call_and_a_changed_class_returns(
    engine: Engine, config: ModelsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(engine, config, ScriptedBackend(), FakeTransport(SETTLED))
    first = brief(engine, date(2026, 11, 19), NOW)
    stories_before = [s["headline"] for s in first["stories"]]
    watch_before = [w["headline"] for w in first["watchlist"]]
    decisions_before = table(engine, "editorial_decisions")
    assessments_before = table(engine, "editorial_assessments")
    calls_before = len(table(engine, "llm_calls"))
    assert {d["policy_version"] for d in decisions_before} == {"v0.2"}

    # The owner tightens the policy: under the next version nothing may exceed watch.
    strict = policy.Ceiling("a rule added for this test", WATCH, lambda facts: True)
    monkeypatch.setattr(policy, "CEILINGS", (*policy.CEILINGS, strict))
    monkeypatch.setattr(policy, "POLICY_VERSION", "v0.3-test")
    backend = ScriptedBackend()
    counts = run(engine, config, backend, FakeTransport(SETTLED), day="2026-11-20", now=LATER)
    second = brief(engine, DAY_TWO, LATER)

    # Every standing assessment was decided again, and no model was asked anything.
    assert counts["assess"]["assessed"] == 0
    assert backend.requests == []
    assert len(table(engine, "llm_calls")) == calls_before
    assert table(engine, "editorial_assessments") == assessments_before
    decisions = table(engine, "editorial_decisions")
    assert decisions[: len(decisions_before)] == decisions_before  # history is kept
    added = decisions[len(decisions_before) :]
    assert len(added) == len(assessments_before)
    assert {d["policy_version"] for d in added} == {"v0.3-test"}
    assert all(d["ceiling"] == "watch" for d in added)
    assert all("a rule added for this test" in d["ceiling_reasons"] for d in added)

    # The stories whose class changed come back, on the watch list, and say why. The items
    # that were already watch have not changed and stay away.
    assert second["stories"] == []
    assert sorted(w["headline"] for w in second["watchlist"]) == sorted(stories_before)
    assert not set(shown(second)) & set(watch_before)
    assert all(policy.CLASS_CHANGED in reason for reason in reasons(engine, second))

    # Composing again under the same version decides nothing again.
    with engine.begin() as connection:
        again = compose(
            connection,
            CATALOGUE,
            local_date=DAY_TWO,
            timezone="UTC",
            configuration_hash=HASH,
            now=LATER + timedelta(hours=1),
        )
    assert (again.created, again.redecided) == (False, 0)
    assert len(table(engine, "editorial_decisions")) == len(decisions)
    assert backend.requests == []


def test_a_policy_change_takes_effect_the_same_day_without_waiting_for_the_next_assessment(
    engine: Engine, config: ModelsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The day's assessment job has already succeeded, so it will not run again today.
    run(engine, config, ScriptedBackend(), FakeTransport(SETTLED))
    first = brief(engine, date(2026, 11, 19), NOW)
    assert len(first["stories"]) == 2
    strict = policy.Ceiling("a rule added for this test", WATCH, lambda facts: True)
    monkeypatch.setattr(policy, "CEILINGS", (*policy.CEILINGS, strict))
    monkeypatch.setattr(policy, "POLICY_VERSION", "v0.3-test")
    backend = ScriptedBackend()
    run(engine, config, backend, FakeTransport(SETTLED), now=NOW + timedelta(hours=1))
    assert backend.requests == []  # the day's stages have run; nothing is asked again
    assert {d["policy_version"] for d in table(engine, "editorial_decisions")} == {"v0.2"}
    # Recomposing the same day applies the policy now in force, as a new version.
    with engine.begin() as connection:
        composed = compose(
            connection,
            CATALOGUE,
            local_date=date(2026, 11, 19),
            timezone="UTC",
            configuration_hash=HASH,
            now=NOW + timedelta(hours=1),
        )
    content = composed.briefing.document()
    assert composed.created is True
    assert composed.redecided == len(table(engine, "editorial_assessments"))
    assert composed.briefing.version == 2
    assert content["stories"] == []
    assert sorted(shown(content)) == sorted(shown(first))
