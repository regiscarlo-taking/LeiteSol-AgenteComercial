import json
import logging
from datetime import UTC, datetime
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
    try:
        payload: dict[str, Any] = record.model_dump(mode="json", by_alias=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        log_method = getattr(logger, record.severity)
        log_method("gateway_exchange %s", line)

        if not settings.gateway_log_to_blob:
            return
        if store is None:
            from leitesol_api.infrastructure.azure_storage import get_blob_storage_gateway

            store = get_blob_storage_gateway()

        log_date = datetime.now(UTC).date().isoformat()
        store.append_line(f"gateway/{log_date}/{record.severity}.jsonl", line)
    except Exception:
        logger.warning("Gateway log persistence failed trace_id=%s", record.trace_id, exc_info=True)
