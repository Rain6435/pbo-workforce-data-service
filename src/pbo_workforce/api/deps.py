"""FastAPI dependencies: settings and database sessions.

``create_app`` stores an ``AppContext`` on ``app.state``; these dependencies
read it from there, so there are no module-level globals and tests can build
apps with their own settings or override ``get_session``.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from pbo_workforce.config import Settings


@dataclass(frozen=True)
class AppContext:
    """Per-application objects shared by all requests."""

    settings: Settings
    session_factory: sessionmaker[Session]


def get_context(request: Request) -> AppContext:
    """The context ``create_app`` attached to the application."""
    context = request.app.state.context
    if not isinstance(context, AppContext):
        raise TypeError("application was not built by create_app")
    return context


def get_app_settings(request: Request) -> Settings:
    """The settings the app was created with."""
    return get_context(request).settings


def get_session(request: Request) -> Iterator[Session]:
    """A session for one request, always closed afterwards.

    The API only reads, so nothing is committed; closing returns the
    connection to the pool and ends its (read-only) transaction.
    """
    with get_context(request).session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[Session, Depends(get_session)]
