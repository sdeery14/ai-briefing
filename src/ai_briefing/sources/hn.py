"""Hacker News, read through its official API only (ADR-003, ADR-010).

Hacker News is a discovery signal: it shows what practitioners are paying attention to.
It is never evidence, and nothing here reads a Hacker News page or a page it links to.

Two kinds of request are made, both to the API host in the catalogue: the list of front
page item ids, and one request per item not seen before. From an item, only the fields
the catalogue lists are read: its id, type, title, link and time. The submitter's name,
the text of the post and its comments are in the API's answer and are never read out of
it, so they cannot be stored.

The score and the comment count are on the catalogue's list too. They are not kept: the
schema has nowhere to put them, and nothing uses them yet. An item's place on the front
page is the popularity signal that is used, and it decides only which items are looked at.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from datetime import UTC, datetime
from urllib.parse import urlsplit

from ai_briefing.domain.records import Source
from ai_briefing.sources.feeds import FeedEntry, FeedError
from ai_briefing.sources.fetcher import Fetcher, FetchResult

FRONT_PAGE = "topstories.json"
MAX_ITEMS = 30
"""How many front page items are looked at on one visit. Each new one is one request."""
LIST_MAX_BYTES = 100_000
ITEM_MAX_BYTES = 200_000
TITLE_CHARS = 500
LINK_CHARS = 2000
DISCUSSION = "https://news.ycombinator.com/item?id={id}"


def discussion_url(external_id: str) -> str:
    """The address of an item's page on Hacker News. Shown to a reader; never fetched."""
    if not external_id.isascii() or not external_id.isdigit():
        raise ValueError("not a Hacker News item id")
    return DISCUSSION.format(id=external_id)


def _api_hosts(source: Source) -> frozenset[str]:
    return frozenset({(urlsplit(source.url).hostname or "").lower()})


def _json(result: FetchResult, what: str) -> object:
    try:
        return json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FeedError(f"the Hacker News {what} is not JSON") from error


def _web_address(link: str) -> str | None:
    """A link as a plain web address with its scheme in lower case, or ``None`` if it is
    not one. Anything else (another scheme, spaces, no host) is not kept as a link."""
    link = link.strip()
    try:
        parts = urlsplit(link)
        host = parts.hostname
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not host or any(c.isspace() for c in link):
        return None
    if len(link) > LINK_CHARS:
        return None
    return scheme + link[len(parts.scheme) :]


def entry_from_item(item: object) -> FeedEntry | None:
    """A candidate from one API item, or ``None`` if it is not a live story with a title.

    Only ``id``, ``type``, ``title``, ``url`` and ``time`` are read. A story with no link
    of its own (a question, for example) is given the address of its discussion.
    """
    if not isinstance(item, dict) or item.get("type") != "story":
        return None
    if item.get("deleted") or item.get("dead"):
        return None
    number, title, link, when = item.get("id"), item.get("title"), item.get("url"), item.get("time")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    external_id = str(number)
    url = discussion_url(external_id)
    if isinstance(link, str):
        url = _web_address(link) or url
    published = None
    if isinstance(when, int) and not isinstance(when, bool) and when > 0:
        try:
            published = datetime.fromtimestamp(when, tz=UTC)
        except (OverflowError, OSError, ValueError):
            published = None
    return FeedEntry(
        external_id=external_id,
        url=url,
        title=" ".join(title.split())[:TITLE_CHARS],
        published_at=published,
        summary=None,
        content=None,
    )


def read(
    fetcher: Fetcher,
    source: Source,
    known: Collection[str],
    *,
    etag: str | None = None,
    last_modified: str | None = None,
) -> tuple[FetchResult, list[FeedEntry]]:
    """The front page's items that are not already stored.

    ``known`` holds the ids of items already stored; no request is made for those. Returns
    the fetch of the list, for its cache validators, and the new candidates.
    """
    hosts = _api_hosts(source)
    spacing = source.rate_limit.min_seconds_between_requests
    base = source.url if source.url.endswith("/") else source.url + "/"
    listing = fetcher.fetch(
        base + FRONT_PAGE,
        allowed_hosts=hosts,
        min_seconds_between_requests=spacing,
        etag=etag,
        last_modified=last_modified,
        max_bytes=LIST_MAX_BYTES,
    )
    if listing.not_modified:
        return listing, []
    ids = _json(listing, "front page list")
    if not isinstance(ids, list):
        raise FeedError("the Hacker News front page list is not a list")
    wanted = [
        str(number)
        for number in ids[:MAX_ITEMS]
        if isinstance(number, int) and not isinstance(number, bool) and number > 0
    ]
    entries: list[FeedEntry] = []
    for external_id in wanted:
        if external_id in known:
            continue
        # The address is built from a number the code checked, on the catalogue's host.
        result = fetcher.fetch(
            f"{base}item/{external_id}.json",
            allowed_hosts=hosts,
            min_seconds_between_requests=spacing,
            max_bytes=ITEM_MAX_BYTES,
        )
        entry = entry_from_item(_json(result, "item"))
        if entry is not None and entry.external_id == external_id:
            entries.append(entry)
    return listing, entries
