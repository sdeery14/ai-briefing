"""Collecting new items from the catalogue's feeds (RFC §4 steps 1 to 3 and 5).

Collection is a job. Its fetching happens first, with no database transaction open; one
source failing is recorded and does not stop the others. Its writes then happen in one
transaction together with the job's completion.

What is stored for an item follows its source's mode, and nothing else is kept:

- ``feed_summary``: metadata and the feed's summary.
- ``full_text`` from the feed: metadata and the entry's text.
- ``full_text`` from the page: metadata only here. The page is fetched later, for items
  that pass screening, through :func:`fetch_body`.
- ``metadata_only``: metadata. Any summary or content in the feed is discarded.
- ``disabled``: the source is never requested.

A source is requested no more often than its ``polling_interval_minutes``, counted from
its last successful fetch. A source that failed last time is tried again on the next run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import BodySource, FetchStatus, SourceKind, SourceMode
from ai_briefing.domain.records import DocumentObservation, Source, SourceDocument
from ai_briefing.sources.feeds import FeedEntry, FeedError, parse_feed
from ai_briefing.sources.fetcher import Fetcher, FetchResult
from ai_briefing.sources.network import FetchError
from ai_briefing.sources.text import page_to_text
from ai_briefing.storage import repositories, source_state
from ai_briefing.storage.jobs import JobOutcome, run_job, utc_now

FEED_KINDS = frozenset({SourceKind.RSS, SourceKind.ATOM})
PAGE_MAX_BYTES = 2_000_000


@dataclass
class _Fetched:
    source: Source
    result: FetchResult | None = None
    entries: list[FeedEntry] = field(default_factory=list)
    error: str | None = None


def content_hash(summary: str | None, body: str | None) -> str:
    """A hash of exactly what an observation stores: its summary and its body text.

    The title is not part of it. The title is stored on the document, so a hash that
    covered it would change with nothing in the observation to show why.
    """
    payload = json.dumps([summary, body], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stored_text(source: Source, entry: FeedEntry) -> tuple[str | None, str | None]:
    """The summary and body that this source's mode allows to be kept for an entry."""
    if source.mode is SourceMode.FEED_SUMMARY and source.store.feed_summary:
        return entry.summary, None
    if (
        source.mode is SourceMode.FULL_TEXT
        and source.body is not None
        and source.body.source is BodySource.FEED
    ):
        return None, entry.content or entry.summary
    return None, None


def is_due(source: Source, last_success_at: datetime | None, now: datetime) -> bool:
    """True when the source's polling interval has passed since it was last fetched."""
    if last_success_at is None:
        return True
    return now - last_success_at >= timedelta(minutes=source.polling_interval_minutes)


def feed_hosts(source: Source) -> frozenset[str]:
    """The hosts a source's feed may be fetched from: its own, and its article hosts."""
    hosts = {(urlsplit(source.url).hostname or "").lower()}
    if source.body is not None:
        hosts.update(host.lower() for host in source.body.hosts)
    return frozenset(hosts)


def collect(
    engine: Engine,
    catalogue: Sequence[Source],
    fetcher: Fetcher,
    *,
    application_version: str,
    configuration_hash: str,
    only: str | None = None,
    idempotency_key: str | None = None,
    on_failure: Callable[[str, str], None] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> JobOutcome:
    """Fetch every enabled feed source and store what is new. Returns the job's outcome.

    With no ``idempotency_key`` each call is its own run. The daily run passes the day,
    so collecting twice for one day does nothing the second time.

    ``on_failure`` is told each source that failed and why, as it happens.
    """
    started = clock()
    wanted = [s for s in catalogue if only is None or s.id == only]
    if only is not None and not wanted:
        raise ValueError(f"no source named {only!r} in the catalogue")
    # A disabled source is never requested, and neither is one this adapter cannot read.
    to_fetch = [s for s in wanted if s.enabled and s.kind in FEED_KINDS]
    without_adapter = [s.id for s in wanted if s.enabled and s.kind not in FEED_KINDS]
    fetched: list[_Fetched] = []
    not_due: list[str] = []

    def prepare(_job_run_id: int) -> None:
        with engine.connect() as connection:
            states = {s.id: source_state.read_feed_state(connection, s.id) for s in to_fetch}
        for source in to_fetch:
            state = states[source.id]
            if not is_due(source, state.last_success_at, started):
                # The catalogue's schedule decides how often a source is asked, however
                # often collection runs.
                not_due.append(source.id)
                continue
            item = _Fetched(source)
            fetched.append(item)
            try:
                item.result = fetcher.fetch(
                    source.url,
                    allowed_hosts=feed_hosts(source),
                    min_seconds_between_requests=source.rate_limit.min_seconds_between_requests,
                    etag=state.etag,
                    last_modified=state.last_modified,
                )
                if not item.result.not_modified:
                    item.entries = parse_feed(item.result.body, feed_url=item.result.final_url)
            except Exception as error:
                # One source failing never fails the run, whatever went wrong with it:
                # a refused or failed fetch, a feed that will not parse, or anything else
                # that its content provoked. It is counted and recorded, and the other
                # sources are still collected.
                item.result = None
                # A refusal by the network policy, a failed request and an unreadable feed
                # are described in this project's own words. Anything else may quote what
                # the source sent, so only its kind is kept.
                expected = isinstance(error, FetchError | FeedError)
                item.error = (
                    f"{type(error).__name__}: {error}"[:300] if expected else type(error).__name__
                )
                if on_failure is not None:
                    on_failure(source.id, item.error)

    def work(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
        counts = {
            "sources_fetched": 0,
            "sources_not_modified": 0,
            "sources_failed": 0,
            "sources_not_due": len(not_due),
            "sources_without_adapter": len(without_adapter),
            "entries_seen": 0,
            "documents_added": 0,
            "observations_added": 0,
        }
        for source in catalogue:
            repositories.upsert_source(connection, source)
        for item in fetched:
            if item.result is None:
                counts["sources_failed"] += 1
                source_state.record_fetch_failure(connection, item.source.id)
                continue
            source_state.record_fetch_success(
                connection,
                item.source.id,
                at=started,
                etag=item.result.etag,
                last_modified=item.result.last_modified,
                keep_validators=item.result.not_modified,
            )
            if item.result.not_modified:
                counts["sources_not_modified"] += 1
                continue
            counts["sources_fetched"] += 1
            for entry in item.entries:
                counts["entries_seen"] += 1
                added_document, added_observation = _store(connection, item.source, entry, started)
                counts["documents_added"] += added_document
                counts["observations_added"] += added_observation
        return counts

    return run_job(
        engine,
        job="collect",
        idempotency_key=idempotency_key or f"collect:{only or 'all'}:{started.isoformat()}",
        application_version=application_version,
        configuration_hash=configuration_hash,
        prepare=prepare,
        work=work,
        clock=clock,
    )


def _store(
    connection: Connection, source: Source, entry: FeedEntry, now: datetime
) -> tuple[int, int]:
    """Store an entry. Returns how many documents and observations were added (0 or 1)."""
    document = repositories.find_document(connection, source.id, entry.external_id)
    added_document = 0
    if document is None:
        document = repositories.add(
            connection,
            SourceDocument(
                source_id=source.id,
                external_id=entry.external_id,
                canonical_url=entry.url,
                title=entry.title,
                published_at=entry.published_at,
                first_seen_at=now,
                source_role=source.role,
            ),
        )
        added_document = 1
    elif document.title != entry.title and document.id is not None:
        # A corrected headline. The document keeps the title its source now gives it.
        source_state.record_title(connection, document.id, entry.title)
    summary, body = stored_text(source, entry)
    return added_document, _observe(connection, document, summary, body, now)


def _observe(
    connection: Connection,
    document: SourceDocument,
    summary: str | None,
    body: str | None,
    now: datetime,
) -> int:
    """Add an observation unless the newest one of its kind already holds this content.

    A page-backed document is observed twice over: from its feed, without article text,
    and from its page, with it. Each is compared with the last observation of the same
    kind, so collecting the feed again after the page was read adds nothing, and neither
    does reading the unchanged page again.
    """
    if document.id is None:
        raise ValueError("the document has not been stored")
    digest = content_hash(summary, body)
    latest = repositories.latest_observation(connection, document.id, with_body=body is not None)
    if latest is not None and latest.content_hash == digest:
        return 0
    repositories.add(
        connection,
        DocumentObservation(
            document_id=document.id,
            retrieved_at=now,
            fetch_status=FetchStatus.OK,
            summary=summary,
            body_text=body,
            content_hash=digest,
        ),
    )
    return 1


def may_fetch_body(source: Source, document: SourceDocument) -> bool:
    """True when the article page may be fetched: a full-text page source, and a link on
    one of the source's own hosts. Anything else stays metadata-only (ADR-012).
    """
    if (
        not source.enabled
        or source.mode is not SourceMode.FULL_TEXT
        or source.body is None
        or source.body.source is not BodySource.PAGE
        or document.source_id != source.id
    ):
        return False
    parts = urlsplit(document.canonical_url)
    host = (parts.hostname or "").lower().rstrip(".")
    return parts.scheme == "https" and host in {h.lower() for h in source.body.hosts}


def fetch_body(fetcher: Fetcher, source: Source, document: SourceDocument) -> str | None:
    """Fetch a document's article page and return its text, or ``None`` if not permitted.

    Makes no request at all when :func:`may_fetch_body` says no. The request and every
    redirect are confined to the source's hosts. Raises ``FetchError`` on failure.
    """
    if not may_fetch_body(source, document) or source.body is None:
        return None
    result = fetcher.fetch(
        document.canonical_url,
        allowed_hosts=frozenset(h.lower() for h in source.body.hosts),
        min_seconds_between_requests=source.rate_limit.min_seconds_between_requests,
        max_bytes=PAGE_MAX_BYTES,
    )
    return page_to_text(_decode(result)) or None


def store_body(
    connection: Connection,
    source: Source,
    document: SourceDocument,
    text: str,
    *,
    now: datetime,
) -> int:
    """Store fetched article text as a new observation. Refused for a source that does
    not permit it. Returns 1 if an observation was added.
    """
    if not may_fetch_body(source, document):
        raise PermissionError(f"{source.id} does not permit storing article text for this link")
    return _observe(connection, document, None, text, now)


def _decode(result: FetchResult) -> str:
    charset = "utf-8"
    for part in (result.content_type or "").split(";")[1:]:
        name, _, value = part.strip().partition("=")
        if name.lower() == "charset" and value:
            charset = value.strip("\"' ")
    try:
        return result.body.decode(charset, errors="replace")
    except LookupError:
        return result.body.decode("utf-8", errors="replace")
