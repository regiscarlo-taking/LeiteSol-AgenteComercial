from datetime import UTC, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")
M = TypeVar("M")


class BaseRequest(BaseModel, Generic[T, M]):
    model_config = ConfigDict(populate_by_name=True)

    data: T | None = None
    metadata: M | None = None
    trace_id: str | None = Field(default=None, alias="traceId")
    timestamp: datetime | None = None


class BaseResponse(BaseModel, Generic[T, M]):
    model_config = ConfigDict(populate_by_name=True)

    data: T | None = None
    status_code: int = Field(alias="statusCode")
    message: str
    error: str | None = None
    success: bool = True
    trace_id: str = Field(alias="traceId")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: M | None = None


class HealthStatusResponse(BaseModel):
    service: str
    status: str
    version: str


class MeasureResponse(BaseModel):
    measure_id: str = Field(alias="measureId")
    friendly_name: str = Field(alias="friendlyName")
    dax_name: str = Field(alias="daxName")
    measure_type: str | None = Field(default=None, alias="type")
    unit: str | None = None
    functional_rule: str | None = Field(default=None, alias="functionalRule")
    dax_expression: str | None = Field(default=None, alias="daxExpression")
    base_object: str | None = Field(default=None, alias="baseObject")
    dependencies: str | None = None
    bi_source: str | None = Field(default=None, alias="biSource")
    agent_visible: str | None = Field(default=None, alias="agentVisible")

    model_config = ConfigDict(populate_by_name=True)


class EntityQueryRequest(BaseModel):
    entity: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=100, ge=1, le=100)


class CatalogEntityResponse(BaseModel):
    name: str
    schema_name: str = Field(alias="schema")
    table: str
    kind: str

    model_config = ConfigDict(populate_by_name=True)


class SqlResultResponse(BaseModel):
    entity: str
    sql: str | None = None
    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int = Field(alias="rowCount")

    model_config = ConfigDict(populate_by_name=True)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class GatewayRequestLogDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = Field(min_length=1, max_length=10)
    path: str = Field(min_length=1, max_length=2048)


class GatewayResponseLogDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_code: int = Field(alias="statusCode", ge=100, le=599)
    duration_ms: float = Field(alias="durationMs", ge=0)


class GatewayLogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    trace_id: str = Field(alias="traceId", min_length=1, max_length=64)
    timestamp: datetime
    severity: Literal["info", "warning", "error"]
    request: GatewayRequestLogDetails
    response: GatewayResponseLogDetails


class ChatQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class ChatQueryResponse(BaseModel):
    answer: str
    sql_result: SqlResultResponse = Field(alias="sqlResult")

    model_config = ConfigDict(populate_by_name=True)


class ChartSeriesResponse(BaseModel):
    name: str
    values: list[float | None]


class ChartAxisResponse(BaseModel):
    label: str
    data_key: str | None = Field(default=None, alias="dataKey")


class ChartSpecificationResponse(BaseModel):
    chart_type: str = Field(alias="chartType")
    title: str
    categories: list[str]
    series: list[ChartSeriesResponse]
    x_axis: ChartAxisResponse = Field(alias="xAxis")
    y_axis: ChartAxisResponse = Field(alias="yAxis")

    model_config = ConfigDict(populate_by_name=True)
