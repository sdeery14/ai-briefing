"""Current state that is updated in place: a source's feed cache validators, last success
and failure count, and a document's current title.

None of this is history. It is kept apart from ``repositories``, which never updates
anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from ai_briefing.storage import schema


@dataclass(frozen=True)
class FeedState:
    etag: str | None = None
    last_modified: str | None = None
    consecutive_failures: int = 0


def read_feed_state(connection: Connection, source_id: str) -> FeedState:
    table = schema.sources
    row = connection.execute(
        select(table.c.feed_etag, table.c.feed_last_modified, table.c.consecutive_failures).where(
            table.c.id == source_id
        )
    ).one_or_none()
    if row is None:
        return FeedState()
    return FeedState(row.feed_etag, row.feed_last_modified, row.consecutive_failures)


def record_fetch_success(
    connection: Connection,
    source_id: str,
    *,
    at: datetime,
    etag: str | None,
    last_modified: str | None,
    keep_validators: bool = False,
) -> None:
    """Note a successful fetch. A 304 keeps the validators it was made with."""
    table = schema.sources
    values: dict[str, object] = {"last_success_at": at, "consecutive_failures": 0}
    if not keep_validators:
        values.update(feed_etag=etag, feed_last_modified=last_modified)
    connection.execute(update(table).where(table.c.id == source_id).values(**values))


def record_fetch_failure(connection: Connection, source_id: str) -> None:
    table = schema.sources
    connection.execute(
        update(table)
        .where(table.c.id == source_id)
        .values(consecutive_failures=table.c.consecutive_failures + 1)
    )


def record_title(connection: Connection, document_id: int, title: str) -> None:
    """Keep a document's title as its source now gives it.

    RFC §5 puts the title on the document, which has a stable identity and is not a
    history record. A corrected headline replaces the earlier one; the earlier wording is
    not kept.
    """
    table = schema.source_documents
    connection.execute(update(table).where(table.c.id == document_id).values(title=title))
