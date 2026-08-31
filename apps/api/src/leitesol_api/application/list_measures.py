from typing import Protocol

from leitesol_api.domain.measure import Measure


class MeasureRepository(Protocol):
    def list_top(self, limit: int = 100) -> list[Measure]: ...


class ListMeasures:
    def __init__(self, repository: MeasureRepository) -> None:
        self._repository = repository

    def execute(self) -> list[Measure]:
        return self._repository.list_top()