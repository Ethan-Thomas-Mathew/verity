import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from shelf.app import ShelfSettings, create_app
from shelf.bugs import ALL_BUGS, BugSet
from shelf.models import Base


def test_parse_all_none_and_list() -> None:
    assert BugSet.parse("all").enabled == ALL_BUGS
    assert BugSet.parse("none").enabled == frozenset()
    assert BugSet.parse("").enabled == frozenset()
    assert BugSet.parse("BUG-1, BUG-4").enabled == {"BUG-1", "BUG-4"}


def test_unknown_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="BUG-99"):
        BugSet.parse("BUG-99")
    with pytest.raises(ValueError):
        BugSet.parse("none").on("BUG-99")


@pytest.mark.db
def test_first_start_seeds_books_once(shelf_db_url: str) -> None:
    engine = create_engine(shelf_db_url)
    Base.metadata.drop_all(engine)
    engine.dispose()
    for _ in range(2):  # a restart must not add the books again
        app = create_app(ShelfSettings(database_url=shelf_db_url, bugs="none"))
        assert len(TestClient(app).get("/api/books").json()) == 6
        app.state.engine.dispose()
