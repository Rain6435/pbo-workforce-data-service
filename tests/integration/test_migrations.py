"""The migrations and the SQLAlchemy models describe the same schema."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, Connection, inspect

from pbo_workforce.db.tables import Base

APP_TABLES = {
    "department",
    "department_alias",
    "import_batch",
    "workforce_monthly",
    "import_rejection",
    "import_warning",
}


def test_models_match_migrations(connection: Connection):
    diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_check_constraint_names_match_models(connection: Connection):
    # compare_metadata does not compare CHECK constraints, so check names here.
    inspector = inspect(connection)
    for table in Base.metadata.sorted_tables:
        in_models = {
            str(c.name) for c in table.constraints if isinstance(c, CheckConstraint)
        }
        in_database = {
            str(c["name"]) for c in inspector.get_check_constraints(table.name)
        }
        assert in_database == in_models, table.name


def test_downgrade_to_base_and_upgrade_again(
    connection: Connection, alembic_config: Config
):
    command.downgrade(alembic_config, "base")
    assert APP_TABLES.isdisjoint(inspect(connection).get_table_names())

    command.upgrade(alembic_config, "head")
    assert set(inspect(connection).get_table_names()) >= APP_TABLES
