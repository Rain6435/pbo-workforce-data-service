"""API-key authentication and security response headers.

Keys are compared as SHA-256 digests: the configuration holds only digests,
so a leaked ``.env`` or process listing does not reveal a usable key. A fast
hash is appropriate (unlike for passwords) because keys are long random
tokens that cannot be guessed by brute force.
"""

import hashlib
import hmac
from typing import Annotated

from fastapi import Security
from fastapi.security import APIKeyHeader
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pbo_workforce.api.deps import SettingsDep

API_KEY_HEADER = "X-API-Key"

# auto_error=False: a missing key goes through the same 401 path (and error
# body) as a wrong key, instead of FastAPI's default 403.
_api_key = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="API key issued to the client.",
)


def hash_api_key(key: str) -> str:
    """The SHA-256 hex digest stored in ``API_KEY_HASHES`` for ``key``."""
    return hashlib.sha256(key.encode()).hexdigest()


def require_api_key(
    settings: SettingsDep, api_key: Annotated[str | None, Security(_api_key)]
) -> None:
    """Allow the request only if ``X-API-Key`` matches a configured digest.

    Every configured digest is compared with ``hmac.compare_digest`` and the
    loop never exits early, so response time does not reveal how much of a
    digest matched or which key was close.
    """
    if not api_key:
        raise HTTPException(401, f"Missing {API_KEY_HEADER} header")
    presented = hash_api_key(api_key)
    matched = False
    for expected in sorted(settings.api_key_hashes):
        matched |= hmac.compare_digest(presented, expected)
    if not matched:
        raise HTTPException(401, "Invalid API key")


# Swagger UI loads scripts and styles, so it cannot run under the strict CSP.
_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect"})

SECURITY_HEADERS: dict[str, str] = {
    # Responses are JSON only: never sniff them as something executable.
    "X-Content-Type-Options": "nosniff",
    # Workforce data is not public: keep it out of shared and browser caches.
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'"


def security_headers(path: str) -> dict[str, str]:
    """Headers to add to a response for ``path``."""
    if path in _DOCS_PATHS:
        return SECURITY_HEADERS
    return SECURITY_HEADERS | {"Content-Security-Policy": _STRICT_CSP}


class SecurityHeadersMiddleware:
    """ASGI middleware adding ``security_headers`` to every HTTP response.

    Written as plain ASGI (not ``BaseHTTPMiddleware``) so it only touches the
    response start message and never buffers bodies.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request through, adding headers to the response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        added = security_headers(str(scope["path"]))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in added.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
