"""OP09 e OP10 - itens que o cliente comprava e deixou de comprar (skill Mix e Portfólio).

OP09 - identificar_produtos_em_churn (21-07, AIC-287 em 02-10): item com
compra válida (FAT R$ > 0 em algum mês) no período anterior e nenhuma no
período atual. Sem período anterior informado, vale o intervalo
imediatamente anterior de MESMO tamanho. Conferida contra o Power BI em
13-10 (Carrefour, item 651).

OP10 - identificar_itens_ausentes (22-07): M-3 é UMA competência, três meses
antes de M; mesma regra de presença. M vigente é parcial e precisa de aviso.

Nenhuma das duas infere a causa da ausência. O motivo (preço, ruptura,
giro na gôndola) é Fase 2/3 do glossário e depende de fontes não integradas.
"""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.analytics import (
    Series,
    add_months,
    build_period,
    column,
    history_notice,
    metric_round,
    month_range,
    month_text,
    monthly_query,
    partial_notice,
    pivot,
    product_level,
    resolve_product,
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

LABELS = (("MAX(p.Familia)", "familia"), ("MAX(p.Grupamento)", "grupamento"))
NO_CAUSE = Notice(
    "SEM_CAUSA",
    "operacao",
    "A lista mostra só a ausência de compra. O agente não indica o motivo (preço, falta de estoque "
    "ou giro na gôndola): essa investigação é da Fase 2/3 e depende de fontes ainda não integradas.",
)


def absent_items(
    items: dict[tuple[Any, ...], Series], before: list[date], after: list[date]
) -> list[dict[str, Any]]:
    """Itens com compra válida em `before` e nenhuma em `after`."""
    lines = []
    for series in items.values():
        bought_before = series.purchase_months(before)
        if not bought_before or series.purchase_months(after):
            continue
        lines.append(
            {
                "item_id": series.key[0],
                **series.labels,
                "fat_rs_antes": metric_round("fat_rs", series.total(before, "fat_rs")),
                "fat_kg_antes": metric_round("fat_kg", series.total(before, "fat_kg")),
                "meses_com_compra_antes": len(bought_before),
                "ultima_compra": month_text(max(series.purchase_months(sorted(series.months)))),
                "fat_kg_depois": metric_round("fat_kg", series.total(after, "fat_kg")),
            }
        )
    lines.sort(key=lambda line: (-line["fat_kg_antes"], str(line["item_id"])))
    return lines


def header(before_label: str, after_label: str) -> list[dict[str, Any]]:
    return [
        column("item_id", "Código"),
        column("item", "Item"),
        column("familia", "Família"),
        column("grupamento", "Grupamento"),
        column("fat_rs_antes", f"FAT R$ {before_label}", "R$"),
        column("fat_kg_antes", f"FAT KG {before_label}", "KG"),
        column("meses_com_compra_antes", f"Meses com compra {before_label}"),
        column("ultima_compra", "Última competência com compra"),
        column("fat_kg_depois", f"FAT KG {after_label} (bonificação/devolução)", "KG"),
    ]


def fetch_items(
    fetcher: SqlFetcher,
    values: dict[str, Any],
    scope: Scope,
    start: date,
    end_exclusive: date,
) -> dict[tuple[Any, ...], Series] | OperationResult:
    level, question = product_level(values)
    if question:
        return question
    product, question = resolve_product(fetcher, values)
    if question:
        return question
    key, label = level
    sql, params = monthly_query(
        values,
        scope,
        start,
        end_exclusive,
        ((key, "item_id"),),
        ((label, "item"), *LABELS),
        product,
        extra=[client_filter(values["escopo_cliente"])],
    )
    return pivot(fetcher.fetch(sql, tuple(params)), ["item_id"], ["item", "familia", "grupamento"])


def status_notice(values: dict[str, Any]) -> list[Notice]:
    if not values.get("status_produto"):
        return []
    return [
        Notice(
            "SEM_STATUS_PRODUTO",
            "resposta",
            "O cadastro de produto do Warehouse não traz a situação (ativo, bloqueado, substituído): "
            "o filtro de status não foi aplicado e todos os itens com histórico aparecem.",
        )
    ]


class ProductChurn:
    operation_id = "OP09"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        start, end = values["periodo_atual_inicio"], values["periodo_atual_fim"]
        if end < start:
            start, end = end, start
        current = month_range(month_start(start), month_end_exclusive(end))
        if values.get("periodo_anterior_inicio") and values.get("periodo_anterior_fim"):
            previous = month_range(
                month_start(values["periodo_anterior_inicio"]),
                month_end_exclusive(values["periodo_anterior_fim"]),
            )
        else:
            previous = month_range(add_months(current[0], -len(current)), current[0])
        first = min(previous[0], current[0])
        end_exclusive = month_end_exclusive(max(previous[-1], current[-1]))

        items = fetch_items(fetcher, values, scope, first, end_exclusive)
        if isinstance(items, OperationResult):
            return items
        last_closed = last_closed_month(fetcher)
        partial = has_open_month(fetcher, current[0], month_end_exclusive(current[-1]))
        lines = absent_items(items, previous, current)

        notices = [
            Notice(
                "OP09_PERIODOS",
                "operacao",
                f"Itens comprados entre {month_text(previous[0])} e {month_text(previous[-1])} "
                f"sem compra entre {month_text(current[0])} e {month_text(current[-1])}. "
                "Itens descontinuados ou com código trocado continuam na lista: a conferência é do analista.",
            ),
            NO_CAUSE,
            *status_notice(values),
        ]
        if partial:
            notices.append(
                partial_notice("O período atual inclui mês ainda não fechado: itens podem voltar.")
            )
        if previous[0] < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: parte do período anterior não tem dado."
                )
            )
        return OperationResult(
            period=build_period(
                current[0],
                month_end_exclusive(current[-1]),
                last_closed,
                (previous[0], month_end_exclusive(previous[-1])),
                partial,
            ),
            main_block={"colunas": header("antes", "no período atual"), "linhas": lines},
            notices=notices,
        )


class MissingItems:
    operation_id = "OP10"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        last_closed = last_closed_month(fetcher)
        requested = values.get("mes_atual")
        if requested is None:
            if last_closed is None:
                return OperationResult.clarification(
                    "Qual mês você quer analisar? Informe o mês e o ano."
                )
            # incluir_mes_atual tem default S nesta operação: M é o mês vigente.
            include_current = values.get("incluir_mes_atual", True)
            requested = add_months(last_closed, 1) if include_current else last_closed
        month = month_start(requested)
        lag = values.get("defasagem_meses") or 3
        base = add_months(month, -lag)

        items = fetch_items(fetcher, values, scope, base, month_end_exclusive(month))
        if isinstance(items, OperationResult):
            return items
        partial = has_open_month(fetcher, month, month_end_exclusive(month))
        lines = absent_items(items, [base], [month])

        notices = [
            Notice(
                "OP10_COMPETENCIAS",
                "operacao",
                f"Itens comprados em {month_text(base)} (M-{lag}) e sem compra em {month_text(month)}. "
                f"M-{lag} é uma competência só, não a soma dos {lag} meses.",
            ),
            NO_CAUSE,
            *status_notice(values),
        ]
        if partial:
            notices.append(
                partial_notice(
                    f"{month_text(month)} ainda não fechou: o resultado é parcial e itens podem ser comprados até o fechamento."
                )
            )
        if base < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: a competência de comparação não tem dado."
                )
            )
        return OperationResult(
            period=build_period(
                month,
                month_end_exclusive(month),
                last_closed,
                (base, month_end_exclusive(base)),
                partial,
            ),
            main_block={"colunas": header(f"em M-{lag}", "em M"), "linhas": lines},
            notices=notices,
        )
