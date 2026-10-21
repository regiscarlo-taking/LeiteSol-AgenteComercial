"""OP15 - analisar_evolucao_por_representante (skill Desempenho Comercial).

Regra do catálogo (22-07, AIC-290 em 07-10, D-A61): padrão = ano corrente,
meses fechados. A venda é do VENDEDOR ATUAL do cliente (BISA1.A1_VEND), como
no Power BI. Visões: representante (só RCA), vendedor (RCA + gestor que
vende), carteira do gestor (gestor + toda a árvore abaixo, D-A57) e vendas
do gestor (clientes cujo vendedor atual é o próprio gestor). Os mesmos
filtros valem em todas as competências e no ano anterior.

Saída em formato de ranking: uma linha por participante, uma coluna por mês,
total do período, total do mesmo período do ano anterior e variação.
"""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.analytics import (
    add_months,
    build_period,
    column,
    direction,
    history_notice,
    limit_notice,
    metric_round,
    metrics_for,
    month_range,
    month_text,
    monthly_query,
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
)
from leitesol_agent.application.operations.common import (
    HISTORY_START,
    METRICS,
    has_open_month,
    last_closed_month,
)
from leitesol_agent.domain.models import Notice, Scope

MAX_ROWS = 100
VIEWS = {
    "representante": ("RCA",),
    "vendedor": ("RCA", "Gestor"),
    "vendas_gestor": ("Gestor",),
}
VIEW_TEXT = {
    "representante": "representante (só RCA, sem gestor)",
    "vendedor": "vendedor (RCA e gestor que vende)",
    "carteira_gestor": "carteira do gestor (gestor e toda a equipe abaixo dele)",
    "vendas_gestor": "vendas do gestor (clientes cujo vendedor atual é o próprio gestor)",
}
TEAM_JOIN = (
    "JOIN [IA_COMERCIAL].[vw_hierarquia_equipe] h ON h.RepresentanteId = c.RCAAtual\n"
    "        LEFT JOIN [IA_COMERCIAL].[vw_dim_representante] g ON g.RepresentanteId = h.GestorId"
)


def resolve_months(values: dict[str, Any], last_closed: date) -> list[date]:
    if values.get("periodo_inicio") and values.get("periodo_fim"):
        start, end = sorted((values["periodo_inicio"], values["periodo_fim"]))
        return month_range(month_start(start), month_end_exclusive(end))
    year = values.get("ano") or last_closed.year
    end = min(date(year, 12, 1), month_start(last_closed))
    return month_range(date(year, 1, 1), month_end_exclusive(end))


def query_parts(view: str, participant: str | None) -> tuple[tuple, tuple, list, str]:
    """Chave, rótulo, filtros extras e JOIN de cada visão comercial."""
    if view == "carteira_gestor":
        keys = (("h.GestorId", "participante_id"),)
        labels = (("MAX(g.Representante)", "participante"),)
        extra = [("h.GestorId <> ?", ["0"])]
        if participant:
            extra.append(
                (
                    "(h.GestorId = ? OR UPPER(g.Representante) = ?)",
                    [participant, participant.upper()],
                )
            )
        return keys, labels, extra, TEAM_JOIN
    roles = VIEWS[view]
    keys = (("c.RCAAtual", "participante_id"),)
    labels = (("MAX(r.Representante)", "participante"),)
    extra = [(f"r.PapelComercial IN ({', '.join('?' for _ in roles)})", list(roles))]
    if participant:
        extra.append(
            ("(c.RCAAtual = ? OR UPPER(r.Representante) = ?)", [participant, participant.upper()])
        )
    return keys, labels, extra, ""


def shape(
    rows: list[dict[str, Any]], months: list[date], previous: list[date], metric_choice: str
) -> dict[str, Any]:
    metrics = metrics_for(metric_choice)
    lead = metrics[0]
    lines = []
    for series in pivot(rows, ["participante_id"], ["participante"]).values():
        line: dict[str, Any] = {"participante_id": series.key[0], **series.labels}
        for month in months:
            line[month_text(month)] = metric_round(lead, series.value(month, source_metric(lead)))
        for metric in metrics:
            current = series.total(months, source_metric(metric))
            before = series.total(previous, source_metric(metric))
            line[f"{metric}_total"] = metric_round(metric, current)
            line[f"{metric}_ano_anterior"] = metric_round(metric, before)
            line[f"{metric}_variacao_pct"] = variation_pct(current, before)
            line[f"{metric}_situacao"] = direction(current, before)
        lines.append(line)
    lines.sort(key=lambda line: (-line[f"{lead}_total"], str(line["participante_id"])))
    for position, line in enumerate(lines, start=1):
        line["posicao"] = position

    label, unit = METRICS[lead]
    header = [
        column("posicao", "Posição"),
        column("participante_id", "Código"),
        column("participante", "Nome"),
    ]
    header.extend(
        column(month_text(month), f"{label} {month.strftime('%m/%y')}", unit) for month in months
    )
    for metric in metrics:
        metric_label, metric_unit = METRICS[metric]
        header.extend(
            [
                column(f"{metric}_total", f"{metric_label} no período", metric_unit),
                column(
                    f"{metric}_ano_anterior",
                    f"{metric_label} mesmo período do ano anterior",
                    metric_unit,
                ),
                column(f"{metric}_variacao_pct", f"Variação {metric_label}", "%"),
                column(f"{metric}_situacao", f"Situação {metric_label}"),
            ]
        )
    return {"colunas": header, "linhas": lines}


class SellerEvolution:
    operation_id = "OP15"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        last_closed = last_closed_month(fetcher)
        if last_closed is None:
            return OperationResult.clarification(
                "Qual período você quer analisar? Informe o mês e o ano."
            )
        months = resolve_months(values, last_closed)
        if not months:
            return OperationResult.clarification(
                "O ano pedido ainda não tem mês fechado. Qual período você quer?"
            )
        previous = [add_months(month, -12) for month in months]
        end_exclusive = month_end_exclusive(months[-1])

        product, question = resolve_product(fetcher, values)
        if question:
            return question
        view = values.get("tipo_visao") or "representante"
        keys, labels, extra, joins = query_parts(
            view, (values.get("participante") or "").strip() or None
        )
        partial = has_open_month(fetcher, months[0], end_exclusive)
        sql, params = monthly_query(
            values, scope, previous[0], end_exclusive, keys, labels, product, extra, joins
        )
        rows = fetcher.fetch(sql, tuple(params))
        main_block = shape(rows, months, previous, values.get("metrica") or "ambas")

        notices: list[Notice] = [
            Notice(
                "OP15_VISAO",
                "operacao",
                f"Visão aplicada: {VIEW_TEXT[view]}. A venda é creditada ao vendedor ATUAL do cliente: "
                "quando um cliente muda de carteira, o histórico dele vai junto para o novo vendedor.",
            )
        ]
        if partial:
            notices.append(partial_notice("O período inclui mês ainda não fechado."))
        if previous[0] < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: parte do ano anterior não tem dado para comparar."
                )
            )
        total = len(main_block["linhas"])
        if total > MAX_ROWS:
            main_block["linhas"] = main_block["linhas"][:MAX_ROWS]
            notices.append(limit_notice(MAX_ROWS, total, "participantes"))
        return OperationResult(
            period=build_period(
                months[0],
                end_exclusive,
                last_closed,
                (previous[0], month_end_exclusive(previous[-1])),
                partial,
            ),
            main_block=main_block,
            notices=notices,
        )
