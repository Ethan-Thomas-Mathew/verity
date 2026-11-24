"""Alembic entry point. The database URL comes from Verity's settings, not alembic.ini."""

from alembic import context

from verity.config import Settings
from verity.db.database import make_engine
from verity.db.models import Base

config = context.config
url = config.attributes.get("url") or Settings().database_url

# disable_existing_loggers is not called here on purpose: Alembic's default
# fileConfig() would silence the application's loggers during migrations.
with make_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
