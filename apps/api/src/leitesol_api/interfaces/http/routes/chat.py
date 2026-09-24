from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from leitesol_api.infrastructure.auth import verify_token
from leitesol_api.infrastructure.fabric import (
    EntityNotAllowedError,
    FabricConnectionError,
    FabricSqlConnection,
)
from leitesol_api.infrastructure.gemini import GeminiError, get_gemini_client
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload
from leitesol_api.interfaces.schemas import BaseResponse, ChatQueryRequest, ChatQueryResponse

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(verify_token)])


@router.post("/query", response_model=BaseResponse[ChatQueryResponse, dict])
def query_chat(
    question: ChatQueryRequest,
    request: Request,
) -> BaseResponse[ChatQueryResponse, dict] | JSONResponse:
    settings = get_settings()
    try:
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
        gemini = get_gemini_client()
        entity = gemini.select_entity(question.question)
        columns = repository.describe_entity(entity)
        plan = gemini.plan_query(question.question, entity=entity, columns=columns)
        result = repository.query_entity(
            plan.entity,
            limit=plan.limit,
            order_by=plan.order_by,
            order_direction=plan.order_direction,
        )
    except GeminiError as error:
        return JSONResponse(status_code=503, content=build_response_payload(
            data=None, message="Gemini is unavailable.", error=str(error), status_code=503,
            trace_id=getattr(request.state, "request_id", None),
        ))
    except EntityNotAllowedError as error:
        return JSONResponse(status_code=400, content=build_response_payload(
            data=None, message="Query plan is not allowed.", error=str(error), status_code=400,
            trace_id=getattr(request.state, "request_id", None),
        ))
    except FabricConnectionError as error:
        return JSONResponse(
            status_code=503,
            content=build_response_payload(
                data=None,
                message="Fabric warehouse is unavailable.",
                error=str(error),
                status_code=503,
                trace_id=getattr(request.state, "request_id", None),
            ),
        )

    payload = build_response_payload(
        data={
            "answer": plan.answer,
            "sqlResult": {
                "entity": result.entity,
                "sql": result.sql,
                "columns": result.columns,
                "rows": result.rows,
                "rowCount": result.row_count,
            },
        },
        message="Chat query processed successfully.",
        status_code=200,
        metadata={"database": settings.fabric_database},
        trace_id=getattr(request.state, "request_id", None),
    )
    return BaseResponse[ChatQueryResponse, dict].model_validate(payload)
