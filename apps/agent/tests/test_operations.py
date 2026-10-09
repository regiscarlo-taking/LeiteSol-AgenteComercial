from datetime import date, datetime
from typing import Any

import pytest

from leitesol_agent.application.operations.monthly_series import MonthlySeries, months_back
from leitesol_agent.application.operations.product_mix import ProductMix, window
from leitesol_agent.application.operations.rank_clients import RankClients
from leitesol_agent.application.operations.returning_clients import ReturningClients
from leitesol_agent.application.operations.sellers_below_average import (
    SellersBelowAverage,
    shape_rows as sellers_shape,
)
from leitesol_agent.application.parameters import validate_parameters
from leitesol_agent.domain.models import Operation, Parameter, Scope

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
        (ProductMix(), {"escopo_cliente": "000001", "filtro_produto": "xpto"}),
    ],
)
def test_unknown_product_term_becomes_clarification(handler, values) -> None:
    # Série: 1ª consulta é o calendário; nas demais o produto é resolvido antes.
    responses = [LAST_CLOSED, [], []] if isinstance(handler, MonthlySeries) else [[], []]
    result = handler.run(CheckingFetcher(responses), values, FULL)

    assert result.question_to_user


# ------------------------------------------------------------------ mix (OP11)

def mix_row(item, familia, ordem, fat_rs, fat_kg, meses=1, ultima="2026-08-01", produto=None):
    return {"item_id": item, "produto": produto or f"Produto {item}", "familia": familia,
            "grupamento": "G", "subtotal": "S", "ordem_subtotal": 1, "ordem_grupamento": 1,
            "ordem_familia": ordem, "uf": "SP", "fat_rs": fat_rs, "fat_kg": fat_kg,
            "meses_com_compra": meses, "ultima_compra": ultima}


MIX_ROWS = [
    mix_row("A", ".02 ZL LPI", 2, 500.0, 900.0),
    mix_row("B", ".01 LPI", 1, 100.0, 50.0),
    mix_row("C", ".01 LPI", 1, 400.0, 300.0, meses=3),
    mix_row("D", None, None, 1000.0, 2000.0),
]


def test_mix_window_skips_current_month_and_follows_closing() -> None:
    # Outubro aberto e setembro ainda não fechado: a janela termina em agosto.
    assert window(date(2026, 10, 9), 3, date(2026, 8, 1), False) == (
        date(2026, 6, 1), date(2026, 9, 1))
    assert window(date(2026, 10, 9), 3, date(2026, 9, 1), False) == (
        date(2026, 7, 1), date(2026, 10, 1))
    assert window(date(2026, 10, 9), 3, date(2026, 9, 1), True) == (
        date(2026, 8, 1), date(2026, 11, 1))


def test_mix_default_order_is_tree_then_kg() -> None:
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, list(MIX_ROWS)])
    result = ProductMix().run(
        fetcher,
        {"escopo_cliente": "000001", "data_referencia": date(2026, 10, 9),
         "nivel_produto": "sku", "janela_meses": 3},
        CARTEIRA,
    )

    sql, params = fetcher.calls[-1]
    assert "HAVING MAX(CASE WHEN fat_rs > 0 THEN 1 ELSE 0 END) = 1" in sql
    assert "GROUP BY p.ProdutoId, f.Data" in sql
    assert params[:2] == (date(2026, 6, 1), date(2026, 9, 1))
    assert "000123" in params and "000001" in params
    lines = result.main_block["linhas"]
    # .01 LPI (C antes de B por KG), depois .02 ZL LPI, e o item sem árvore por último.
    assert [line["item_id"] for line in lines] == ["C", "B", "A", "D"]
    assert lines[0]["participacao_kg_pct"] == 9.23  # 300 de 3.250 KG
    assert lines[0]["meses_com_compra"] == 3
    assert lines[0]["ultima_compra"] == "2026-08"
    assert "MIX_PRESENCA" in codes(result)
    assert result.period.last_closed_month == "2026-08"


def test_mix_fat_rs_orders_inside_family_by_rs() -> None:
    rows = [mix_row("B", ".01 LPI", 1, 400.0, 50.0), mix_row("C", ".01 LPI", 1, 100.0, 300.0)]
    result = ProductMix().run(
        CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows]),
        {"escopo_cliente": "x", "data_referencia": date(2026, 10, 9),
         "metrica_principal": "fat_rs"},
        FULL,
    )

    assert [line["item_id"] for line in result.main_block["linhas"]] == ["B", "C"]


@pytest.mark.parametrize(
    "ordering, expected",
    [
        ("maior volume", ["D", "A", "C", "B"]),
        ("faturamento em R$", ["D", "A", "C", "B"]),
        ("meses com compra", ["C", "D", "A", "B"]),
        ("descrição", ["A", "B", "C", "D"]),
    ],
)
def test_mix_alternative_orderings(ordering, expected) -> None:
    result = ProductMix().run(
        CheckingFetcher([LAST_CLOSED, NOT_OPEN, list(MIX_ROWS)]),
        {"escopo_cliente": "x", "data_referencia": date(2026, 10, 9), "ordenacao": ordering},
        FULL,
    )

    assert [line["item_id"] for line in result.main_block["linhas"]] == expected


def test_mix_unknown_ordering_and_subgroup_become_questions() -> None:
    values = {"escopo_cliente": "x", "data_referencia": date(2026, 10, 9)}
    by_color = ProductMix().run(
        CheckingFetcher([LAST_CLOSED, NOT_OPEN, list(MIX_ROWS)]),
        {**values, "ordenacao": "cor"},
        FULL,
    )
    subgroup = ProductMix().run(CheckingFetcher([]), {**values, "nivel_produto": "subgrupo"}, FULL)

    assert "cor" in by_color.question_to_user
    assert "grupamento" in subgroup.question_to_user


def test_mix_family_level_drops_product_column_and_warns_status() -> None:
    rows = [mix_row(".01 LPI", ".01 LPI", 1, 100.0, 10.0)]
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows])
    result = ProductMix().run(
        fetcher,
        {"escopo_cliente": "x", "data_referencia": date(2026, 10, 9), "nivel_produto": "familia",
         "status_produto": "bloqueado"},
        FULL,
    )

    assert "GROUP BY p.Familia, f.Data" in fetcher.calls[-1][0]
    assert "produto" not in result.main_block["linhas"][0]
    assert "produto" not in {column["id"] for column in result.main_block["colunas"]}
    assert "STATUS_PRODUTO" in codes(result)


def test_mix_without_purchase_and_partial_month() -> None:
    result = ProductMix().run(
        CheckingFetcher([LAST_CLOSED, [{"TemParcial": 1}], []]),
        {"escopo_cliente": "x", "data_referencia": date(2025, 2, 1), "incluir_mes_atual": True},
        FULL,
    )

    assert {"SEM_COMPRA", "TR02", "BASE2025"} <= codes(result)
    assert "PARTICIPACAO" not in codes(result)


def test_enum_domain_is_case_insensitive() -> None:
    op = Operation("OP11", "SK03", "x", "x", "x", None,
                   parameters=(Parameter("nivel_produto", "enum", False,
                                         "SKU|FAMILIA|GRUPO|SUBGRUPO", "SKU", "Nivel"),))

    assert validate_parameters(op, {}).values == {"nivel_produto": "sku"}
    mixed_case = validate_parameters(op, {"nivel_produto": "Familia"})
    assert mixed_case.values == {"nivel_produto": "familia"}
