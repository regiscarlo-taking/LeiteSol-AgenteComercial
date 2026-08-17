from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentProfile:
    name: str
    purpose: str
