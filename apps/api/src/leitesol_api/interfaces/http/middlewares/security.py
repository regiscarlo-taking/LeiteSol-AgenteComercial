from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload

PUBLIC_PATHS = {
    "/health",
    "/health/live",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
        return response


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        is_public_path = request.url.path in PUBLIC_PATHS or request.url.path.startswith("/docs/")

        if not settings.api_key or is_public_path:
            return await call_next(request)

        provided_key = request.headers.get("x-api-key", "")
        if provided_key == settings.api_key:
            return await call_next(request)

        payload = build_response_payload(
            data=None,
            message="Request rejected.",
            error="Invalid API key.",
            status_code=401,
            trace_id=getattr(request.state, "request_id", request.headers.get("x-request-id")),
        )
        return JSONResponse(status_code=401, content=payload)
