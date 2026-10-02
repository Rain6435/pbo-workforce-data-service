"""Engine and session factories.

Callers pass the URL explicitly so each process chooses its own database role
(API, importer, migrations); nothing here reads settings.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    """Create an engine that checks connections before use.

    ``pool_pre_ping`` avoids handing a request a connection the database
    already closed (e.g. after a Postgres restart).
    """
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False)
