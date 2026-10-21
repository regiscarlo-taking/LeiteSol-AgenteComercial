"""Testes unitários das funções puras de cálculo (operations/analytics.py).

Sem banco e sem classe: cada função recebe números e devolve números ou
rótulos, então as regras de negócio homologadas ficam presas aqui.
"""

from datetime import date

import pytest
from leitesol_agent.application.operations.analytics import (
    OPEN_RULE,
    abc_curve,
    add_months,
    average,
    classify_ticket,
    closed_anchor,
    compare_literal,
    coverage_label,
    direction,
    frequency_class,
    growth_criteria,
    month_range,
    months_between,
    negative_notice,
    open_rule_notice,
    pivot,
    product_trend_status,
    recency,
    reference_month,
    seasonal_profile,
    split_halves,
    ticket,
    turnover_status,
    variation_pct,
)
from leitesol_agent.application.operations.regional_performance import parse_windows

# --- calendário --------------------------------------------------------------


def test_add_months_crosses_year_boundaries() -> None:
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert add_months(date(2025, 11, 1), 3) == date(2026, 2, 1)
    assert add_months(date(2026, 7, 1), -12) == date(2025, 7, 1)


def test_months_between_counts_competences() -> None:
    assert months_between(date(2026, 4, 1), date(2026, 7, 1)) == 3
    assert months_between(date(2025, 12, 1), date(2026, 1, 1)) == 1
    assert months_between(date(2026, 7, 1), date(2026, 7, 1)) == 0


def test_month_range_is_half_open() -> None:
    assert month_range(date(2026, 1, 1), date(2026, 4, 1)) == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]


def test_reference_month_defaults_to_last_closed() -> None:
    assert reference_month(None, date(2026, 7, 1)) == date(2026, 7, 1)
    assert reference_month(date(2026, 3, 15), date(2026, 7, 1)) == date(2026, 3, 1)
    assert reference_month(None, None) is None


def test_closed_anchor_never_goes_past_last_closed() -> None:
    assert closed_anchor(date(2026, 9, 1), date(2026, 7, 1)) == date(2026, 7, 1)
    assert closed_anchor(date(2026, 3, 1), date(2026, 7, 1)) == date(2026, 3, 1)
    assert closed_anchor(None, date(2026, 7, 1)) == date(2026, 7, 1)


# --- comparações ---------------------------------------------------------------


def test_variation_pct_without_reference_is_none() -> None:
    assert variation_pct(10, 0) is None
    assert variation_pct(110, 100) == 10.0
    assert variation_pct(-50, -100) == 50.0


def test_compare_literal_has_no_tolerance() -> None:
    assert compare_literal(100.0, 100.0) == "igual"
    assert compare_literal(100.01, 100.0) == "acima"
    assert compare_literal(99.99, 100.0) == "abaixo"
    assert direction(90, 100) == "queda"
    assert direction(100, 100) == "igual"


def test_average_uses_fixed_denominator() -> None:
    # Seis meses, dois com compra: média = soma / 6, não soma / 2.
    assert average(600, 6) == 100
    assert average(0, 0) == 0.0


@pytest.mark.parametrize(
    ("reference", "mean", "expected"),
    [
        (0, 0, "Sem movimento"),
        (10, 0, "Movimento atual sem base histórica"),
        (12, 10, "Crescimento"),
        (8, 10, "Queda"),
        (10, 10, "Estabilidade"),
    ],
)
def test_product_trend_status(reference: float, mean: float, expected: str) -> None:
    assert product_trend_status(reference, mean) == expected


# --- curva ABC (casos da comparação com o Power BI, 13-10) ----------------------


def test_abc_item_crossing_the_limit_stays_in_upper_class() -> None:
    curve, total = abc_curve([("a", 70), ("b", 15), ("c", 10), ("d", 5)])
    classes = {line.item_id: line.abc_class for line in curve}
    # a: 0 -> 70 (A); b: 70 -> 85 cruza 80 e fica em A; c: 85 -> 95 em B; d: 95 -> 100 em C.
    assert classes == {"a": "A", "b": "A", "c": "B", "d": "C"}
    assert total == 100
    assert [line.cumulative for line in curve] == [70.0, 85.0, 95.0, 100.0]


def test_abc_negative_goes_last_in_c_and_cumulative_passes_100() -> None:
    curve, total = abc_curve([("a", 90), ("neg", -10), ("b", 20)])
    assert total == 100
    assert [line.item_id for line in curve] == ["a", "b", "neg"]
    assert curve[1].cumulative == 110.0
    assert curve[-1].abc_class == "C"


def test_abc_zero_is_without_participation_and_ties_break_by_code() -> None:
    curve, _ = abc_curve([("z", 50), ("y", 50), ("x", 0)])
    assert [line.item_id for line in curve] == ["y", "z", "x"]
    assert curve[-1].abc_class == "sem_participacao"
    assert curve[-1].share == 0.0


def test_abc_without_positive_total_does_not_divide() -> None:
    curve, total = abc_curve([("a", 10), ("b", -20)])
    assert total == -10
    assert {line.abc_class for line in curve} == {"sem_base"}
    assert all(line.share is None for line in curve)


# --- frequência e recência --------------------------------------------------------


@pytest.mark.parametrize(
    ("months", "expected"),
    [
        (12, "Mensal"),
        (9, "Mensal"),
        (8, "Bimestral"),
        (6, "Bimestral"),
        (5, "Trimestral"),
        (4, "Trimestral"),
        (3, "Semestral"),
        (2, "Semestral"),
        (1, "Ocasional"),
        (0, "Ocasional"),
    ],
)
def test_frequency_bands_follow_power_bi(months: int, expected: str) -> None:
    assert frequency_class(months) == expected


def test_recency_counts_competences_until_reference() -> None:
    assert recency(date(2026, 7, 1), date(2026, 7, 1)) == 0
    assert recency(date(2026, 4, 1), date(2026, 7, 1)) == 3
    assert recency(None, date(2026, 7, 1)) is None


# --- ticket médio ----------------------------------------------------------------


def test_ticket_sums_before_dividing_and_refuses_non_positive_kg() -> None:
    assert ticket(1000, 400) == 2.5
    assert ticket(1000, 0) is None
    assert ticket(1000, -5) is None


@pytest.mark.parametrize(
    ("current", "previous", "status"),
    [
        (10.2, 10.0, "estavel"),
        (9.8, 10.0, "estavel"),
        (10.21, 10.0, "ascensao"),
        (9.79, 10.0, "queda"),
        (None, 10.0, "nao_calculavel"),
        (10.0, None, "nao_calculavel"),
    ],
)
def test_ticket_tolerance_includes_the_limits(current, previous, status) -> None:
    assert classify_ticket(current, previous)[1] == status


def test_split_halves_puts_extra_month_in_second_half() -> None:
    months = month_range(date(2026, 1, 1), date(2026, 6, 1))  # 5 meses
    first, second = split_halves(months)
    assert len(first) == 2
    assert len(second) == 3


# --- sazonalidade ------------------------------------------------------------------


def test_coverage_labels() -> None:
    assert coverage_label(11) == "historico_insuficiente"
    assert coverage_label(19) == "perfil_descritivo"
    assert coverage_label(24) == "indicio_sazonal"
    assert coverage_label(36) == "indice_sazonal_consolidado"


def test_seasonal_index_uses_only_complete_years() -> None:
    series = {date(2025, month, 1): (100.0, 10.0) for month in range(1, 13)}
    series[date(2025, 12, 1)] = (200.0, 20.0)
    # 2026 incompleto: entra na média descritiva, não no índice.
    series.update({date(2026, month, 1): (1000.0, 1.0) for month in range(1, 8)})
    profile = seasonal_profile(series)
    assert profile.complete_years == [2025]
    yearly_mean = (100 * 11 + 200) / 12
    assert profile.by_month[12]["indice"] == round(200 / yearly_mean, 4)
    assert profile.by_month[1]["indice"] == round(100 / yearly_mean, 4)
    assert profile.by_month[1]["competencias"] == 2
    assert profile.by_month[1]["media_fat_rs"] == 550.0


def test_seasonal_year_without_sales_is_flagged() -> None:
    series = {date(2025, month, 1): (0.0, 0.0) for month in range(1, 13)}
    profile = seasonal_profile(series)
    assert profile.years_without_base == [2025]
    assert profile.by_month[1]["indice"] is None


# --- potencial de crescimento ---------------------------------------------------------


def test_growth_requires_all_three_criteria() -> None:
    ok = growth_criteria(9, 12, 2, 600, 900, 6)
    assert ok["candidato"] is True
    assert ok["crescimento_pct"] == 50.0
    # 8 de 12 = 66,7%: não passa do limite ESTRITO de 70%.
    assert growth_criteria(8, 12, 5, 600, 900, 6)["candidato"] is False
    assert growth_criteria(12, 12, 1, 600, 900, 6)["candidato"] is False
    assert growth_criteria(12, 12, 3, 900, 900, 6)["candidato"] is False


# --- baixo giro ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((5, 10, 50, 100, False), "baixo_giro"),
        ((5, 10, 150, 100, False), "resultado_misto"),
        ((15, 10, 50, 100, False), "resultado_misto"),
        ((10, 10, 100, 100, False), "sem_queda"),
        ((0, 0, 0, 0, False), "sem_queda"),
        ((5, 10, 50, 100, True), "novo/sem historico suficiente"),
    ],
)
def test_turnover_status(args, expected) -> None:
    assert turnover_status(*args) == expected


# --- séries e avisos --------------------------------------------------------------------


def test_pivot_sums_rows_of_the_same_key_and_month() -> None:
    rows = [
        {"item_id": "1", "competencia": "2026-05-01", "fat_rs": 10, "fat_kg": 1},
        {"item_id": "1", "competencia": date(2026, 5, 1), "fat_rs": 5, "fat_kg": 2},
        {"item_id": "2", "competencia": date(2026, 6, 1), "fat_rs": None, "fat_kg": 3},
    ]
    series = pivot(rows, ["item_id"])
    assert series[("1",)].months[date(2026, 5, 1)] == (15.0, 3.0)
    assert series[("2",)].value(date(2026, 6, 1), "fat_rs") == 0.0
    assert series[("2",)].purchase_months([date(2026, 6, 1)]) == []


def test_open_rule_and_negative_notices_are_informative() -> None:
    notice = open_rule_notice("a tolerância ainda não foi definida.")
    assert notice.code == OPEN_RULE
    assert "não fechada por completo" in notice.text
    assert "informativo" in notice.text
    assert "2 item(ns)" in negative_notice(2).text


def test_regional_windows_parse_subsets() -> None:
    assert parse_windows("3|6|12") == [3, 6, 12]
    assert parse_windows("6") == [6]
    assert parse_windows("12, 3") == [3, 12]
    assert parse_windows(None) == [3, 6, 12]
    assert parse_windows("24") == [3, 6, 12]
