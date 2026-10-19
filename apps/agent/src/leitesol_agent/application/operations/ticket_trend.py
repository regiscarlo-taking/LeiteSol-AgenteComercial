"""OP07 - analisar_tendencia_ticket_medio (skill Comportamento de Compra).

Regra do catálogo (21-07 e 07-08): ticket médio = PREÇO MÉDIO R$/kg, com
FAT R$ e FAT KG somados antes da divisão (nunca média dos tickets mensais).
O período analisado é comparado com o intervalo imediatamente anterior de
MESMA duração. Tendência interna = período dividido em duas metades
cronológicas (mês excedente na segunda). KG zero ou negativo não divide:
'nao_calculavel'.

Em aberto: a tolerância de ±2% e o método das metades são diretriz técnica
de 07-08, sem DAX equivalente e ainda não homologada com o cliente.
"""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.analytics import (
    Series,
    add_months,
    build_period,
    classify_ticket,
    column,
    history_notice,
    metric_round,
    month_range,
    month_text,
    monthly_query,
    open_rule_notice,
    partial_notice,
    pivot,
    resolve_product,
    split_halves,
    ticket,
)
from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
    month_start,
)
from leitesol_agent.application.operations.common import (
    HISTORY_START,
    client_filter,
    has_open_month,
    last_closed_month,
)
from leitesol_agent.domain.models import Notice, Scope

PRODUCT_FILTERS = ("produto", "familia", "grupo_subgrupo")


def periods(start: date, end: date) -> tuple[list[date], list[date]]:
    """Meses analisados e os do intervalo imediatamente anterior de mesma duração."""
    analyzed = month_range(month_start(start), month_end_exclusive(end))
    previous = month_range(add_months(analyzed[0], -len(analyzed)), analyzed[0])
    return analyzed, previous


def period_line(label: str, series: Series, months: list[date]) -> dict[str, Any]:
    fat_rs = series.total(months, "fat_rs")
    fat_kg = series.total(months, "fat_kg")
    return {
        "indicador": label,
        "periodo": f"{month_text(months[0])} a {month_text(months[-1])}",
        "fat_rs": metric_round("fat_rs", fat_rs),
        "fat_kg": metric_round("fat_kg", fat_kg),
        "ticket_rs_kg": ticket(fat_rs, fat_kg),
        "meses_com_compra": len(series.purchase_months(months)),
        "meses": len(months),
        "variacao_pct": None,
        "classificacao": None,
    }


def comparison_line(label: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    change, status = classify_ticket(after["ticket_rs_kg"], before["ticket_rs_kg"])
    return {
        "indicador": label,
        "periodo": f"{before['periodo']} -> {after['periodo']}",
        "fat_rs": None,
        "fat_kg": None,
        "ticket_rs_kg": None,
        "meses_com_compra": None,
        "meses": None,
        "variacao_pct": change,
        "classificacao": status,
    }


def shape(series: Series, analyzed: list[date], previous: list[date]) -> dict[str, Any]:
    before = period_line("Período de comparação", series, previous)
    after = period_line("Período analisado", series, analyzed)
    lines = [before, after, comparison_line("Comparação entre períodos", before, after)]
    if len(analyzed) >= 2:
        first, second = split_halves(analyzed)
        first_line = period_line("1ª metade do período analisado", series, first)
        second_line = period_line("2ª metade do período analisado", series, second)
        lines.extend(
            [first_line, second_line, comparison_line("Tendência interna", first_line, second_line)]
        )
    header = [
        column("indicador", "Indicador"),
        column("periodo", "Período"),
        column("fat_rs", "FAT R$", "R$"),
        column("fat_kg", "FAT KG", "KG"),
        column("ticket_rs_kg", "Preço médio", "R$/kg"),
        column("meses_com_compra", "Meses com compra"),
        column("meses", "Meses"),
        column("variacao_pct", "Variação", "%"),
        column("classificacao", "Classificação"),
    ]
    return {"colunas": header, "linhas": lines}


class TicketTrend:
    operation_id = "OP07"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        start, end = values["periodo_inicio"], values["periodo_fim"]
        if end < start:
            start, end = end, start
        analyzed, previous = periods(start, end)
        end_exclusive = month_end_exclusive(analyzed[-1])

        product, question = resolve_product(fetcher, values, PRODUCT_FILTERS)
        if question:
            return question

        last_closed = last_closed_month(fetcher)
        partial = has_open_month(fetcher, analyzed[0], end_exclusive)
        client = client_filter(values["cliente_loja"])
        common = {key: value for key, value in values.items() if key != "cliente_loja"}
        sql, params = monthly_query(
            common,
            scope,
            previous[0],
            end_exclusive,
            (("f.ClienteId", "cliente_id"),),
            product=product,
            extra=[client],
        )
        rows = fetcher.fetch(sql, tuple(params))
        units = {row["cliente_id"] for row in rows}
        merged = next(iter(pivot(rows, []).values()), Series(()))

        notices: list[Notice] = [
            Notice(
                "OP07_TICKET",
                "operacao",
                "Ticket médio aqui é o preço médio em R$/kg (FAT R$ / FAT KG somados no período); "
                "a base é mensal e não tem pedido ou nota. Comparação e tendência interna são "
                "indicadores separados.",
            ),
            open_rule_notice(
                "a tolerância de ±2% para estável e a divisão do período em duas metades são "
                "diretriz técnica, sem fórmula equivalente no Power BI."
            ),
        ]
        if len(units) > 1:
            notices.append(
                Notice(
                    "OP07_UNIDADES",
                    "resposta",
                    f"O cliente informado corresponde a {len(units)} unidades (lojas), somadas no cálculo. "
                    "Para uma loja só, informe o código com a loja.",
                )
            )
        if partial:
            notices.append(partial_notice("O período analisado inclui mês ainda não fechado."))
        if previous[0] < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: parte do período de comparação não tem dado."
                )
            )
        return OperationResult(
            period=build_period(
                analyzed[0], end_exclusive, last_closed, (previous[0], analyzed[0]), partial
            ),
            main_block=shape(merged, analyzed, previous),
            notices=notices,
        )
