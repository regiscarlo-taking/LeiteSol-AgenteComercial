from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from leitesol_api.application.list_measures import ListMeasures
from leitesol_api.infrastructure.fabric import FabricConnectionError, FabricSqlConnection
from leitesol_api.infrastructure.entra_id import EntraIdClientCredentials
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload
from leitesol_api.interfaces.schemas import BaseResponse, MeasureResponse

router = APIRouter(prefix="/fabric", tags=["fabric"])


@router.get("/measures", response_model=BaseResponse[list[MeasureResponse], dict])
def list_measures(request: Request) -> BaseResponse[list[MeasureResponse], dict] | JSONResponse:
    settings = get_settings()
    token_provider = EntraIdClientCredentials(
        tenant_id=settings.entra_tenant_id,
        client_id=settings.entra_client_id,
        client_secret=settings.entra_client_secret,
    )
    repository = FabricSqlConnection(
        server=settings.fabric_server,
        database=settings.fabric_database,
        driver=settings.fabric_driver,
        timeout=settings.fabric_connection_timeout,
        access_token_provider=token_provider,
    )

    try:
        measures = ListMeasures(repository).execute()
    except FabricConnectionError as error:
        payload = build_response_payload(
            data=None,
            message="Fabric warehouse is unavailable.",
            error=str(error),
            status_code=503,
            trace_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=503, content=payload)

    payload = build_response_payload(
        data=[asdict(measure) for measure in measures],
        message="Measures loaded successfully.",
        status_code=200,
        metadata={"source": f"{settings.fabric_database}.IA_COMERCIAL.AGT_MEDIDA", "limit": 100},
        trace_id=getattr(request.state, "request_id", None),
    )
    return BaseResponse[list[MeasureResponse], dict].model_validate(payload)