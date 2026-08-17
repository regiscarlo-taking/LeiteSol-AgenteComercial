from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def build_response_payload(
    *,
    data: Any,
    message: str,
    status_code: int,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "data": data,
        "statusCode": status_code,
        "message": message,
        "error": error,
        "success": error is None and status_code < 400,
        "traceId": trace_id or str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "metadata": metadata,
    }
