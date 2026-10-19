from datetime import date, datetime
from typing import Any

import pytest
from leitesol_agent.application.operations.average_price_per_kg import (
    AveragePricePerKg,
)
from leitesol_agent.application.operations.compare_previous_year import (
    CompareWithPreviousYear,
)
from leitesol_agent.application.operations.monthly_series import MonthlySeries, months_back
from leitesol_agent.application.operations.product_mix import ProductMix, window
from leitesol_agent.application.operations.rank_clients import RankClients
from leitesol_agent.application.operations.rank_representatives import RankRepresentatives
from leitesol_agent.application.operations.returning_clients import ReturningClients
from leitesol_agent.application.operations.sales_breakdowns import SalesBreakdowns
from leitesol_agent.application.operations.sellers_below_average import (
    SellersBelowAverage,
)
from leitesol_agent.application.operations.sellers_below_average import (
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


def test_comparison_window_uses_closed_months_and_previous_year() -> None:
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, []])

    result = CompareWithPreviousYear().run(
        fetcher,
        {"janela_meses": 3, "metrica": "ambas"},
        FULL,
    )

    assert result.period.start == date(2026, 6, 1)
    assert result.period.end_exclusive == date(2026, 9, 1)
    assert result.period.comparison_start == date(2025, 6, 1)
    assert result.period.comparison_end_exclusive == date(2025, 9, 1)
    assert result.period.partial is False
    assert fetcher.calls[-1][1][:4] == (
        date(2026, 6, 1),
        date(2026, 9, 1),
        date(2025, 6, 1),
        date(2025, 9, 1),
    )


def test_comparison_month_by_month_includes_total_period_row() -> None:
    fetcher = CheckingFetcher(
        [
            LAST_CLOSED,
            NOT_OPEN,
            [
                {
                    "comparison_month": 5,
                    "fat_rs_atual": 100.0,
                    "fat_rs_anterior": 90.0,
                    "fat_kg_atual": 50.0,
                    "fat_kg_anterior": 45.0,
                },
                {
                    "comparison_month": 7,
                    "fat_rs_atual": 120.0,
                    "fat_rs_anterior": 110.0,
                    "fat_kg_atual": 60.0,
                    "fat_kg_anterior": 55.0,
                },
            ],
        ]
    )

    result = CompareWithPreviousYear().run(
        fetcher,
        {
            "periodo_inicio": date(2026, 5, 1),
            "periodo_fim": date(2026, 7, 31),
        },
        FULL,
    )

    sql, _ = fetcher.calls[-1]
    lines = result.main_block["linhas"]
    assert "MONTH(f.Data) AS comparison_month" in sql
    assert "GROUP BY MONTH(f.Data)" in sql
    assert [line["comparison_month"] for line in lines] == [
        "05/2026",
        "06/2026",
        "07/2026",
        "Total do período",
    ]
    assert lines[1]["fat_rs_atual"] == 0.0
    assert lines[1]["fat_rs_anterior"] == 0.0
    assert lines[-1]["fat_rs_atual"] == 220.0
    assert lines[-1]["fat_rs_anterior"] == 200.0
    assert lines[-1]["fat_rs_variacao_abs"] == 20.0
    assert lines[-1]["fat_rs_variacao_pct"] == 10.0


# -------------------------------------------------------- preço médio por kg

def test_average_price_per_kg_divides_period_totals_and_preserves_scope() -> None:
    fetcher = CheckingFetcher(
        [
            LAST_CLOSED,
            [{"fat_rs": 900.0, "fat_kg": 300.0}],
        ]
    )
    result = AveragePricePerKg().run(
        fetcher,
        {"janela_meses": 6},
        CARTEIRA,
    )

    sql, params = fetcher.calls[-1]
    assert "SUM(f.Vendas_R - f.Dev_R) AS fat_rs" in sql
    assert "SUM(f.Vendas_Kg + f.Bonif_Kg - f.Dev_Kg) AS fat_kg" in sql
    assert "c.RCAAtual IN (?)" in sql
    assert params == (date(2026, 3, 1), date(2026, 9, 1), "000123")
    assert result.main_block["linhas"] == [
        {"fat_rs": 900.0, "fat_kg": 300, "preco_medio_kg": 3.0}
    ]
    assert result.period.start == date(2026, 3, 1)
    assert result.period.end_exclusive == date(2026, 9, 1)


def test_average_price_per_kg_does_not_report_zero_when_denominator_is_invalid() -> None:
    result = AveragePricePerKg().run(
        CheckingFetcher([LAST_CLOSED, [{"fat_rs": 300.0, "fat_kg": 0.0}]]),
        {"janela_meses": 6},
        FULL,
    )

    assert result.main_block["linhas"][0]["preco_medio_kg"] is None
    assert "PRECO_MEDIO_NAO_CALCULAVEL" in codes(result)


@pytest.mark.parametrize(
    ("window", "expected_start", "expected_end"),
    [
        (9, date(2025, 12, 1), date(2026, 9, 1)),
        (10, date(2025, 11, 1), date(2026, 9, 1)),
        (12, date(2025, 9, 1), date(2026, 9, 1)),
        (24, date(2024, 9, 1), date(2026, 9, 1)),
    ],
)
def test_average_price_per_kg_accepts_arbitrary_positive_window(
    window: int,
    expected_start: date,
    expected_end: date,
) -> None:
    fetcher = CheckingFetcher([LAST_CLOSED, [{"fat_rs": 600.0, "fat_kg": 200.0}]])

    result = AveragePricePerKg().run(fetcher, {"janela_meses": window}, FULL)

    assert result.question_to_user is None
    assert result.period.start == expected_start
    assert result.period.end_exclusive == expected_end


@pytest.mark.parametrize("window", [0, -1, True, 6.5, "10"])
def test_average_price_per_kg_rejects_invalid_window(window: Any) -> None:
    result = AveragePricePerKg().run(CheckingFetcher([]), {"janela_meses": window}, FULL)

    assert result.question_to_user
    assert "número positivo" in result.question_to_user


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

def test_ranking_applies_tie_break_and_computes_share() -> None:
    # Consulta devolve N + 1 linhas já ordenadas; B e C empatam em KG na 2ª posição
    # e B fica por ter mais R$ (regra da Adm. Vendas, AIC-289).
    rows = [
        {"posicao": 1, "participante_id": "A", "participante": "Rede A", "uf": "SP",
         "fat_rs": 300.0, "fat_kg": 600.0, "total_escopo": 1000.0},
        {"posicao": 2, "participante_id": "B", "participante": "Rede B", "uf": "Várias",
         "fat_rs": 200.0, "fat_kg": 200.0, "total_escopo": 1000.0},
        {"posicao": 3, "participante_id": "C", "participante": "Rede C", "uf": "MG",
         "fat_rs": 100.0, "fat_kg": 200.0, "total_escopo": 1000.0},
    ]
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows])
    result = RankClients().run(
        fetcher,
        {"periodo_inicio": date(2026, 1, 1), "periodo_fim": date(2026, 6, 30),
         "metrica_ranking": "fat_kg", "granularidade_cliente": "rede", "top_n": 2, "uf": "sp"},
        CARTEIRA,
    )

    sql, params = fetcher.calls[-1]
    assert ("ROW_NUMBER() OVER (ORDER BY fat_kg DESC, fat_rs DESC, "
            "CASE WHEN participante IS NULL THEN 1 ELSE 0 END, participante ASC, participante_id ASC)") in sql
    assert "RANK()" not in sql
    assert params[-1] == 3  # N + 1, para saber quem ficou de fora no limite
    assert "GROUP BY c.Rede" in sql
    lines = result.main_block["linhas"]
    assert [line["participante_id"] for line in lines] == ["A", "B"]
    assert "DESEMPATE" in codes(result)
    assert "faturamento em R$" in next(n for n in result.notices if n.code == "DESEMPATE").text
    assert lines[0]["participacao_pct"] == 60.0
    assert lines[0]["fat_tons"] == 0.6


def test_ranking_by_rs_breaks_ties_by_name() -> None:
    rows = [
        {"posicao": 1, "participante_id": "9", "participante": "ARCOR", "uf": "SP",
         "fat_rs": 50.0, "fat_kg": 24.0, "total_escopo": 100.0},
        {"posicao": 2, "participante_id": "1", "participante": "CARINO", "uf": "SP",
         "fat_rs": 50.0, "fat_kg": 24.0, "total_escopo": 100.0},
    ]
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows])
    result = RankClients().run(
        fetcher,
        {"periodo_inicio": date(2026, 1, 1), "periodo_fim": date(2026, 1, 31),
         "metrica_ranking": "fat_rs", "top_n": 1},
        FULL,
    )

    sql = fetcher.calls[-1][0]
    assert "ORDER BY fat_rs DESC, CASE WHEN participante IS NULL" in sql
    assert "fat_rs DESC, fat_rs DESC" not in sql
    assert [line["participante"] for line in result.main_block["linhas"]] == ["ARCOR"]
    assert "ordem alfabética" in next(n for n in result.notices if n.code == "DESEMPATE").text


def test_ranking_without_tie_at_the_limit_has_no_notice() -> None:
    rows = [
        {"posicao": 1, "participante_id": "A", "participante": "A", "uf": "SP",
         "fat_rs": 10.0, "fat_kg": 30.0, "total_escopo": 50.0},
        {"posicao": 2, "participante_id": "B", "participante": "B", "uf": "SP",
         "fat_rs": 10.0, "fat_kg": 20.0, "total_escopo": 50.0},
    ]
    result = RankClients().run(
        CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows]),
        {"periodo_inicio": date(2026, 1, 1), "periodo_fim": date(2026, 1, 31), "top_n": 1},
        FULL,
    )

    assert len(result.main_block["linhas"]) == 1
    assert "DESEMPATE" not in codes(result)


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


def test_ranking_defaults_to_rede_and_store_only_when_asked() -> None:
    # O Power BI ranqueia o cliente agrupado (comparação de 13-10, AIC-289).
    period = {"periodo_inicio": date(2026, 8, 1), "periodo_fim": date(2026, 8, 31)}
    default = CheckingFetcher([LAST_CLOSED, NOT_OPEN, []])
    RankClients().run(default, period, FULL)
    store = CheckingFetcher([LAST_CLOSED, NOT_OPEN, []])
    RankClients().run(store, {**period, "granularidade_cliente": "cliente_loja"}, FULL)

    assert "GROUP BY c.Rede" in default.calls[-1][0]
    assert "MAX(c.RedeNome)" in default.calls[-1][0]
    assert "GROUP BY c.ClienteId" in store.calls[-1][0]


def test_representative_ranking_credits_current_seller_by_default() -> None:
    rows = [
        {"posicao": 1, "vendedor_id": "17", "vendedor": "Ana", "papel": "RCA",
         "fat_rs": 1000, "fat_kg": 500},
        {"posicao": 2, "vendedor_id": "21", "vendedor": "Beto", "papel": "RCA",
         "fat_rs": 500, "fat_kg": 300},
    ]
    fetcher = CheckingFetcher([LAST_CLOSED, rows, NOT_OPEN])
    result = RankRepresentatives().run(
        fetcher,
        {"metrica_desempenho": "fat_kg", "papel_comercial": "representante"},
        CARTEIRA,
    )

    sql, params = fetcher.calls[1]
    assert "c.RCAAtual AS vendedor_id" in sql
    assert "GROUP BY c.RCAAtual" in sql
    assert "f.VendedorId" not in sql
    assert "c.RCAAtual IN (?)" in sql
    assert "r.PapelComercial IN (?)" in sql
    assert params[:2] == (date(2026, 6, 1), date(2026, 9, 1))
    assert result.main_block["linhas"][0]["vendedor"] == "Ana"


def test_representative_ranking_uses_transaction_seller_only_when_asked() -> None:
    fetcher = CheckingFetcher([LAST_CLOSED, [], NOT_OPEN])
    RankRepresentatives().run(
        fetcher,
        {"metrica_desempenho": "fat_rs", "tipo_atribuicao": "vendedor_da_venda"},
        CARTEIRA,
    )

    sql, _ = fetcher.calls[1]
    assert "f.VendedorId AS vendedor_id" in sql
    assert "v.RepresentanteId = f.VendedorId" in sql
    assert "c.RCAAtual IN (?)" in sql


def test_representative_ranking_refuses_unapproved_composite_metric() -> None:
    result = RankRepresentatives().run(
        CheckingFetcher([]),
        {"metrica_desempenho": "composto"},
        FULL,
    )

    assert result.question_to_user and "FAT KG ou FAT R$" in result.question_to_user


def test_sales_breakdown_ranks_products_within_each_uf() -> None:
    rows = [
        {"uf": "SP", "produto_id": "P1", "produto": "Produto 1", "posicao": 1,
         "fat_rs": 100, "fat_kg": 60},
        {"uf": "RJ", "produto_id": "P2", "produto": "Produto 2", "posicao": 1,
         "fat_rs": 90, "fat_kg": 55},
    ]
    fetcher = CheckingFetcher([LAST_CLOSED, rows])
    result = SalesBreakdowns().run(
        fetcher,
        {"dimensao": "produto_por_regiao", "metrica": "fat_kg"},
        CARTEIRA,
    )

    sql, params = fetcher.calls[-1]
    assert "PARTITION BY uf ORDER BY fat_kg DESC" in sql
    assert "ORDER BY fat_kg DESC, uf, produto_id, produto" in sql
    assert "DESC, c.UF" not in sql
    assert "ORDER BY uf, posicao" in sql
    assert "c.UF AS uf" in sql
    assert "p.ProdutoId AS produto_id" in sql
    assert "c.RCAAtual IN (?)" in sql
    assert params == (date(2026, 6, 1), date(2026, 9, 1), "000123", 5)
    assert [line["uf"] for line in result.main_block["linhas"]] == ["SP", "RJ"]
    assert [line["fat_kg"] for line in result.main_block["linhas"]] == [60, 55]


def test_regional_breakdown_defaults_to_client_uf_and_all_regions() -> None:
    fetcher = CheckingFetcher(
        [LAST_CLOSED, [{"uf": "SP", "posicao": 1, "fat_rs": 20, "fat_kg": 10}]]
    )
    result = SalesBreakdowns().run(
        fetcher,
        {"dimensao": "regiao"},
        FULL,
    )

    sql, params = fetcher.calls[-1]
    assert "c.UF AS uf" in sql
    assert "ORDER BY fat_kg DESC, uf" in sql
    assert "ORDER BY fat_kg DESC, c.UF" not in sql
    assert "WHERE posicao <= ?" not in sql
    assert params == (date(2026, 6, 1), date(2026, 9, 1))
    assert result.main_block["linhas"][0]["uf"] == "SP"


def test_named_region_level_ranks_by_cte_alias() -> None:
    fetcher = CheckingFetcher(
        [LAST_CLOSED, [{"regiao": "Sudeste", "posicao": 1, "fat_rs": 20, "fat_kg": 10}]]
    )
    SalesBreakdowns().run(
        fetcher,
        {"dimensao": "regiao", "nivel_geografico": "regiao"},
        FULL,
    )

    sql = fetcher.calls[-1][0]
    assert "c.Regiao AS regiao" in sql
    assert "ORDER BY fat_kg DESC, regiao" in sql
    assert "ORDER BY fat_kg DESC, c.Regiao" not in sql


def test_product_breakdown_uses_reference_month_and_returns_rank_order() -> None:
    fetcher = CheckingFetcher(
        [LAST_CLOSED, [{"produto_id": "P1", "produto": "Produto", "posicao": 1,
                        "fat_rs": 20, "fat_kg": 10}]]
    )
    SalesBreakdowns().run(
        fetcher,
        {"dimensao": "produto", "data_referencia": date(2026, 5, 10)},
        FULL,
    )

    sql, params = fetcher.calls[-1]
    assert params[:2] == (date(2026, 3, 1), date(2026, 6, 1))
    assert "ORDER BY posicao" in sql
    assert params[-1] == 20


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
    assert "TR01" in codes(result)
    assert "BASE2025" not in codes(result)


@pytest.mark.parametrize("window", [3, 6, 9, 12])
def test_monthly_series_supports_requested_windows_without_widening_scope(window: int) -> None:
    fetcher = CheckingFetcher([LAST_CLOSED, []])
    result = MonthlySeries().run(
        fetcher,
        {"janela_meses": window, "competencia_referencia": date(2026, 8, 1)},
        CARTEIRA,
    )

    sql, params = fetcher.calls[-1]
    assert len(result.main_block["linhas"]) == window
    assert "c.RCAAtual IN (?)" in sql
    assert "000123" in params


def test_monthly_series_rejects_unsupported_window() -> None:
    fetcher = CheckingFetcher([])

    result = MonthlySeries().run(fetcher, {"janela_meses": 2}, FULL)

    assert result.question_to_user
    assert "3, 6, 9 ou 12" in result.question_to_user
    assert fetcher.calls == []


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


def test_sellers_are_the_client_current_seller() -> None:
    # AIC-290: a venda é do vendedor atual do cliente, como no Power BI.
    fetcher = CheckingFetcher([LAST_CLOSED, NOT_OPEN, []])
    SellersBelowAverage().run(fetcher, {"mes_referencia": date(2026, 7, 1)}, CARTEIRA)

    sql, _ = fetcher.calls[-1]
    assert "r.RepresentanteId = c.RCAAtual" in sql
    assert "GROUP BY c.RCAAtual" in sql
    assert "c.RCAAtual IN (?)" in sql
    assert "f.VendedorId" not in sql


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


def test_mix_strips_trailing_spaces_from_source_text() -> None:
    rows = [mix_row("655", ".01. LPI - LS - FRACIONADO ", 1, 10.0, 5.0,
                    produto="LEITE EM PO INTEGRAL LA SERENISSIMA 12X700G      ")]
    result = ProductMix().run(
        CheckingFetcher([LAST_CLOSED, NOT_OPEN, rows]),
        {"escopo_cliente": "x", "data_referencia": date(2026, 10, 9)},
        FULL,
    )

    line = result.main_block["linhas"][0]
    assert line["produto"] == "LEITE EM PO INTEGRAL LA SERENISSIMA 12X700G"
    assert line["familia"] == ".01. LPI - LS - FRACIONADO"
