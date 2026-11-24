import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from playwright.sync_api import sync_playwright
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from verity.db.database import make_engine


@pytest.fixture(scope="session")
def shelf_db_url() -> str:
    return os.environ.get(
        "TEST_SHELF_DATABASE_URL", "postgresql+psycopg://verity:verity@127.0.0.1:5432/shelf_test"
    )


@pytest.fixture(scope="session")
def verity_db_url() -> str:
    return os.environ.get(
        "TEST_VERITY_DATABASE_URL", "postgresql+psycopg://verity:verity@127.0.0.1:5432/verity_test"
    )


@pytest.fixture(scope="session")
def browser_executable() -> str | None:
    """Path to a Chromium binary, or None to use Playwright's own download.

    Skips the test when neither exists, so the suite still runs on a machine
    where `playwright install chromium` has not been done.
    """
    configured = os.environ.get("VERITY_TEST_BROWSER")
    if configured:
        return configured
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("no Chromium: run `uv run playwright install chromium`")
    return None


@pytest.fixture(scope="session")
def verity_factory(verity_db_url: str) -> Iterator[sessionmaker[Session]]:
    """Migrate the test database from scratch once per test session."""
    config = Config("alembic.ini")
    config.attributes["url"] = verity_db_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = make_engine(verity_db_url)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(verity_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """An empty database for each test."""
    with verity_factory() as session, session.begin():
        session.execute(text("TRUNCATE chunks, runs, test_cases, bug_reports, run_events"))
    return verity_factory
