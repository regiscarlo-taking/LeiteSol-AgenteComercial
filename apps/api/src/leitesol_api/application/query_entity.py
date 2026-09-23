from typing import Protocol

from leitesol_api.domain.sql_result import CatalogEntity, SqlResult


class EntityQueryRepository(Protocol):
    def list_entities(self) -> list[CatalogEntity]: ...

    def query_entity(self, entity: str, limit: int = 100) -> SqlResult: ...


class QueryEntity:
    def __init__(self, repository: EntityQueryRepository) -> None:
        self._repository = repository

    def list_entities(self) -> list[CatalogEntity]:
        return self._repository.list_entities()

    def execute(self, entity: str, limit: int = 100) -> SqlResult:
        return self._repository.query_entity(entity=entity, limit=limit)
