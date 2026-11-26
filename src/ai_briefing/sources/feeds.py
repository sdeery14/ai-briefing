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
    absolute, _fragment = urldefrag(urljoin(base, candidate.strip()))
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return absolute


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
        raise FeedError("the response is not an RSS or Atom feed")
    entries: list[FeedEntry] = []
    for entry in parsed.entries:
        url = _web_url(entry.get("link"), feed_url)
        title = _text(entry.get("title"))
        if url is None or title is None:
            continue
        external_id = entry.get("id") if isinstance(entry.get("id"), str) else None
        contents = entry.get("content") or []
        content = _text(contents[0].get("value")) if contents else None
        entries.append(
            FeedEntry(
                external_id=(external_id or url).strip(),
                url=url,
                title=" ".join(title.split()),
                published_at=_published(entry),
                summary=_text(entry.get("summary")),
                content=content,
            )
        )
    return entries
