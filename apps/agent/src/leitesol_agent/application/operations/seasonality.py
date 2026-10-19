"""OP08 - analisar_sazonalidade (skill Histórico e Evolução de Vendas).

Regra do catálogo (21-07 e 07-08): série mensal desde jan/2025 até o último
mês fechado, mês sem compra = zero. O nível citado é literal: CNPJ é aquele
CNPJ, rede só quando a rede for pedida. Índice em duas etapas (mês / média
mensal do próprio ano; depois média do mesmo mês entre anos COMPLETOS). A
força da conclusão segue a cobertura: com menos de 24 competências o
resultado é perfil descritivo, nunca sazonalidade consolidada.

Em aberto (P05): o método foi definido em 07-08 sem estatística e ainda não
foi validado com casos reais da área comercial.
"""

import re
from typing import Any

from leitesol_agent.application.operations.analytics import (
    build_period,
    closed_anchor,
    column,
    coverage_label,
    metric_round,
    month_range,
    month_text,
    monthly_query,
    open_rule_notice,
    pivot,
    resolve_product,
    seasonal_profile,
)
from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
)
from leitesol_agent.application.operations.common import (
    HISTORY_START,
    client_filter,
    last_closed_month,
)
from leitesol_agent.domain.models import Notice, Scope

MONTH_NAMES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
COVERAGE_TEXT = {
    "historico_insuficiente": "histórico insuficiente (menos de 12 competências)",
    "perfil_descritivo": "perfil descritivo (12 a 23 competências), não sazonalidade consolidada",
    "indicio_sazonal": "indício sazonal (24 a 35 competências)",
    "indice_sazonal_consolidado": "índice sazonal consolidado (36 ou mais competências)",
}


def entity_filter(entity: str, text: str) -> tuple[str, list[Any]]:
    """CNPJ = aquele cadastro; rede = toda a rede (Rede ajustada) do cliente informado."""
    clause, params = client_filter(text)
    if entity != "rede":
        return clause, params
    inner = re.sub(r"\bc\.", "k.", clause)
    return (
        f"c.Rede IN (SELECT k.Rede FROM [IA_COMERCIAL].[vw_dim_cliente] k WHERE {inner})",
        params,
    )


def shape(
    series_months: dict[Any, tuple[float, float]], months: list[Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    full = {month: series_months.get(month, (0.0, 0.0)) for month in months}
    profile = seasonal_profile(full)
    lines = []
    for number in range(1, 13):
        data = profile.by_month[number]
        index = data["indice"]
        lines.append(
            {
                "mes": MONTH_NAMES[number - 1],
                "indice_sazonal": index,
                "diferenca_media_pct": round((index - 1) * 100, 2) if index is not None else None,
                "media_fat_rs": metric_round("fat_rs", data["media_fat_rs"])
                if data["competencias"]
                else None,
                "media_fat_kg": metric_round("fat_kg", data["media_fat_kg"])
                if data["competencias"]
                else None,
                "competencias": data["competencias"],
            }
        )
    purchases = [month for month, values in full.items() if values[0] > 0]
    summary = {
        "competencias": len(months),
        "meses_com_compra": len(purchases),
        "anos_completos": profile.complete_years,
        "anos_sem_base": profile.years_without_base,
        "cobertura": coverage_label(len(months)),
    }
    ranked = [line for line in lines if line["indice_sazonal"] is not None]
    key = "indice_sazonal" if ranked else "media_fat_rs"
    ranked = ranked or [line for line in lines if line["media_fat_rs"] is not None]
    if ranked:
        summary["maior"] = max(ranked, key=lambda line: line[key])["mes"]
        summary["menor"] = min(ranked, key=lambda line: line[key])["mes"]
    header = [
        column("mes", "Mês"),
        column("indice_sazonal", "Índice sazonal (R$)"),
        column("diferenca_media_pct", "Diferença da média do ano", "%"),
        column("media_fat_rs", "Média FAT R$ do mês", "R$"),
        column("media_fat_kg", "Média FAT KG do mês", "KG"),
        column("competencias", "Competências observadas"),
    ]
    return {"colunas": header, "linhas": lines}, summary


class Seasonality:
    operation_id = "OP08"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        product, question = resolve_product(fetcher, values)
        if question:
            return question
        last_closed = last_closed_month(fetcher)
        anchor = closed_anchor(values.get("data_referencia"), last_closed)
        if anchor is None:
            return OperationResult.clarification(
                "Qual período você quer analisar? Informe o mês e o ano."
            )
        end_exclusive = month_end_exclusive(anchor)
        months = month_range(HISTORY_START, end_exclusive)

        entity = values.get("entidade") or "cnpj"
        sql, params = monthly_query(
            values,
            scope,
            HISTORY_START,
            end_exclusive,
            (),
            product=product,
            extra=[entity_filter(entity, values["escopo_cliente"])],
        )
        rows = fetcher.fetch(sql, tuple(params))
        merged = next(iter(pivot(rows, []).values()), None)
        main_block, summary = shape(merged.months if merged else {}, months)

        notices: list[Notice] = [
            Notice(
                "OP08_COBERTURA",
                "operacao",
                f"Nível analisado: {'rede' if entity == 'rede' else 'CNPJ informado'}. "
                f"{summary['competencias']} competências desde {month_text(months[0])}, "
                f"{summary['meses_com_compra']} com compra. Situação da análise: "
                f"{COVERAGE_TEXT[summary['cobertura']]}. Anos completos no índice: "
                f"{', '.join(map(str, summary['anos_completos'])) or 'nenhum'}.",
            ),
            open_rule_notice(
                "o índice sazonal foi definido em 07-08 e ainda não foi validado com casos reais. "
                "Não é teste estatístico e não explica a causa de picos ou vales."
            ),
        ]
        if not summary["anos_completos"]:
            notices.append(
                Notice(
                    "OP08_SEM_ANO_COMPLETO",
                    "base_historica",
                    "Não há ano completo (12 competências de janeiro a dezembro) no período: "
                    "o índice não sai, e a tabela mostra só a média de cada mês.",
                )
            )
        if summary["anos_sem_base"]:
            notices.append(
                Notice(
                    "OP08_ANO_ZERADO",
                    "resposta",
                    f"Ano(s) sem faturamento médio, fora do índice: {', '.join(map(str, summary['anos_sem_base']))}.",
                )
            )
        if "maior" in summary:
            notices.append(
                Notice(
                    "OP08_RESUMO",
                    "resposta",
                    f"Mês mais forte: {summary['maior']}; mais fraco: {summary['menor']}.",
                )
            )
        return OperationResult(
            period=build_period(HISTORY_START, end_exclusive, last_closed),
            main_block=main_block,
            notices=notices,
        )
