"""OP12 - comparar_ano_anterior (skill SK02).

Regra do catálogo: período obrigatório, sem período padrão; o mesmo intervalo
deslocado em -1 ano, com limites fechado-aberto; os mesmos filtros nos dois
anos; base zero no ano anterior não gera percentual (RT24).

Os números saem de T-SQL sobre as views do Warehouse, com as fórmulas das
medidas do catálogo (AGT_MEDIDA): FAT R$ = vendas - devoluções; FAT KG =
vendas + bonificação - devoluções; FAT TONS = FAT KG / 1000.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    add_years,
    month_end_exclusive,
    month_start,
)
from leitesol_agent.application.operations.common import (
    FAT_KG,
    FAT_RS,
    HISTORY_START,
    METRICS,
    UNIVERSE_FROM,
    has_open_month,
    last_closed_month,
    metric_value,
    product_filter,
    product_question,
    universe_where,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Period, Scope

MAX_ROWS = 50

# granularidade -> colunas (expressão SQL, id da coluna, rótulo). A UF do
# cadastro acompanha o detalhamento por cliente e por município (RT25).
GRANULARITY_COLUMNS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "total": (),
    "cliente": (
        ("c.ClienteId", "cliente_id", "Código"),
        ("c.RazaoSocial", "cliente", "Cliente"),
        ("c.UF", "uf", "UF"),
    ),
    "produto": (("p.ProdutoId", "produto_id", "Código"), ("p.Produto", "produto", "Produto")),
    "vendedor": (
        ("c.RCAAtual", "vendedor_id", "Código"),
        ("r.Representante", "vendedor", "Vendedor"),
    ),
    "uf": (("c.UF", "uf", "UF"),),
    "municipio": (("c.UF", "uf", "UF"), ("c.Municipio", "municipio", "Município")),
    "segmento": (
        ("c.SegmentoCodigo", "segmento_id", "Código"),
        ("c.SegmentoDescricao", "segmento", "Segmento"),
    ),
}

@dataclass(slots=True)
class QueryPlan:
    sql: str
    params: list[Any] = field(default_factory=list)
    columns: tuple[tuple[str, str, str], ...] = ()


def resolve_period(values: dict[str, Any]) -> tuple[Period, bool]:
    """Normaliza para competências inteiras (RT17) e desloca -1 ano (TR06).

    Devolve o período e se houve ajuste do que o usuário pediu.
    """
    start_requested: date = values["periodo_inicio"]
    end_requested: date = values["periodo_fim"]
    if end_requested < start_requested:
        start_requested, end_requested = end_requested, start_requested
    start = month_start(start_requested)
    end_exclusive = month_end_exclusive(end_requested)
    adjusted = start != start_requested or date.fromordinal(end_exclusive.toordinal() - 1) != end_requested
    return (
        Period(
            start=start,
            end_exclusive=end_exclusive,
            comparison_start=add_years(start, -1),
            comparison_end_exclusive=add_years(end_exclusive, -1),
        ),
        adjusted,
    )


def build_query(
    values: dict[str, Any],
    period: Period,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> QueryPlan:
    granularity = values.get("granularidade") or "total"
    columns = GRANULARITY_COLUMNS.get(granularity, ())
    monthly_comparison = values.get("comparar_mes_a_mes") is True
    if monthly_comparison:
        columns = (*columns, ("MONTH(f.Data)", "comparison_month", "Competência"))
    select_dims = "".join(f"{expr} AS {col_id}, " for expr, col_id, _ in columns)
    group_by = ", ".join(expr for expr, _, _ in columns)

    current = "f.Data >= ? AND f.Data < ?"
    previous = "f.Data >= ? AND f.Data < ?"
    current_params = [period.start, period.end_exclusive]
    previous_params = [period.comparison_start, period.comparison_end_exclusive]
    where = universe_where(values, scope, product)

    sql = f"""
        SELECT {select_dims}
            SUM(CASE WHEN {current} THEN {FAT_RS} ELSE 0 END) AS fat_rs_atual,
            SUM(CASE WHEN {previous} THEN {FAT_RS} ELSE 0 END) AS fat_rs_anterior,
            SUM(CASE WHEN {current} THEN {FAT_KG} ELSE 0 END) AS fat_kg_atual,
            SUM(CASE WHEN {previous} THEN {FAT_KG} ELSE 0 END) AS fat_kg_anterior
        {UNIVERSE_FROM}
        WHERE (({current}) OR ({previous}))
{where.sql}"""
    # Ordem dos parâmetros = ordem dos ? no texto: SELECT (4 janelas), WHERE, filtros.
    params: list[Any] = [
        *current_params,
        *previous_params,
        *current_params,
        *previous_params,
        *current_params,
        *previous_params,
        *where.params,
    ]
    if group_by:
        sql += f"GROUP BY {group_by}\n"
    return QueryPlan(sql=sql, params=params, columns=columns)


def shape_rows(
    rows: list[dict[str, Any]],
    columns: tuple[tuple[str, str, str], ...],
    metric: str,
    situation: str,
    period_start: date | None = None,
    period_end_exclusive: date | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Monta o bloco principal e o de exceções (base zero, RT24)."""
    metrics = list(METRICS) if metric == "ambas" else [metric]
    # Métrica que decide ordem, situação e exceção quando o usuário pediu "ambas".
    lead = "fat_rs" if metric == "ambas" else metric

    shaped: list[dict[str, Any]] = []
    zero_base: list[dict[str, Any]] = []
    monthly_comparison = any(col_id == "comparison_month" for _, col_id, _ in columns)
    total_values = {
        "fat_rs": [0.0, 0.0],
        "fat_kg": [0.0, 0.0],
    }
    for row in rows:
        values = {
            "fat_rs": (float(row["fat_rs_atual"] or 0), float(row["fat_rs_anterior"] or 0)),
            "fat_kg": (float(row["fat_kg_atual"] or 0), float(row["fat_kg_anterior"] or 0)),
        }
        for name in total_values:
            total_values[name][0] += values[name][0]
            total_values[name][1] += values[name][1]

        line: dict[str, Any] = {}
        for _, col_id, _ in columns:
            value = row.get(col_id)
            if col_id == "comparison_month" and period_start is not None:
                month_offset = (int(value) - period_start.month) % 12
                year = period_start.year + (period_start.month - 1 + month_offset) // 12
                value = f"{int(value):02d}/{year}"
            line[col_id] = value
        for name in metrics:
            current = metric_value(name, values["fat_rs"][0], values["fat_kg"][0])
            previous = metric_value(name, values["fat_rs"][1], values["fat_kg"][1])
            line[f"{name}_atual"] = current
            line[f"{name}_anterior"] = previous
            line[f"{name}_variacao_abs"] = round(current - previous, 3)
            line[f"{name}_variacao_pct"] = (
                round((current - previous) / previous * 100, 2) if previous else None
            )

        variation = line[f"{lead}_variacao_abs"]
        if situation == "crescimento" and variation <= 0:
            continue
        if situation == "queda" and variation >= 0:
            continue
        if situation == "igual" and variation != 0:
            continue
        if not line[f"{lead}_anterior"]:
            zero_base.append(line)
            if monthly_comparison:
                shaped.append(line)
        else:
            shaped.append(line)

    if monthly_comparison:
        shaped.sort(key=lambda line: line.get("comparison_month", ""))
        if period_start is not None:
            if period_end_exclusive is not None and not any(
                col_id != "comparison_month" for _, col_id, _ in columns
            ):
                existing_months = {
                    line["comparison_month"]: line
                    for line in shaped
                    if line.get("comparison_month") != "Total do período"
                }
                month_count = (
                    (period_end_exclusive.year - period_start.year) * 12
                    + period_end_exclusive.month
                    - period_start.month
                )
                for offset in range(month_count):
                    month_index = period_start.year * 12 + period_start.month - 1 + offset
                    year, month_zero_based = divmod(month_index, 12)
                    label = f"{month_zero_based + 1:02d}/{year}"
                    if label not in existing_months:
                        zero_line: dict[str, Any] = {
                            "comparison_month": label,
                        }
                        for name in metrics:
                            zero_line[f"{name}_atual"] = 0.0
                            zero_line[f"{name}_anterior"] = 0.0
                            zero_line[f"{name}_variacao_abs"] = 0.0
                            zero_line[f"{name}_variacao_pct"] = None
                        shaped.append(zero_line)
                shaped.sort(key=lambda line: line.get("comparison_month", ""))
            total_line: dict[str, Any] = {
                col_id: "Total do período" if col_id == "comparison_month" else None
                for _, col_id, _ in columns
            }
            for name in metrics:
                current = metric_value(name, total_values["fat_rs"][0], total_values["fat_kg"][0])
                previous = metric_value(name, total_values["fat_rs"][1], total_values["fat_kg"][1])
                total_line[f"{name}_atual"] = current
                total_line[f"{name}_anterior"] = previous
                total_line[f"{name}_variacao_abs"] = round(current - previous, 3)
                total_line[f"{name}_variacao_pct"] = (
                    round((current - previous) / previous * 100, 2) if previous else None
                )
            shaped.append(total_line)
    else:
        shaped.sort(key=lambda line: abs(line[f"{lead}_variacao_abs"]), reverse=True)
    total = len(shaped)

    header = [{"id": col_id, "rotulo": label, "unidade": None} for _, col_id, label in columns]
    for name in metrics:
        label, unit = METRICS[name]
        header.extend(
            [
                {"id": f"{name}_atual", "rotulo": f"{label} atual", "unidade": unit},
                {"id": f"{name}_anterior", "rotulo": f"{label} ano anterior", "unidade": unit},
                {"id": f"{name}_variacao_abs", "rotulo": f"Variação {label}", "unidade": unit},
                {"id": f"{name}_variacao_pct", "rotulo": f"Variação {label} %", "unidade": "%"},
            ]
        )

    exceptions = (
        [{"motivo": "Base do ano anterior igual a zero", "linhas": zero_base}]
        if zero_base and not monthly_comparison
        else []
    )
    return {"colunas": header, "linhas": shaped[:MAX_ROWS]}, exceptions, total


class CompareWithPreviousYear:
    operation_id = "OP12"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        notices: list[Notice] = []

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        last_closed = last_closed_month(fetcher)
        window = values.get("janela_meses")
        if window is not None:
            if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
                return OperationResult.clarification(
                    "Informe uma quantidade positiva de competências para comparar."
                )
            if last_closed is None:
                return OperationResult.clarification(
                    "Não encontrei competência fechada no calendário para definir a comparação."
                )
            closed_month = month_start(last_closed)
            months = months_back(closed_month, window)
            start = months[0]
            end_exclusive = month_end_exclusive(closed_month)
            period = Period(
                start=start,
                end_exclusive=end_exclusive,
                comparison_start=add_years(start, -1),
                comparison_end_exclusive=add_years(end_exclusive, -1),
                partial=False,
                last_closed_month=last_closed.strftime("%Y-%m"),
            )
            adjusted = False
        else:
            period, adjusted = resolve_period(values)

        partial = has_open_month(fetcher, period.start, period.end_exclusive)
        period = Period(
            start=period.start,
            end_exclusive=period.end_exclusive,
            comparison_start=period.comparison_start,
            comparison_end_exclusive=period.comparison_end_exclusive,
            partial=partial,
            last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
        )

        month_count = (
            (period.end_exclusive.year - period.start.year) * 12
            + period.end_exclusive.month
            - period.start.month
        )
        monthly_comparison = values.get("comparar_mes_a_mes") is True or (
            (values.get("granularidade") or "total") == "total"
            and 1 < month_count <= 12
        )
        query_values = {**values, "comparar_mes_a_mes": monthly_comparison}
        plan = build_query(query_values, period, scope, product)
        rows = fetcher.fetch(plan.sql, tuple(plan.params))
        main_block, exceptions, total = shape_rows(
            rows,
            plan.columns,
            values.get("metrica") or "ambas",
            values.get("situacao") or "todas",
            period.start if monthly_comparison else None,
            period.end_exclusive if monthly_comparison else None,
        )

        if adjusted:
            notices.append(
                Notice(
                    "RT17",
                    "regra_transversal",
                    "O período foi ajustado para meses completos: o faturamento é consolidado por mês.",
                )
            )
        if partial:
            notices.append(
                Notice(
                    "TR02",
                    "regra_tempo",
                    "O período inclui mês ainda não fechado: os valores desse mês são parciais.",
                )
            )
        if period.comparison_start and period.comparison_start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base histórica começa em janeiro de 2025: antes disso não há dado para comparar.",
                )
            )
        if exceptions:
            notices.append(
                Notice(
                    "RT24",
                    "regra_transversal",
                    "Itens sem faturamento no ano anterior ficam em bloco separado, sem percentual.",
                )
            )
        if total > MAX_ROWS:
            notices.append(
                Notice(
                    "LIMITE",
                    "resposta",
                    f"Exibindo as {MAX_ROWS} maiores variações de {total} linhas.",
                )
            )

        return OperationResult(
            period=period,
            main_block=main_block,
            exceptions=exceptions,
            notices=notices,
        )
