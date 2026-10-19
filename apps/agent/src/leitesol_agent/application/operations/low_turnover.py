"""OP21 - identificar_produtos_baixo_giro (skill Mix e Portfólio).

Regra do catálogo (22-07): giro = desempenho de VENDA em KG (não há posição
de estoque). Cada produto é comparado consigo mesmo. Baixo giro exige queda
nas DUAS comparações: mês contra o mesmo mês do ano anterior E acumulado do
ano contra o acumulado equivalente. Queda em uma só = resultado misto.
Produto lançado depois do início da referência anterior = novo, nunca baixo
giro. Comparação literal, sem percentual mínimo.

Em aberto (P08): a área ficou de conferir a medida de giro do Power BI
(Índice Giro) contra esta regra.
"""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.analytics import (
    Series,
    add_months,
    build_period,
    column,
    commercial_filter,
    history_notice,
    metric_round,
    month_range,
    month_text,
    monthly_query,
    open_rule_notice,
    partial_notice,
    pivot,
    product_level,
    reference_month,
    resolve_product,
    turnover_status,
    variation_pct,
)
from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
)
from leitesol_agent.application.operations.common import (
    FAT_RS,
    HISTORY_START,
    UNIVERSE_FROM,
    has_open_month,
    last_closed_month,
    universe_where,
)
from leitesol_agent.domain.models import Notice, Scope

LABELS = (("MAX(p.Familia)", "familia"), ("MAX(p.Grupamento)", "grupamento"))


def buyers_query(
    values: dict[str, Any],
    scope: Scope,
    key: str,
    start: date,
    end_exclusive: date,
    product: tuple[str, list[Any]] | None,
    extra: list[tuple[str, list[Any]]],
) -> tuple[str, list[Any]]:
    """Clientes com compra válida (FAT R$ > 0 no acumulado) por item."""
    where = universe_where(values, scope, product)
    for clause, params in extra:
        where.add(clause, *params)
    sql = f"""
        SELECT item_id, COUNT(*) AS compradores
        FROM (
            SELECT {key} AS item_id, f.ClienteId
            {UNIVERSE_FROM}
            WHERE f.Data >= ? AND f.Data < ?
{where.sql}            GROUP BY {key}, f.ClienteId
            HAVING SUM({FAT_RS}) > 0
        ) x
        GROUP BY item_id
    """
    return sql, [start, end_exclusive, *where.params]


def classify(
    series: Series, reference: date, accumulated: list[date], buyers: int
) -> dict[str, Any]:
    last_year = add_months(reference, -12)
    previous = [add_months(month, -12) for month in accumulated]
    month_now = series.value(reference, "fat_kg")
    month_before = series.value(last_year, "fat_kg")
    acc_now = series.total(accumulated, "fat_kg")
    acc_before = series.total(previous, "fat_kg")
    sold = [month for month in sorted(series.months) if series.value(month, "fat_kg") > 0]
    first_sale = sold[0] if sold else None
    is_new = first_sale is not None and first_sale > previous[0]
    return {
        "item_id": series.key[0],
        **series.labels,
        "kg_mes": metric_round("fat_kg", month_now),
        "kg_mes_ano_anterior": metric_round("fat_kg", month_before),
        "variacao_mes_pct": variation_pct(month_now, month_before),
        "kg_acumulado": metric_round("fat_kg", acc_now),
        "kg_acumulado_ano_anterior": metric_round("fat_kg", acc_before),
        "variacao_acumulado_pct": variation_pct(acc_now, acc_before),
        "situacao": turnover_status(month_now, month_before, acc_now, acc_before, is_new),
        "fat_rs_acumulado": metric_round("fat_rs", series.total(accumulated, "fat_rs")),
        "meses_com_venda": len(
            [month for month in accumulated if series.value(month, "fat_kg") > 0]
        ),
        "compradores": buyers,
        "ultima_venda": month_text(sold[-1]) if sold else None,
    }


HEADER = [
    column("item_id", "Código"),
    column("item", "Item"),
    column("familia", "Família"),
    column("grupamento", "Grupamento"),
    column("kg_mes", "FAT KG no mês", "KG"),
    column("kg_mes_ano_anterior", "FAT KG mesmo mês do ano anterior", "KG"),
    column("variacao_mes_pct", "Variação no mês", "%"),
    column("kg_acumulado", "FAT KG acumulado no ano", "KG"),
    column("kg_acumulado_ano_anterior", "FAT KG acumulado do ano anterior", "KG"),
    column("variacao_acumulado_pct", "Variação acumulada", "%"),
    column("situacao", "Situação"),
    column("fat_rs_acumulado", "FAT R$ acumulado", "R$"),
    column("meses_com_venda", "Meses com venda no ano"),
    column("compradores", "Clientes compradores"),
    column("ultima_venda", "Última competência com venda"),
]


def shape(
    items: dict[tuple[Any, ...], Series],
    buyers: dict[Any, int],
    reference: date,
    accumulated: list[date],
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    lines = [
        classify(series, reference, accumulated, buyers.get(series.key[0], 0))
        for series in items.values()
    ]
    low = [line for line in lines if line["situacao"] == "baixo_giro"]
    low.sort(
        key=lambda line: (
            line["variacao_acumulado_pct"] if line["variacao_acumulado_pct"] is not None else 0,
            str(line["item_id"]),
        )
    )
    exceptions = []
    for status, reason in (
        ("resultado_misto", "Queda em só uma das comparações (resultado misto, não é baixo giro)"),
        ("novo/sem historico suficiente", "Produto novo ou sem histórico suficiente para comparar"),
    ):
        group = [line for line in lines if line["situacao"] == status]
        if group:
            exceptions.append({"motivo": reason, "linhas": group})
    without_fall = len([line for line in lines if line["situacao"] == "sem_queda"])
    return {"colunas": HEADER, "linhas": low}, exceptions, without_fall


class LowTurnover:
    operation_id = "OP21"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        last_closed = last_closed_month(fetcher)
        requested = values.get("mes_referencia")
        if requested is None and values.get("incluir_mes_atual") and last_closed:
            requested = add_months(last_closed, 1)
        reference = reference_month(requested, last_closed)
        if reference is None:
            return OperationResult.clarification(
                "Qual mês você quer analisar? Informe o mês e o ano."
            )
        accumulated = month_range(date(reference.year, 1, 1), month_end_exclusive(reference))
        end_exclusive = month_end_exclusive(reference)

        level, question = product_level(values)
        if question:
            return question
        product, question = resolve_product(fetcher, values)
        if question:
            return question
        key, label = level
        extra = commercial_filter(values)
        partial = has_open_month(fetcher, reference, end_exclusive)
        sql, params = monthly_query(
            values,
            scope,
            HISTORY_START,
            end_exclusive,
            ((key, "item_id"),),
            ((label, "item"), *LABELS),
            product,
            extra,
        )
        items = pivot(
            fetcher.fetch(sql, tuple(params)), ["item_id"], ["item", "familia", "grupamento"]
        )
        sql, params = buyers_query(
            values, scope, key, accumulated[0], end_exclusive, product, extra
        )
        buyers = {
            row["item_id"]: int(row["compradores"] or 0)
            for row in fetcher.fetch(sql, tuple(params))
        }
        main_block, exceptions, without_fall = shape(items, buyers, reference, accumulated)

        notices: list[Notice] = [
            Notice(
                "OP21_REGRA",
                "operacao",
                f"Giro = venda em KG (não há dado de estoque). Baixo giro = queda em {month_text(reference)} "
                f"contra o mesmo mês do ano anterior E no acumulado de {month_text(accumulated[0])} a "
                f"{month_text(reference)} contra o mesmo intervalo do ano anterior. "
                f"{without_fall} item(ns) sem queda ficaram fora da lista.",
            ),
            open_rule_notice(
                "a medida de giro ainda não foi conferida com o indicador de giro do Power BI."
            ),
        ]
        if partial:
            notices.append(
                partial_notice(
                    "O mês analisado ainda não fechou: a queda no mês pode ser só parcial."
                )
            )
        if add_months(accumulated[0], -12) < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: o ano anterior não tem dado completo."
                )
            )
        return OperationResult(
            period=build_period(
                accumulated[0],
                end_exclusive,
                last_closed,
                (add_months(accumulated[0], -12), add_months(end_exclusive, -12)),
                partial,
            ),
            main_block=main_block,
            exceptions=exceptions,
            notices=notices,
        )
