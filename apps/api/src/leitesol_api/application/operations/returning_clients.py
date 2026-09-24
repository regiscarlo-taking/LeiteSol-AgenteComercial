"""OP01 - identificar_clientes_com_retomada_de_compra (skill Comportamento de Compra).

Regra do catálogo: compra válida = FAT R$ > 0 no mês (bonificação isolada
não conta); janela = N meses imediatamente anteriores ao INÍCIO do período,
sem sobreposição, N padrão 6; a ausência é verificada MÊS A MÊS, nunca pela
soma da janela - uma devolução num mês compensaria a compra de outro.
Cliente sem nenhum registro na janela também é elegível. Não classificar
como "novo" ou "recuperado": a leitura é do analista.
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

MAX_ROWS = 200


def build_query(
    values: dict[str, Any],
    period_start: Any,
    period_end: Any,
    history_start: Any,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope, product)
    # Compra válida é do CLIENTE no MÊS: agrega antes de testar > 0.
    sql = f"""
        WITH mensal AS (
            SELECT f.ClienteId, f.Data,
                   SUM({FAT_RS}) AS fat_rs,
                   SUM({FAT_KG}) AS fat_kg
            {UNIVERSE_FROM}
            WHERE f.Data >= ? AND f.Data < ?
{where.sql}            GROUP BY f.ClienteId, f.Data
        ),
        periodo AS (
            SELECT ClienteId,
                   SUM(fat_rs) AS fat_rs,
                   SUM(fat_kg) AS fat_kg,
                   MIN(CASE WHEN fat_rs > 0 THEN Data END) AS competencia_compra
            FROM mensal
            WHERE Data >= ?
            GROUP BY ClienteId
            HAVING MAX(CASE WHEN fat_rs > 0 THEN 1 ELSE 0 END) = 1
        )
        SELECT c.ClienteId AS cliente_id, c.RazaoSocial AS cliente, c.CNPJ AS cnpj,
               c.RedeNome AS rede, c.UF AS uf,
               c.PrimeiraCompraCadastro AS primeira_compra_cadastro,
               p.competencia_compra, p.fat_rs, p.fat_kg
        FROM periodo p
        JOIN [IA_COMERCIAL].[vw_dim_cliente] c ON c.ClienteId = p.ClienteId
        WHERE NOT EXISTS (
            SELECT 1 FROM mensal h
            WHERE h.ClienteId = p.ClienteId AND h.Data < ? AND h.fat_rs > 0
        )
        ORDER BY c.UF, c.RazaoSocial, c.ClienteCodigo, c.Loja
    """
    params = [history_start, period_end, *where.params, period_start, period_start]
    return sql, params


def shape_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [
        {
            "cliente_id": row["cliente_id"],
            "cliente": row["cliente"],
            "cnpj": row["cnpj"],
            "rede": row["rede"],
            "uf": row["uf"],
            # Informativa, do cadastro: não entra no critério.
            "primeira_compra_cadastro": row["primeira_compra_cadastro"] or "não informada",
            "competencia_compra": str(row["competencia_compra"])[:7] if row["competencia_compra"] else None,
            "fat_rs": metric_value("fat_rs", float(row["fat_rs"] or 0), 0),
            "fat_kg": metric_value("fat_kg", 0, float(row["fat_kg"] or 0)),
        }
        for row in rows[:MAX_ROWS]
    ]
    header = [
        {"id": "cliente_id", "rotulo": "Código", "unidade": None},
        {"id": "cliente", "rotulo": "Cliente", "unidade": None},
        {"id": "cnpj", "rotulo": "CNPJ", "unidade": None},
        {"id": "rede", "rotulo": "Rede", "unidade": None},
        {"id": "uf", "rotulo": "UF", "unidade": None},
        {"id": "primeira_compra_cadastro", "rotulo": "Primeira compra (cadastro)", "unidade": None},
        {"id": "competencia_compra", "rotulo": "Mês da compra", "unidade": None},
        {"id": "fat_rs", "rotulo": "FAT R$ no período", "unidade": "R$"},
        {"id": "fat_kg", "rotulo": "FAT KG no período", "unidade": "KG"},
    ]
    return {"colunas": header, "linhas": lines}


class ReturningClients:
    operation_id = "OP01"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        window = values.get("meses_sem_compra") or 6
        period_start = month_start(values["periodo_referencia"])
        period_end = month_end_exclusive(period_start)
        history_start = months_back(period_start, window + 1)[0]

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        last_closed = last_closed_month(fetcher)
        partial = has_open_month(fetcher, period_start, period_end)
        sql, params = build_query(values, period_start, period_end, history_start, scope, product)
        rows = fetcher.fetch(sql, tuple(params))

        notices: list[Notice] = [
            Notice(
                "OP01_LEITURA",
                "operacao",
                f"A lista mostra clientes com compra no período e nenhuma compra válida nos {window} meses anteriores. "
                "Ela não classifica o cliente como novo ou recuperado.",
            )
        ]
        if history_start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base começa em janeiro de 2025: parte da janela sem compra não tem dado, e clientes "
                    "que compravam antes disso podem aparecer na lista.",
                )
            )
        if partial:
            notices.append(
                Notice(
                    "TR02",
                    "regra_tempo",
                    "O mês analisado ainda não fechou: a lista pode crescer até o fechamento.",
                )
            )
        if len(rows) > MAX_ROWS:
            notices.append(
                Notice("LIMITE", "resposta", f"Exibindo {MAX_ROWS} de {len(rows)} clientes.")
            )
        return OperationResult(
            period=Period(
                start=period_start,
                end_exclusive=period_end,
                comparison_start=history_start,
                comparison_end_exclusive=period_start,
                partial=partial,
                last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
            ),
            main_block=shape_rows(rows),
            notices=notices,
        )
