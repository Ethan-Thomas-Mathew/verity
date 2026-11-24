"""Verity's own tables: indexed requirements, runs, test cases, results and bug reports."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Chunk(Base):
    """One section of a requirements document, with its embedding for retrieval."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(200))
    heading: Mapped[str] = mapped_column(String(300))
    requirement_id: Mapped[str | None] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text)
    # Vectors from different embedding models are not comparable, so each row
    # records which model made it and queries filter on it.
    embedder: Mapped[str] = mapped_column(String(100), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector())


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    story_key: Mapped[str] = mapped_column(String(50))
    target_url: Mapped[str] = mapped_column(String(300))
    model: Mapped[str] = mapped_column(String(100))
    # queued -> running -> finished | failed
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="run", order_by="TestCase.position"
    )
    bugs: Mapped[list["BugReport"]] = relationship(back_populates="run")
    events: Mapped[list["RunEvent"]] = relationship(back_populates="run", order_by="RunEvent.id")


class TestCase(Base):
    __tablename__ = "test_cases"
    __test__ = False  # tells pytest this is not a test class

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    requirement_id: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(10))  # api | ui
    title: Mapped[str] = mapped_column(String(300))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # passed | failed | error (the test itself could not run)
    outcome: Mapped[str | None] = mapped_column(String(10))
    detail: Mapped[str | None] = mapped_column(Text)
    # pending -> approved | rejected. Only approved tests join the regression suite.
    review: Mapped[str] = mapped_column(String(10), default="pending")

    run: Mapped[Run] = relationship(back_populates="test_cases")


class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"))
    requirement_id: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(10))
    steps_to_reproduce: Mapped[list[str]] = mapped_column(JSONB)
    expected: Mapped[str] = mapped_column(Text)
    actual: Mapped[str] = mapped_column(Text)

    run: Mapped[Run] = relationship(back_populates="bugs")


class RunEvent(Base):
    """Trace of what each agent did during a run, shown by the API for debugging."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped[Run] = relationship(back_populates="events")
