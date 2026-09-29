"""OP17 - gerar_serie_e_grafico_12_meses (skill Histórico e Evolução de Vendas).

Regra do catálogo: 12 competências FECHADAS (TR01), terminando na última
fechada salvo pedido; meses sem venda entram com zero; os mesmos filtros nas
doze competências. O mês vigente só entra se pedido, e com aviso. A entrega
desta fase é a tabela da série: não há gráfico na interface (D-A19).
"""

from datetime import date
from typing import Any

from leitesol_api.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
    month_start,
)
from leitesol_api.application.operations.common import (
    FAT_KG,
    FAT_RS,
    HISTORY_START,
    METRICS,
    UNIVERSE_FROM,
    as_date,
    last_closed_month,
    metric_value,
    month_label,
    product_filter,
    product_question,
    universe_where,
)
from leitesol_api.domain.agent import Notice, Period, Scope


def months_back(end_month: date, count: int) -> list[date]:
    """As `count` competências que terminam em `end_month`, em ordem crescente."""
    months = [month_start(end_month)]
    while len(months) < count:
        first = months[0]
        previous = date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)
        months.insert(0, previous)
    return months


def build_query(
    values: dict[str, Any],
    start: date,
    end_exclusive: date,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope, product)
    sql = f"""
        SELECT f.Data AS competencia,
               SUM({FAT_RS}) AS fat_rs,
               SUM({FAT_KG}) AS fat_kg
        {UNIVERSE_FROM}
        WHERE f.Data >= ? AND f.Data < ?
{where.sql}        GROUP BY f.Data
    """
    return sql, [start, end_exclusive, *where.params]


def shape_rows(rows: list[dict[str, Any]], months: list[date], metric: str) -> dict[str, Any]:
    """Série completa: mês sem venda entra com zero; variação contra o mês anterior."""
    by_month = {as_date(row["competencia"]): row for row in rows}
    metrics = list(METRICS) if metric == "ambas" else [metric]
    lines: list[dict[str, Any]] = []
    previous: dict[str, float] = {}
    for month in months:
        row = by_month.get(month, {})
        fat_rs = float(row.get("fat_rs") or 0)
        fat_kg = float(row.get("fat_kg") or 0)
        line: dict[str, Any] = {"competencia": month_label(month)}
        for name in metrics:
            value = metric_value(name, fat_rs, fat_kg)
            line[name] = value
            before = previous.get(name)
            line[f"{name}_variacao_pct"] = (
                round((value - before) / before * 100, 2) if before else None
            )
            previous[name] = value
        lines.append(line)

    header = [{"id": "competencia", "rotulo": "Competência", "unidade": None}]
    for name in metrics:
        label, unit = METRICS[name]
        header.append({"id": name, "rotulo": label, "unidade": unit})
        header.append({"id": f"{name}_variacao_pct", "rotulo": f"Variação mensal {label}", "unidade": "%"})
    return {"colunas": header, "linhas": lines}


class MonthlySeries:
    operation_id = "OP17"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        notices: list[Notice] = []
        window = values.get("janela_meses") or 12
        include_current = bool(values.get("incluir_mes_atual"))

        last_closed = last_closed_month(fetcher)
        requested = values.get("competencia_referencia")
        reference = month_start(requested) if requested else last_closed
        if reference is None:
            return OperationResult.clarification(
                "Não encontrei mês fechado no calendário. Qual mês você quer usar como referência?"
            )
        # Sem pedido explícito do mês vigente, a série termina na última fechada.
        if last_closed and reference > last_closed and not include_current:
            reference = last_closed
            notices.append(
                Notice(
                    "TR01",
                    "regra_tempo",
                    "A série termina no último mês fechado; o mês em andamento não entra sem pedido.",
                )
            )

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        months = months_back(reference, window)
        start, end_exclusive = months[0], month_end_exclusive(months[-1])
        sql, params = build_query(values, start, end_exclusive, scope, product)
        rows = fetcher.fetch(sql, tuple(params))
        main_block = shape_rows(rows, months, values.get("metrica") or "ambas")

        partial = bool(last_closed and reference > last_closed)
        if partial:
            notices.append(
                Notice(
                    "TR02",
                    "regra_tempo",
                    "O último mês da série ainda não fechou: os valores dele são parciais.",
                )
            )
        if start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base começa em janeiro de 2025: os meses anteriores aparecem com zero por falta de dado, não por ausência de venda.",
                )
            )
        notices.append(
            Notice("FORMATO", "resposta", "Nesta versão a evolução é apresentada em tabela, sem gráfico.")
        )
        return OperationResult(
            period=Period(
                start=start,
                end_exclusive=end_exclusive,
                partial=partial,
                last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
            ),
            main_block=main_block,
            notices=notices,
        )
