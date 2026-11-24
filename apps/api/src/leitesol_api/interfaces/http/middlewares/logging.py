import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from leitesol_api.infrastructure.service_log import record_service_request
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.schemas import GatewayLogRecord

logger = logging.getLogger("leitesol.api.http")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        request.state.request_id = request_id
        started_at = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (perf_counter() - started_at) * 1000
            logger.exception(
                "request_id=%s method=%s path=%s status=500 duration_ms=%.2f",
                request_id,
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise

        elapsed_ms = (perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id

        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        record = GatewayLogRecord(
            traceId=request_id,
            timestamp=datetime.now(UTC),
            severity=(
                "error"
                if response.status_code >= 500
                else "warning"
                if response.status_code >= 400
                else "info"
            ),
            request={"method": request.method, "path": request.url.path},
            response={
                "statusCode": response.status_code,
                "durationMs": round(elapsed_ms, 2),
            },
        )
        previous_background = response.background

        async def persist_api_log() -> None:
            if previous_background is not None:
                await previous_background()
            await run_in_threadpool(record_service_request, "api", record, get_settings())

        response.background = BackgroundTask(persist_api_log)
        return response
