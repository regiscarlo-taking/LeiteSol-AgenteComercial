import json
import logging
from time import monotonic
from typing import Any, Protocol

from leitesol_api.infrastructure.settings import Settings
from leitesol_api.interfaces.schemas import GatewayLogRecord

logger = logging.getLogger("leitesol.api.gateway")


class AppendStore(Protocol):
    def append_line(self, name: str, line: str) -> None: ...


def record_gateway_request(
    record: GatewayLogRecord,
    settings: Settings,
    store: AppendStore | None = None,
) -> None:
    """Writes metadata-only request/response pairs without affecting the request."""
    payload: dict[str, Any] = record.model_dump(mode="json", by_alias=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    log_method = getattr(logger, record.severity)
    log_method("gateway_exchange %s", line)

    if not settings.gateway_log_to_blob:
        logger.info(
            "gateway_log_blob_write %s",
            json.dumps(
                {
                    "event": "gateway_log_blob_write",
                    "trace_id": record.trace_id,
                    "result": "skipped",
                    "reason": "blob_logging_disabled",
                },
                separators=(",", ":"),
            ),
        )
        return

    started_at = monotonic()
    blob_name = "gateway/logs.jsonl"
    try:
        if store is None:
            from leitesol_api.infrastructure.azure_storage import get_blob_storage_gateway

            store = get_blob_storage_gateway()

        store.append_line(blob_name, line)
    except Exception as error:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        logger.error(
            "gateway_log_blob_write %s",
            json.dumps(
                {
                    "event": "gateway_log_blob_write",
                    "trace_id": record.trace_id,
                    "result": "failed",
                    "error_type": type(error).__name__,
                    "error_code": getattr(error, "error_code", None),
                    "status_code": getattr(error, "status_code", None),
                    "storage_request_id": (
                        headers.get("x-ms-request-id") if headers is not None else None
                    ),
                    "duration_ms": round((monotonic() - started_at) * 1000, 2),
                },
                separators=(",", ":"),
            ),
        )
        return

    logger.info(
        "gateway_log_blob_write %s",
        json.dumps(
            {
                "event": "gateway_log_blob_write",
                "trace_id": record.trace_id,
                "result": "written",
                "blob": blob_name,
                "duration_ms": round((monotonic() - started_at) * 1000, 2),
            },
            separators=(",", ":"),
        ),
    )
