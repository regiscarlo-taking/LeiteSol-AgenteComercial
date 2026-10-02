"""OP13 - ranquear_clientes (skill Desempenho Comercial).

Regra do catálogo: período obrigatório; "volume" = FAT KG (com toneladas),
FAT R$ só quando pedido; Top 20 por padrão; participante padrão = cliente +
loja, CNPJ ou rede só quando a pergunta citar; filtros aplicados ANTES do
ranking.

Desempate (Adm. Vendas, 29-09, AIC-289): no mesmo valor da métrica, vence o
maior FAT R$; persistindo o empate, o nome do cliente em ordem alfabética. O
código do participante só fecha o empate residual para a ordem ser estável.
Por isso a posição é ROW_NUMBER() e a lista tem exatamente N posições. A
consulta traz uma linha a mais (N + 1) só para saber se a regra decidiu quem
ficou de fora no limite; essa linha não vai para a resposta.
"""

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
    UNIVERSE_FROM,
    has_open_month,
    last_closed_month,
    metric_value,
    product_filter,
    product_question,
    universe_where,
)
from leitesol_agent.domain.models import Notice, Period, Scope

# granularidade -> (chave de agrupamento, expressão do nome)
PARTICIPANTS = {
    "cliente_loja": ("c.ClienteId", "MAX(c.RazaoSocial)"),
    "cnpj": ("c.CNPJ", "MAX(c.RazaoSocial)"),
    "rede": ("c.Rede", "MAX(c.RedeNome)"),
}
# Métrica do ranking -> coluna agregada que ordena (toneladas ordena igual a KG).
RANK_COLUMN = {"fat_kg": "fat_kg", "fat_tons": "fat_kg", "fat_rs": "fat_rs"}
DEFAULT_TOP_N = 20


def tie_break_order(rank_column: str) -> str:
    """ORDER BY do ranking com o desempate oficial (métrica, R$, nome, código)."""
    keys = [f"{rank_column} DESC"]
    if rank_column != "fat_rs":
        keys.append("fat_rs DESC")
    # Sem nome, o participante vai para o fim do empate em vez de vir antes de "A".
    keys += ["CASE WHEN participante IS NULL THEN 1 ELSE 0 END", "participante ASC", "participante_id ASC"]
    return ", ".join(keys)


def build_query(
    values: dict[str, Any],
    period: Period,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    key, name_expr = PARTICIPANTS[values.get("granularidade_cliente") or "cliente_loja"]
    rank_column = RANK_COLUMN[values.get("metrica_ranking") or "fat_kg"]
    where = universe_where(values, scope, product)

    # UF sempre no retorno (RT25): rede e CNPJ podem cruzar estados.
    sql = f"""
        WITH base AS (
            SELECT
                {key} AS participante_id,
                {name_expr} AS participante,
                CASE WHEN MIN(c.UF) = MAX(c.UF) THEN MIN(c.UF) ELSE 'Várias' END AS uf,
                SUM({FAT_RS}) AS fat_rs,
                SUM({FAT_KG}) AS fat_kg
            {UNIVERSE_FROM}
            WHERE f.Data >= ? AND f.Data < ?
{where.sql}            GROUP BY {key}
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (ORDER BY {tie_break_order(rank_column)}) AS posicao,
                   SUM({rank_column}) OVER () AS total_escopo
            FROM base
        )
        SELECT * FROM ranked WHERE posicao <= ? ORDER BY posicao
    """
    top_n = values.get("top_n") or DEFAULT_TOP_N
    params = [period.start, period.end_exclusive, *where.params, top_n + 1]
    return sql, params


def shape_rows(rows: list[dict[str, Any]], metric: str) -> tuple[dict[str, Any], bool]:
    """Bloco principal e se o total do escopo é não positivo (participação sem sentido)."""
    rank_column = RANK_COLUMN[metric]
    lines = []
    non_positive_total = False
    for row in rows:
        total = float(row["total_escopo"] or 0)
        value = float(row[rank_column] or 0)
        non_positive_total = non_positive_total or total <= 0
        lines.append(
            {
                "posicao": row["posicao"],
                "participante_id": row["participante_id"],
                "participante": row["participante"],
                "uf": row["uf"],
                "fat_kg": metric_value("fat_kg", 0, float(row["fat_kg"] or 0)),
                "fat_tons": metric_value("fat_tons", 0, float(row["fat_kg"] or 0)),
                "fat_rs": metric_value("fat_rs", float(row["fat_rs"] or 0), 0),
                "participacao_pct": round(value / total * 100, 2) if total > 0 else None,
            }
        )
    header = [
        {"id": "posicao", "rotulo": "Posição", "unidade": None},
        {"id": "participante_id", "rotulo": "Código", "unidade": None},
        {"id": "participante", "rotulo": "Cliente", "unidade": None},
        {"id": "uf", "rotulo": "UF", "unidade": None},
        {"id": "fat_kg", "rotulo": "FAT KG", "unidade": "KG"},
        {"id": "fat_tons", "rotulo": "FAT TONS", "unidade": "t"},
        {"id": "fat_rs", "rotulo": "FAT R$", "unidade": "R$"},
        {"id": "participacao_pct", "rotulo": "Participação no total", "unidade": "%"},
    ]
    return {"colunas": header, "linhas": lines}, non_positive_total


class RankClients:
    operation_id = "OP13"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        start_requested: date = values["periodo_inicio"]
        end_requested: date = values["periodo_fim"]
        if end_requested < start_requested:
            start_requested, end_requested = end_requested, start_requested
        start = month_start(start_requested)
        end_exclusive = month_end_exclusive(end_requested)

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        last_closed = last_closed_month(fetcher)
        partial = has_open_month(fetcher, start, end_exclusive)
        period = Period(
            start=start,
            end_exclusive=end_exclusive,
            partial=partial,
            last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
        )

        sql, params = build_query(values, period, scope, product)
        rows = fetcher.fetch(sql, tuple(params))
        metric = values.get("metrica_ranking") or "fat_kg"
        top_n = values.get("top_n") or DEFAULT_TOP_N
        shown, left_out = rows[:top_n], rows[top_n:top_n + 1]
        main_block, non_positive_total = shape_rows(shown, metric)

        notices: list[Notice] = []
        rank_column = RANK_COLUMN[metric]
        if shown and left_out and shown[-1][rank_column] == left_out[0][rank_column]:
            by_rs = rank_column != "fat_rs" and shown[-1]["fat_rs"] != left_out[0]["fat_rs"]
            criterion = "pelo maior faturamento em R$" if by_rs else "pela ordem alfabética do nome do cliente"
            notices.append(
                Notice(
                    "DESEMPATE",
                    "operacao",
                    f"Houve empate na {top_n}ª posição: o desempate foi feito {criterion}, "
                    "conforme a regra definida pela área comercial.",
                )
            )
        if non_positive_total:
            notices.append(
                Notice(
                    "PARTICIPACAO",
                    "operacao",
                    "O total do recorte não é positivo (devoluções superam vendas): a participação não foi calculada.",
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
        return OperationResult(period=period, main_block=main_block, notices=notices)
