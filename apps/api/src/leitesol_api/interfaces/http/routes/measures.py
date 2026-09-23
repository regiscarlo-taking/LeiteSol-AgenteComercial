from dataclasses import asdict
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from leitesol_api.application.list_measures import ListMeasures
from leitesol_api.infrastructure.auth import verify_token
from leitesol_api.infrastructure.fabric import (
    EntityNotAllowedError,
    FabricConnectionError,
    FabricSqlConnection,
)
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload
from leitesol_api.interfaces.schemas import (
    BaseResponse,
    CatalogEntityResponse,
    EntityQueryRequest,
    MeasureResponse,
    SqlResultResponse,
)

router = APIRouter(
    prefix="/fabric",
    tags=["fabric"],
    dependencies=[Depends(verify_token)],
)
logger = logging.getLogger("leitesol.api.http.fabric")


@router.get("/measures", response_model=BaseResponse[list[MeasureResponse], dict])
def list_measures(request: Request) -> BaseResponse[list[MeasureResponse], dict] | JSONResponse:
    settings = get_settings()
    logger.info(
        "fabric measures request server_configured=%s database=%s entra_configured=%s",
        bool(settings.fabric_server),
        settings.fabric_database,
        bool(settings.entra_tenant_id and settings.entra_client_id and settings.entra_client_secret),
    )
    repository = FabricSqlConnection(
        server=settings.fabric_server,
        database=settings.fabric_database,
        driver=settings.fabric_driver,
        authentication=settings.fabric_authentication,
        client_id=settings.entra_client_id,
        tenant_id=settings.entra_tenant_id,
        client_secret=settings.entra_client_secret,
        timeout=settings.fabric_connection_timeout,
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


@router.get("/entities", response_model=BaseResponse[list[CatalogEntityResponse], dict])
def list_entities(request: Request) -> BaseResponse[list[CatalogEntityResponse], dict]:
    settings = get_settings()
    repository = FabricSqlConnection(
        server=settings.fabric_server,
        database=settings.fabric_database,
        driver=settings.fabric_driver,
        authentication=settings.fabric_authentication,
        client_id=settings.entra_client_id,
        tenant_id=settings.entra_tenant_id,
        client_secret=settings.entra_client_secret,
        timeout=settings.fabric_connection_timeout,
    )
    entities = repository.list_entities()
    payload = build_response_payload(
        data=[
            {
                "name": entity.name,
                "schema": entity.schema,
                "table": entity.table,
                "kind": entity.kind,
            }
            for entity in entities
        ],
        message="Fabric entities loaded successfully.",
        status_code=200,
        metadata={"count": len(entities)},
        trace_id=getattr(request.state, "request_id", None),
    )
    return BaseResponse[list[CatalogEntityResponse], dict].model_validate(payload)


@router.post("/query", response_model=BaseResponse[SqlResultResponse, dict])
def query_entity(
    query_request: EntityQueryRequest,
    request: Request,
) -> BaseResponse[SqlResultResponse, dict] | JSONResponse:
    settings = get_settings()
    repository = FabricSqlConnection(
        server=settings.fabric_server,
        database=settings.fabric_database,
        driver=settings.fabric_driver,
        authentication=settings.fabric_authentication,
        client_id=settings.entra_client_id,
        tenant_id=settings.entra_tenant_id,
        client_secret=settings.entra_client_secret,
        timeout=settings.fabric_connection_timeout,
    )

    try:
        result = repository.query_entity(query_request.entity, query_request.limit)
    except EntityNotAllowedError as error:
        payload = build_response_payload(
            data=None,
            message="Entity is not available for querying.",
            error=str(error),
            status_code=400,
            trace_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=400, content=payload)
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
        data={
            "entity": result.entity,
            "sql": result.sql,
            "columns": result.columns,
            "rows": result.rows,
            "rowCount": result.row_count,
        },
        message="SQL result loaded successfully.",
        status_code=200,
        metadata={"database": settings.fabric_database},
        trace_id=getattr(request.state, "request_id", None),
    )
    return BaseResponse[SqlResultResponse, dict].model_validate(payload)