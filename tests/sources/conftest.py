"""Fakes for source tests: a resolver and a transport that never touch the network, a
migrated database, and synthetic sources and feeds. Every host is under ``example.org``,
``example.com`` or ``example.net``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from ai_briefing.domain.records import Source
from ai_briefing.sources.fetcher import Fetcher
from ai_briefing.sources.network import FetchError, NetworkPolicy
from ai_briefing.sources.transport import HopRequest, HopResponse
from ai_briefing.storage import database

PUBLIC = "93.184.216.34"
OTHER_PUBLIC = "93.184.216.35"
NO_ROBOTS = HopResponse(status=404)

Reply = HopResponse | Exception | Callable[[HopRequest], HopResponse]


class FakeResolver:
    """Resolves the hosts it was told about. Counts every lookup."""

    def __init__(self, addresses: dict[str, list[str]] | None = None) -> None:
        self.addresses = addresses or {}
        self.lookups: list[str] = []

    def resolve(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        if host in self.addresses:
            return list(self.addresses[host])
        if host.endswith(("example.org", "example.com", "example.net")):
            return [PUBLIC]
        raise FetchError(f"could not resolve {host}")


class FakeTransport:
    """Answers from a table of URL to reply. Records every request it is asked to send.

    A URL with several replies gives them in turn and then repeats the last. robots.txt
    answers 404 (no rules) unless a reply is set for it.
    """

    def __init__(self, replies: Mapping[str, Any] | None = None) -> None:
        self.replies: dict[str, Reply | list[Reply]] = dict(replies or {})
        self.requests: list[HopRequest] = []

    def url_of(self, request: HopRequest) -> str:
        return f"{request.scheme}://{request.host}{request.path}"

    @property
    def urls(self) -> list[str]:
        return [self.url_of(r) for r in self.requests]

    @property
    def content_urls(self) -> list[str]:
        return [url for url in self.urls if not url.endswith("/robots.txt")]

    def send(self, request: HopRequest) -> HopResponse:
        self.requests.append(request)
        url = self.url_of(request)
        if url not in self.replies:
            if request.path == "/robots.txt":
                return NO_ROBOTS
            raise AssertionError(f"unexpected request: {url}")
        reply = self.replies[url]
        if isinstance(reply, list):
            reply = reply.pop(0) if len(reply) > 1 else reply[0]
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(request)
        return reply


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_fetcher(
    transport: FakeTransport,
    resolver: FakeResolver | None = None,
    *,
    policy: NetworkPolicy | None = None,
    clock: FakeClock | None = None,
) -> Fetcher:
    clock = clock or FakeClock()
    return Fetcher(
        transport=transport,
        resolver=resolver or FakeResolver(),
        policy=policy,
        clock=clock,
        sleep=clock.sleep,
    )


def ok(body: bytes | str = b"", **headers: str) -> HopResponse:
    data = body.encode("utf-8") if isinstance(body, str) else body
    return HopResponse(
        status=200, headers={k.replace("_", "-"): v for k, v in headers.items()}, body=data
    )


def redirect(location: str, status: int = 302) -> HopResponse:
    return HopResponse(status=status, headers={"location": location})


# --- A migrated database ----------------------------------------------------------------------


@pytest.fixture
def database_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "test.sqlite3"


@pytest.fixture
def engine(database_file: Path) -> Iterator[Engine]:
    database_file.parent.mkdir(parents=True)
    engine = database.create_database_engine(database_file)
    database.upgrade(engine)
    yield engine
    engine.dispose()


# --- Synthetic sources and feeds --------------------------------------------------------------


def source(source_id: str, mode: str, **changes: Any) -> Source:
    host = f"{source_id}.example.org"
    entry: dict[str, Any] = {
        "id": source_id,
        "name": f"Example {source_id}",
        "kind": "rss",
        "url": f"https://{host}/feed.xml",
        "role": "vendor",
        "enabled": mode != "disabled",
        "mode": mode,
        "polling_interval_minutes": 360,
        "rate_limit": {"min_seconds_between_requests": 10, "max_connections": 1},
        "store": {
            "metadata": mode != "disabled",
            "feed_summary": mode == "feed_summary",
            "body": mode == "full_text",
        },
        "model_submission": {
            "full_text": "full_text",
            "feed_summary": "title_and_summary",
            "metadata_only": "metadata",
            "disabled": "none",
        }[mode],
        "retention_days": {"metadata": None, "feed_summary": 0},
        "excerpts_allowed": mode in ("full_text", "feed_summary"),
        "attribution": "Link to the original post.",
        "terms": {
            "reviewed_on": "2026-11-21",
            "approved_by_owner_on": "2026-11-23",
            "urls": ["https://example.org/terms"],
            "automated_access": "explicit",
            "restrictions": ["None stated."],
            "uncertainties": ["Synthetic."],
        },
    }
    if mode == "full_text":
        entry["body"] = {"source": "page", "hosts": [host]}
        entry["retention_days"]["body"] = 90
        entry["excerpt_limit_chars"] = 300
    if mode == "feed_summary":
        entry["retention_days"]["feed_summary"] = None
    entry.update(changes)
    return Source.model_validate(entry)


def rss(host: str, *items: tuple[str, str, str]) -> bytes:
    """An RSS feed. Each item is (guid, title, description HTML)."""
    body = "".join(
        f"<item><title>{title}</title><link>https://{host}/{guid}</link><guid>{guid}</guid>"
        f"<pubDate>Thu, 19 Nov 2026 11:15:00 GMT</pubDate>"
        f"<description><![CDATA[{description}]]></description></item>"
        for guid, title, description in items
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        f"<title>Synthetic</title><link>https://{host}/</link>{body}</channel></rss>"
    ).encode()


def atom(host: str, *items: tuple[str, str, str]) -> bytes:
    """An Atom feed carrying full content. Each item is (id, title, content HTML)."""
    body = "".join(
        f"<entry><title>{title}</title><id>tag:{host},2026:{ident}</id>"
        f'<link href="https://{host}/{ident}"/><updated>2026-11-20T00:00:00Z</updated>'
        f"<published>2026-11-19T11:15:00Z</published>"
        f'<content type="html"><![CDATA[{content}]]></content></entry>'
        for ident, title, content in items
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>Synthetic</title><id>tag:{host},2026:feed</id>"
        f"<updated>2026-11-20T00:00:00Z</updated>{body}</feed>"
    ).encode()
