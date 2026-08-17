from fastapi import APIRouter, Request

from leitesol_api.application.get_system_status import GetSystemStatus
from leitesol_api.interfaces.responses import build_response_payload
from leitesol_api.interfaces.schemas import BaseResponse, HealthStatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=BaseResponse[HealthStatusResponse, dict])
def read_health(request: Request) -> BaseResponse[HealthStatusResponse, dict]:
    use_case = GetSystemStatus()
    status = use_case.execute()
    payload = build_response_payload(
        data={
            "service": status.service,
            "status": status.status,
            "version": status.version,
        },
        message="Health check completed successfully.",
        status_code=200,
        metadata={"path": request.url.path},
        trace_id=getattr(request.state, "request_id", None),
    )
    return BaseResponse[HealthStatusResponse, dict].model_validate(payload)
