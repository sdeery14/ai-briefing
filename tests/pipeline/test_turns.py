"""Every source gets its turn at assessment. From the second live run, where one source
with 132 fresh stories used the whole run and three blog posts waited behind it."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import Engine

from ai_briefing.editorial import process as processing
from ai_briefing.editorial.process import in_turn
from ai_briefing.llm.config import ModelsConfig

from .conftest import FakeTransport, ScriptedBackend, run_day
from .test_first_briefing import rated

Item = tuple[str, int, str]  # source, rank (lower is better), name


def ordered(items: list[Item]) -> list[str]:
    result = in_turn(items, source_of=lambda item: item[0], rank=lambda item: (item[1],))
    return [item[2] for item in result]


def test_each_source_takes_a_turn_before_any_takes_a_second() -> None:
    items: list[Item] = [
        ("big", 1, "big-1"),
        ("big", 2, "big-2"),
        ("big", 3, "big-3"),
        ("big", 4, "big-4"),
        ("small", 9, "small-1"),
        ("other", 5, "other-1"),
        ("other", 6, "other-2"),
    ]
    assert ordered(items) == [
        "big-1",
        "other-1",
        "small-1",  # every source's best, the better-ranked first
        "big-2",
        "other-2",
        "big-3",
        "big-4",
    ]


def test_turns_do_not_depend_on_the_order_the_items_arrived_in() -> None:
    # Ranks are distinct, as they are in use: the story id is the last part of the rank.
    items: list[Item] = [("a", 3, "a-2"), ("b", 2, "b-1"), ("a", 1, "a-1"), ("b", 4, "b-3")]
    assert ordered(items) == ordered(list(reversed(items))) == ["a-1", "b-1", "a-2", "b-3"]


def test_one_source_alone_is_simply_ranked_and_nothing_is_lost() -> None:
    items: list[Item] = [("a", 3, "c"), ("a", 1, "a"), ("a", 2, "b")]
    assert ordered(items) == ["a", "b", "c"]
    assert ordered([]) == []


def feed(host: str, *items: tuple[str, str]) -> bytes:
    body = "".join(
        f"<item><title>{title}</title><link>https://{host}/{guid}</link>"
        f'<guid isPermaLink="false">{guid}</guid>'
        "<pubDate>Thu, 19 Nov 2026 08:00:00 GMT</pubDate>"
        f"<description>Abstract of {title}. It reports a measured result.</description></item>"
        for guid, title in items
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        f"<title>Synthetic</title><link>https://{host}/</link>{body}</channel></rss>"
    ).encode()


def test_a_busy_source_does_not_use_up_the_run(
    engine: Engine, config: ModelsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(processing, "MAX_ASSESSED_PER_RUN", 2)
    papers = [(f"p{n}", f"Paper number {n}") for n in range(1, 6)]
    transport = FakeTransport(
        {
            "https://papers.example.org/feed.xml": feed("papers.example.org", *papers),
            "https://vendor.example.org/feed.xml": feed("vendor.example.org"),
            "https://notes.example.org/feed.xml": feed(
                "notes.example.org", ("n1", "The one note of the day")
            ),
        }
    )
    # Every paper is rated above the note. By rating alone the note would never be reached.
    ratings = {title: 4 for _, title in papers} | {"The one note of the day": 2}
    backend = ScriptedBackend(rated(ratings))
    counts = run_day(engine, config, backend, transport)
    assert counts["assess"]["assessed"] == 2
    assessed = [
        json.loads(request.user)["observations"][0]["title"]
        for request in backend.requests
        if "observations" in request.user
    ]
    assert len(assessed) == 2
    assert assessed[0].startswith("Paper number")
    assert assessed[1] == "The one note of the day"
