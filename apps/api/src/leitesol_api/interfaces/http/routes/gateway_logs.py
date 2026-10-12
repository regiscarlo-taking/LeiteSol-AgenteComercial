import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse

from leitesol_api.infrastructure.gateway_log import record_gateway_request
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.schemas import GatewayLogRecord

router = APIRouter(prefix="/internal", tags=["internal"])
logger = logging.getLogger("leitesol.api.gateway")


@router.post("/gateway-logs", status_code=status.HTTP_202_ACCEPTED)
def ingest_gateway_log(
    record: GatewayLogRecord,
    api_key: str | None = Header(default=None, alias="x-api-key"),
) -> JSONResponse:
    configured_key = get_settings().api_key
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gateway log ingestion is not configured.",
        )
    if api_key is None or not hmac.compare_digest(
        api_key.encode("utf-8"), configured_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid gateway credentials.",
        )

    record_gateway_request(record, get_settings())
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"accepted": True})
