from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.orm import Session, sessionmaker

from verity.db.models import Base
from verity.rag.embeddings import HashingEmbedder
from verity.rag.store import index_directory, retrieve, split_markdown

REQUIREMENTS = Path(__file__).parents[2] / "requirements" / "shelf"


def test_split_markdown_keeps_one_requirement_per_chunk() -> None:
    sections = split_markdown("requirements.md", (REQUIREMENTS / "requirements.md").read_text())
    ids = [s.requirement_id for s in sections if s.requirement_id]
    assert len(ids) == len(set(ids)) == 10
    loan_limit = next(s for s in sections if s.requirement_id == "REQ-LOAN-1")
    assert "at most 3 active" in loan_limit.content
    assert "REQ-LOAN-2" not in loan_limit.content


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    a, b = HashingEmbedder(64).embed(["late fee cap", "late fee cap"])
    assert a == b
    assert abs(sum(v * v for v in a) - 1.0) < 1e-9


@pytest.mark.db
def test_retrieve_returns_named_requirements_then_nearest_context(
    db: sessionmaker[Session],
) -> None:
    embedder = HashingEmbedder()
    with db() as session, session.begin():
        stored = index_directory(session, embedder, REQUIREMENTS)
        assert stored == index_directory(session, embedder, REQUIREMENTS)  # re-index replaces
    with db() as session:
        found = retrieve(
            session, embedder, "borrow loans member book due", ["REQ-LOAN-1", "REQ-LOAN-3"], k=2
        )
    exact = [r.section.requirement_id for r in found if r.match == "exact"]
    semantic = [r for r in found if r.match == "semantic"]
    assert exact == ["REQ-LOAN-1", "REQ-LOAN-3"]
    assert len(semantic) == 2
    assert all(r.section.requirement_id not in exact for r in semantic)
    assert semantic[0].distance is not None and semantic[0].distance <= semantic[1].distance  # type: ignore[operator]


@pytest.mark.db
def test_migrations_match_the_models(verity_factory: sessionmaker[Session]) -> None:
    with verity_factory() as session:
        diff = compare_metadata(MigrationContext.configure(session.connection()), Base.metadata)
    assert diff == []


@pytest.mark.db
def test_migrations_downgrade_and_upgrade(verity_db_url: str) -> None:
    config = Config("alembic.ini")
    config.attributes["url"] = verity_db_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
