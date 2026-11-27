"""Comparison judgements: the reader's blind preference between a day's pipeline briefing
and its baseline digest (M1 issue 1.8, ADR-007).

Append-only, like the rest of the history: a judgement is never updated or deleted.

Revision ID: 0003_comparison_judgments
Revises: 0002_screening_decisions
Create Date: 2026-11-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_comparison_judgments"
down_revision: str | None = "0002_screening_decisions"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

TRIGGERS: dict[str, str] = {
    "comparison_judgments_no_update": (
        "CREATE TRIGGER comparison_judgments_no_update BEFORE UPDATE ON comparison_judgments "
        "FOR EACH ROW BEGIN SELECT RAISE(ABORT, "
        "'comparison_judgments is append-only: a row is never updated'); END"
    ),
    "comparison_judgments_no_delete": (
        "CREATE TRIGGER comparison_judgments_no_delete BEFORE DELETE ON comparison_judgments "
        "FOR EACH ROW BEGIN SELECT RAISE(ABORT, "
        "'comparison_judgments is append-only: a row is never deleted'); END"
    ),
}


def upgrade() -> None:
    op.create_table(
        "comparison_judgments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("pipeline_briefing_id", sa.Integer(), nullable=False),
        sa.Column("baseline_briefing_id", sa.Integer(), nullable=False),
        sa.Column("presentation_order", sa.String(length=20), nullable=False),
        sa.Column("choice", sa.String(length=20), nullable=False),
        sa.Column("in_force", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "presentation_order IN ('pipeline_first', 'baseline_first')",
            name=op.f("ck_comparison_judgments_presentation_order"),
        ),
        sa.CheckConstraint(
            "choice IN ('first', 'second', 'no_preference')",
            name=op.f("ck_comparison_judgments_choice"),
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_comparison_judgments_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["pipeline_briefing_id"],
            ["briefings.id"],
            name=op.f("fk_comparison_judgments_pipeline_briefing_id_briefings"),
        ),
        sa.ForeignKeyConstraint(
            ["baseline_briefing_id"],
            ["briefings.id"],
            name=op.f("fk_comparison_judgments_baseline_briefing_id_briefings"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comparison_judgments")),
        sa.UniqueConstraint("local_date", "sequence", name="uq_comparison_judgments_sequence"),
    )
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("comparison_judgments")
