"""OP04 - classificar_tendencia_6m (skill Histórico e Evolução de Vendas).

Regra do catálogo (21-07): mês de referência = último fechado; janela = N
meses fechados ANTERIORES (padrão 6), sem o mês de referência. Universo =
produtos com movimento no mês OU na janela; mês sem movimento vale zero.
Cada produto é comparado com a própria média (soma / N). Nível = SKU.

Em aberto (P04): a tolerância que separa crescimento, queda e estabilidade
não foi homologada. A comparação é literal e a resposta leva a ressalva.
"""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.analytics import (
    TREND_ORDER,
    add_months,
    average,
    build_period,
    column,
    history_notice,
    metric_round,
    metrics_for,
    monthly_query,
    negative_notice,
    open_rule_notice,
    partial_notice,
    pivot,
    product_trend_status,
    reference_month,
    resolve_product,
    variation_pct,
)
from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
)
from leitesol_agent.application.operations.common import (
    HISTORY_START,
    METRICS,
    client_filter,
    has_open_month,
    last_closed_month,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Scope

PRODUCT_FILTERS = ("produto", "familia", "grupo_subgrupo")
STATUS_FILTER = {
    "crescimento": "Crescimento",
    "queda": "Queda",
    "estabilidade": "Estabilidade",
}
KEYS = (("p.ProdutoId", "item_id"),)
LABELS = (
    ("MAX(p.Produto)", "produto"),
    ("MAX(p.Familia)", "familia"),
    ("MAX(p.Grupamento)", "grupamento"),
    ("MAX(c.UF)", "uf"),
)


def shape_rows(
    rows: list[dict[str, Any]],
    reference: date,
    history: list[date],
    metric_choice: str,
    wanted: str,
) -> tuple[dict[str, Any], int]:
    metrics = metrics_for(metric_choice, default="fat_kg")
    lead = metrics[0]
    months = len(history)
    negatives = 0
    lines: list[dict[str, Any]] = []
    for series in pivot(rows, ["item_id"], ["produto", "familia", "grupamento", "uf"]).values():
        line: dict[str, Any] = {"produto_id": series.key[0], **series.labels}
        skip = False
        for metric in metrics:
            current = series.value(reference, metric)
            mean = average(series.total(history, metric), months)
            negatives += int(current < 0 or mean < 0)
            status = product_trend_status(current, mean)
            if metric == lead and status == "Sem movimento":
                skip = True
            line[f"{metric}_referencia"] = metric_round(metric, current)
            line[f"{metric}_media"] = metric_round(metric, mean)
            line[f"{metric}_diferenca"] = metric_round(metric, current - mean)
            line[f"{metric}_variacao_pct"] = variation_pct(current, mean)
            line[f"{metric}_classificacao"] = status
        if skip:
            continue
        line["serie"] = " | ".join(
            f"{month.strftime('%m/%y')} {metric_round(lead, series.value(month, lead))}"
            for month in [*history, reference]
        )
        if wanted in STATUS_FILTER and line[f"{lead}_classificacao"] != STATUS_FILTER[wanted]:
            continue
        lines.append(line)

    lines.sort(
        key=lambda line: (
            TREND_ORDER.get(line[f"{lead}_classificacao"], 9),
            -abs(line[f"{lead}_variacao_pct"] or 0),
            str(line.get("familia") or ""),
            str(line.get("produto") or ""),
            str(line["produto_id"]),
        )
    )
    header = [
        column("produto_id", "Código"),
        column("produto", "Produto"),
        column("familia", "Família"),
        column("grupamento", "Grupamento"),
        column("uf", "UF"),
    ]
    for metric in metrics:
        label, unit = METRICS[metric]
        header.extend(
            [
                column(f"{metric}_referencia", f"{label} no mês", unit),
                column(f"{metric}_media", f"Média {label} {months} meses", unit),
                column(f"{metric}_diferenca", f"Diferença {label}", unit),
                column(f"{metric}_variacao_pct", f"Variação {label}", "%"),
                column(f"{metric}_classificacao", f"Classificação {label}"),
            ]
        )
    header.append(column("serie", f"Série mensal ({METRICS[lead][1]})"))
    return {"colunas": header, "linhas": lines}, negatives


class ClientProductTrend:
    operation_id = "OP04"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        months = values.get("meses_media") or 6
        last_closed = last_closed_month(fetcher)
        requested = values.get("mes_referencia")
        if requested is None and values.get("incluir_mes_atual") and last_closed:
            requested = add_months(last_closed, 1)
        reference = reference_month(requested, last_closed)
        if reference is None:
            return OperationResult.clarification(
                "Qual mês você quer analisar? Informe o mês e o ano."
            )
        window = months_back(reference, months + 1)
        history = window[:-1]
        end_exclusive = month_end_exclusive(reference)

        product, question = resolve_product(fetcher, values, PRODUCT_FILTERS)
        if question:
            return question

        partial = has_open_month(fetcher, reference, end_exclusive)
        # cliente_loja aceita código, CNPJ ou rede (client_filter), não só o código
        # que o universe_where conhece - por isso sai dos filtros comuns.
        client = client_filter(values["cliente_loja"])
        common = {key: value for key, value in values.items() if key != "cliente_loja"}
        sql, params = monthly_query(
            common, scope, window[0], end_exclusive, KEYS, LABELS, product, extra=[client]
        )
        rows = fetcher.fetch(sql, tuple(params))
        main_block, negatives = shape_rows(
            rows,
            reference,
            history,
            values.get("metrica_comparacao") or "fat_kg",
            values.get("tipo_evolucao") or "todas",
        )

        notices: list[Notice] = [
            open_rule_notice(
                "a margem de tolerância que separa crescimento, queda e estabilidade ainda não foi "
                "definida. A classificação usa comparação literal com a média e é provisória."
            )
        ]
        if partial:
            notices.append(partial_notice())
        if window[0] < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: parte da janela da média não tem dado."
                )
            )
        if negatives:
            notices.append(negative_notice(negatives))
        return OperationResult(
            period=build_period(
                reference, end_exclusive, last_closed, (window[0], reference), partial
            ),
            main_block=main_block,
            notices=notices,
        )
