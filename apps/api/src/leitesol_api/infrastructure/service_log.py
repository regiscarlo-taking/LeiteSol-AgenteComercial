import json
import logging
from time import monotonic
from typing import Any, Literal, Protocol

from leitesol_api.infrastructure.settings import Settings
from leitesol_api.interfaces.schemas import GatewayLogRecord

ServiceName = Literal["api", "web"]


class AppendStore(Protocol):
    def append_line(self, name: str, line: str) -> None: ...


def record_service_request(
    service: ServiceName,
    record: GatewayLogRecord,
    settings: Settings,
    store: AppendStore | None = None,
) -> None:
    logger = logging.getLogger(f"leitesol.api.{service}")
    event = "service_log_blob_write"
    enabled = settings.api_log_to_blob if service == "api" else settings.web_log_to_blob
    if not enabled:
        logger.info(
            "%s %s",
            event,
            json.dumps(
                {
                    "event": event,
                    "service": service,
                    "trace_id": record.trace_id,
                    "result": "skipped",
                    "reason": "blob_logging_disabled",
                },
                separators=(",", ":"),
            ),
        )
        return

    payload: dict[str, Any] = record.model_dump(mode="json", by_alias=True)
    payload["service"] = service
    started_at = monotonic()
    blob_name = f"{service}/logs.jsonl"
    try:
        if store is None:
            from leitesol_api.infrastructure.azure_storage import get_blob_storage_gateway

            store = get_blob_storage_gateway()
        store.append_line(blob_name, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except Exception as error:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        logger.error(
            "%s %s",
            event,
            json.dumps(
                {
                    "event": event,
                    "service": service,
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
        "%s %s",
        event,
        json.dumps(
            {
                "event": event,
                "service": service,
                "trace_id": record.trace_id,
                "result": "written",
                "blob": blob_name,
                "duration_ms": round((monotonic() - started_at) * 1000, 2),
            },
            separators=(",", ":"),
        ),
    )
