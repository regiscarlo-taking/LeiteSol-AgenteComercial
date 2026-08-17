from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload


class HealthcheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health/live":
            settings = get_settings()
            payload = build_response_payload(
                data={
                    "service": settings.service_name,
                    "status": "healthy",
                    "version": settings.api_version,
                },
                message="API liveness check completed.",
                status_code=200,
                trace_id=request.headers.get("x-request-id"),
            )
            return JSONResponse(status_code=200, content=payload)

        return await call_next(request)
