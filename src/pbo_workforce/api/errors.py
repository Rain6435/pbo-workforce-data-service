"""Consistent error bodies and exception handlers (D13).

Every error, whether raised by our code, by request validation, by routing
(404/405), or unexpected, leaves as ``{"error": {"code", "message"}}``.
Unexpected errors are logged with a reference ID and the client receives
only that ID: no stack trace, SQL, or data.
"""

import logging
import uuid
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pbo_workforce.api.schemas import ErrorDetail, ErrorResponse
from pbo_workforce.api.security import security_headers

logger = logging.getLogger(__name__)

_HTTP_CODES = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """An error with a status code and a stable, documented error code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Render the standard error body."""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


def _handle(request: Request, exc: Exception) -> JSONResponse:
    match exc:
        case ApiError():
            return error_response(exc.status_code, exc.code, exc.message)
        case RequestValidationError():
            problems = [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]
            return error_response(422, "invalid_request", "; ".join(problems))
        case StarletteHTTPException():
            code = _HTTP_CODES.get(exc.status_code, "http_error")
            return error_response(exc.status_code, code, str(exc.detail), exc.headers)
        case _:
            reference = uuid.uuid4().hex
            logger.error(
                "unhandled error %s on %s %s",
                reference,
                request.method,
                request.url.path,
                exc_info=exc,
            )
            # Unexpected errors are answered outside the middleware stack
            # (by Starlette's ServerErrorMiddleware), so add headers here.
            return error_response(
                500,
                "internal_error",
                f"Internal server error (reference {reference})",
                security_headers(request.url.path),
            )


def register_error_handlers(app: FastAPI) -> None:
    """Install the handler that produces the standard error body."""
    for exc_class in (
        ApiError,
        RequestValidationError,
        StarletteHTTPException,
        Exception,
    ):
        app.add_exception_handler(exc_class, _handle)
