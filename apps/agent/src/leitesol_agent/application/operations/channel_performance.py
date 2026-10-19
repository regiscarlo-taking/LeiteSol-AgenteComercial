"""OP20 - analisar_desempenho_por_canal_segmento (skill Desempenho Comercial).

Regra do catálogo (13-07 e 22-07): canal = SEGMENTO ATUAL do cadastro
(BISA1.A1_USEGMEN); "hoje" = mês vigente, porque a base é mensal. Cada
segmento é comparado com o mesmo mês do ano anterior E o acumulado fechado
do ano com o acumulado equivalente do ano anterior - nunca só com o mês
imediatamente anterior. R$ e KG separados. ND e OUTRO ficam sinalizados.

Em aberto: o canal comercial de verdade (Direta LS, RCA, Agenciador,
Funcionário, Transportadora) está na coluna FILTRO VENDEDOR da planilha
ZZ_GESTOR_COMERCIAL, que não chegou ao banco (P-CANAL). Segmento é a
aproximação decidida com o cliente em 22-07, e a tabela de pedidos saiu do
escopo em 13-07.
"""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.analytics import (
    add_months,
    build_period,
    column,
    commercial_filter,
    direction,
    history_notice,
    metric_round,
    metrics_for,
    month_range,
    month_text,
    monthly_query,
    open_rule_notice,
    partial_notice,
    pivot,
    resolve_product,
    source_metric,
    variation_pct,
)
from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
    month_start,
    normalize_term,
)
from leitesol_agent.application.operations.common import (
    HISTORY_START,
    METRICS,
    has_open_month,
    last_closed_month,
)
from leitesol_agent.domain.models import Notice, Scope

KEYS = (("c.SegmentoCodigo", "segmento_id"),)
LABELS = (("MAX(c.SegmentoDescricao)", "segmento"),)
UNCLASSIFIED = {"ND", "OUTRO", "OUTROS", "", "NONE"}


def accumulated_months(reference: date, last_closed: date | None) -> list[date]:
    """Acumulado FECHADO do ano: janeiro até a última competência fechada <= referência."""
    end = reference
    if last_closed is None:
        end = add_months(reference, -1)
    elif month_start(last_closed) < reference:
        end = month_start(last_closed)
    if end.year != reference.year:
        return []
    return month_range(date(reference.year, 1, 1), month_end_exclusive(end))


def shape(
    rows: list[dict[str, Any]],
    reference: date,
    accumulated: list[date],
    metric_choice: str,
    top_n: int | None,
) -> dict[str, Any]:
    metrics = metrics_for(metric_choice)
    lead = metrics[0]
    last_year = add_months(reference, -12)
    previous_accumulated = [add_months(month, -12) for month in accumulated]
    segments = list(pivot(rows, ["segmento_id"], ["segmento"]).values())
    totals = {
        metric: sum(series.value(reference, source_metric(metric)) for series in segments)
        for metric in metrics
    }
    lines = []
    for series in segments:
        code = str(series.key[0] or "").strip()
        line: dict[str, Any] = {
            "segmento_id": code or None,
            "segmento": series.labels.get("segmento") or "Sem segmento",
            "observacao": "Sem classificação de segmento" if code.upper() in UNCLASSIFIED else None,
        }
        for metric in metrics:
            source = source_metric(metric)
            month = series.value(reference, source)
            before = series.value(last_year, source)
            line[f"{metric}_mes"] = metric_round(metric, month)
            line[f"{metric}_mes_ano_anterior"] = metric_round(metric, before)
            line[f"{metric}_variacao_mes_pct"] = variation_pct(month, before)
            line[f"{metric}_situacao_mes"] = direction(month, before)
            line[f"{metric}_participacao"] = (
                round(month / totals[metric] * 100, 2) if totals[metric] > 0 else None
            )
            if accumulated:
                current_acc = series.total(accumulated, source)
                previous_acc = series.total(previous_accumulated, source)
                line[f"{metric}_acumulado"] = metric_round(metric, current_acc)
                line[f"{metric}_acumulado_ano_anterior"] = metric_round(metric, previous_acc)
                line[f"{metric}_variacao_acumulado_pct"] = variation_pct(current_acc, previous_acc)
                line[f"{metric}_situacao_acumulado"] = direction(current_acc, previous_acc)
        lines.append(line)
    lines.sort(key=lambda line: (-line[f"{lead}_mes"], str(line["segmento_id"])))
    for position, line in enumerate(lines, start=1):
        line["posicao"] = position
    if top_n:
        lines = lines[:top_n]

    header = [
        column("posicao", "Posição"),
        column("segmento_id", "Código"),
        column("segmento", "Segmento (canal)"),
    ]
    for metric in metrics:
        label, unit = METRICS[metric]
        header.extend(
            [
                column(f"{metric}_mes", f"{label} {month_text(reference)}", unit),
                column(f"{metric}_mes_ano_anterior", f"{label} {month_text(last_year)}", unit),
                column(f"{metric}_variacao_mes_pct", f"Variação {label} no mês", "%"),
                column(f"{metric}_situacao_mes", f"Situação {label} no mês"),
                column(f"{metric}_participacao", f"Participação {label} no mês", "%"),
            ]
        )
        if accumulated:
            header.extend(
                [
                    column(f"{metric}_acumulado", f"{label} acumulado {reference.year}", unit),
                    column(
                        f"{metric}_acumulado_ano_anterior",
                        f"{label} acumulado {reference.year - 1}",
                        unit,
                    ),
                    column(f"{metric}_variacao_acumulado_pct", f"Variação {label} acumulada", "%"),
                    column(f"{metric}_situacao_acumulado", f"Situação {label} acumulada"),
                ]
            )
    header.append(column("observacao", "Observação"))
    return {"colunas": header, "linhas": lines}


class ChannelPerformance:
    operation_id = "OP20"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        last_closed = last_closed_month(fetcher)
        requested = values.get("mes_referencia")
        if requested is None:
            if last_closed is None:
                return OperationResult.clarification(
                    "Qual mês você quer analisar? Informe o mês e o ano."
                )
            requested = add_months(last_closed, 1)  # "hoje" = mês vigente
        reference = month_start(requested)
        accumulated = accumulated_months(reference, last_closed)
        start = date(reference.year - 1, 1, 1)
        end_exclusive = month_end_exclusive(reference)

        product, question = resolve_product(fetcher, values)
        if question:
            return question
        extra = commercial_filter(values)
        if values.get("canal_segmento"):
            segment = values["canal_segmento"].strip()
            extra.append(
                (
                    "(c.SegmentoCodigo = ? OR UPPER(c.SegmentoDescricao) = ?)",
                    [segment, normalize_term(segment)],
                )
            )
        partial = has_open_month(fetcher, reference, end_exclusive)
        sql, params = monthly_query(
            values, scope, start, end_exclusive, KEYS, LABELS, product, extra
        )
        rows = fetcher.fetch(sql, tuple(params))
        main_block = shape(
            rows, reference, accumulated, values.get("metrica") or "ambas", values.get("top_n")
        )

        accumulated_text = (
            f"acumulado de {month_text(accumulated[0])} a {month_text(accumulated[-1])} contra o mesmo "
            "intervalo do ano anterior"
            if accumulated
            else "sem acumulado fechado no ano (a referência é o primeiro mês do ano)"
        )
        notices: list[Notice] = [
            Notice(
                "OP20_COMPARACAO",
                "operacao",
                f"{month_text(reference)} contra {month_text(add_months(reference, -12))}, e {accumulated_text}. "
                "O segmento é o do cadastro atual e vale para todo o histórico do cliente.",
            ),
            open_rule_notice(
                "o canal comercial (Direta LS, RCA, Agenciador, Funcionário, Transportadora) não está na "
                "base do agente; a análise usa o segmento do cadastro como canal, conforme combinado em "
                "22-07, e não lê a tabela de pedidos."
            ),
        ]
        if partial:
            notices.append(
                partial_notice(
                    f"{month_text(reference)} ainda não fechou: o valor do mês é parcial e tende a ficar abaixo do ano anterior."
                )
            )
        if start < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: o ano anterior pode estar incompleto."
                )
            )
        return OperationResult(
            period=build_period(
                reference,
                end_exclusive,
                last_closed,
                (add_months(reference, -12), add_months(end_exclusive, -12)),
                partial,
            ),
            main_block=main_block,
            notices=notices,
        )
