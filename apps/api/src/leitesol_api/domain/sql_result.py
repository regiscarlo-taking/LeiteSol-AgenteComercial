from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SqlResult:
    entity: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int


@dataclass(frozen=True, slots=True)
class CatalogEntity:
    name: str
    schema: str
    table: str
    kind: str

    @property
    def qualified_name(self) -> str:
        return f"[{self.schema}].[{self.table}]"
