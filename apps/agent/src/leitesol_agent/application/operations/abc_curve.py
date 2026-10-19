"""OP05 - classificar_curva_abc (skill Mix e Portfólio).

Regra do catálogo (21-07, AIC-285 em 07-10, D-A60/D-A62): 12 competências
fechadas por padrão. Sem cliente na pergunta, a curva é dos CLIENTES do
escopo; com cliente, é dos PRODUTOS dele no nível pedido. R$ e KG têm curvas
independentes. Participação sobre o total líquido; classe pelo acumulado
anterior ao item (80/95%); negativo no fim, em C. Conferida contra o Power
BI em 13-10 (clientes de DF, jun/26).
"""

from typing import Any

from leitesol_agent.application.operations.analytics import (
    abc_curve,
    add_months,
    build_period,
    closed_anchor,
    column,
    history_notice,
    limit_notice,
    metric_round,
    metrics_for,
    partial_notice,
    product_level,
    resolve_product,
    window_months,
)
from leitesol_agent.application.operations.base import OperationResult, SqlFetcher
from leitesol_agent.application.operations.common import (
    FAT_KG,
    FAT_RS,
    HISTORY_START,
    METRICS,
    UNIVERSE_FROM,
    client_filter,
    has_open_month,
    last_closed_month,
    universe_where,
)
from leitesol_agent.domain.models import Notice, Scope

MAX_ROWS = 200
CLIENT_LEVEL = ("c.ClienteId", "MAX(c.RazaoSocial)")


def build_query(
    values: dict[str, Any],
    start: Any,
    end_exclusive: Any,
    scope: Scope,
    level: tuple[str, str],
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope, product)
    if values.get("escopo_cliente"):
        clause, params = client_filter(values["escopo_cliente"])
        where.add(clause, *params)
    key, label = level
    sql = f"""
        SELECT {key} AS item_id,
               {label} AS item,
               CASE WHEN MIN(c.UF) = MAX(c.UF) THEN MIN(c.UF) ELSE 'Várias' END AS uf,
               SUM({FAT_RS}) AS fat_rs,
               SUM({FAT_KG}) AS fat_kg
        {UNIVERSE_FROM}
        WHERE f.Data >= ? AND f.Data < ?
{where.sql}        GROUP BY {key}
    """
    return sql, [start, end_exclusive, *where.params]


def shape_rows(
    rows: list[dict[str, Any]], metric_choice: str, wanted: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = metrics_for(metric_choice)
    lead = metrics[0]
    lines: dict[str, dict[str, Any]] = {
        str(row["item_id"]): {
            "item_id": str(row["item_id"]),
            "item": row["item"],
            "uf": row["uf"],
            "fat_rs": metric_round("fat_rs", float(row["fat_rs"] or 0)),
            "fat_kg": metric_round("fat_kg", float(row["fat_kg"] or 0)),
        }
        for row in rows
    }
    order: list[str] = []
    summary: dict[str, Any] = {"negativos": 0, "sem_base": [], "classes": {}}
    for metric in metrics:
        curve, total = abc_curve((str(row["item_id"]), float(row[metric] or 0)) for row in rows)
        if total <= 0:
            summary["sem_base"].append(METRICS[metric][0])
        counts: dict[str, int] = {}
        for line in curve:
            target = lines[line.item_id]
            target[f"{metric}_participacao"] = line.share
            target[f"{metric}_acumulado"] = line.cumulative
            target[f"{metric}_classe"] = line.abc_class
            counts[line.abc_class] = counts.get(line.abc_class, 0) + 1
            if metric == lead:
                order.append(line.item_id)
                summary["negativos"] += int(line.value < 0)
        summary["classes"][metric] = counts

    selected = [lines[item_id] for item_id in order]
    if wanted != "todas":
        selected = [line for line in selected if str(line[f"{lead}_classe"]).lower() == wanted]
    header = [column("item_id", "Código"), column("item", "Item"), column("uf", "UF")]
    for metric in metrics:
        label, unit = METRICS[metric]
        header.extend(
            [
                column(metric, label, unit),
                column(f"{metric}_participacao", f"Participação {label}", "%"),
                column(f"{metric}_acumulado", f"Acumulado {label}", "%"),
                column(f"{metric}_classe", f"Classe {label}"),
            ]
        )
    return {"colunas": header, "linhas": selected}, summary


class AbcCurve:
    operation_id = "OP05"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        by_client = bool(values.get("escopo_cliente"))
        level = CLIENT_LEVEL
        if by_client:
            product_level_value, question = product_level(values)
            if question:
                return question
            level = product_level_value

        product, question = resolve_product(fetcher, values)
        if question:
            return question

        last_closed = last_closed_month(fetcher)
        anchor = closed_anchor(values.get("data_referencia"), last_closed)
        if anchor is None:
            return OperationResult.clarification(
                "Qual período você quer analisar? Informe o mês e o ano."
            )
        if values.get("incluir_mes_atual") and not values.get("data_referencia"):
            anchor = add_months(anchor, 1)
        months, start, end_exclusive = window_months(anchor, values.get("periodo_meses") or 12)
        partial = has_open_month(fetcher, start, end_exclusive)

        sql, params = build_query(values, start, end_exclusive, scope, level, product)
        rows = fetcher.fetch(sql, tuple(params))
        main_block, summary = shape_rows(
            rows, values.get("metrica_abc") or "ambas", values.get("classe_abc") or "todas"
        )

        universe = "produtos do cliente" if by_client else "clientes do escopo"
        notices: list[Notice] = [
            Notice(
                "OP05_UNIVERSO",
                "operacao",
                f"Curva ABC dos {universe} em {len(months)} competência(s). A classe sai do acumulado "
                "anterior ao item (A até 80%, B até 95%); R$ e KG têm curvas independentes.",
            )
        ]
        if summary["negativos"]:
            notices.append(
                Notice(
                    "OP05_NEGATIVO",
                    "resposta",
                    f"{summary['negativos']} item(ns) com valor negativo (devolução maior que venda) "
                    "ficam no fim, em C, e reduzem o total, como no Power BI: o acumulado pode passar de 100%.",
                )
            )
        if summary["sem_base"]:
            notices.append(
                Notice(
                    "OP05_SEM_BASE",
                    "resposta",
                    f"Total zero ou negativo em {', '.join(summary['sem_base'])}: não há base para a curva.",
                )
            )
        if partial:
            notices.append(partial_notice("A janela inclui o mês vigente, ainda parcial."))
        if start < HISTORY_START:
            notices.append(
                history_notice("A base começa em janeiro de 2025: parte da janela não tem dado.")
            )
        total = len(main_block["linhas"])
        if total > MAX_ROWS:
            main_block["linhas"] = main_block["linhas"][:MAX_ROWS]
            notices.append(limit_notice(MAX_ROWS, total, "itens"))
        return OperationResult(
            period=build_period(start, end_exclusive, last_closed, partial=partial),
            main_block=main_block,
            notices=notices,
        )
