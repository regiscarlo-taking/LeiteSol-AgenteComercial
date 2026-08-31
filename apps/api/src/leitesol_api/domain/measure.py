from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Measure:
    measure_id: str
    friendly_name: str
    dax_name: str
    measure_type: str | None
    unit: str | None
    functional_rule: str | None
    dax_expression: str | None
    base_object: str | None
    dependencies: str | None
    bi_source: str | None
    agent_visible: str | None