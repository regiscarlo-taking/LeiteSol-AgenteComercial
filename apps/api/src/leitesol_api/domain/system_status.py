from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SystemStatus:
    service: str
    status: str
    version: str
