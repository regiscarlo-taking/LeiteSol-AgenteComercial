"""OP16 - comparar_regiao_com_historico (skill Desempenho Comercial).

Regra do catálogo (22-07): métrica padrão FAT KG; região padrão = UF do
cadastro do cliente. A última competência fechada é comparada com as médias
dos 3, 6 e 12 meses fechados ANTERIORES e com o mesmo mês do ano anterior.
Cada região é comparada CONSIGO MESMA, nunca com as outras. UF sem venda no
horizonte não pode sumir: vai para as exceções.

Em aberto (P04): não há tolerância homologada; a igualdade é literal.
"""

import re
from datetime import date
from typing import Any

from leitesol_agent.application.operations.analytics import (
    add_months,
    average,
    build_period,
    column,
    compare_literal,
    history_notice,
    metric_round,
    metrics_for,
    month_text,
    monthly_query,
    negative_notice,
    open_rule_notice,
    partial_notice,
    pivot,
    reference_month,
    resolve_product,
    source_metric,
    variation_pct,
)
from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
    normalize_term,
)
from leitesol_agent.application.operations.common import (
    HISTORY_START,
    METRICS,
    has_open_month,
    last_closed_month,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Scope

DEFAULT_WINDOWS = (3, 6, 12)
LEVELS = {
    "uf": ((("c.UF", "uf"),), ()),
    "regiao": ((("c.Regiao", "regiao"),), ()),
    "municipio": ((("c.UF", "uf"), ("c.Municipio", "municipio")), ()),
}
ALL_UFS_SQL = """
    SELECT UF AS uf FROM [IA_COMERCIAL].[vw_dim_geografia]
    WHERE UF NOT IN ('EX', 'US')
"""


def parse_windows(value: Any) -> list[int]:
    """'3|6|12', '3,6' ou 6 -> janelas válidas, em ordem; vazio = as três."""
    numbers = sorted(
        {int(item) for item in re.findall(r"\d+", str(value or ""))} & set(DEFAULT_WINDOWS)
    )
    return numbers or list(DEFAULT_WINDOWS)


def shape(
    rows: list[dict[str, Any]],
    key_aliases: list[str],
    reference: date,
    windows: list[int],
    metric_choice: str,
) -> tuple[dict[str, Any], int, set[str]]:
    metrics = metrics_for(metric_choice, default="fat_kg")
    lead = metrics[0]
    last_year = add_months(reference, -12)
    negatives = 0
    seen: set[str] = set()
    lines = []
    for series in pivot(rows, key_aliases).values():
        line: dict[str, Any] = dict(zip(key_aliases, series.key, strict=True))
        seen.add(str(series.key[0]))
        for metric in metrics:
            source = source_metric(metric)
            current = series.value(reference, source)
            negatives += int(current < 0)
            line[f"{metric}_atual"] = metric_round(metric, current)
            for window in windows:
                history = months_back(add_months(reference, -1), window)
                mean = average(series.total(history, source), window)
                line[f"{metric}_media_{window}m"] = metric_round(metric, mean)
                line[f"{metric}_dif_{window}m_pct"] = variation_pct(current, mean)
                line[f"{metric}_situacao_{window}m"] = (
                    compare_literal(current, mean) if mean else "sem_base"
                )
            before = series.value(last_year, source)
            line[f"{metric}_ano_anterior"] = metric_round(metric, before)
            line[f"{metric}_dif_ano_anterior_pct"] = variation_pct(current, before)
            line[f"{metric}_situacao_ano_anterior"] = (
                compare_literal(current, before) if before else "sem_base"
            )
        lines.append(line)
    first = windows[0]
    lines.sort(
        key=lambda line: (
            -abs(line.get(f"{lead}_dif_{first}m_pct") or 0),
            str(line[key_aliases[-1]]),
        )
    )

    header = [
        column(alias, alias.upper() if alias == "uf" else alias.capitalize())
        for alias in key_aliases
    ]
    for metric in metrics:
        label, unit = METRICS[metric]
        header.append(column(f"{metric}_atual", f"{label} {month_text(reference)}", unit))
        for window in windows:
            header.extend(
                [
                    column(f"{metric}_media_{window}m", f"Média {label} {window} meses", unit),
                    column(
                        f"{metric}_dif_{window}m_pct", f"Diferença da média {window} meses", "%"
                    ),
                    column(f"{metric}_situacao_{window}m", f"Situação {window} meses"),
                ]
            )
        header.extend(
            [
                column(f"{metric}_ano_anterior", f"{label} {month_text(last_year)}", unit),
                column(f"{metric}_dif_ano_anterior_pct", "Diferença do ano anterior", "%"),
                column(f"{metric}_situacao_ano_anterior", "Situação contra o ano anterior"),
            ]
        )
    return {"colunas": header, "linhas": lines}, negatives, seen


class RegionalPerformance:
    operation_id = "OP16"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        last_closed = last_closed_month(fetcher)
        reference = reference_month(values.get("competencia_referencia"), last_closed)
        if reference is None:
            return OperationResult.clarification(
                "Qual mês você quer analisar? Informe o mês e o ano."
            )
        level = values.get("nivel_geografico") or "uf"
        keys, labels = LEVELS.get(level, LEVELS["uf"])
        windows = parse_windows(values.get("janelas"))
        start = add_months(reference, -12)
        end_exclusive = month_end_exclusive(reference)

        product, question = resolve_product(fetcher, values)
        if question:
            return question
        extra = []
        if values.get("regiao"):
            extra.append(("UPPER(c.Regiao) = ?", [normalize_term(values["regiao"])]))
        partial = has_open_month(fetcher, reference, end_exclusive)
        sql, params = monthly_query(
            values, scope, start, end_exclusive, keys, labels, product, extra
        )
        rows = fetcher.fetch(sql, tuple(params))
        key_aliases = [alias for _, alias in keys]
        main_block, negatives, seen = shape(
            rows, key_aliases, reference, windows, values.get("metrica") or "fat_kg"
        )

        exceptions: list[dict[str, Any]] = []
        if level == "uf" and scope.sees_everything and not values.get("uf") and not extra:
            missing = sorted(
                str(row["uf"]) for row in fetcher.fetch(ALL_UFS_SQL) if str(row["uf"]) not in seen
            )
            if missing:
                exceptions.append(
                    {
                        "motivo": "UF sem nenhuma venda nos 13 meses analisados",
                        "linhas": [{"uf": uf} for uf in missing],
                    }
                )

        notices: list[Notice] = [
            Notice(
                "OP16_REFERENCIA",
                "operacao",
                f"Cada região é comparada com a própria média dos {', '.join(map(str, windows))} meses "
                f"anteriores a {month_text(reference)} e com o mesmo mês do ano anterior. A região é a do "
                "cadastro do cliente (UF, região ou município).",
            ),
            open_rule_notice(
                "não há margem de tolerância definida para considerar uma região 'igual' à média; "
                "a comparação é literal."
            ),
        ]
        if partial:
            notices.append(partial_notice())
        if start < HISTORY_START:
            notices.append(
                history_notice(
                    "A base começa em janeiro de 2025: parte das referências não tem dado."
                )
            )
        if negatives:
            notices.append(negative_notice(negatives))
        return OperationResult(
            period=build_period(reference, end_exclusive, last_closed, (start, reference), partial),
            main_block=main_block,
            exceptions=exceptions,
            notices=notices,
        )
