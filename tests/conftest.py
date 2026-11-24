import os

import pytest


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
