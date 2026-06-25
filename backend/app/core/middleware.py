"""Cross-cutting ASGI middleware (Steps 6 & 8).

- `RequestContextMiddleware` — assigns a correlation id to every request, makes
  it visible in logs and on the `X-Request-ID` response header, and is the outer
  net that turns any *unhandled* exception into a clean, generic 500 (the real
  traceback goes only to the private logs). This is Step 6's "front desk that
  never prints the internal blueprint onto the customer's receipt."
- `SecurityHeadersMiddleware` — stamps the standard browser-safety headers on
  every response (Step 8's "fire-exit / no-smoking signs").
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import get_logger, new_request_id, set_request_id

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamp a request id and catch anything that escapes the route handlers."""

    async def dispatch(self, request: Request, call_next):
        # Honour an upstream id (e.g. from Caddy) for end-to-end tracing, else mint one.
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        set_request_id(request_id)
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 — last line of defence, must catch all
            # Full detail to private logs only; the user gets a generic message + id.
            logger.exception(
                "Unhandled error on %s %s", request.method, request.url.path
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error.",
                    "request_id": request_id,
                },
            )
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard hardening headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # HSTS only makes sense once the front door (Caddy) terminates HTTPS; in
        # plain-HTTP dev it would wrongly pin localhost to https for months.
        if settings.is_production:
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
