from datetime import date, datetime
from typing import Any

import pytest

from leitesol_api.application.operations.monthly_series import MonthlySeries, months_back
from leitesol_api.application.operations.rank_clients import RankClients
from leitesol_api.application.operations.returning_clients import ReturningClients
from leitesol_api.application.operations.sellers_below_average import (
    SellersBelowAverage,
    shape_rows as sellers_shape,
)
from leitesol_api.application.parameters import validate_parameters
from leitesol_api.domain.agent import Operation, Parameter, Scope

FULL = Scope(sees_everything=True)
CARTEIRA = Scope(sees_everything=False, sellers=frozenset({"000123"}), teams=frozenset({"997"}))


class CheckingFetcher:
    """Devolve respostas por ordem e confere que cada ? do SQL tem parâmetro."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        assert sql.count("?") == len(params), f"{sql.count('?')} placeholders x {len(params)} params"
        self.calls.append((sql, params))
        return self.responses.pop(0) if self.responses else []


LAST_CLOSED = [{"UltimaFechada": datetime(2026, 8, 1)}]
NOT_OPEN = [{"TemParcial": 0}]


def codes(result) -> set[str]:
    return {notice.code for notice in result.notices}


# ------------------------------------------------------------------ parâmetros

def test_month_int_and_bool_parameters() -> None:
    op = Operation(
        "OPX", "SK", "x", "x", "x", None,
        parameters=(
            Parameter("mes", "date", True, "AAAA-MM", None, "Mes"),
            Parameter("janela", "int", False, ">0", "3", "Janela"),
            Parameter("parcial", "bool", False, "S|N", "N", "Parcial"),
        ),
    )
    result = validate_parameters(op, {"mes": "2026-07"})

    assert result.values == {"mes": date(2026, 7, 1), "janela": 3, "parcial": False}


def test_missing_month_asks_for_a_month() -> None:
    op = Operation("OPX", "SK", "x", "x", "x", None,
                   parameters=(Parameter("mes", "date", True, "AAAA-MM", None, "Mes"),))

    assert "Qual mês" in validate_parameters(op, {}).questions[0]


# ------------------------------------------------------------------ ranking

def test_ranking_keeps_ties_and_computes_share() -> None:
    rows = [
        {"posicao": 1, "participante_id": "A", "participante": "Rede A", "uf": "SP",
         "fat_rs": 300.0, "fat_kg": 600.0, "total_escopo": 1000.0},
        {"posicao": 2, "participante_id": "B", "participante": "Rede B", "uf": "Várias",
         "fat_rs": 200.0, "fat_kg": 200.0, "total_escopo": 1000.0},
        {"posicao": 2, "participante_id": "C", "participante": "Rede C", "uf": "MG",
         "fat_rs": 100.0, "fat_kg": 200.0, "total_escopo": 1000.0},
    ]
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows])
    result = RankClients().run(
        fetcher,
        {"periodo_inicio": date(2026, 1, 1), "periodo_fim": date(2026, 6, 30),
         "metrica_ranking": "fat_kg", "granularidade_cliente": "rede", "top_n": 2, "uf": "sp"},
        CARTEIRA,
    )

    sql = fetcher.calls[-1][0]
    assert "RANK() OVER (ORDER BY fat_kg DESC)" in sql
    assert "GROUP BY c.Rede" in sql
    assert "EMPATE" in codes(result)
    first = result.main_block["linhas"][0]
    assert first["participacao_pct"] == 60.0
    assert first["fat_tons"] == 0.6


def test_ranking_without_positive_total_has_no_share() -> None:
    rows = [{"posicao": 1, "participante_id": "A", "participante": "A", "uf": "SP",
             "fat_rs": -10.0, "fat_kg": -5.0, "total_escopo": -5.0}]
    result = RankClients().run(
        CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows]),
        {"periodo_inicio": date(2026, 1, 1), "periodo_fim": date(2026, 1, 31)},
        FULL,
    )

    assert result.main_block["linhas"][0]["participacao_pct"] is None
    assert "PARTICIPACAO" in codes(result)


# ------------------------------------------------------------------ série 12 meses

def test_months_back_crosses_the_year() -> None:
    months = months_back(date(2026, 2, 1), 4)

    assert months == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]


def test_series_fills_missing_months_with_zero_and_stops_at_last_closed() -> None:
    rows = [
        {"competencia": "2026-07-01T00:00:00", "fat_rs": 100.0, "fat_kg": 10.0},
        {"competencia": "2026-08-01T00:00:00", "fat_rs": 150.0, "fat_kg": 12.0},
    ]
    fetcher = CheckingFetcher([LAST_CLOSED, rows])
    result = MonthlySeries().run(
        fetcher, {"competencia_referencia": date(2026, 9, 1), "metrica": "fat_rs"}, FULL
    )

    lines = result.main_block["linhas"]
    assert len(lines) == 12
    assert lines[-1]["competencia"] == "2026-08"
    assert lines[0]["competencia"] == "2025-09"
    assert lines[-3]["fat_rs"] == 0.0
    assert lines[-1]["fat_rs_variacao_pct"] == 50.0
    assert {"TR01", "FORMATO"} <= codes(result)
    assert "BASE2025" not in codes(result)


def test_series_warns_when_window_precedes_base() -> None:
    result = MonthlySeries().run(
        CheckingFetcher([LAST_CLOSED, []]), {"competencia_referencia": date(2025, 6, 1)}, FULL
    )

    assert "BASE2025" in codes(result)


# ------------------------------------------------------------------ vendedores

def test_average_counts_months_without_sale_as_zero() -> None:
    rows = [
        # 300 em 3 meses = média 100; mês com 80 = queda de 20%.
        {"vendedor_id": "1", "vendedor": "Ana", "papel": "RCA",
         "fat_rs_mes": 80.0, "fat_rs_3m": 300.0, "fat_kg_mes": 30.0, "fat_kg_3m": 60.0},
        {"vendedor_id": "2", "vendedor": "Bia", "papel": "RCA",
         "fat_rs_mes": 50.0, "fat_rs_3m": 0.0, "fat_kg_mes": 5.0, "fat_kg_3m": 0.0},
        {"vendedor_id": "3", "vendedor": "Caio", "papel": "Gestor",
         "fat_rs_mes": 500.0, "fat_rs_3m": 300.0, "fat_kg_mes": 90.0, "fat_kg_3m": 90.0},
    ]
    main_block, exceptions, others = sellers_shape(rows, "ambas", 3)

    ana = main_block["linhas"][0]
    assert ana["fat_rs_media"] == 100.0
    assert ana["fat_rs_variacao_pct"] == -20.0
    assert ana["fat_rs_situacao"] == "queda"
    # KG: 30 no mês contra média 20 = acima; a queda é avaliada por métrica.
    assert ana["fat_kg_situacao"] == "acima"
    assert exceptions[0]["linhas"][0]["vendedor"] == "Bia"
    assert others == 1


def test_sellers_query_filters_role_and_scope() -> None:
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, []])
    result = SellersBelowAverage().run(
        fetcher, {"mes_referencia": date(2026, 7, 1), "papel_comercial": "representante"}, CARTEIRA
    )

    sql, params = fetcher.calls[-1]
    assert "r.PapelComercial IN (?)" in sql
    assert "RCA" in params and "000123" in params
    assert result.period.comparison_start == date(2026, 4, 1)
    assert "SEM_TRANSACAO" in codes(result)


# ------------------------------------------------------------------ retomada

def test_returning_clients_window_and_notices() -> None:
    rows = [{"cliente_id": "0001-01", "cliente": "Mercado X", "cnpj": "1", "rede": "X", "uf": "SP",
             "primeira_compra_cadastro": None, "competencia_compra": "2026-07-01",
             "fat_rs": 10.5, "fat_kg": 2.5}]
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows])
    result = ReturningClients().run(fetcher, {"periodo_referencia": date(2026, 7, 1)}, FULL)

    sql, params = fetcher.calls[-1]
    assert params[0] == date(2026, 1, 1)  # 6 meses antes de julho
    assert "h.fat_rs > 0" in sql  # ausência mês a mês, não pela soma
    line = result.main_block["linhas"][0]
    assert line["primeira_compra_cadastro"] == "não informada"
    assert line["fat_kg"] == 3
    assert "BASE2025" not in codes(result)


def test_returning_clients_warns_when_window_precedes_base() -> None:
    result = ReturningClients().run(
        CheckingFetcher([LAST_CLOSED, NOT_OPEN, []]), {"periodo_referencia": date(2025, 3, 1)}, FULL
    )

    assert "BASE2025" in codes(result)


@pytest.mark.parametrize(
    "handler, values",
    [
        (RankClients(), {"periodo_inicio": date(2026, 1, 1), "periodo_fim": date(2026, 1, 31),
                         "filtro_produto": "xpto"}),
        (MonthlySeries(), {"filtro_produto": "xpto"}),
        (SellersBelowAverage(), {"mes_referencia": date(2026, 7, 1), "filtro_produto": "xpto"}),
        (ReturningClients(), {"periodo_referencia": date(2026, 7, 1), "filtro_produto": "xpto"}),
    ],
)
def test_unknown_product_term_becomes_clarification(handler, values) -> None:
    # Série: 1ª consulta é o calendário; nas demais o produto é resolvido antes.
    responses = [LAST_CLOSED, [], []] if isinstance(handler, MonthlySeries) else [[], []]
    result = handler.run(CheckingFetcher(responses), values, FULL)

    assert result.question_to_user
