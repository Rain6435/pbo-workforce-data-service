"""Alembic environment.

Runs online only. Uses a connection supplied through
``config.attributes["connection"]`` (the test suite does this so migrations
run inside its transaction), otherwise connects with
``MIGRATIONS_DATABASE_URL``, the schema owner's role.
"""

from alembic import context
from sqlalchemy import Connection

from pbo_workforce.config import get_migration_settings
from pbo_workforce.db.engine import make_engine
from pbo_workforce.db.tables import Base


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using a supplied connection or the owner URL."""
    supplied = context.config.attributes.get("connection")
    if isinstance(supplied, Connection):
        _run(supplied)
        return
    engine = make_engine(get_migration_settings().migrations_database_url)
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


run_migrations_online()
