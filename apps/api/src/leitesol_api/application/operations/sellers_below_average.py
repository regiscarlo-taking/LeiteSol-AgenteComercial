"""OP18 - comparar_vendedor_com_media_3m (skill Desempenho Comercial).

Regra do catálogo: mês de referência obrigatório; vendedor = quem realizou a
venda (RCA e gestor que vende); média INDIVIDUAL dos 3 meses fechados
anteriores, com mês sem venda valendo zero (soma / 3, não média dos meses
com venda); queda avaliada literalmente por métrica - sem métrica pedida, R$
e KG são avaliados separadamente; os mesmos filtros nos quatro meses.
Média zero não gera percentual (RT24): o vendedor vai para exceções.
"""

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
    has_open_month,
    last_closed_month,
    metric_value,
    product_filter,
    product_question,
    universe_where,
)
from leitesol_api.application.operations.monthly_series import months_back
from leitesol_api.domain.agent import Notice, Period, Scope

# papel_comercial do catálogo -> valores de vw_dim_representante.PapelComercial.
ROLES = {"representante": ("RCA",), "gestor": ("Gestor",)}


def build_query(
    values: dict[str, Any],
    reference_start: Any,
    reference_end: Any,
    history_start: Any,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope, product)
    roles = ROLES.get(values.get("papel_comercial") or "todos")
    if roles:
        where.add(f"r.PapelComercial IN ({', '.join('?' for _ in roles)})", *roles)

    current = "f.Data >= ? AND f.Data < ?"
    history = "f.Data >= ? AND f.Data < ?"
    sql = f"""
        SELECT f.VendedorId AS vendedor_id,
               MAX(r.Representante) AS vendedor,
               MAX(r.PapelComercial) AS papel,
               SUM(CASE WHEN {current} THEN {FAT_RS} ELSE 0 END) AS fat_rs_mes,
               SUM(CASE WHEN {history} THEN {FAT_RS} ELSE 0 END) AS fat_rs_3m,
               SUM(CASE WHEN {current} THEN {FAT_KG} ELSE 0 END) AS fat_kg_mes,
               SUM(CASE WHEN {history} THEN {FAT_KG} ELSE 0 END) AS fat_kg_3m
        {UNIVERSE_FROM}
        WHERE f.Data >= ? AND f.Data < ?
{where.sql}        GROUP BY f.VendedorId
    """
    windows = [reference_start, reference_end, history_start, reference_start]
    params = [*windows, *windows, history_start, reference_end, *where.params]
    return sql, params


def shape_rows(
    rows: list[dict[str, Any]], metric: str, months: int
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    metrics = ["fat_rs", "fat_kg"] if metric == "ambas" else [metric]
    lead = metrics[0]
    falling: list[dict[str, Any]] = []
    no_history: list[dict[str, Any]] = []
    others = 0
    for row in rows:
        line: dict[str, Any] = {
            "vendedor_id": row["vendedor_id"],
            "vendedor": row["vendedor"],
            "papel": row["papel"],
        }
        in_fall = False
        zero_average = False
        for name in metrics:
            source = "fat_rs" if name == "fat_rs" else "fat_kg"
            month_raw = float(row[f"{source}_mes"] or 0)
            average_raw = float(row[f"{source}_3m"] or 0) / months
            value = metric_value(name, month_raw, month_raw)
            average = metric_value(name, average_raw, average_raw)
            line[f"{name}_mes"] = value
            line[f"{name}_media"] = average
            line[f"{name}_diferenca"] = round(value - average, 3)
            line[f"{name}_variacao_pct"] = round((value - average) / average * 100, 2) if average else None
            situation = "queda" if value < average else "igual" if value == average else "acima"
            line[f"{name}_situacao"] = situation
            in_fall = in_fall or situation == "queda"
            zero_average = zero_average or not average
        if zero_average:
            no_history.append(line)
        elif in_fall:
            falling.append(line)
        else:
            others += 1

    # Variação mais negativa primeiro, na métrica principal.
    falling.sort(key=lambda line: line[f"{lead}_variacao_pct"])
    header = [
        {"id": "vendedor_id", "rotulo": "Código", "unidade": None},
        {"id": "vendedor", "rotulo": "Vendedor", "unidade": None},
        {"id": "papel", "rotulo": "Papel", "unidade": None},
    ]
    for name in metrics:
        label, unit = METRICS[name]
        header.extend(
            [
                {"id": f"{name}_mes", "rotulo": f"{label} no mês", "unidade": unit},
                {"id": f"{name}_media", "rotulo": f"Média {label} 3 meses", "unidade": unit},
                {"id": f"{name}_diferenca", "rotulo": f"Diferença {label}", "unidade": unit},
                {"id": f"{name}_variacao_pct", "rotulo": f"Variação {label}", "unidade": "%"},
                {"id": f"{name}_situacao", "rotulo": f"Situação {label}", "unidade": None},
            ]
        )
    exceptions = (
        [{"motivo": "Sem venda nos 3 meses anteriores: não há média para comparar", "linhas": no_history}]
        if no_history
        else []
    )
    return {"colunas": header, "linhas": falling}, exceptions, others


class SellersBelowAverage:
    operation_id = "OP18"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        window = values.get("janela_meses") or 3
        reference = month_start(values["mes_referencia"])
        history = months_back(reference, window + 1)[:-1]
        reference_end = month_end_exclusive(reference)

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        last_closed = last_closed_month(fetcher)
        partial = has_open_month(fetcher, reference, reference_end)
        sql, params = build_query(values, reference, reference_end, history[0], scope, product)
        rows = fetcher.fetch(sql, tuple(params))
        main_block, exceptions, others = shape_rows(rows, values.get("metrica") or "ambas", window)

        notices: list[Notice] = []
        if partial:
            notices.append(
                Notice(
                    "TR02",
                    "regra_tempo",
                    "O mês analisado ainda não fechou: o valor dele é parcial e tende a ficar abaixo da média.",
                )
            )
        if history[0] < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base começa em janeiro de 2025: parte da janela de comparação não tem dado.",
                )
            )
        # Pendente: o catálogo pede que o vendedor elegível sem nenhuma venda
        # na janela apareça sinalizado; hoje só aparece quem vendeu em algum
        # dos quatro meses. Declarado para não sumir em silêncio.
        notices.append(
            Notice(
                "SEM_TRANSACAO",
                "operacao",
                "Vendedores sem nenhuma venda no mês e nos três meses anteriores não aparecem nesta versão.",
            )
        )
        if others:
            notices.append(
                Notice(
                    "SEM_QUEDA",
                    "resposta",
                    f"{others} vendedor(es) ficaram iguais ou acima da própria média e não aparecem na lista.",
                )
            )
        return OperationResult(
            period=Period(
                start=reference,
                end_exclusive=reference_end,
                comparison_start=history[0],
                comparison_end_exclusive=reference,
                partial=partial,
                last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
            ),
            main_block=main_block,
            exceptions=exceptions,
            notices=notices,
        )
