"""Screening decisions: whether each item is worth assessing, and why (M1 issue 1.6).

Append-only, like the rest of the history: a decision is never updated or deleted.

Revision ID: 0002_screening_decisions
Revises: 0001_first_schema
Create Date: 2026-11-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_screening_decisions"
down_revision: str | None = "0001_first_schema"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

TRIGGERS: dict[str, str] = {
    "screening_decisions_no_update": (
        "CREATE TRIGGER screening_decisions_no_update BEFORE UPDATE ON screening_decisions "
        "FOR EACH ROW BEGIN SELECT RAISE(ABORT, "
        "'screening_decisions is append-only: a row is never updated'); END"
    ),
    "screening_decisions_no_delete": (
        "CREATE TRIGGER screening_decisions_no_delete BEFORE DELETE ON screening_decisions "
        "FOR EACH ROW BEGIN SELECT RAISE(ABORT, "
        "'screening_decisions is append-only: a row is never deleted'); END"
    ),
}


def upgrade() -> None:
    op.create_table(
        "screening_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("relevance", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("model_call_id", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('passed', 'rejected')", name=op.f("ck_screening_decisions_outcome")
        ),
        sa.CheckConstraint(
            "relevance BETWEEN 0 AND 4", name=op.f("ck_screening_decisions_relevance_range")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.id"],
            name=op.f("fk_screening_decisions_document_id_source_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["model_call_id"],
            ["llm_calls.id"],
            name=op.f("fk_screening_decisions_model_call_id_llm_calls"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screening_decisions")),
        sa.UniqueConstraint("document_id", name="uq_screening_decisions_document"),
    )
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("screening_decisions")
