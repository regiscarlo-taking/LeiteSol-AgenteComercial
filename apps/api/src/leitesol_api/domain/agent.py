"""Tipos do agente: catálogo de operações, alçada e envelope de resposta.

Os nomes dos campos do envelope seguem o contrato de dados
(06-contrato-dados-backend.md, §6), que é o que o front consome.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class ResponseStatus(StrEnum):
    ANSWERED = "respondida"
    CLARIFICATION = "esclarecimento"
    OUT_OF_SCOPE = "fora_de_escopo"
    NO_SCOPE = "sem_alcada"
    ERROR = "erro"


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    kind: str
    required: bool
    domain: str | None
    default: str | None
    description: str | None

    @property
    def enum_values(self) -> tuple[str, ...]:
        if self.kind != "enum" or not self.domain:
            return ()
        return tuple(value.strip() for value in self.domain.split("|") if value.strip())


@dataclass(frozen=True, slots=True)
class Operation:
    operation_id: str
    skill_id: str
    intent_id: str
    technical_name: str
    business_intent: str
    alerts: str | None
    parameters: tuple[Parameter, ...] = ()
    examples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Catalog:
    operations: tuple[Operation, ...]
    transversal_rules: dict[str, str]

    def by_intent(self, intent_id: str) -> Operation | None:
        return next((op for op in self.operations if op.intent_id == intent_id), None)


@dataclass(frozen=True, slots=True)
class Scope:
    """Alçada do usuário: ou vê tudo, ou vê só a carteira de vendedores (RT34)."""

    sees_everything: bool
    sellers: frozenset[str] = frozenset()
    teams: frozenset[str] = frozenset()

    @property
    def description(self) -> str:
        if self.sees_everything:
            return "visão completa"
        return "dentro da sua carteira"


@dataclass(frozen=True, slots=True)
class Notice:
    code: str
    origin: str
    text: str


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end_exclusive: date
    comparison_start: date | None = None
    comparison_end_exclusive: date | None = None
    partial: bool = False
    last_closed_month: str | None = None


@dataclass(slots=True)
class AgentResponse:
    correlation_id: str
    status: ResponseStatus
    operation: Operation | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    period: Period | None = None
    scope: Scope | None = None
    main_block: dict[str, Any] | None = None
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    narrative: str | None = None
    question_to_user: str | None = None

    def to_contract(self) -> dict[str, Any]:
        period = None
        if self.period is not None:
            last_day = date.fromordinal(self.period.end_exclusive.toordinal() - 1)
            comparison = None
            if self.period.comparison_start and self.period.comparison_end_exclusive:
                comparison = {
                    "inicio": self.period.comparison_start.isoformat(),
                    "fim_exclusivo": self.period.comparison_end_exclusive.isoformat(),
                }
            period = {
                "inicio": self.period.start.isoformat(),
                "fim_exclusivo": self.period.end_exclusive.isoformat(),
                "fim_exibicao": last_day.isoformat(),
                "comparacao": comparison,
                "periodo_parcial": self.period.partial,
                "ultima_competencia_fechada": self.period.last_closed_month,
            }
        return {
            "correlation_id": self.correlation_id,
            "status": self.status.value,
            "operacao": (
                {
                    "id": self.operation.operation_id,
                    "nome_tecnico": self.operation.technical_name,
                    "skill": self.operation.skill_id,
                }
                if self.operation
                else None
            ),
            "parametros_interpretados": self.parameters,
            "periodo": period,
            "recorte": (
                {
                    "tipo": "total" if self.scope.sees_everything else "carteira",
                    "descricao": self.scope.description,
                }
                if self.scope
                else None
            ),
            "dados": (
                {"principal": self.main_block, "excecoes": self.exceptions}
                if self.main_block is not None
                else None
            ),
            "avisos": [
                {"codigo": notice.code, "origem": notice.origin, "texto": notice.text}
                for notice in self.notices
            ],
            "cobertura": None,
            "narrativa": self.narrative,
            "pergunta_ao_usuario": self.question_to_user,
        }
