"""Testes das operações que completaram a Fase 1 em 19-10 (OP02-OP10, OP15, OP16, OP19-OP22).

Funções de teste soltas, sem classe. O banco é a fixture `fake_fetcher` do
conftest: as respostas saem na ordem das consultas de cada operação e cada
`?` do SQL precisa de um parâmetro. Último mês fechado = jul/26 (D-A64).
"""

from datetime import date, datetime

from leitesol_agent.application.operations import OPERATION_HANDLERS
from leitesol_agent.application.operations.abc_curve import AbcCurve
from leitesol_agent.application.operations.analytics import OPEN_RULE
from leitesol_agent.application.operations.channel_performance import (
    ChannelPerformance,
    accumulated_months,
)
from leitesol_agent.application.operations.client_product_trend import ClientProductTrend
from leitesol_agent.application.operations.client_vs_average import CompareClientsWithAverage
from leitesol_agent.application.operations.growth_candidates import GrowthCandidates
from leitesol_agent.application.operations.low_turnover import LowTurnover
from leitesol_agent.application.operations.mix_expansion import MixExpansion
from leitesol_agent.application.operations.non_positivated import ListNonPositivated
from leitesol_agent.application.operations.product_absence import MissingItems, ProductChurn
from leitesol_agent.application.operations.purchase_frequency import PurchaseFrequency
from leitesol_agent.application.operations.regional_performance import RegionalPerformance
from leitesol_agent.application.operations.seasonality import Seasonality
from leitesol_agent.application.operations.seller_evolution import SellerEvolution
from leitesol_agent.application.operations.ticket_trend import TicketTrend
from leitesol_agent.application.parameters import validate_parameters
from leitesol_agent.domain.models import Operation, Parameter, Scope

FULL = Scope(sees_everything=True)
CARTEIRA = Scope(sees_everything=False, sellers=frozenset({"000123"}), teams=frozenset({"997"}))
LAST_CLOSED = [{"UltimaFechada": datetime(2026, 7, 1)}]
NOT_OPEN = [{"TemParcial": 0}]
OPEN = [{"TemParcial": 1}]


def codes(result) -> set[str]:
    return {notice.code for notice in result.notices}


def month_row(key: dict, month: date, fat_rs: float, fat_kg: float) -> dict:
    return {**key, "competencia": month, "fat_rs": fat_rs, "fat_kg": fat_kg}


# --- registro ------------------------------------------------------------------------


def test_every_phase_one_question_has_a_handler() -> None:
    expected = {f"OP{number:02d}" for number in range(1, 23)}
    assert expected <= set(OPERATION_HANDLERS)


# --- OP02 --------------------------------------------------------------------------


def op02_row(client: str, ref_rs: float, hist_rs: float, ref_kg: float, hist_kg: float) -> dict:
    return {
        "cliente_id": client,
        "cliente": f"Cliente {client}",
        "cnpj": None,
        "rede": None,
        "uf": "SP",
        "fat_rs_ref": ref_rs,
        "fat_rs_hist": hist_rs,
        "fat_kg_ref": ref_kg,
        "fat_kg_hist": hist_kg,
    }


def test_op02_below_average_uses_own_six_month_mean(fake_fetcher) -> None:
    rows = [
        op02_row("1", 100, 1200, 10, 60),  # R$ abaixo (média 200), KG igual (média 10)
        op02_row("2", 300, 1200, 30, 60),  # acima nas duas
        op02_row("3", 50, 0, 5, 0),  # sem histórico: exceção
    ]
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])

    result = CompareClientsWithAverage().run(
        fetcher, {"periodo_referencia": date(2026, 7, 1), "tipo_comparacao": "abaixo"}, CARTEIRA
    )

    lines = result.main_block["linhas"]
    assert [line["cliente_id"] for line in lines] == ["1"]
    assert lines[0]["fat_rs_media"] == 200.0
    assert lines[0]["fat_kg_situacao"] == "igual"
    assert lines[0]["criterio_atendido"] == "FAT R$"
    assert result.exceptions[0]["linhas"][0]["cliente_id"] == "3"
    assert result.period.comparison_start == date(2026, 1, 1)
    sql, params = fetcher.calls[-1]
    assert "c.RCAAtual IN (?)" in sql
    assert "000123" in params


def test_op02_flags_negative_values(fake_fetcher) -> None:
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, [op02_row("1", 10, -60, 1, 6)]])
    result = CompareClientsWithAverage().run(
        fetcher, {"periodo_referencia": date(2026, 7, 1), "tipo_comparacao": "acima"}, FULL
    )
    assert "VALOR_NEGATIVO" in codes(result)


# --- OP03 --------------------------------------------------------------------------


def op03_row(client: str, seller: str | None, uf: str, fat_rs: float) -> dict:
    return {
        "cliente_id": client,
        "cliente": client,
        "rede_id": "000534",
        "rede": "VIPAO",
        "uf": uf,
        "vendedor_id": seller,
        "vendedor": f"V{seller}",
        "papel": "RCA",
        "gestor": "G",
        "fat_rs": fat_rs,
        "fat_kg": fat_rs / 10,
    }


def test_op03_positivation_is_per_group_and_current_seller(fake_fetcher) -> None:
    rows = [
        op03_row("A", "100", "SP", 500),  # vendedor 100 comprou numa loja
        op03_row("B", "100", "RJ", 0),
        op03_row("C", "200", "MG", 0),  # vendedor 200 não positivou
        op03_row("D", None, "BA", 0),  # sem responsável
    ]
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])

    result = ListNonPositivated().run(
        fetcher, {"cliente_rede": "534", "periodo_referencia": date(2026, 7, 1)}, FULL
    )

    lines = result.main_block["linhas"]
    assert [(line["vendedor_id"], line["situacao"]) for line in lines] == [
        ("200", "Não positivado")
    ]
    assert result.exceptions[0]["linhas"][0]["status"] == "Responsavel nao identificado"
    sql, params = fetcher.calls[-1]
    assert "WITH alvo AS" in sql
    assert "000534" in params


def test_op03_both_statuses_and_all_ufs_visible(fake_fetcher) -> None:
    rows = [op03_row("A", "100", "SP", 500), op03_row("B", "100", "RJ", 0)]
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])
    result = ListNonPositivated().run(
        fetcher,
        {
            "cliente_rede": "534",
            "periodo_referencia": date(2026, 7, 1),
            "status_positivacao": "ambos",
        },
        FULL,
    )
    line = result.main_block["linhas"][0]
    assert line["ufs"] == "RJ, SP"
    assert line["lojas"] == 2
    assert line["lojas_com_compra"] == 1


def test_op03_unknown_client_becomes_question(fake_fetcher) -> None:
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, []])
    result = ListNonPositivated().run(
        fetcher, {"cliente_rede": "XYZ", "periodo_referencia": date(2026, 7, 1)}, FULL
    )
    assert result.question_to_user


# --- OP04 --------------------------------------------------------------------------


def test_op04_classifies_products_and_carries_open_rule(fake_fetcher) -> None:
    key = {"item_id": "651", "produto": "LP 400g", "familia": "LP", "grupamento": "PO", "uf": "SP"}
    other = {"item_id": "700", "produto": "Queijo", "familia": "Q", "grupamento": "Q", "uf": "SP"}
    rows = [month_row(key, date(2026, month, 1), 100, 60) for month in range(1, 7)]
    rows.append(month_row(key, date(2026, 7, 1), 100, 30))  # queda em KG
    rows.append(month_row(other, date(2026, 7, 1), 50, 10))  # sem base histórica
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])

    result = ClientProductTrend().run(fetcher, {"cliente_loja": "17351"}, FULL)

    lines = result.main_block["linhas"]
    assert lines[0]["produto_id"] == "651"
    assert lines[0]["fat_kg_classificacao"] == "Queda"
    assert lines[0]["fat_kg_media"] == 60
    assert lines[1]["fat_kg_classificacao"] == "Movimento atual sem base histórica"
    assert OPEN_RULE in codes(result)
    assert result.period.start == date(2026, 7, 1)
    assert result.period.comparison_start == date(2026, 1, 1)
    _, params = fetcher.calls[-1]
    assert "017351" in params  # código com zeros recompostos


# --- OP05 --------------------------------------------------------------------------


def test_op05_without_client_ranks_clients_and_matches_power_bi_borders(fake_fetcher) -> None:
    rows = [
        {"item_id": "1", "item": "Gran Coffee", "uf": "DF", "fat_rs": 0, "fat_kg": 5475},
        {"item_id": "2", "item": "Outro", "uf": "DF", "fat_rs": 0, "fat_kg": 2917},
        {"item_id": "3", "item": "Barolo", "uf": "DF", "fat_rs": 0, "fat_kg": 1129},
        {"item_id": "4", "item": "Rio Brasa", "uf": "DF", "fat_rs": 0, "fat_kg": -21},
        {"item_id": "5", "item": "Resto", "uf": "DF", "fat_rs": 0, "fat_kg": 500},
    ]
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])

    result = AbcCurve().run(
        fetcher,
        {
            "metrica_abc": "fat_kg",
            "data_referencia": date(2026, 6, 1),
            "periodo_meses": 1,
            "uf": "DF",
        },
        FULL,
    )

    classes = {line["item"]: line["fat_kg_classe"] for line in result.main_block["linhas"]}
    assert classes["Gran Coffee"] == "A"
    assert classes["Outro"] == "A"  # 54,75% -> 83,92%: cruza 80 e fica em A
    assert classes["Rio Brasa"] == "C"
    assert result.main_block["linhas"][-1]["item"] == "Rio Brasa"
    assert "OP05_NEGATIVO" in codes(result)
    assert result.period.start == date(2026, 6, 1)
    sql, _ = fetcher.calls[-1]
    assert "GROUP BY c.ClienteId" in sql


def test_op05_with_client_uses_products_and_filters_class(fake_fetcher) -> None:
    rows = [
        {"item_id": "651", "item": "LP", "uf": "SP", "fat_rs": 900, "fat_kg": 90},
        {"item_id": "700", "item": "Q", "uf": "SP", "fat_rs": 100, "fat_kg": 10},
    ]
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])
    result = AbcCurve().run(fetcher, {"escopo_cliente": "17351", "classe_abc": "a"}, FULL)
    assert [line["item_id"] for line in result.main_block["linhas"]] == ["651"]
    assert "GROUP BY p.ProdutoId" in fetcher.calls[-1][0]
    assert result.period.start == date(2025, 8, 1)  # 12 fechados até jul/26


def test_op05_subgroup_level_becomes_question(fake_fetcher) -> None:
    result = AbcCurve().run(
        fake_fetcher([]), {"escopo_cliente": "17351", "nivel_produto": "subgrupo"}, FULL
    )
    assert result.question_to_user


# --- OP06 --------------------------------------------------------------------------


def test_op06_frequency_and_recency_from_fact(fake_fetcher) -> None:
    labels = {"cliente": "Assaí", "rede": "Assaí", "uf": "SP"}
    rows = [month_row(labels, date(2025, month, 1), 100, 10) for month in range(8, 13)]
    rows += [month_row(labels, date(2026, month, 1), 100, 10) for month in (1, 2, 3, 4)]
    rows.append(month_row(labels, date(2026, 5, 1), -5, 0))  # devolução: não é compra
    fetcher = fake_fetcher([LAST_CLOSED, rows])

    result = PurchaseFrequency().run(
        fetcher, {"escopo_cliente": "Assaí", "incluir_serie": True}, FULL
    )

    line = result.main_block["linhas"][0]
    assert line["meses_com_compra"] == 9
    assert line["classificacao"] == "Mensal"
    assert line["ultima_compra"] == "2026-04"
    assert line["recencia_competencias"] == 3
    assert line["situacao"] == "com_compra_na_janela"
    assert "serie" in line
    assert result.period.start == date(2025, 8, 1)


def test_op06_client_without_purchase(fake_fetcher) -> None:
    result = PurchaseFrequency().run(fake_fetcher([LAST_CLOSED, []]), {"escopo_cliente": "1"}, FULL)
    line = result.main_block["linhas"][0]
    assert line["situacao"] == "sem_compra_localizada"
    assert line["classificacao"] == "Ocasional"


# --- OP07 --------------------------------------------------------------------------


def test_op07_compares_with_previous_period_and_halves(fake_fetcher) -> None:
    key = {"cliente_id": "01735101"}
    rows = [month_row(key, date(2025, month, 1), 1000, 100) for month in range(7, 13)]  # 10 R$/kg
    rows += [month_row(key, date(2026, month, 1), 1100, 100) for month in range(1, 7)]  # 11 R$/kg
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])

    result = TicketTrend().run(
        fetcher,
        {
            "cliente_loja": "01735101",
            "periodo_inicio": date(2026, 1, 1),
            "periodo_fim": date(2026, 6, 30),
        },
        FULL,
    )

    lines = {line["indicador"]: line for line in result.main_block["linhas"]}
    assert lines["Período de comparação"]["ticket_rs_kg"] == 10.0
    assert lines["Período analisado"]["ticket_rs_kg"] == 11.0
    assert lines["Comparação entre períodos"]["classificacao"] == "ascensao"
    assert lines["Tendência interna"]["classificacao"] == "estavel"
    assert OPEN_RULE in codes(result)
    assert result.period.comparison_start == date(2025, 7, 1)


def test_op07_zero_kg_is_not_calculable(fake_fetcher) -> None:
    key = {"cliente_id": "1"}
    rows = [month_row(key, date(2026, 1, 1), 100, 0)]
    result = TicketTrend().run(
        fake_fetcher([LAST_CLOSED, NOT_OPEN, rows]),
        {"cliente_loja": "1", "periodo_inicio": date(2026, 1, 1), "periodo_fim": date(2026, 1, 31)},
        FULL,
    )
    comparison = result.main_block["linhas"][2]
    assert comparison["classificacao"] == "nao_calculavel"


# --- OP08 --------------------------------------------------------------------------


def test_op08_is_descriptive_with_short_history(fake_fetcher) -> None:
    rows = [month_row({}, date(2025, month, 1), 100 * month, 10) for month in range(1, 13)]
    rows += [month_row({}, date(2026, month, 1), 100, 10) for month in range(1, 8)]
    fetcher = fake_fetcher([LAST_CLOSED, rows])

    result = Seasonality().run(fetcher, {"entidade": "rede", "escopo_cliente": "534"}, FULL)

    lines = result.main_block["linhas"]
    assert [line["mes"] for line in lines][:3] == ["jan", "fev", "mar"]  # ordem do calendário
    assert lines[11]["indice_sazonal"] > lines[0]["indice_sazonal"]
    assert OPEN_RULE in codes(result)
    coverage = next(n for n in result.notices if n.code == "OP08_COBERTURA")
    assert "perfil descritivo" in coverage.text
    sql, params = fetcher.calls[-1]
    assert "c.Rede IN (SELECT k.Rede" in sql
    assert "000534" in params


def test_op08_cnpj_level_does_not_expand_to_network(fake_fetcher) -> None:
    fetcher = fake_fetcher([LAST_CLOSED, []])
    Seasonality().run(fetcher, {"entidade": "cnpj", "escopo_cliente": "12345678000199"}, FULL)
    sql, params = fetcher.calls[-1]
    assert "c.Rede IN" not in sql
    assert "12345678000199" in params


# --- OP09 / OP10 -------------------------------------------------------------------


def item(item_id: str) -> dict:
    return {"item_id": item_id, "item": f"Item {item_id}", "familia": "F", "grupamento": "G"}


def test_op09_lists_items_bought_before_and_absent_now(fake_fetcher) -> None:
    rows = [
        month_row(item("651"), date(2026, 1, 1), 100, 277),
        month_row(item("651"), date(2026, 5, 1), 0, 4),  # só bonificação: não é compra
        month_row(item("700"), date(2026, 2, 1), 100, 10),
        month_row(item("700"), date(2026, 5, 1), 100, 10),  # voltou: não é churn
    ]
    fetcher = fake_fetcher([rows, LAST_CLOSED, NOT_OPEN])

    result = ProductChurn().run(
        fetcher,
        {
            "escopo_cliente": "Carrefour",
            "periodo_atual_inicio": date(2026, 4, 1),
            "periodo_atual_fim": date(2026, 6, 30),
        },
        FULL,
    )

    lines = result.main_block["linhas"]
    assert [line["item_id"] for line in lines] == ["651"]
    assert lines[0]["fat_kg_depois"] == 4
    assert result.period.comparison_start == date(2026, 1, 1)
    assert "SEM_CAUSA" in codes(result)


def test_op10_compares_single_month_m_minus_3_with_partial_current(fake_fetcher) -> None:
    rows = [
        month_row(item("651"), date(2026, 5, 1), 100, 10),
        month_row(item("700"), date(2026, 5, 1), 100, 10),
        month_row(item("700"), date(2026, 8, 1), 100, 10),
    ]
    fetcher = fake_fetcher([LAST_CLOSED, rows, OPEN])

    result = MissingItems().run(
        fetcher, {"escopo_cliente": "1", "incluir_mes_atual": True, "defasagem_meses": 3}, FULL
    )

    assert [line["item_id"] for line in result.main_block["linhas"]] == ["651"]
    assert result.period.start == date(2026, 8, 1)  # mês vigente
    assert result.period.comparison_start == date(2026, 5, 1)
    assert result.period.partial is True
    assert {"TR02", "SEM_CAUSA"} <= codes(result)


# --- OP15 --------------------------------------------------------------------------


def test_op15_ranks_sellers_with_monthly_columns_and_previous_year(fake_fetcher) -> None:
    ana = {"participante_id": "100", "participante": "Ana"}
    bia = {"participante_id": "200", "participante": "Bia"}
    rows = [month_row(ana, date(2026, month, 1), 100, 10) for month in range(1, 8)]
    rows += [month_row(bia, date(2026, month, 1), 300, 30) for month in range(1, 8)]
    rows += [month_row(bia, date(2025, month, 1), 600, 60) for month in range(1, 8)]
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows])

    result = SellerEvolution().run(fetcher, {"tipo_visao": "vendedor"}, FULL)

    lines = result.main_block["linhas"]
    assert [line["participante"] for line in lines] == ["Bia", "Ana"]
    assert lines[0]["posicao"] == 1
    assert lines[0]["2026-03"] == 300.0
    assert lines[0]["fat_rs_situacao"] == "queda"
    assert lines[1]["fat_rs_variacao_pct"] is None  # sem ano anterior
    assert result.period.start == date(2026, 1, 1)
    sql, params = fetcher.calls[-1]
    assert "r.PapelComercial IN (?, ?)" in sql
    assert {"RCA", "Gestor"} <= set(params)


def test_op15_manager_portfolio_uses_team_tree(fake_fetcher) -> None:
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, []])
    SellerEvolution().run(fetcher, {"tipo_visao": "carteira_gestor", "participante": "997"}, FULL)
    sql, params = fetcher.calls[-1]
    assert "vw_hierarquia_equipe" in sql
    assert "GROUP BY h.GestorId" in sql
    assert "997" in params


# --- OP16 --------------------------------------------------------------------------


def test_op16_region_against_its_own_history(fake_fetcher) -> None:
    sp = {"uf": "SP"}
    rows = [month_row(sp, date(2025, 7, 1), 0, 200)]
    rows += [month_row(sp, add, 0, 100) for add in (date(2026, month, 1) for month in range(1, 7))]
    rows += [month_row(sp, date(2025, month, 1), 0, 100) for month in range(8, 13)]
    rows.append(month_row(sp, date(2026, 7, 1), 0, 150))
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows, [{"uf": "SP"}, {"uf": "AC"}]])

    result = RegionalPerformance().run(fetcher, {"janelas": "3|6|12"}, FULL)

    line = result.main_block["linhas"][0]
    assert line["fat_kg_atual"] == 150
    assert line["fat_kg_media_3m"] == 100
    assert line["fat_kg_situacao_3m"] == "acima"
    assert line["fat_kg_situacao_ano_anterior"] == "abaixo"
    assert result.exceptions[0]["linhas"] == [{"uf": "AC"}]
    assert OPEN_RULE in codes(result)


def test_op16_janelas_default_validates_as_text() -> None:
    operation = Operation(
        "OP16",
        "SK04",
        "comparar_desempenho_regional",
        "x",
        "x",
        None,
        (Parameter("janelas", "enum", False, "3|6|12 (subconjunto)", "3|6|12", None),),
    )
    validated = validate_parameters(operation, {})
    assert validated.is_complete
    assert validated.values["janelas"] == "3|6|12"


# --- OP19 --------------------------------------------------------------------------


def test_op19_keeps_only_heuristic_candidates(fake_fetcher) -> None:
    rows = [
        {
            "entidade_id": "534",
            "entidade": "VIPAO",
            "uf": "SP",
            "segmento": "Varejo",
            "meses_com_compra": 11,
            "kg_semestre_1": 600,
            "kg_semestre_2": 900,
            "fat_rs": 10000,
            "fat_kg": 1500,
            "mix": 4,
        },
        {
            "entidade_id": "999",
            "entidade": "Queda",
            "uf": "SP",
            "segmento": "Varejo",
            "meses_com_compra": 12,
            "kg_semestre_1": 900,
            "kg_semestre_2": 600,
            "fat_rs": 10000,
            "fat_kg": 1500,
            "mix": 4,
        },
    ]
    fetcher = fake_fetcher([LAST_CLOSED, rows])

    result = GrowthCandidates().run(fetcher, {}, FULL)

    lines = result.main_block["linhas"]
    assert [line["entidade_id"] for line in lines] == ["534"]
    assert lines[0]["crescimento_pct"] == 50.0
    assert OPEN_RULE in codes(result)
    sql, params = fetcher.calls[-1]
    assert "GROUP BY c.Rede" in sql
    assert params[-1] == 12
    assert date(2026, 2, 1) in params  # início do 2º semestre da janela ago/25-jul/26


# --- OP20 --------------------------------------------------------------------------


def test_op20_accumulated_window_is_closed_months_of_the_year() -> None:
    assert accumulated_months(date(2026, 8, 1), date(2026, 7, 1))[-1] == date(2026, 7, 1)
    assert accumulated_months(date(2026, 5, 1), date(2026, 7, 1))[-1] == date(2026, 5, 1)
    assert accumulated_months(date(2026, 1, 1), date(2025, 12, 1)) == []


def test_op20_segments_against_previous_year_with_channel_disclaimer(fake_fetcher) -> None:
    varejo = {"segmento_id": "01", "segmento": "Varejo"}
    nd = {"segmento_id": "ND", "segmento": None}
    rows = [
        month_row(varejo, date(2026, 8, 1), 500, 50),
        month_row(varejo, date(2025, 8, 1), 800, 80),
    ]
    rows += [month_row(varejo, date(2026, month, 1), 100, 10) for month in range(1, 8)]
    rows += [month_row(varejo, date(2025, month, 1), 50, 5) for month in range(1, 8)]
    rows.append(month_row(nd, date(2026, 8, 1), 100, 10))
    fetcher = fake_fetcher([LAST_CLOSED, OPEN, rows])

    result = ChannelPerformance().run(fetcher, {}, FULL)

    lines = {line["segmento_id"]: line for line in result.main_block["linhas"]}
    assert lines["01"]["fat_rs_situacao_mes"] == "queda"
    assert lines["01"]["fat_rs_situacao_acumulado"] == "crescimento"
    assert lines["ND"]["observacao"] == "Sem classificação de segmento"
    assert result.period.start == date(2026, 8, 1)
    assert {OPEN_RULE, "TR02"} <= codes(result)


# --- OP21 --------------------------------------------------------------------------


def test_op21_low_turnover_needs_both_falls(fake_fetcher) -> None:
    low = {"item_id": "651", "item": "LP", "familia": "F", "grupamento": "G"}
    mixed = {"item_id": "700", "item": "Q", "familia": "F", "grupamento": "G"}
    rows = [month_row(low, date(2025, month, 1), 100, 100) for month in range(1, 8)]
    rows += [month_row(low, date(2026, month, 1), 50, 50) for month in range(1, 8)]
    rows += [month_row(mixed, date(2025, month, 1), 100, 100) for month in range(1, 8)]
    rows += [month_row(mixed, date(2026, month, 1), 100, 200) for month in range(1, 7)]
    rows.append(month_row(mixed, date(2026, 7, 1), 10, 10))
    fetcher = fake_fetcher([LAST_CLOSED, NOT_OPEN, rows, [{"item_id": "651", "compradores": 3}]])

    result = LowTurnover().run(fetcher, {}, FULL)

    lines = result.main_block["linhas"]
    assert [line["item_id"] for line in lines] == ["651"]
    assert lines[0]["situacao"] == "baixo_giro"
    assert lines[0]["compradores"] == 3
    assert result.exceptions[0]["linhas"][0]["item_id"] == "700"
    assert OPEN_RULE in codes(result)


# --- OP22 --------------------------------------------------------------------------


GROUPS = [{"grupamento": "Leite em Pó"}, {"grupamento": "Queijos"}]


def test_op22_leads_need_peers_buying_the_complement(fake_fetcher) -> None:
    rows = [
        {
            "entidade_id": "1",
            "entidade": "A",
            "segmento": "Varejo",
            "uf": "SP",
            "origem_rs": 100,
            "complemento_rs": 0,
            "fat_rs": 100,
            "fat_kg": 10,
        },
        {
            "entidade_id": "2",
            "entidade": "B",
            "segmento": "Varejo",
            "uf": "SP",
            "origem_rs": 100,
            "complemento_rs": 50,
            "fat_rs": 150,
            "fat_kg": 15,
        },
        {
            "entidade_id": "3",
            "entidade": "C",
            "segmento": "Varejo",
            "uf": "SP",
            "origem_rs": 0,
            "complemento_rs": 0,
            "fat_rs": 20,
            "fat_kg": 2,
        },
    ]
    fetcher = fake_fetcher([GROUPS, LAST_CLOSED, rows])

    result = MixExpansion().run(
        fetcher,
        {
            "segmento": "Varejo",
            "uf": "sp",
            "agrupamento_origem": "leite em po",
            "agrupamento_complementar": "QUEIJOS",
        },
        FULL,
    )

    lines = result.main_block["linhas"]
    assert [line["entidade_id"] for line in lines] == ["1"]
    assert lines[0]["pares_compradores"] == 1
    assert lines[0]["proporcao_pares_pct"] == 33.33
    assert OPEN_RULE in codes(result)
    sql, params = fetcher.calls[-1]
    assert params[:2] == ("Leite em Pó", "Queijos")
    assert result.period.start == date(2024, 8, 1)


def test_op22_unclassified_segment_and_unknown_group_ask(fake_fetcher) -> None:
    base = {"uf": "SP", "agrupamento_origem": "Queijos", "agrupamento_complementar": "Leite em Pó"}
    assert MixExpansion().run(fake_fetcher([]), {**base, "segmento": "ND"}, FULL).question_to_user
    unknown = MixExpansion().run(
        fake_fetcher([GROUPS]), {**base, "segmento": "Varejo", "agrupamento_origem": "Doces"}, FULL
    )
    assert "Doces" in unknown.question_to_user
