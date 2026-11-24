"""Initial schema: chunks with pgvector embeddings, runs, test cases, bug reports, events.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("heading", sa.String(300), nullable=False),
        sa.Column("requirement_id", sa.String(50)),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedder", sa.String(100), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
    )
    op.create_index("ix_chunks_requirement_id", "chunks", ["requirement_id"])
    op.create_index("ix_chunks_embedder", "chunks", ["embedder"])
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("story_key", sa.String(50), nullable=False),
        sa.Column("target_url", sa.String(300), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "test_cases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Uuid, sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("requirement_id", sa.String(50), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("outcome", sa.String(10)),
        sa.Column("detail", sa.Text),
        sa.Column("review", sa.String(10), nullable=False),
    )
    op.create_index("ix_test_cases_run_id", "test_cases", ["run_id"])
    op.create_table(
        "bug_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Uuid, sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "test_case_id",
            sa.Integer,
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement_id", sa.String(50), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("steps_to_reproduce", JSONB, nullable=False),
        sa.Column("expected", sa.Text, nullable=False),
        sa.Column("actual", sa.Text, nullable=False),
    )
    op.create_index("ix_bug_reports_run_id", "bug_reports", ["run_id"])
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Uuid, sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent", sa.String(30), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])


def downgrade() -> None:
    for table in ("run_events", "bug_reports", "test_cases", "runs", "chunks"):
        op.drop_table(table)
