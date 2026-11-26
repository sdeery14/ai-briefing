"""A server that compresses its response although it was asked not to, and a failure
message that says what came back instead of a feed. Both from the second live run."""

from __future__ import annotations

import gzip
import zlib

import pytest

from ai_briefing.sources.feeds import FeedError, describe, parse_feed
from ai_briefing.sources.network import Blocked, FetchError
from ai_briefing.sources.transport import ResponseTooLarge

from .conftest import FakeTransport, make_fetcher, ok, rss

FEED = "https://feeds.example.org/feed.xml"
ROBOTS = "https://feeds.example.org/robots.txt"
BODY = rss("feeds.example.org", ("one", "A title", "A summary of the item."))


def fetch(transport: FakeTransport, max_bytes: int | None = None):  # type: ignore[no-untyped-def]
    options: dict[str, object] = {"allowed_hosts": None, "min_seconds_between_requests": 0}
    if max_bytes is not None:
        options["max_bytes"] = max_bytes
    return make_fetcher(transport).fetch(FEED, **options)  # type: ignore[arg-type]


def raw_deflate(data: bytes) -> bytes:
    packer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return packer.compress(data) + packer.flush()


def test_the_request_asks_for_an_unencoded_response() -> None:
    transport = FakeTransport({FEED: ok(BODY)})
    fetch(transport)
    assert transport.requests[-1].headers["Accept-Encoding"] == "identity"


@pytest.mark.parametrize(
    ("encoding", "packed"),
    [
        ("gzip", gzip.compress(BODY)),
        ("GZIP", gzip.compress(BODY)),
        ("x-gzip", gzip.compress(BODY)),
        ("deflate", zlib.compress(BODY)),
        ("deflate", raw_deflate(BODY)),
    ],
)
def test_a_response_compressed_anyway_is_read(encoding: str, packed: bytes) -> None:
    result = fetch(FakeTransport({FEED: ok(packed, content_encoding=encoding)}))
    assert result.body == BODY
    assert len(parse_feed(result.body, feed_url=FEED)) == 1


@pytest.mark.parametrize("encoding", ["identity", ""])
def test_an_unencoded_response_is_left_alone(encoding: str) -> None:
    assert fetch(FakeTransport({FEED: ok(BODY, content_encoding=encoding)})).body == BODY
    assert fetch(FakeTransport({FEED: ok(BODY)})).body == BODY


def test_the_size_limit_applies_to_what_a_compressed_response_expands_to() -> None:
    bomb = gzip.compress(b"x" * 1_000_000)
    assert len(bomb) < 2000  # well under the limit as sent
    with pytest.raises(ResponseTooLarge, match="expands beyond the limit of 5000 bytes"):
        fetch(FakeTransport({FEED: ok(bomb, content_encoding="gzip")}), max_bytes=5000)
    # Exactly at the limit is accepted; one byte over is not.
    exact = gzip.compress(b"x" * 5000)
    assert len(fetch(FakeTransport({FEED: ok(exact, content_encoding="gzip")}), 5000).body) == 5000
    over = gzip.compress(b"x" * 5001)
    with pytest.raises(ResponseTooLarge):
        fetch(FakeTransport({FEED: ok(over, content_encoding="gzip")}), max_bytes=5000)


def test_an_encoding_that_is_not_read_is_a_failure_and_not_a_guess() -> None:
    with pytest.raises(FetchError, match="content encoding that is not read: br"):
        fetch(FakeTransport({FEED: ok(BODY, content_encoding="br")}))


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_a_body_that_is_not_what_its_encoding_says_is_a_failure(encoding: str) -> None:
    with pytest.raises(FetchError, match=f"says it is {encoding}"):
        fetch(FakeTransport({FEED: ok(b"plain words, not compressed", content_encoding=encoding)}))


def test_a_compressed_robots_txt_is_still_obeyed() -> None:
    rules = gzip.compress(b"User-agent: *\nDisallow: /\n")
    transport = FakeTransport({ROBOTS: ok(rules, content_encoding="gzip"), FEED: ok(BODY)})
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetch(transport)
    assert transport.content_urls == []


def test_a_robots_txt_that_cannot_be_decoded_allows_nothing() -> None:
    transport = FakeTransport({ROBOTS: ok(b"not gzip", content_encoding="gzip"), FEED: ok(BODY)})
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetch(transport)
    assert transport.content_urls == []


@pytest.mark.parametrize(
    ("data", "says"),
    [
        (b"", "is empty"),
        (b"  \n ", "is empty"),
        (gzip.compress(BODY), "is gzip-compressed"),
        (b"<!DOCTYPE html><html><body>Sign in</body></html>", "is an HTML page"),
        (b"\n <html><body>Not a feed</body></html>", "is an HTML page"),
        (b'{"error": "nope"}', "looks like JSON"),
        (b'<?xml version="1.0"?><rss version="2.0"><channel>', "is XML of 49 bytes"),
        (b"plain words", "is 11 bytes of an unrecognised kind"),
    ],
)
def test_a_feed_failure_says_what_came_back_without_quoting_it(data: bytes, says: str) -> None:
    assert says in describe(data)
    for word in (b"Sign in", b"nope", b"plain words"):
        assert word.decode() not in describe(data)


def test_the_feed_error_carries_the_description() -> None:
    with pytest.raises(FeedError, match="not an RSS or Atom feed; it is gzip-compressed"):
        parse_feed(gzip.compress(BODY), feed_url=FEED)


# --- All of a compressed body, or a failure ---------------------------------------------------


def flushed_then_cut(data: bytes, rest: bytes, wbits: int) -> bytes:
    """A compressed stream cut off after a point where everything so far can be read."""
    packer = zlib.compressobj(wbits=wbits)
    start = packer.compress(data) + packer.flush(zlib.Z_SYNC_FLUSH)
    end = packer.compress(rest) + packer.flush()
    return start + end[: len(end) // 2]


@pytest.mark.parametrize(
    ("encoding", "wbits"),
    [("gzip", 16 + zlib.MAX_WBITS), ("deflate", zlib.MAX_WBITS), ("deflate", -zlib.MAX_WBITS)],
)
def test_a_compressed_response_that_stops_early_is_refused(encoding: str, wbits: int) -> None:
    cut = flushed_then_cut(BODY, b"more of the feed " * 50, wbits)
    with pytest.raises(FetchError):
        fetch(FakeTransport({FEED: ok(cut, content_encoding=encoding)}))
    with pytest.raises(FetchError):
        fetch(FakeTransport({FEED: ok(gzip.compress(BODY)[:-9], content_encoding="gzip")}))


def test_a_robots_txt_cut_off_before_its_last_rule_allows_nothing() -> None:
    # The part that arrived allows everything. The part that did not might not have.
    cut = flushed_then_cut(
        b"User-agent: *\nAllow: /\n", b"Disallow: /feed.xml\n" * 40, 16 + zlib.MAX_WBITS
    )
    transport = FakeTransport({ROBOTS: ok(cut, content_encoding="gzip"), FEED: ok(BODY)})
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetch(transport)
    assert transport.content_urls == []


def test_every_member_of_a_gzip_response_is_read() -> None:
    half = len(BODY) // 2
    joined = gzip.compress(BODY[:half]) + gzip.compress(BODY[half:])
    assert fetch(FakeTransport({FEED: ok(joined, content_encoding="gzip")})).body == BODY


def test_a_rule_in_a_later_gzip_member_of_robots_txt_is_obeyed() -> None:
    rules = gzip.compress(b"User-agent: *\nAllow: /public\n") + gzip.compress(
        b"Disallow: /feed.xml\n"
    )
    transport = FakeTransport({ROBOTS: ok(rules, content_encoding="gzip"), FEED: ok(BODY)})
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetch(transport)
    assert transport.content_urls == []


def test_the_size_limit_is_on_all_the_members_together() -> None:
    two = gzip.compress(b"x" * 3000) + gzip.compress(b"y" * 2000)
    assert len(fetch(FakeTransport({FEED: ok(two, content_encoding="gzip")}), 5000).body) == 5000
    three = two + gzip.compress(b"z")
    with pytest.raises(ResponseTooLarge):
        fetch(FakeTransport({FEED: ok(three, content_encoding="gzip")}), max_bytes=5000)


@pytest.mark.parametrize(
    ("encoding", "packed"),
    [
        ("gzip", gzip.compress(BODY) + b"not another member"),
        ("deflate", zlib.compress(BODY) + b"trailing"),
        ("deflate", zlib.compress(BODY) + zlib.compress(BODY)),
    ],
)
def test_anything_after_the_compressed_body_that_is_not_part_of_it_is_refused(
    encoding: str, packed: bytes
) -> None:
    with pytest.raises(FetchError):
        fetch(FakeTransport({FEED: ok(packed, content_encoding=encoding)}))
