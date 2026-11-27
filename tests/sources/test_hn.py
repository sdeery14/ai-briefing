"""The Hacker News adapter (M1 issue 1.9; ADR-003, ADR-010): the official API only, the
catalogue's fields only, and never a page."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from ai_briefing.sources import hn
from ai_briefing.sources.collect import collect
from ai_briefing.sources.feeds import FeedError
from ai_briefing.sources.transport import HopResponse
from ai_briefing.storage import schema
from ai_briefing.storage.jobs import JobOutcome

from .conftest import FakeTransport, make_fetcher, ok, rss, source

NOW = datetime(2026, 11, 19, 11, 15, tzinfo=UTC)
HASH = "c" * 64
API = "https://api.example.org/v0/"
HN = source(
    "api",
    "metadata_only",
    kind="hn_api",
    url=API,
    role="community",
    rate_limit={"min_seconds_between_requests": 1, "max_connections": 1},
    stored_fields=["id", "title", "url", "score", "descendants", "time", "type"],
)
OTHER = source("summary", "feed_summary")
POSTED = int(datetime(2026, 11, 19, 9, 0, tzinfo=UTC).timestamp())

# What the API returns for an item, including everything that must never be kept.
SUBMITTER = "a-submitter-name"
POST_TEXT = "The text of the post itself, written by its submitter."


def item(number: int, **changes: Any) -> dict[str, Any]:
    made: dict[str, Any] = {
        "id": number,
        "type": "story",
        "by": SUBMITTER,
        "title": f"Item {number}",
        "url": f"https://elsewhere.example.com/post-{number}",
        "score": 321,
        "descendants": 45,
        "kids": [9001, 9002],
        "text": POST_TEXT,
        "time": POSTED,
    }
    made.update(changes)
    return {key: value for key, value in made.items() if value is not None}


def api(ids: list[Any], *items: dict[str, Any]) -> dict[str, HopResponse]:
    replies = {API + "topstories.json": ok(json.dumps(ids), etag='"list-1"')}
    for one in items:
        replies[f"{API}item/{one['id']}.json"] = ok(json.dumps(one))
    return replies


def run(engine: Engine, transport: FakeTransport, at: datetime = NOW, **more: Any) -> JobOutcome:
    return collect(
        engine,
        more.pop("catalogue", (HN,)),
        make_fetcher(transport),
        application_version="0.0.0",
        configuration_hash=HASH,
        clock=lambda: at,
        **more,
    )


def rows(engine: Engine, table: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        found = connection.execute(select(schema.metadata.tables[table])).mappings().all()
    return [dict(row) for row in found]


# --- What is read and stored --------------------------------------------------------------------


def test_front_page_stories_are_stored_with_the_listed_fields_and_nothing_else(
    engine: Engine,
) -> None:
    transport = FakeTransport(api([11, 12], item(11), item(12, title="  Spaced   out  title ")))
    outcome = run(engine, transport)
    assert outcome.counts["sources_fetched"] == 1
    assert outcome.counts["sources_without_adapter"] == 0
    assert outcome.counts["documents_added"] == 2
    documents = rows(engine, "source_documents")
    assert [
        (d["external_id"], d["canonical_url"], d["title"], d["source_role"]) for d in documents
    ] == [
        ("11", "https://elsewhere.example.com/post-11", "Item 11", "community"),
        ("12", "https://elsewhere.example.com/post-12", "Spaced out title", "community"),
    ]
    assert all(d["published_at"] == datetime.fromtimestamp(POSTED, tz=UTC) for d in documents)
    # Metadata only: an observation with no summary and no body.
    observations = rows(engine, "document_observations")
    assert [(o["summary"], o["body_text"]) for o in observations] == [(None, None), (None, None)]


def test_no_username_and_no_post_or_comment_text_is_stored_anywhere(engine: Engine) -> None:
    run(engine, FakeTransport(api([11], item(11))))
    everything = json.dumps(
        [rows(engine, name) for name in ("source_documents", "document_observations", "sources")],
        default=str,
    )
    assert "Item 11" in everything  # the search below would find what is there
    for never in (SUBMITTER, POST_TEXT, "9001", "9002", "321"):
        assert never not in everything


def test_only_the_api_host_is_ever_requested(engine: Engine) -> None:
    transport = FakeTransport(api([11, 12], item(11), item(12)))
    run(engine, transport)
    assert {request.host for request in transport.requests} == {"api.example.org"}
    assert transport.content_urls == [
        API + "topstories.json",
        API + "item/11.json",
        API + "item/12.json",
    ]
    # One second between requests, as the catalogue says; nothing is hurried.
    assert all(request.max_bytes <= hn.ITEM_MAX_BYTES for request in transport.requests[2:])


def test_a_story_with_no_link_of_its_own_gets_its_discussion_address(engine: Engine) -> None:
    transport = FakeTransport(
        api(
            [21, 22, 23],
            item(21, url=None),
            item(22, url="javascript:alert(1)"),
            item(23, url="ftp://files.example.org/x"),
        )
    )
    run(engine, transport)
    assert [d["canonical_url"] for d in rows(engine, "source_documents")] == [
        "https://news.ycombinator.com/item?id=21",
        "https://news.ycombinator.com/item?id=22",
        "https://news.ycombinator.com/item?id=23",
    ]
    assert {request.host for request in transport.requests} == {"api.example.org"}


@pytest.mark.parametrize(
    "unwanted",
    [
        item(31, type="comment"),
        item(31, type="job"),
        item(31, type="poll"),
        item(31, deleted=True),
        item(31, dead=True),
        item(31, title=None),
        item(31, title="   "),
        item(31, title=7),
        item(31, id="31"),
        item(31, id=True),
        item(31, id=-4),
        None,
        [],
        "a string",
        {},
    ],
)
def test_what_is_not_a_live_story_with_a_title_is_not_a_candidate(unwanted: object) -> None:
    assert hn.entry_from_item(unwanted) is None


def test_a_time_that_is_not_a_time_is_left_unknown_and_never_guessed() -> None:
    for bad in (None, "yesterday", True, -1, 10**30):
        entry = hn.entry_from_item(item(41, time=bad))
        assert entry is not None
        assert entry.published_at is None


def test_an_item_that_answers_with_another_id_is_not_stored(engine: Engine) -> None:
    replies = api([51])
    replies[API + "item/51.json"] = ok(json.dumps(item(52)))
    run(engine, FakeTransport(replies))
    assert rows(engine, "source_documents") == []


def test_only_the_first_items_of_the_front_page_are_looked_at(engine: Engine) -> None:
    ids = list(range(1000, 1000 + hn.MAX_ITEMS + 20))
    transport = FakeTransport(api(ids, *(item(number) for number in ids[: hn.MAX_ITEMS])))
    outcome = run(engine, transport)
    assert outcome.counts["documents_added"] == hn.MAX_ITEMS == 30
    assert len(transport.content_urls) == 1 + hn.MAX_ITEMS


def test_ids_that_are_not_positive_numbers_are_never_put_in_an_address(engine: Engine) -> None:
    transport = FakeTransport(api(["../../x", -3, True, 2.5, None, {"id": 1}, 61], item(61)))
    outcome = run(engine, transport)
    assert outcome.counts["documents_added"] == 1
    assert transport.content_urls == [API + "topstories.json", API + "item/61.json"]


# --- Collecting again -----------------------------------------------------------------------------


def test_an_item_already_stored_is_not_asked_for_again(engine: Engine) -> None:
    run(engine, FakeTransport(api([11, 12], item(11), item(12))))
    later = NOW + timedelta(hours=7)  # past the polling interval
    transport = FakeTransport(api([13, 12, 11], item(13)))  # 11 and 12 have no reply set
    outcome = run(engine, transport, at=later)
    assert outcome.counts["documents_added"] == 1
    assert outcome.counts["sources_failed"] == 0
    assert transport.content_urls == [API + "topstories.json", API + "item/13.json"]
    assert len(rows(engine, "source_documents")) == 3
    # Collecting the same front page once more adds nothing and asks for no item.
    again = FakeTransport(api([13, 12, 11]))
    outcome = run(engine, again, at=later + timedelta(hours=7))
    assert outcome.counts["documents_added"] == outcome.counts["observations_added"] == 0
    assert again.content_urls == [API + "topstories.json"]


def test_the_list_is_asked_for_conditionally_and_not_before_its_interval(engine: Engine) -> None:
    run(engine, FakeTransport(api([11], item(11))))
    # Inside the polling interval: not requested at all.
    early = FakeTransport()
    outcome = run(engine, early, at=NOW + timedelta(minutes=30))
    assert early.requests == []
    assert outcome.counts["sources_not_due"] == 1
    # After it: asked with the stored validator, and a 304 adds nothing.
    unchanged = FakeTransport({API + "topstories.json": HopResponse(status=304)})
    outcome = run(engine, unchanged, at=NOW + timedelta(hours=7))
    assert unchanged.requests[-1].headers["If-None-Match"] == '"list-1"'
    assert outcome.counts["sources_not_modified"] == 1
    assert len(rows(engine, "source_documents")) == 1


# --- Failure --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "listing",
    [b"<html>not json</html>", b'{"not": "a list"}', b"\xff\xfe"],
)
def test_a_front_page_that_cannot_be_read_fails_this_source_and_no_other(
    engine: Engine, listing: bytes
) -> None:
    failures: list[tuple[str, str]] = []
    transport = FakeTransport(
        {
            API + "topstories.json": ok(listing),
            OTHER.url: ok(rss("summary.example.org", ("s1", "Summary one", "<p>Text.</p>"))),
        }
    )
    outcome = run(
        engine,
        transport,
        catalogue=(HN, OTHER),
        on_failure=lambda source_id, why: failures.append((source_id, why)),
    )
    assert outcome.counts["sources_failed"] == 1
    assert outcome.counts["documents_added"] == 1
    ((failed, why),) = failures
    assert failed == "api"
    assert why.startswith("FeedError: the Hacker News front page list is not")
    assert "html" not in why  # described, not quoted


def test_one_unreadable_item_fails_the_visit_and_stores_nothing_half_done(engine: Engine) -> None:
    replies = api([71, 72], item(71))
    replies[API + "item/72.json"] = ok(b"not json")
    outcome = run(engine, FakeTransport(replies))
    assert outcome.counts["sources_failed"] == 1
    assert rows(engine, "source_documents") == []
    # A source that failed is tried again on the next run, which reads both.
    soon = NOW + timedelta(minutes=5)
    outcome = run(engine, FakeTransport(api([71, 72], item(71), item(72))), at=soon)
    assert outcome.counts["documents_added"] == 2


def test_reading_raises_in_the_projects_own_words() -> None:
    transport = FakeTransport({API + "topstories.json": ok(b"[1]"), API + "item/1.json": ok(b"{")})
    with pytest.raises(FeedError, match="the Hacker News item is not JSON"):
        hn.read(make_fetcher(transport), HN, frozenset())


# --- The discussion address -----------------------------------------------------------------------


def test_the_discussion_address_is_built_only_from_a_number() -> None:
    assert hn.discussion_url("12345") == "https://news.ycombinator.com/item?id=12345"
    full_width = chr(0xFF11) + chr(0xFF12)  # digits, but not the ASCII ones
    for bad in ("", "12a", "1&x=2", "../1", " 1", full_width):
        with pytest.raises(ValueError, match="not a Hacker News item id"):
            hn.discussion_url(bad)


@pytest.mark.parametrize(
    ("link", "kept"),
    [
        ("https://elsewhere.example.com/a", "https://elsewhere.example.com/a"),
        ("HTTPS://Elsewhere.Example.com/A?b=1#c", "https://Elsewhere.Example.com/A?b=1#c"),
        ("  http://elsewhere.example.com/a  ", "http://elsewhere.example.com/a"),
        ("https://elsewhere.example.com/a b", None),
        ("https://elsewhere.example.com/a" + chr(10) + "b", None),
        ("https://", None),
        ("https://[::1", None),
        ("data:text/html,hello", None),
        ("https://elsewhere.example.com/" + "a" * 3000, None),
    ],
)
def test_a_link_is_kept_only_as_a_plain_web_address(link: str, kept: str | None) -> None:
    entry = hn.entry_from_item(item(81, url=link))
    assert entry is not None
    assert entry.url == (kept or "https://news.ycombinator.com/item?id=81")


def test_a_link_that_is_not_a_web_address_does_not_cost_the_visit(engine: Engine) -> None:
    transport = FakeTransport(
        api([82, 83], item(82, url="HTTPS://Elsewhere.Example.com/x"), item(83, url="h t t p"))
    )
    outcome = run(engine, transport)
    assert outcome.counts["sources_failed"] == 0
    assert [d["canonical_url"] for d in rows(engine, "source_documents")] == [
        "https://Elsewhere.Example.com/x",
        "https://news.ycombinator.com/item?id=83",
    ]
