import json
import logging
from time import monotonic

from leitesol_api.infrastructure.azure_storage import get_blob_storage_gateway


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("leitesol.api.blob")
    started_at = monotonic()

    try:
        get_blob_storage_gateway().check_connection()
    except Exception as error:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        logger.error(
            "blob_storage_connection_check %s",
            json.dumps(
                {
                    "event": "blob_storage_connection_check",
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
        return 1

    logger.info(
        "blob_storage_connection_check %s",
        json.dumps(
            {
                "event": "blob_storage_connection_check",
                "result": "connected",
                "duration_ms": round((monotonic() - started_at) * 1000, 2),
            },
            separators=(",", ":"),
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
