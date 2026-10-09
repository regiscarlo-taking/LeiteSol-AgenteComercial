from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from leitesol_agent.application.operations.monthly_series import build_query
from leitesol_agent.application.parameters import validate_parameters
from leitesol_agent.application.where_filters import (
    WhereFilter,
    compile_where_filters,
    validate_where_filters,
)
from leitesol_agent.domain.models import Operation, Scope
from leitesol_agent.infrastructure import gemini
from leitesol_agent.infrastructure.gemini import GeminiLanguageModel
from leitesol_agent.infrastructure.view_knowledge import retrieve_view_context

FULL = Scope(sees_everything=True)
CARTEIRA = Scope(sees_everything=False, sellers=frozenset({"000123"}))
OPERATION = Operation("OP12", "SK", "comparar", "comparar_vendas", "Comparar faturamento", None)


def test_where_filter_is_validated_and_compiled_as_a_parameter() -> None:
    filters, questions = validate_where_filters(
        [
            {"campo": "cliente.uf", "operador": "eq", "valor": "sp"},
            {"campo": "produto.peso_volume_unitario", "operador": "gte", "valor": "1.5"},
        ]
    )

    assert questions == []
    assert filters == [
        WhereFilter("cliente.uf", "eq", "sp"),
        WhereFilter("produto.peso_volume_unitario", "gte", Decimal("1.5")),
    ]
    sql, params = build_query(
        {"where": filters},
        date(2026, 1, 1),
        date(2026, 2, 1),
        FULL,
    )

    assert "UPPER(c.UF) = ?" in sql
    assert "p.PesoVolumeUnitario >= ?" in sql
    assert params[-2:] == ["SP", Decimal("1.5")]

    scoped_sql, scoped_params = build_query(
        {"where": filters},
        date(2026, 1, 1),
        date(2026, 2, 1),
        CARTEIRA,
    )
    assert "c.RCAAtual IN (?)" in scoped_sql
    assert scoped_params[-3:] == ["000123", "SP", Decimal("1.5")]


def test_where_filter_text_search_does_not_interpret_sql_or_like_wildcards() -> None:
    filters, questions = validate_where_filters(
        [
            {
                "campo": "cliente.nome",
                "operador": "contains",
                "valor": "X%' OR 1=1 --",
            }
        ]
    )
    clauses, params = compile_where_filters(filters)

    assert questions == []
    assert clauses == ["CHARINDEX(?, UPPER(c.RazaoSocial)) > 0"]
    assert params == ["X%' OR 1=1 --"]


def test_unrecognized_where_field_requires_clarification() -> None:
    filters, questions = validate_where_filters(
        [{"campo": "cliente.nome; DROP TABLE", "operador": "eq", "valor": "x"}]
    )

    assert filters == []
    assert questions


def test_invalid_where_operator_requires_clarification() -> None:
    filters, questions = validate_where_filters(
        [{"campo": "cliente.uf", "operador": "LIKE", "valor": "SP"}]
    )

    assert filters == []
    assert questions


def test_parameter_validation_keeps_filters_and_blocks_invalid_filters() -> None:
    operation = Operation("OPX", "SK", "x", "x", "x", None)
    valid = validate_parameters(
        operation,
        {"where": [{"campo": "produto.marca", "operador": "eq", "valor": "Marca A"}]},
    )
    invalid = validate_parameters(
        operation,
        {"where": [{"campo": "produto.marca", "operador": "gt", "valor": "Marca A"}]},
    )

    assert valid.is_complete
    assert valid.values["where"] == [WhereFilter("produto.marca", "eq", "Marca A")]
    assert not invalid.is_complete


def test_view_context_retrieval_includes_relevant_view_rules() -> None:
    context = retrieve_view_context("faturamento da região por marca")

    assert "vw_fato_faturamento" in context
    assert "vw_dim_cliente" in context
    assert "vw_dim_produto" in context
    assert "UFVenda" in context
    assert "RCAAtual" in context


def test_parameter_prompt_contains_view_context_and_where_allowlist(monkeypatch) -> None:
    request: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> httpx.Response:
        request.update(kwargs)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"where": []}'}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini.httpx, "post", post)

    GeminiLanguageModel("key", "gemini-test").extract_parameters(
        "Compare faturamento por UF e marca", OPERATION, date(2026, 9, 30)
    )

    prompt = request["json"]["contents"][0]["parts"][0]["text"]
    assert "vw_fato_faturamento" in prompt
    assert "vw_dim_cliente" in prompt
    assert "vw_dim_produto" in prompt
    assert "cliente.uf" in prompt
    assert "SQL" in prompt
