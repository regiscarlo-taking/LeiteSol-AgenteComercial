from datetime import UTC, datetime
from typing import Generic, TypeVar

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
