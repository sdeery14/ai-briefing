"""Alembic environment.

Migrations are run by ``ai_briefing.storage.database.upgrade`` and ``downgrade``, which
pass an open connection in. Batch mode is always on: SQLite cannot alter most things in
place, so Alembic rebuilds the table (ADR-002).
"""

from __future__ import annotations

from alembic import context

from ai_briefing.storage import schema

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError(
        "run migrations through ai_briefing.storage.database (for example "
        "`ai-briefing db upgrade`), which supplies the connection"
    )

context.configure(
    connection=connection,
    target_metadata=schema.metadata,
    render_as_batch=True,
)
with context.begin_transaction():
    context.run_migrations()
