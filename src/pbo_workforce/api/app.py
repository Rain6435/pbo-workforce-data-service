"""Application factory.

Run with ``uvicorn --factory pbo_workforce.api.app:create_app``.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from pbo_workforce.api.deps import AppContext
from pbo_workforce.api.errors import register_error_handlers
from pbo_workforce.api.routes import departments, health
from pbo_workforce.api.security import SecurityHeadersMiddleware, require_api_key
from pbo_workforce.config import Settings, get_settings
from pbo_workforce.db.engine import make_engine, make_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API. ``settings`` defaults to the environment's.

    The engine uses ``DATABASE_URL``, the read-only ``pbo_api`` role.
    Interactive docs and the OpenAPI schema are served only when
    ``DOCS_ENABLED`` is set (never in prod, see ``Settings``).
    """
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        engine.dispose()

    docs = settings.docs_enabled
    app = FastAPI(
        title="PBO Workforce Data Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.context = AppContext(settings, make_session_factory(engine))
    register_error_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware)
    # /health stays open for probes; everything under /api needs a key.
    app.include_router(health.router)
    app.include_router(departments.router, dependencies=[Depends(require_api_key)])
    return app
