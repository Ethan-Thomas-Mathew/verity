from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    # A short connect timeout makes a missing database fail fast with a clear error.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One unit of work: commit if the block succeeds, roll back if it raises."""
    with factory() as session, session.begin():
        yield session
