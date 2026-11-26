"""The monthly cap and the day's allowance (RFC §7.2, ADR-009).

A call is refused when its worst-case cost would pass either limit. The monthly cap is the
figure in ``models.yaml``. The day's allowance stops one busy day from using up the rest
of the month: unless the configuration fixes an amount, it is what was left of the month
when the day began, shared equally over the days that remain, today included.

Both figures are worked out from the recorded calls alone (RFC §5). Months and days are
calendar periods in UTC.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, select

from ai_briefing.llm.config import Budget
from ai_briefing.storage import schema

MONTHLY = "BudgetExceeded"
DAILY = "DailyAllowanceExceeded"


@dataclass(frozen=True)
class Spend:
    """What has been spent, and what may still be."""

    month_to_date: Decimal
    today: Decimal
    monthly_limit: Decimal
    daily_allowance: Decimal

    @property
    def left_this_month(self) -> Decimal:
        return self.monthly_limit - self.month_to_date

    @property
    def left_today(self) -> Decimal:
        return self.daily_allowance - self.today

    def refusal(self, worst_case: Decimal) -> str | None:
        """Why a call that could cost ``worst_case`` must not be made, or ``None``."""
        if self.month_to_date + worst_case > self.monthly_limit:
            return MONTHLY
        if self.today + worst_case > self.daily_allowance:
            return DAILY
        return None


def _spent_since(engine: Engine, start: datetime) -> Decimal:
    calls = schema.llm_calls
    with engine.connect() as connection:
        costs = connection.execute(
            select(calls.c.estimated_cost_usd).where(calls.c.created_at >= start)
        ).scalars()
        return sum(costs, Decimal(0))


def month_to_date(engine: Engine, now: datetime) -> Decimal:
    """What has been spent on model calls so far this calendar month (UTC)."""
    moment = now.astimezone(UTC)
    return _spent_since(engine, moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0))


def daily_allowance(budget: Budget, spent_before_today: Decimal, now: datetime) -> Decimal:
    """The most that may be spent today."""
    if budget.daily_allowance is not None:
        return budget.daily_allowance
    moment = now.astimezone(UTC)
    days_in_month = calendar.monthrange(moment.year, moment.month)[1]
    days_left = days_in_month - moment.day + 1  # today counts
    return max(budget.monthly_limit - spent_before_today, Decimal(0)) / days_left


def current_spend(engine: Engine, budget: Budget, now: datetime) -> Spend:
    moment = now.astimezone(UTC)
    month = month_to_date(engine, moment)
    today = _spent_since(engine, moment.replace(hour=0, minute=0, second=0, microsecond=0))
    return Spend(
        month_to_date=month,
        today=today,
        monthly_limit=budget.monthly_limit,
        daily_allowance=daily_allowance(budget, month - today, moment),
    )


@dataclass(frozen=True)
class TaskSpend:
    task: str
    calls: int
    cost: Decimal
    tokens_in: int
    tokens_out: int


def spend_by_task(engine: Engine, now: datetime) -> list[TaskSpend]:
    """This month's recorded calls, grouped by task. Every call counts, whatever its
    outcome: answered, refused, failed, or stopped by the budget check."""
    moment = now.astimezone(UTC)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls = schema.llm_calls
    totals: dict[str, list[Decimal | int]] = {}
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                calls.c.purpose, calls.c.estimated_cost_usd, calls.c.tokens_in, calls.c.tokens_out
            ).where(calls.c.created_at >= start)
        ).all()
    for row in rows:
        total = totals.setdefault(row.purpose, [0, Decimal(0), 0, 0])
        total[0] += 1
        total[1] += row.estimated_cost_usd
        total[2] += row.tokens_in
        total[3] += row.tokens_out
    return [
        TaskSpend(task, int(t[0]), Decimal(t[1]), int(t[2]), int(t[3]))
        for task, t in sorted(totals.items())
    ]
