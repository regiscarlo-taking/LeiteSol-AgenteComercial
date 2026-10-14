"""OP14 - ranking comercial por uma métrica explícita."""

from datetime import date
from typing import Any

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
    metric_value,
    product_filter,
    product_question,
    universe_where,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Period, Scope

ROLE_FILTERS = {
    "representante": ("RCA",),
    "vendedor": ("RCA", "Gestor"),
    "gestor": ("Gestor",),
}
METRIC_COLUMNS = {"fat_rs": "fat_rs", "fat_kg": "fat_kg"}
SUPPORTED_METRICS = frozenset(METRIC_COLUMNS)


def _period(
    values: dict[str, Any], last_closed: date | None
) -> tuple[date, date] | None:
    start_requested = values.get("periodo_inicio")
    end_requested = values.get("periodo_fim")
    if bool(start_requested) != bool(end_requested):
        return None
    if start_requested and end_requested:
        if end_requested < start_requested:
            start_requested, end_requested = end_requested, start_requested
        start = month_start(start_requested)
        return start, month_end_exclusive(end_requested)
    if last_closed is None:
        return None
    reference = values.get("data_referencia")
    anchor = month_start(reference) if reference else month_start(last_closed)
    if anchor > month_start(last_closed):
        anchor = month_start(last_closed)
    window = values.get("janela_meses", 3)
    months = months_back(anchor, window)
    return months[0], month_end_exclusive(months[-1])


def build_query(
    values: dict[str, Any],
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    # A venda é do vendedor atual do cliente (regra homologada pela Adm. Vendas,
    # igual ao "vend atual" do Power BI). O vendedor da transação fica só para
    # conferência, quando pedido explicitamente.
    attribution = values.get("tipo_atribuicao") or "carteira_atual"
    if attribution == "carteira_atual":
        participant_id, participant_name, role_column, manager_id, manager_name = (
            "c.RCAAtual",
            "r.Representante",
            "r.PapelComercial",
            "r.GestorId",
            "r.Gestor",
        )
    else:
        participant_id, participant_name, role_column, manager_id, manager_name = (
            "f.VendedorId",
            "v.Representante",
            "v.PapelComercial",
            "v.GestorId",
            "v.Gestor",
        )

    where = universe_where(values, scope, product)
    role = values.get("papel_comercial") or "representante"
    roles = ROLE_FILTERS.get(role)
    if roles:
        where.add(f"{role_column} IN ({', '.join('?' for _ in roles)})", *roles)
    if role == "gestor" and values.get("gestor_supervisor"):
        manager = values["gestor_supervisor"].strip()
        where.add(f"({manager_id} = ? OR UPPER({manager_name}) = ?)", manager, manager.upper())

    seller_join = (
        ""
        if attribution == "carteira_atual"
        else "LEFT JOIN [IA_COMERCIAL].[vw_dim_representante] v "
        "ON v.RepresentanteId = f.VendedorId"
    )
    sql = f"""
        WITH base AS (
            SELECT {participant_id} AS vendedor_id,
                   MAX({participant_name}) AS vendedor,
                   MAX({role_column}) AS papel,
                   SUM({FAT_RS}) AS fat_rs,
                   SUM({FAT_KG}) AS fat_kg
            {UNIVERSE_FROM}
            {seller_join}
            WHERE f.Data >= ? AND f.Data < ?
{where.sql}            GROUP BY {participant_id}
        )
        SELECT *, ROW_NUMBER() OVER (
            ORDER BY {METRIC_COLUMNS[values["metrica_desempenho"]]} DESC,
                     vendedor ASC, vendedor_id ASC
        ) AS posicao
        FROM base
        ORDER BY posicao
    """
    return sql, [values["_period_start"], values["_period_end"], *where.params]


class RankRepresentatives:
    operation_id = "OP14"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        metric = values.get("metrica_desempenho") or "composto"
        if metric not in SUPPORTED_METRICS:
            return OperationResult.clarification(
                "O ranking geral composto ainda não foi homologado. "
                "Qual métrica quer ranquear: FAT KG ou FAT R$?"
            )

        last_closed = last_closed_month(fetcher)
        period_range = _period(values, last_closed)
        if period_range is None:
            return OperationResult.clarification(
                "Informe início e fim do período, ou indique a competência de referência."
            )
        start, end_exclusive = period_range
        if last_closed and end_exclusive > month_end_exclusive(last_closed):
            return OperationResult.clarification(
                "O ranking considera somente competências fechadas. "
                "Informe um período até a última competência fechada."
            )

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        query_values = {
            **values,
            "_period_start": start,
            "_period_end": end_exclusive,
            "metrica_desempenho": metric,
        }
        sql, params = build_query(query_values, scope, product)
        rows = fetcher.fetch(sql, tuple(params))
        top_n = values.get("top_n") or 20
        lines = [
            {
                "posicao": row["posicao"],
                "vendedor_id": row["vendedor_id"],
                "vendedor": row["vendedor"],
                "papel": row["papel"],
                "fat_kg": metric_value("fat_kg", 0, float(row["fat_kg"] or 0)),
                "fat_rs": metric_value("fat_rs", float(row["fat_rs"] or 0), 0),
            }
            for row in rows[:top_n]
        ]
        columns = [
            {"id": "posicao", "rotulo": "Posição", "unidade": None},
            {"id": "vendedor_id", "rotulo": "Código", "unidade": None},
            {"id": "vendedor", "rotulo": "Vendedor", "unidade": None},
            {"id": "papel", "rotulo": "Papel comercial", "unidade": None},
            {"id": "fat_kg", "rotulo": "FAT KG", "unidade": "KG"},
            {"id": "fat_rs", "rotulo": "FAT R$", "unidade": "R$"},
        ]
        notices = []
        if start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base começa em janeiro de 2025; o período pode conter competências sem dados.",
                )
            )
        if has_open_month(fetcher, start, end_exclusive):
            notices.append(
                Notice(
                    "TR02",
                    "regra_tempo",
                    "O período inclui mês ainda não fechado: os valores desse mês são parciais.",
                )
            )
        return OperationResult(
            period=Period(
                start=start,
                end_exclusive=end_exclusive,
                partial=bool(notices and any(n.code == "TR02" for n in notices)),
                last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
            ),
            main_block={"colunas": columns, "linhas": lines},
            notices=notices,
        )
