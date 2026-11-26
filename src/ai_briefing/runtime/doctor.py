"""``ai-briefing doctor``: is the system in a state to run? (RFC §3.5)

Each check reports ``ok``, ``warn`` or ``fail`` with one line of detail. Nothing here
changes anything, and nothing here prints a secret or any source or model text.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select

from ai_briefing.domain.records import Source
from ai_briefing.llm.budget import current_spend
from ai_briefing.llm.config import Budget
from ai_briefing.storage import database, schema

OK, WARN, FAIL = "ok", "warn", "fail"
MIN_FREE_BYTES = 1_000_000_000
FAILURES_BEFORE_WARNING = 3
STALE_AFTER = timedelta(hours=36)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def check_database(path: Path) -> tuple[Check, bool]:
    """Whether the database exists and is at the current schema."""
    if not path.is_file():
        return Check(
            "database", FAIL, f"{path} does not exist; run `ai-briefing db upgrade`"
        ), False
    engine = database.create_database_engine(path)
    try:
        current, head = database.current_revision(engine), database.head_revision()
    except Exception as error:
        return Check("database", FAIL, f"cannot be read: {type(error).__name__}"), False
    finally:
        engine.dispose()
    if current != head:
        detail = f"at {current or 'no revision'}, expected {head}; run `ai-briefing db upgrade`"
        return Check("database", FAIL, detail), False
    return Check("database", OK, f"{path} at {head}"), True


def check_disk(path: Path, free: Callable[[Path], int] | None = None) -> Check:
    folder = path.parent if path.parent.exists() else Path.cwd()
    available = free(folder) if free else shutil.disk_usage(folder).free
    gigabytes = available / 1_000_000_000
    status = OK if available >= MIN_FREE_BYTES else WARN
    return Check("disk", status, f"{gigabytes:.1f} GB free at {folder}")


def check_sources(engine: Engine, catalogue: Sequence[Source], now: datetime) -> list[Check]:
    table = schema.sources
    with engine.connect() as connection:
        rows = {row.id: row for row in connection.execute(select(table))}
    checks: list[Check] = []
    for source in catalogue:
        if not source.enabled:
            continue
        row = rows.get(source.id)
        name = f"source {source.id}"
        if row is None or row.last_success_at is None:
            failures = row.consecutive_failures if row is not None else 0
            status = WARN if failures else OK
            detail = f"never fetched; {failures} failure(s)" if failures else "not fetched yet"
            checks.append(Check(name, status, detail))
            continue
        age = now - row.last_success_at
        due = timedelta(minutes=source.polling_interval_minutes)
        failing = row.consecutive_failures >= FAILURES_BEFORE_WARNING
        stale = age > max(due * 3, STALE_AFTER)
        detail = (
            f"last fetched {row.last_success_at:%Y-%m-%d %H:%M} UTC; "
            f"{row.consecutive_failures} consecutive failure(s)"
        )
        checks.append(Check(name, WARN if failing or stale else OK, detail))
    return checks


def check_last_runs(engine: Engine) -> list[Check]:
    """The newest run of each job, and whether it succeeded."""
    runs = schema.job_runs
    with engine.connect() as connection:
        rows = connection.execute(select(runs).order_by(runs.c.id.desc())).mappings().all()
    newest: dict[str, dict[str, Any]] = {}
    for row in rows:
        newest.setdefault(str(row["job"]), dict(row))
    if not newest:
        return [Check("jobs", OK, "no job has run yet")]
    checks = []
    for job in sorted(newest):
        latest = newest[job]
        state = latest["status"]
        status = OK if state == "succeeded" else FAIL if state == "failed" else WARN
        when = latest["ended_at"] or latest["started_at"]
        detail = f"{state} at {when:%Y-%m-%d %H:%M} UTC"
        if state == "failed" and latest["error"]:
            # Only the kind of error: the message can quote a source or a model.
            detail += f" ({str(latest['error']).split(':', 1)[0]})"
        checks.append(Check(f"job {job}", status, detail))
    return checks


def check_budget(engine: Engine, budget: Budget, now: datetime) -> Check:
    spend = current_spend(engine, budget, now)
    detail = (
        f"{spend.month_to_date:.4f} of {spend.monthly_limit:.2f} {budget.currency} this month; "
        f"{spend.today:.4f} of {spend.daily_allowance:.4f} today"
    )
    if spend.left_this_month <= 0:
        return Check("budget", FAIL, detail + "; the monthly cap is reached")
    if spend.left_today <= 0:
        return Check("budget", WARN, detail + "; today's allowance is used")
    return Check("budget", OK, detail)


def worst(checks: Sequence[Check]) -> str:
    statuses = {check.status for check in checks}
    return FAIL if FAIL in statuses else WARN if WARN in statuses else OK


def render(checks: Sequence[Check]) -> str:
    width = max(len(check.name) for check in checks)
    lines = [f"{check.status:<4}  {check.name.ljust(width)}  {check.detail}" for check in checks]
    return "\n".join(lines) + "\n"
