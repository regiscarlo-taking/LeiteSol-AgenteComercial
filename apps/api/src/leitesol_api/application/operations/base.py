import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from leitesol_api.domain.agent import Notice, Period, Scope


class SqlFetcher(Protocol):
    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...


@dataclass(slots=True)
class OperationResult:
    period: Period | None = None
    main_block: dict[str, Any] | None = None
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    question_to_user: str | None = None

    @classmethod
    def clarification(cls, question: str) -> "OperationResult":
        return cls(question_to_user=question)


class OperationHandler(Protocol):
    operation_id: str

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult: ...


def normalize_term(text: str) -> str:
    """Maiúsculas e sem acento - mesma normalização de vw_produto_termo.TermoNormalizado."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(stripped.upper().split())


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end_exclusive(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # 29-02 em ano não bissexto.
        return value.replace(year=value.year + years, day=28)
