"""OP03 - listar_nao_positivados (skill Desempenho Comercial).

Regra do catálogo (21-07): o agrupamento de positivação é a rede ajustada do
BI (GRUPO_AJUSTADO_2 = grupo de venda, senão raiz do CNPJ - coluna Rede da
vw_dim_cliente). A apuração é por AGRUPAMENTO + RESPONSÁVEL ATUAL
(BISA1.A1_VEND): a compra de uma loja atendida por um vendedor não positiva
as lojas do mesmo agrupamento atendidas por outro. Positivado = FAT R$ > 0
no período. Todas as UFs ficam visíveis. Cliente sem responsável vai para
as exceções, nunca é atribuído a alguém.

O universo parte da CARTEIRA (cadastro), não da fato: quem não comprou nada
não tem linha na fato e sumiria de uma consulta só sobre vendas.
"""

from typing import Any

from leitesol_agent.application.operations.analytics import (
    build_period,
    column,
    partial_notice,
    resolve_product,
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
    Where,
    client_filter,
    has_open_month,
    last_closed_month,
    metric_value,
)
from leitesol_agent.domain.models import Notice, Scope

NOT_FOUND_QUESTION = (
    'Não encontrei o cliente ou agrupamento "{text}" no cadastro dentro da sua carteira. '
    "Pode informar o código, o CNPJ ou o nome da rede?"
)


def build_query(
    values: dict[str, Any],
    start: Any,
    end_exclusive: Any,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    target_clause, target_params = client_filter(values["cliente_rede"])
    portfolio = Where()
    portfolio.add("c.FlagExterior = 0")
    if not scope.sees_everything:
        sellers = sorted(scope.sellers)
        portfolio.add(f"c.RCAAtual IN ({', '.join('?' for _ in sellers)})", *sellers)
    if values.get("uf"):
        portfolio.add("c.UF = ?", values["uf"].strip().upper())
    if values.get("vendedor_rca"):
        seller = values["vendedor_rca"].strip()
        portfolio.add("(c.RCAAtual = ? OR UPPER(r.Representante) = ?)", seller, seller.upper())
    if values.get("loja"):
        portfolio.add("c.Loja = ?", values["loja"].strip())
    if values.get("cnpj"):
        digits = "".join(char for char in values["cnpj"] if char.isdigit())
        portfolio.add(
            "(c.CNPJRaiz = ? OR REPLACE(REPLACE(REPLACE(c.CNPJ, '.', ''), '/', ''), '-', '') = ?)",
            digits[:8],
            digits,
        )
    if values.get("gestor_supervisor"):
        manager = values["gestor_supervisor"].strip()
        portfolio.add("(r.GestorId = ? OR UPPER(r.Gestor) = ?)", manager, manager.upper())

    sales = Where()
    sales.add("p.FlagProdutoAcabado = 1")
    if product:
        sales.add(product[0], *product[1])

    sql = f"""
        WITH alvo AS (
            SELECT DISTINCT c.Rede
            FROM [IA_COMERCIAL].[vw_dim_cliente] c
            WHERE {target_clause}
        ),
        carteira AS (
            SELECT c.ClienteId, c.RazaoSocial, c.Rede, c.RedeNome, c.UF, c.RCAAtual,
                   r.Representante, r.PapelComercial, r.Gestor
            FROM [IA_COMERCIAL].[vw_dim_cliente] c
            JOIN alvo a ON a.Rede = c.Rede
            LEFT JOIN [IA_COMERCIAL].[vw_dim_representante] r ON r.RepresentanteId = c.RCAAtual
            WHERE 1 = 1
{portfolio.sql}        ),
        venda AS (
            SELECT f.ClienteId, SUM({FAT_RS}) AS fat_rs, SUM({FAT_KG}) AS fat_kg
            FROM [IA_COMERCIAL].[vw_fato_faturamento] f
            JOIN [IA_COMERCIAL].[vw_dim_produto] p ON p.ProdutoId = f.ProdutoId
            WHERE f.Data >= ? AND f.Data < ?
              AND f.ClienteId IN (SELECT ClienteId FROM carteira)
{sales.sql}            GROUP BY f.ClienteId
        )
        SELECT k.ClienteId AS cliente_id, k.RazaoSocial AS cliente, k.Rede AS rede_id,
               k.RedeNome AS rede, k.UF AS uf, k.RCAAtual AS vendedor_id,
               k.Representante AS vendedor, k.PapelComercial AS papel, k.Gestor AS gestor,
               COALESCE(v.fat_rs, 0) AS fat_rs, COALESCE(v.fat_kg, 0) AS fat_kg
        FROM carteira k
        LEFT JOIN venda v ON v.ClienteId = k.ClienteId
        ORDER BY k.Rede, k.RCAAtual, k.UF, k.ClienteId
    """
    params = [*target_params, *portfolio.params, start, end_exclusive, *sales.params]
    return sql, params


def shape_rows(
    rows: list[dict[str, Any]], status: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    groups: dict[tuple[Any, Any], dict[str, Any]] = {}
    without_owner: list[dict[str, Any]] = []
    for row in rows:
        seller = str(row["vendedor_id"] or "").strip()
        if not seller:
            without_owner.append(
                {
                    "cliente_id": row["cliente_id"],
                    "cliente": row["cliente"],
                    "uf": row["uf"],
                    "status": "Responsavel nao identificado",
                }
            )
            continue
        key = (row["rede_id"], seller)
        group = groups.setdefault(
            key,
            {
                "rede_id": row["rede_id"],
                "rede": row["rede"],
                "vendedor_id": seller,
                "vendedor": row["vendedor"],
                "papel": row["papel"],
                "gestor": row["gestor"],
                "ufs": set(),
                "lojas": 0,
                "lojas_com_compra": 0,
                "fat_rs": 0.0,
                "fat_kg": 0.0,
            },
        )
        group["ufs"].add(row["uf"])
        group["lojas"] += 1
        group["lojas_com_compra"] += int(float(row["fat_rs"] or 0) > 0)
        group["fat_rs"] += float(row["fat_rs"] or 0)
        group["fat_kg"] += float(row["fat_kg"] or 0)

    counts = {"positivado": 0, "nao_positivado": 0}
    lines: list[dict[str, Any]] = []
    for group in groups.values():
        situation = "positivado" if group["fat_rs"] > 0 else "nao_positivado"
        counts[situation] += 1
        if status != "ambos" and situation != status:
            continue
        lines.append(
            {
                **group,
                "ufs": ", ".join(sorted(uf for uf in group["ufs"] if uf)),
                "fat_rs": metric_value("fat_rs", group["fat_rs"], 0),
                "fat_kg": metric_value("fat_kg", 0, group["fat_kg"]),
                "situacao": "Positivado" if situation == "positivado" else "Não positivado",
            }
        )
    lines.sort(
        key=lambda line: (
            line["situacao"] != "Não positivado",
            str(line["rede_id"]),
            str(line["vendedor_id"]),
        )
    )
    header = [
        column("rede_id", "Agrupamento"),
        column("rede", "Nome do agrupamento"),
        column("vendedor_id", "Código do vendedor"),
        column("vendedor", "Vendedor atual"),
        column("papel", "Papel"),
        column("gestor", "Gestor"),
        column("ufs", "UFs"),
        column("lojas", "Lojas na carteira"),
        column("lojas_com_compra", "Lojas com compra"),
        column("fat_rs", "FAT R$ no período", "R$"),
        column("fat_kg", "FAT KG no período", "KG"),
        column("situacao", "Situação"),
    ]
    exceptions = (
        [{"motivo": "Cliente sem responsável comercial no cadastro", "linhas": without_owner}]
        if without_owner
        else []
    )
    return {"colunas": header, "linhas": lines}, exceptions, counts


class ListNonPositivated:
    operation_id = "OP03"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        start = month_start(values["periodo_referencia"])
        end_exclusive = month_end_exclusive(start)

        product, question = resolve_product(fetcher, values)
        if question:
            return question

        last_closed = last_closed_month(fetcher)
        partial = has_open_month(fetcher, start, end_exclusive)
        sql, params = build_query(values, start, end_exclusive, scope, product)
        rows = fetcher.fetch(sql, tuple(params))
        if not rows:
            return OperationResult.clarification(
                NOT_FOUND_QUESTION.format(text=values["cliente_rede"])
            )
        main_block, exceptions, counts = shape_rows(
            rows, values.get("status_positivacao") or "nao_positivado"
        )

        notices: list[Notice] = [
            Notice(
                "OP03_CARTEIRA",
                "operacao",
                "A positivação é apurada por agrupamento (rede ou raiz do CNPJ) e vendedor ATUAL do "
                "cadastro: a compra de uma loja atendida por outro vendedor não positiva as demais. "
                "A carteira é a de hoje; não há histórico de quem atendia o cliente no passado.",
            ),
            Notice(
                "OP03_CONTAGEM",
                "resposta",
                f"{counts['nao_positivado']} combinação(ões) agrupamento × vendedor sem compra e "
                f"{counts['positivado']} com compra no período.",
            ),
        ]
        if partial:
            notices.append(
                partial_notice(
                    "O mês analisado ainda não fechou: a positivação pode mudar até o fechamento."
                )
            )
        return OperationResult(
            period=build_period(start, end_exclusive, last_closed, partial=partial),
            main_block=main_block,
            exceptions=exceptions,
            notices=notices,
        )
