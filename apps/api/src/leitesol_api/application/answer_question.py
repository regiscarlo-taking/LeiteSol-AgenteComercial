"""Fluxo de uma pergunta (contrato de dados §2).

1 autenticação (rota) -> 2 alçada -> 3 intenção -> 4 parâmetros ->
5 execução -> 6 ressalvas -> 7 redação. Só as etapas 3, 4 e 7 usam a LLM;
alçada, validação, execução e ressalvas são código determinístico.
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from leitesol_api.application.operations.base import OperationHandler, SqlFetcher
from leitesol_api.application.parameters import validate_parameters
from leitesol_api.domain.agent import (
    AgentResponse,
    Catalog,
    Notice,
    Operation,
    ResponseStatus,
    Scope,
)

logger = logging.getLogger("leitesol.api.agent")

OUT_OF_SCOPE_TEXT = (
    "Essa pergunta está fora do que o agente responde hoje. Ele cobre faturamento "
    "(valores, volume, comparações, clientes, produtos e vendedores) dentro das "
    "perguntas mapeadas com a área comercial."
)
NO_SCOPE_TEXT = (
    "Seu usuário não tem alçada comercial cadastrada, então o agente não pode mostrar "
    "dados. Peça à Administração de Vendas para incluir seu e-mail na tabela de acesso."
)
# Grão mensal (RT17): vale para toda resposta de faturamento.
MONTHLY_GRAIN_TEXT = "Faturamento consolidado por mês; não há resposta por dia."


class CatalogProvider(Protocol):
    def get(self) -> Catalog: ...


class ScopeProvider(Protocol):
    def resolve(self, *, email: str | None, full_access: bool) -> Scope | None: ...


class LanguageModel(Protocol):
    def classify_intent(self, question: str, catalog: Catalog) -> str | None: ...

    def extract_parameters(
        self, question: str, operation: Operation, today: date
    ) -> dict[str, Any]: ...

    def compose_narrative(
        self, question: str, operation: Operation, contract: dict[str, Any]
    ) -> str: ...


class AnswerQuestion:
    def __init__(
        self,
        *,
        catalog: CatalogProvider,
        scopes: ScopeProvider,
        llm: LanguageModel,
        fetcher: SqlFetcher,
        handlers: dict[str, OperationHandler],
        today: Callable[[], date] = date.today,
    ) -> None:
        self._catalog = catalog
        self._scopes = scopes
        self._llm = llm
        self._fetcher = fetcher
        self._handlers = handlers
        self._today = today

    def execute(
        self,
        *,
        question: str,
        email: str | None,
        full_access: bool,
        correlation_id: str,
    ) -> AgentResponse:
        # 2. Alçada antes de qualquer dado: sem recorte, não há resposta.
        scope = self._scopes.resolve(email=email, full_access=full_access)
        if scope is None:
            return AgentResponse(
                correlation_id=correlation_id,
                status=ResponseStatus.NO_SCOPE,
                narrative=NO_SCOPE_TEXT,
            )

        # 3. Intenção.
        catalog = self._catalog.get()
        intent = self._llm.classify_intent(question, catalog)
        operation = catalog.by_intent(intent) if intent else None
        if operation is None:
            return AgentResponse(
                correlation_id=correlation_id,
                status=ResponseStatus.OUT_OF_SCOPE,
                scope=scope,
                narrative=OUT_OF_SCOPE_TEXT,
            )

        handler = self._handlers.get(operation.operation_id)
        if handler is None:
            return AgentResponse(
                correlation_id=correlation_id,
                status=ResponseStatus.ERROR,
                operation=operation,
                scope=scope,
                narrative=(
                    f"Entendi a pergunta ({operation.business_intent.lower()}), mas essa "
                    "análise ainda não está disponível nesta versão do agente."
                ),
            )

        # 4. Parâmetros: a LLM propõe, o catálogo valida.
        raw = self._llm.extract_parameters(question, operation, self._today())
        validated = validate_parameters(operation, raw)
        if not validated.is_complete:
            return AgentResponse(
                correlation_id=correlation_id,
                status=ResponseStatus.CLARIFICATION,
                operation=operation,
                parameters=_serializable(validated.values),
                scope=scope,
                question_to_user=" ".join(validated.questions),
            )

        # 5. Execução (única etapa que produz número).
        result = handler.run(self._fetcher, validated.values, scope)
        if result.question_to_user:
            return AgentResponse(
                correlation_id=correlation_id,
                status=ResponseStatus.CLARIFICATION,
                operation=operation,
                parameters=_serializable(validated.values),
                scope=scope,
                question_to_user=result.question_to_user,
            )

        # 6. Ressalvas: vêm do catálogo e da execução, não da LLM.
        notices = [Notice("RT17", "regra_transversal", MONTHLY_GRAIN_TEXT), *result.notices]
        if operation.alerts:
            notices.append(Notice(operation.operation_id, "operacao", operation.alerts))

        response = AgentResponse(
            correlation_id=correlation_id,
            status=ResponseStatus.ANSWERED,
            operation=operation,
            parameters=_serializable(validated.values),
            period=result.period,
            scope=scope,
            main_block=result.main_block,
            exceptions=result.exceptions,
            notices=notices,
        )

        # 7. Redação. Se a LLM falhar, a resposta sai com os dados e sem texto.
        try:
            response.narrative = self._llm.compose_narrative(
                question, operation, response.to_contract()
            )
        except Exception:
            logger.exception("Narrative composition failed correlation_id=%s", correlation_id)
            response.notices.append(
                Notice("NARRATIVA", "resposta", "O resumo em texto não pôde ser gerado; os dados estão abaixo.")
            )
        return response


def _serializable(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in values.items()
    }
