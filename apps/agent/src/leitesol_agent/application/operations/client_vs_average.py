"""OP02 - comparar_clientes_com_media_historica (skill Comportamento de Compra).

Regra do catálogo (21-07): universo = clientes com FAT R$ > 0 no mês de
referência; média = soma dos N meses imediatamente anteriores / N (padrão 6),
com mês sem movimento valendo zero - nunca a média da empresa, da rede ou só
dos meses com compra. R$ e KG classificados de forma independente, por
igualdade literal. Com as duas métricas, o cliente entra quando R$ OU KG
atende ao tipo pedido, e a linha diz qual critério atendeu. Média zero não
gera classificação: a linha vai para as exceções.
"""

from typing import Any

from leitesol_agent.application.operations.analytics import (
    average,
    build_period,
    column,
    compare_literal,
    history_notice,
    limit_notice,
    metric_round,
    metrics_for,
    negative_notice,
    partial_notice,
    resolve_product,
    variation_pct,
)
from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
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
    universe_where,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Scope

MAX_ROWS = 200


def build_query(
    values: dict[str, Any],
    reference_start: Any,
    reference_end: Any,
    history_start: Any,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope, product)
    sql = f"""
        SELECT f.ClienteId AS cliente_id,
               MAX(c.RazaoSocial) AS cliente,
               MAX(c.CNPJ) AS cnpj,
               MAX(c.RedeNome) AS rede,
               MAX(c.UF) AS uf,
               SUM(CASE WHEN f.Data >= ? THEN {FAT_RS} ELSE 0 END) AS fat_rs_ref,
               SUM(CASE WHEN f.Data < ? THEN {FAT_RS} ELSE 0 END) AS fat_rs_hist,
               SUM(CASE WHEN f.Data >= ? THEN {FAT_KG} ELSE 0 END) AS fat_kg_ref,
               SUM(CASE WHEN f.Data < ? THEN {FAT_KG} ELSE 0 END) AS fat_kg_hist
        {UNIVERSE_FROM}
        WHERE f.Data >= ? AND f.Data < ?
{where.sql}        GROUP BY f.ClienteId
        HAVING SUM(CASE WHEN f.Data >= ? THEN {FAT_RS} ELSE 0 END) > 0
    """
    split = [reference_start] * 4
    params = [*split, history_start, reference_end, *where.params, reference_start]
    return sql, params


def shape_rows(
    rows: list[dict[str, Any]], comparison: str, metric_choice: str, months: int
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Bloco principal, exceções (média zero) e quantidade de negativos."""
    metrics = metrics_for(metric_choice)
    lead = metrics[0]
    selected: list[dict[str, Any]] = []
    zero_average: list[dict[str, Any]] = []
    negatives = 0
    for row in rows:
        line: dict[str, Any] = {
            "cliente_id": row["cliente_id"],
            "cliente": row["cliente"],
            "cnpj": row["cnpj"],
            "rede": row["rede"],
            "uf": row["uf"],
        }
        met: list[str] = []
        evaluated = 0
        for metric in metrics:
            reference = float(row[f"{metric}_ref"] or 0)
            history = float(row[f"{metric}_hist"] or 0)
            mean = average(history, months)
            negatives += int(reference < 0 or history < 0)
            line[f"{metric}_periodo"] = metric_round(metric, reference)
            line[f"{metric}_media"] = metric_round(metric, mean)
            if mean == 0:
                line[f"{metric}_variacao_pct"] = None
                line[f"{metric}_situacao"] = None
                continue
            evaluated += 1
            situation = compare_literal(reference, mean)
            line[f"{metric}_variacao_pct"] = variation_pct(reference, mean)
            line[f"{metric}_situacao"] = situation
            if situation == comparison:
                met.append(METRICS[metric][0])
        if not evaluated:
            line["status"] = "Media historica igual a zero"
            zero_average.append(line)
            continue
        if met:
            line["criterio_atendido"] = " e ".join(met)
            selected.append(line)

    def sort_key(line: dict[str, Any]) -> tuple[bool, float]:
        change = line.get(f"{lead}_variacao_pct")
        if change is None:
            return True, 0.0
        return False, -change if comparison == "acima" else change

    selected.sort(key=sort_key)
    header = [
        column("cliente_id", "Código"),
        column("cliente", "Cliente"),
        column("cnpj", "CNPJ"),
        column("rede", "Rede"),
        column("uf", "UF"),
    ]
    for metric in metrics:
        label, unit = METRICS[metric]
        header.extend(
            [
                column(f"{metric}_periodo", f"{label} no mês", unit),
                column(f"{metric}_media", f"Média {label} {months} meses", unit),
                column(f"{metric}_variacao_pct", f"Variação {label}", "%"),
                column(f"{metric}_situacao", f"Situação {label}"),
            ]
        )
    header.append(column("criterio_atendido", "Critério atendido"))
    exceptions = (
        [{"motivo": "Media historica igual a zero: sem base para comparar", "linhas": zero_average}]
        if zero_average
        else []
    )
    return {"colunas": header, "linhas": selected}, exceptions, negatives


class CompareClientsWithAverage:
    operation_id = "OP02"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        months = values.get("meses_media") or 6
        reference = month_start(values["periodo_referencia"])
        reference_end = month_end_exclusive(reference)
        history_start = months_back(reference, months + 1)[0]

        product, question = resolve_product(fetcher, values)
        if question:
            return question

        last_closed = last_closed_month(fetcher)
        partial = has_open_month(fetcher, reference, reference_end)
        sql, params = build_query(values, reference, reference_end, history_start, scope, product)
        rows = fetcher.fetch(sql, tuple(params))
        main_block, exceptions, negatives = shape_rows(
            rows, values["tipo_comparacao"], values.get("metrica_comparacao") or "ambas", months
        )

        notices: list[Notice] = [
            Notice(
                "OP02_MEDIA",
                "operacao",
                f"A média é do próprio cliente nos {months} meses anteriores, com mês sem compra "
                "valendo zero. R$ e KG são avaliados separadamente, sem tolerância.",
            )
        ]
        if partial:
            notices.append(
                partial_notice("O mês analisado ainda não fechou: o valor dele é parcial.")
            )
        if history_start < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: parte da janela da média não tem dado."
                )
            )
        if negatives:
            notices.append(negative_notice(negatives))
        total = len(main_block["linhas"])
        if total > MAX_ROWS:
            main_block["linhas"] = main_block["linhas"][:MAX_ROWS]
            notices.append(limit_notice(MAX_ROWS, total, "clientes"))
        return OperationResult(
            period=build_period(
                reference, reference_end, last_closed, (history_start, reference), partial
            ),
            main_block=main_block,
            exceptions=exceptions,
            notices=notices,
        )
