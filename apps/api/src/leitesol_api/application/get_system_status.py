from leitesol_api.domain.system_status import SystemStatus
from leitesol_api.infrastructure.settings import get_settings


class GetSystemStatus:
    def execute(self) -> SystemStatus:
        settings = get_settings()
        return SystemStatus(
            service=settings.service_name,
            status="healthy",
            version=settings.api_version,
        )
