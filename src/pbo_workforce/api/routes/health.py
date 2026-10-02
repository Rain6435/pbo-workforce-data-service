"""Unauthenticated health check.

Used by the container orchestrator and load balancer, which hold no API key.
It reveals only whether the database answers.
"""

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pbo_workforce.api.deps import SessionDep
from pbo_workforce.api.errors import ApiError
from pbo_workforce.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(session: SessionDep) -> HealthResponse:
    """``ok`` if the database answers a trivial query, otherwise 503."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ApiError(503, "unavailable", "Database unavailable") from exc
    return HealthResponse(status="ok")
