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
