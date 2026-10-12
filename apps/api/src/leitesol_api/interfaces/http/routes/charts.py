from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from leitesol_agent.application.charts import ChartDataError, build_chart_specification
from pydantic import BaseModel, Field

from leitesol_api.infrastructure.auth import verify_token
from leitesol_api.interfaces.responses import build_response_payload

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(verify_token)],
)


class ChartRequest(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=100)
    rows: list[dict[str, object]] = Field(max_length=1000)
    category_column: str = Field(alias="categoryColumn", min_length=1, max_length=100)
    value_columns: list[str] = Field(alias="valueColumns", min_length=1, max_length=10)
    chart_type: Literal["auto", "bar", "line", "pie"] = Field(default="auto", alias="chartType")
    title: str | None = Field(default=None, max_length=160)


@router.post("/chart")
def create_chart(
    chart_request: ChartRequest,
    request: Request,
) -> JSONResponse:
    try:
        specification = build_chart_specification(
            columns=chart_request.columns,
            rows=chart_request.rows,
            category_column=chart_request.category_column,
            value_columns=chart_request.value_columns,
            chart_type=chart_request.chart_type,
            title=chart_request.title,
        )
    except ChartDataError as error:
        payload = build_response_payload(
            data=None,
            message="Chart data is invalid.",
            error=str(error),
            status_code=422,
            trace_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=422, content=payload)

    payload = build_response_payload(
        data=specification.to_dict(),
        message="Chart specification created successfully.",
        metadata={"source": "agent-query-result", "rendering": "client"},
        status_code=200,
        trace_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(status_code=200, content=payload)
