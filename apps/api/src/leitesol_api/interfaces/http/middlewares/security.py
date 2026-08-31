import base64

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload

PUBLIC_PATHS = {
    "/health",
    "/health/live",
    "/token",
    "/docs",
    "/docs/",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
    "/redoc/",
}


def _is_valid_basic_auth(request: Request) -> bool:
    settings = get_settings()
    if not settings.basic_auth_username or not settings.basic_auth_password:
        return True

    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("basic "):
        return False

    try:
        decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False

    return username == settings.basic_auth_username and password == settings.basic_auth_password


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        settings = get_settings()
        
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = settings.csp_policy
        return response


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        is_public_path = request.url.path in PUBLIC_PATHS or request.url.path.startswith("/docs/")

        if is_public_path:
            return await call_next(request)

        if settings.api_key:
            provided_key = request.headers.get("x-api-key", "")
            if provided_key == settings.api_key:
                return await call_next(request)

        if settings.basic_auth_username and settings.basic_auth_password:
            if _is_valid_basic_auth(request):
                return await call_next(request)

            payload = build_response_payload(
                data=None,
                message="Request rejected.",
                error="Authentication required.",
                status_code=401,
                trace_id=getattr(request.state, "request_id", request.headers.get("x-request-id")),
            )
            return JSONResponse(
                status_code=401,
                content=payload,
                headers={"WWW-Authenticate": "Basic realm=\"LeiteSol API\""},
            )

        if settings.api_key:
            payload = build_response_payload(
                data=None,
                message="Request rejected.",
                error="Invalid API key.",
                status_code=401,
                trace_id=getattr(request.state, "request_id", request.headers.get("x-request-id")),
            )
            return JSONResponse(status_code=401, content=payload)

        return await call_next(request)
