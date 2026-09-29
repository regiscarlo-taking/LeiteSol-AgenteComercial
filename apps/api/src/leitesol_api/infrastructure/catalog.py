"""Leitura do catálogo do agente (IA_COMERCIAL.AGT_*) com cache em memória.

O catálogo muda por carga (10_carga_catalogo_agente.sql), não por pergunta:
um TTL curto evita ir ao Warehouse a cada chamada sem exigir restart quando
a carga for refeita.
"""

import threading
import time
from collections import defaultdict
from typing import Any, Protocol

from leitesol_api.domain.agent import Catalog, Operation, Parameter

OPERATIONS_SQL = """
    SELECT operacao_id, skill_id, intencao_id, nome_tecnico, intencao_negocio, alertas
    FROM [IA_COMERCIAL].[AGT_OPERACAO]
"""
PARAMETERS_SQL = """
    SELECT operacao_id, parametro, tipo, obrigatorio, dominio_valores, valor_default, descricao
    FROM [IA_COMERCIAL].[AGT_OPERACAO_PARAMETRO]
"""
EXAMPLES_SQL = """
    SELECT operacao_id, pergunta_exemplo
    FROM [IA_COMERCIAL].[AGT_INTENCAO_EXEMPLO]
"""
RULES_SQL = """
    SELECT regra_id, regra_canonica
    FROM [IA_COMERCIAL].[AGT_REGRA_TRANSVERSAL]
"""


class SqlFetcher(Protocol):
    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_catalog(
    operations: list[dict[str, Any]],
    parameters: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> Catalog:
    params_by_op: dict[str, list[Parameter]] = defaultdict(list)
    for row in parameters:
        params_by_op[row["operacao_id"]].append(
            Parameter(
                name=row["parametro"],
                kind=(row["tipo"] or "").strip().lower(),
                # "S" = obrigatório; qualquer outro valor ("N", "Condicional"...) não bloqueia.
                required=(row["obrigatorio"] or "").strip().upper() == "S",
                domain=_text(row["dominio_valores"]),
                default=_text(row["valor_default"]),
                description=_text(row["descricao"]),
            )
        )
    examples_by_op: dict[str, list[str]] = defaultdict(list)
    for row in examples:
        examples_by_op[row["operacao_id"]].append(row["pergunta_exemplo"])

    return Catalog(
        operations=tuple(
            Operation(
                operation_id=row["operacao_id"],
                skill_id=row["skill_id"],
                intent_id=row["intencao_id"],
                technical_name=row["nome_tecnico"],
                business_intent=row["intencao_negocio"],
                alerts=_text(row["alertas"]),
                parameters=tuple(params_by_op.get(row["operacao_id"], ())),
                examples=tuple(examples_by_op.get(row["operacao_id"], ())),
            )
            for row in sorted(operations, key=lambda item: item["operacao_id"])
        ),
        transversal_rules={row["regra_id"]: row["regra_canonica"] for row in rules},
    )


class CatalogRepository:
    def __init__(self, fetcher: SqlFetcher, ttl_seconds: int = 600) -> None:
        self._fetcher = fetcher
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cached: Catalog | None = None
        self._loaded_at = 0.0

    def get(self) -> Catalog:
        with self._lock:
            if self._cached is None or time.monotonic() - self._loaded_at > self._ttl:
                self._cached = build_catalog(
                    self._fetcher.fetch(OPERATIONS_SQL),
                    self._fetcher.fetch(PARAMETERS_SQL),
                    self._fetcher.fetch(EXAMPLES_SQL),
                    self._fetcher.fetch(RULES_SQL),
                )
                self._loaded_at = time.monotonic()
            return self._cached
