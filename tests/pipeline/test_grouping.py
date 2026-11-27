"""Link-based grouping, with Hacker News as the discussion of a post (M1 issue 1.9;
ADR-003, ADR-010; RFC §4 step 6). Everything is synthetic."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine

from ai_briefing.briefings.compose import compose
from ai_briefing.domain.records import Source
from ai_briefing.editorial.policy import v0 as policy
from ai_briefing.editorial.process import Settings, process
from ai_briefing.llm.backends import ModelRequest, ModelResponse
from ai_briefing.llm.client import ModelClient
from ai_briefing.llm.config import ModelsConfig
from ai_briefing.llm.pricing import Usage
from ai_briefing.sources.collect import collect
from ai_briefing.stories import grouping

from .conftest import (
    HASH,
    MODEL_ID,
    NOW,
    PAPERS,
    SOUND,
    VENDOR,
    VENDOR_PAGE_TEXT,
    FakeTransport,
    ScriptedBackend,
    _rss,
    _source,
    make_fetcher,
    scripted,
)
from .test_first_briefing import table

API = "https://hn.example.org/v0/"
HN = _source("hn", "metadata_only", "community", kind="hn_api", url=API)
CATALOGUE: tuple[Source, ...] = (PAPERS, VENDOR, HN)
POSTED = int(datetime(2026, 11, 19, 9, 0, tzinfo=NOW.tzinfo).timestamp())
PAPER = "https://papers.example.org/p-sound"
RELEASE = "https://vendor.example.org/v-release"
QUOTE = "It improves accuracy by 4 points over the baseline."


def hn_item(number: int, title: str, url: str | None) -> dict[str, Any]:
    made = {
        "id": number,
        "type": "story",
        "by": "a-submitter-name",
        "title": title,
        "score": 250,
        "descendants": 80,
        "time": POSTED,
        "text": "Text written by the submitter.",
    }
    if url is not None:
        made["url"] = url
    return made


def world(*items: dict[str, Any], papers: bool = True, vendor: bool = False) -> FakeTransport:
    """The paper feed, optionally the vendor's release, and a Hacker News front page."""
    content: dict[str, bytes] = {
        PAPERS.url: _rss(
            "papers.example.org",
            *([("p-sound", "A sound paper on retrieval", f"<p>{SOUND}</p>")] if papers else []),
        ),
        VENDOR.url: _rss(
            "vendor.example.org",
            *(
                [("v-release", "Library version 2 released", "<p>Announcement.</p>")]
                if vendor
                else []
            ),
        ),
        API + "topstories.json": json.dumps([i["id"] for i in items]).encode(),
    }
    for one in items:
        content[f"{API}item/{one['id']}.json"] = json.dumps(one).encode()
    return FakeTransport(content)


def answer(request: ModelRequest) -> ModelResponse:
    """Screening passes everything. An assessment quotes the first observation that has
    text, or, when none has, offers words no observation could hold."""
    payload = json.loads(request.user)
    if "items" in payload:
        return scripted(request)
    observations = payload["observations"]
    with_text = [o for o in observations if o["text"]]
    cited = (with_text or observations)[0]
    if with_text and QUOTE in cited["text"]:
        quote = QUOTE
    elif with_text:
        quote = "Today we are releasing version 2 of our library."
    else:
        quote = "Something certainly happened here."
    out = {
        "claims": [
            {
                "text": "The source makes a claim.",
                "evidence": [
                    {
                        "observation_id": cited["observation_id"],
                        "quote": quote,
                        "support": "supports",
                    }
                ],
            }
        ],
        "uncertainty": "Based on what the sources themselves say.",
        "scores": {
            "impact": 2,
            "evidence": 3,
            "novelty": 2,
            "professional_relevance": 3,
            "maturity": 2,
        },
        "suggested_class": "practical",
        "headline": cited["title"],
        "summary": "A synthetic summary.",
        "why_it_matters": "It may be useful.",
    }
    return ModelResponse(json.dumps(out), "end_turn", Usage(input_tokens=500, output_tokens=100))


def run(
    engine: Engine,
    config: ModelsConfig,
    transport: FakeTransport,
    backend: ScriptedBackend | None = None,
    *,
    day: str = "2026-11-19",
    now: datetime = NOW,
) -> tuple[dict[str, Mapping[str, int]], ScriptedBackend]:
    backend = backend or ScriptedBackend(answer)
    fetcher = make_fetcher(transport)
    collect(
        engine,
        CATALOGUE,
        fetcher,
        application_version="0.0.0",
        configuration_hash=HASH,
        clock=lambda: now,
    )
    client = ModelClient(engine=engine, config=config, backend=backend, clock=lambda: now)
    settings = Settings(application_version="0.0.0", configuration_hash=HASH, day=day)
    counts = process(engine, CATALOGUE, client, fetcher, MODEL_ID, settings, clock=lambda: now)
    return counts, backend


def brief(engine: Engine, day: date = date(2026, 11, 19), now: datetime = NOW) -> dict[str, Any]:
    with engine.begin() as connection:
        composed = compose(
            connection, CATALOGUE, local_date=day, timezone="UTC", configuration_hash=HASH, now=now
        )
    return composed.briefing.document()


def stories_of(engine: Engine) -> dict[int, list[str]]:
    """Each story with the sources of the documents it holds now."""
    source_of = {d["id"]: d["source_id"] for d in table(engine, "source_documents")}
    held: dict[int, list[str]] = {}
    for row in table(engine, "story_documents"):
        held.setdefault(row["story_id"], []).append(source_of[row["document_id"]])
    return {story: sorted(members) for story, members in held.items()}


def assessments_sent(backend: ScriptedBackend) -> list[list[dict[str, Any]]]:
    return [
        json.loads(request.user)["observations"]
        for request in backend.requests
        if "observations" in request.user
    ]


def hosts(transport: FakeTransport) -> set[str]:
    return {url.split("/")[2] for url in transport.requests}


# --- A post and its discussion are one story ------------------------------------------------------


def test_a_feed_item_and_a_hacker_news_item_linking_to_it_form_one_story(
    engine: Engine, config: ModelsConfig
) -> None:
    # The link as people post it: another case, a trailing slash, tracking, a fragment.
    link = "HTTPS://Papers.Example.org/p-sound/?utm_source=hn&utm_medium=social#discussion"
    transport = world(hn_item(501, "A sound paper on retrieval [pdf]", link))
    _, backend = run(engine, config, transport)

    assert stories_of(engine) == {1: ["hn", "papers"]}
    events = table(engine, "story_membership_events")
    assert [(e["story_id"], e["action"], e["decided_by_rule"]) for e in events] == [
        (1, "add", grouping.OWN_STORY_RULE),
        (1, "add", grouping.SAME_URL_RULE),
    ]
    assert all(e["decided_by_model_call_id"] is None for e in events)

    # The story is assessed once, from both: the paper's abstract, and the item's title
    # with no text at all.
    (sent,) = assessments_sent(backend)
    assert [(o["source_name"], o["source_role"], bool(o["text"])) for o in sent] == [
        ("Example Papers", "primary", True),
        ("Example Hn", "community", False),
    ]
    for never in ("a-submitter-name", "Text written by the submitter", "250", "utm_source"):
        assert never not in json.dumps(sent[1])
    (assessment,) = table(engine, "editorial_assessments")
    inputs = [i["observation_id"] for i in table(engine, "assessment_inputs")]
    assert sorted(inputs) == sorted(o["observation_id"] for o in sent)

    # A discussion is not evidence, and it does not make the story community-only.
    (decision,) = table(engine, "editorial_decisions")
    assert decision["final_class"] == "practical"
    assert json.loads(decision["ceiling_reasons"]) == []
    assert decision["independent_source_count"] == 1
    assert assessment["id"] == decision["assessment_id"]

    # The reader is given the paper, and the discussion's own page beside it.
    (story,) = brief(engine)["stories"]
    assert story["evidence"] == [
        {
            "title": "A sound paper on retrieval",
            "url": PAPER,
            "source_name": "Example Papers",
            "source_role": "primary",
        },
        {
            "title": "A sound paper on retrieval [pdf]",
            "url": "https://news.ycombinator.com/item?id=501",
            "source_name": "Example Hn",
            "source_role": "community",
        },
    ]
    # Nothing was requested but the two feeds and the API. No Hacker News page, ever.
    assert hosts(transport) == {"papers.example.org", "vendor.example.org", "hn.example.org"}


def test_the_discussion_may_come_first_and_the_post_joins_it(
    engine: Engine, config: ModelsConfig
) -> None:
    item = hn_item(502, "Show: a sound paper on retrieval", PAPER)
    _, first = run(engine, config, world(item, papers=False))
    assert stories_of(engine) == {1: ["hn"]}
    (alone,) = assessments_sent(first)
    assert [o["source_role"] for o in alone] == ["community"]
    (decision,) = table(engine, "editorial_decisions")
    assert decision["final_class"] == "watch"

    # The paper's own feed carries it the next day. It joins the story already there.
    later = NOW + timedelta(hours=25)
    _, second = run(engine, config, world(item, papers=True), day="2026-11-20", now=later)
    assert stories_of(engine) == {1: ["hn", "papers"]}
    assert len(table(engine, "stories")) == 1
    # The story's input changed, so it is assessed again, now with the abstract.
    (both,) = assessments_sent(second)
    assert [o["source_role"] for o in both] == ["community", "primary"]
    decisions = table(engine, "editorial_decisions")
    assert [d["final_class"] for d in decisions] == ["watch", "practical"]
    # It is known by the paper now, not by the discussion of it.
    (story,) = brief(engine, date(2026, 11, 20), later)["stories"]
    assert story["headline"] == "A sound paper on retrieval"
    assert [e["source_role"] for e in story["evidence"]] == ["primary", "community"]


def test_a_full_text_page_is_read_under_its_own_source_and_never_because_of_the_link(
    engine: Engine, config: ModelsConfig
) -> None:
    transport = world(
        hn_item(503, "Library version 2 released", RELEASE), papers=False, vendor=True
    )
    _, backend = run(engine, config, transport)
    assert stories_of(engine) == {1: ["hn", "vendor"]}
    # The page was fetched once, for the vendor's document, on the vendor's own host.
    assert transport.requests.count(RELEASE) == 1
    bodies = [o for o in table(engine, "document_observations") if o["body_text"]]
    documents = {d["id"]: d["source_id"] for d in table(engine, "source_documents")}
    assert [documents[o["document_id"]] for o in bodies] == ["vendor"]
    (sent,) = assessments_sent(backend)
    by_role = {o["source_role"]: o["text"] for o in sent}
    assert VENDOR_PAGE_TEXT in by_role["vendor"]
    assert by_role["community"] is None  # the item is never given the page's text


# --- An item on a host outside the catalogue ------------------------------------------------------


def test_an_item_on_an_uncatalogued_host_has_no_body_and_causes_no_request_to_that_host(
    engine: Engine, config: ModelsConfig
) -> None:
    elsewhere = "https://elsewhere.example.com/a-post"
    transport = world(hn_item(504, "A post on a site nobody catalogued", elsewhere), papers=False)
    counts, backend = run(engine, config, transport)

    assert "elsewhere.example.com" not in hosts(transport)
    assert hosts(transport) == {"papers.example.org", "vendor.example.org", "hn.example.org"}
    assert counts["fetch-bodies"]["bodies_stored"] == 0
    (document,) = table(engine, "source_documents")
    assert document["canonical_url"] == elsewhere
    (observation,) = table(engine, "document_observations")
    assert (observation["summary"], observation["body_text"]) == (None, None)

    # Known only by a headline from a community source: it cannot exceed watch.
    (sent,) = assessments_sent(backend)
    assert [o["text"] for o in sent] == [None]
    (decision,) = table(engine, "editorial_decisions")
    assert decision["final_class"] == decision["ceiling"] == "watch"
    assert json.loads(decision["ceiling_reasons"]) == [
        policy.NO_VERIFIED_EVIDENCE,
        policy.METADATA_ONLY,
        policy.COMMUNITY_ONLY,
    ]
    content = brief(engine)
    assert content["stories"] == []
    assert content["watchlist"] == [
        {"item_id": "i1", "headline": "A post on a site nobody catalogued", "url": elsewhere}
    ]


def test_items_with_different_links_are_different_stories(
    engine: Engine, config: ModelsConfig
) -> None:
    transport = world(
        hn_item(505, "A sound paper on retrieval, version two", PAPER + "v2"),
        hn_item(506, "A question with no link", None),
        hn_item(507, "The same paper on another scheme", PAPER.replace("https", "http")),
    )
    run(engine, config, transport)
    assert stories_of(engine) == {1: ["papers"], 2: ["hn"], 3: ["hn"], 4: ["hn"]}


def test_two_items_linking_to_one_page_share_a_story(engine: Engine, config: ModelsConfig) -> None:
    elsewhere = "https://elsewhere.example.com/a-post"
    transport = world(
        hn_item(508, "A post, submitted once", elsewhere),
        hn_item(509, "A post, submitted again", elsewhere + "/?utm_campaign=x"),
        papers=False,
    )
    run(engine, config, transport)
    assert stories_of(engine) == {1: ["hn", "hn"]}
    (decision,) = table(engine, "editorial_decisions")
    assert policy.COMMUNITY_ONLY in decision["ceiling_reasons"]


# --- Grouping again -------------------------------------------------------------------------------


def test_regrouping_adds_no_membership_events(engine: Engine, config: ModelsConfig) -> None:
    item = hn_item(510, "A sound paper on retrieval", PAPER)
    run(engine, config, world(item))
    events = table(engine, "story_membership_events")
    stories = table(engine, "stories")
    assert len(events) == 2
    for _ in range(2):
        with engine.begin() as connection:
            assert grouping.group(connection, NOW + timedelta(hours=1)) == {
                "stories_started": 0,
                "documents_joined": 0,
            }
    # And a whole further day over the same items changes nothing either.
    later = NOW + timedelta(hours=25)
    _, backend = run(engine, config, world(item), day="2026-11-20", now=later)
    assert table(engine, "story_membership_events") == events
    assert table(engine, "stories") == stories
    assert backend.requests == []


def test_a_story_known_only_from_a_discussion_is_assessed_after_every_other(
    engine: Engine, config: ModelsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_briefing.editorial import process as processing

    monkeypatch.setattr(processing, "MAX_ASSESSED_PER_RUN", 1)
    elsewhere = "https://elsewhere.example.com/a-post"
    # Each source would have its turn, and Hacker News is collected with the others. With
    # room for one assessment, it goes to the paper, which can be more than a watch item.
    _, backend = run(engine, config, world(hn_item(511, "A post elsewhere", elsewhere)))
    assert stories_of(engine) == {1: ["papers"], 2: ["hn"]}
    (sent,) = assessments_sent(backend)
    assert [o["source_role"] for o in sent] == ["primary"]
