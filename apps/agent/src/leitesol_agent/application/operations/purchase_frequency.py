"""OP06 - calcular_frequencia_recencia (skill Histórico e Evolução de Vendas).

Regra do catálogo (21-07, AIC-286 em 07-10, D-A60): janela = EXATAMENTE 12
competências fechadas, sem o mês vigente; cada competência conta uma vez;
compra = FAT R$ > 0 no mês. Faixas do Power BI: >= 9 meses Mensal, >= 6
Bimestral, >= 4 Trimestral, >= 2 Semestral, abaixo Ocasional. Recência =
competências entre a última compra (buscada em TODO o histórico da fato,
nunca no A1_ULTCOM do cadastro) e a competência de referência.
"""

from typing import Any

from leitesol_agent.application.operations.analytics import (
    build_period,
    closed_anchor,
    column,
    frequency_class,
    history_notice,
    metric_round,
    month_range,
    month_text,
    monthly_query,
    pivot,
    recency,
    resolve_product,
    window_months,
)
from leitesol_agent.application.operations.base import OperationResult, SqlFetcher
from leitesol_agent.application.operations.common import (
    HISTORY_START,
    client_filter,
    last_closed_month,
)
from leitesol_agent.domain.models import Notice, Scope

LABELS = (("MAX(c.RazaoSocial)", "cliente"), ("MAX(c.RedeNome)", "rede"), ("MAX(c.UF)", "uf"))


def summarize(
    rows: list[dict[str, Any]], window: list[Any], anchor: Any, include_series: bool
) -> dict[str, Any]:
    entity = next(iter(pivot(rows, [], ["cliente", "rede", "uf"]).values()), None)
    history = sorted(entity.months) if entity else []
    purchases_all = entity.purchase_months(history) if entity else []
    purchases = entity.purchase_months(window) if entity else []
    last_purchase = max(purchases_all) if purchases_all else None
    if not purchases_all:
        status = "sem_compra_localizada"
    elif not purchases:
        status = "sem_compra_na_janela"
    else:
        status = "com_compra_na_janela"
    line: dict[str, Any] = {
        **(entity.labels if entity else {"cliente": None, "rede": None, "uf": None}),
        "meses_com_compra": len(purchases),
        "competencias": len(window),
        "taxa_frequencia": round(len(purchases) / len(window) * 100, 2),
        "classificacao": frequency_class(len(purchases)),
        "ultima_compra": month_text(last_purchase),
        "recencia_competencias": recency(last_purchase, anchor),
        "fat_rs": metric_round("fat_rs", entity.total(window, "fat_rs") if entity else 0),
        "fat_kg": metric_round("fat_kg", entity.total(window, "fat_kg") if entity else 0),
        "situacao": status,
    }
    if include_series and entity:
        line["serie"] = " | ".join(
            f"{month.strftime('%m/%y')} {'compra' if entity.value(month, 'fat_rs') > 0 else '-'}"
            for month in window
        )
    return line


HEADER = [
    column("cliente", "Cliente"),
    column("rede", "Rede"),
    column("uf", "UF"),
    column("meses_com_compra", "Meses com compra"),
    column("competencias", "Competências analisadas"),
    column("taxa_frequencia", "Frequência", "%"),
    column("classificacao", "Classificação"),
    column("ultima_compra", "Última competência com compra"),
    column("recencia_competencias", "Recência (competências)"),
    column("fat_rs", "FAT R$ na janela", "R$"),
    column("fat_kg", "FAT KG na janela", "KG"),
    column("situacao", "Situação"),
]


class PurchaseFrequency:
    operation_id = "OP06"

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
        window, start, end_exclusive = window_months(anchor, values.get("janela_meses") or 12)

        client = client_filter(values["escopo_cliente"])
        # Recência olha todo o histórico até o fim da janela; a frequência, só a janela.
        sql, params = monthly_query(
            values,
            scope,
            min(HISTORY_START, start),
            end_exclusive,
            (),
            LABELS,
            product,
            extra=[client],
        )
        rows = fetcher.fetch(sql, tuple(params))
        line = summarize(rows, window, anchor, bool(values.get("incluir_serie")))
        header = list(HEADER)
        if "serie" in line:
            header.append(column("serie", "Compra por competência"))

        notices: list[Notice] = [
            Notice(
                "OP06_JANELA",
                "operacao",
                f"Frequência sobre {len(window)} competências fechadas "
                f"({month_text(window[0])} a {month_text(window[-1])}). A recência usa a última compra "
                "na base de faturamento, não a data de última compra do cadastro.",
            )
        ]
        if start < HISTORY_START:
            notices.append(
                history_notice("A base começa em janeiro de 2025: parte da janela não tem dado.")
            )
        coverage = len(month_range(max(start, HISTORY_START), end_exclusive))
        if coverage < len(window):
            notices.append(
                Notice(
                    "OP06_COBERTURA",
                    "base_historica",
                    f"Só {coverage} das {len(window)} competências têm base: a frequência fica subestimada.",
                )
            )
        return OperationResult(
            period=build_period(start, end_exclusive, last_closed),
            main_block={"colunas": header, "linhas": [line]},
            notices=notices,
        )
