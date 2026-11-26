"""Reading an RSS or Atom feed into typed candidates (RFC §4 step 1).

One adapter covers both formats. It is given bytes that were already fetched; it never
fetches anything itself. A published time is taken only when the feed states one. It is
never guessed, and an entry's "updated" time is not used in its place.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urldefrag, urljoin, urlsplit

import feedparser

from ai_briefing.sources.text import html_to_text


class FeedError(ValueError):
    """The bytes could not be read as a feed."""


@dataclass(frozen=True)
class FeedEntry:
    external_id: str
    url: str
    title: str
    published_at: datetime | None
    summary: str | None  # plain text
    content: str | None  # plain text of the full entry, when the feed carries it


def describe(data: bytes) -> str:
    """What some bytes that are not a feed look like, in a few words. For a failure
    message: enough to tell a web page from a compressed body from nothing at all,
    without quoting the content.
    """
    start = data[:512].lstrip().lower()
    if not data.strip():
        return "is empty"
    if data[:2] == b"\x1f\x8b":
        return "is gzip-compressed"
    if start.startswith((b"<!doctype html", b"<html")):
        return "is an HTML page"
    if start.startswith((b"<?xml", b"<rss", b"<feed", b"<rdf")):
        return f"is XML of {len(data)} bytes with no entries that could be read"
    if start.startswith((b"{", b"[")):
        return "looks like JSON"
    return f"is {len(data)} bytes of an unrecognised kind"


def _published(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed")
    if parsed is None:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return html_to_text(value) or None


def _web_url(candidate: object, base: str) -> str | None:
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    try:
        absolute, _fragment = urldefrag(urljoin(base, candidate.strip()))
        parts = urlsplit(absolute)
        usable = parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return None  # a link that cannot be parsed, such as an unclosed "[" in the host
    return absolute if usable else None


def parse_feed(data: bytes, *, feed_url: str) -> list[FeedEntry]:
    """The entries of a feed that have a link, a title and an identity.

    An entry without one of those is skipped: there would be nothing to show a reader or
    nothing to recognise it by next time. Raises :class:`FeedError` when the bytes are
    not a feed at all.
    """
    if not isinstance(data, bytes):
        # feedparser would treat a string as a URL or a file name and go and fetch it.
        raise TypeError("parse_feed takes the fetched bytes")
    parsed = feedparser.parse(data, sanitize_html=False, resolve_relative_uris=False)
    if not parsed.entries and (parsed.get("bozo") or not parsed.get("version")):
        raise FeedError(f"the response is not an RSS or Atom feed; it {describe(data)}")
    entries: list[FeedEntry] = []
    for entry in parsed.entries:
        try:
            candidate = _entry(entry, feed_url)
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            # One entry the feed got wrong is skipped. It must not cost the other entries,
            # or the other sources.
            continue
        if candidate is not None:
            entries.append(candidate)
    return entries


def _entry(entry: feedparser.FeedParserDict, feed_url: str) -> FeedEntry | None:
    url = _web_url(entry.get("link"), feed_url)
    title = _text(entry.get("title"))
    if url is None or title is None:
        return None
    external_id = entry.get("id") if isinstance(entry.get("id"), str) else None
    contents = entry.get("content") or []
    content = _text(contents[0].get("value")) if contents else None
    return FeedEntry(
        external_id=(external_id or url).strip(),
        url=url,
        title=" ".join(title.split()),
        published_at=_published(entry),
        summary=_text(entry.get("summary")),
        content=content,
    )
