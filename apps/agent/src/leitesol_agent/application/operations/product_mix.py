"""OP11 - consultar_mix_atual_cliente (skill Mix e Portfólio).

Regra do catálogo: janela = N competências completas anteriores (padrão 3),
sem o mês vigente salvo pedido explícito; presença no mix exige FAT R$ > 0
em ao menos um mês - bonificação compõe o KG, mas não coloca o item no mix;
nível padrão = SKU; o filtro de produto entra ANTES dos totais e das
participações. Itens bloqueados ou substituídos ficam quando houve compra.

Ordem padrão homologada (AIC-288, D-A60): família na ordem da árvore
comercial e, dentro da família, FAT KG decrescente - vale também para
cliente específico. Ordem alternativa só quando o usuário pede.
"""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
    month_start,
    normalize_term,
)
from leitesol_agent.application.operations.common import (
    FAT_KG,
    FAT_RS,
    HISTORY_START,
    UNIVERSE_FROM,
    client_filter,
    has_open_month,
    last_closed_month,
    metric_value,
    product_filter,
    product_question,
    universe_where,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Period, Scope

MAX_ROWS = 200

# nível -> (chave de agrupamento, expressão do produto, expressão da família).
# "grupo" é o grupamento da árvore comercial; "subgrupo" não tem nível
# correspondente nela (subtotal -> grupamento -> família) e vira pergunta.
LEVELS = {
    "sku": ("p.ProdutoId", "MAX(p.Produto)", "MAX(p.Familia)"),
    "familia": ("p.Familia", "NULL", "MAX(p.Familia)"),
    "grupo": ("p.Grupamento", "NULL", "NULL"),
}

SUBGROUP_QUESTION = (
    "A árvore comercial tem três níveis: subtotal, grupamento e família. "
    "Quer o mix por produto (SKU), por família ou por grupamento?"
)
ORDER_QUESTION = (
    'Não entendi a ordem "{text}". Posso ordenar por família (padrão), volume em KG, '
    "faturamento em R$, participação, meses com compra, última compra ou descrição."
)


def window(
    reference: date, months: int, last_closed: date | None, include_current: bool
) -> tuple[date, date]:
    """Início e fim exclusivo da janela: N competências que terminam antes do mês vigente."""
    if include_current:
        end_exclusive = month_end_exclusive(reference)
    else:
        end_exclusive = month_start(reference)
        # Só competência fechada: se o fechamento atrasou, a janela recua junto.
        if last_closed and month_end_exclusive(last_closed) < end_exclusive:
            end_exclusive = month_end_exclusive(last_closed)
    last_month = months_back(end_exclusive, 2)[0]
    return months_back(last_month, months)[0], end_exclusive


def build_query(
    values: dict[str, Any],
    start: date,
    end_exclusive: date,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    key, product_expr, family_expr = LEVELS[values.get("nivel_produto") or "sku"]
    where = universe_where(values, scope, product)
    clause, params = client_filter(values["escopo_cliente"])
    where.add(clause, *params)

    # Presença é do ITEM no MÊS: agrega antes de testar FAT R$ > 0.
    sql = f"""
        WITH mensal AS (
            SELECT
                {key} AS item_id,
                f.Data,
                {product_expr} AS produto,
                {family_expr} AS familia,
                MAX(p.Grupamento) AS grupamento,
                MAX(p.Subtotal) AS subtotal,
                MIN(p.OrdemSubtotal) AS ordem_subtotal,
                MIN(p.OrdemGrupamento) AS ordem_grupamento,
                MIN(p.OrdemFamilia) AS ordem_familia,
                MIN(c.UF) AS uf_min,
                MAX(c.UF) AS uf_max,
                SUM({FAT_RS}) AS fat_rs,
                SUM({FAT_KG}) AS fat_kg
            {UNIVERSE_FROM}
            WHERE f.Data >= ? AND f.Data < ?
{where.sql}            GROUP BY {key}, f.Data
        )
        SELECT
            item_id,
            MAX(produto) AS produto,
            MAX(familia) AS familia,
            MAX(grupamento) AS grupamento,
            MAX(subtotal) AS subtotal,
            MIN(ordem_subtotal) AS ordem_subtotal,
            MIN(ordem_grupamento) AS ordem_grupamento,
            MIN(ordem_familia) AS ordem_familia,
            CASE WHEN MIN(uf_min) = MAX(uf_max) THEN MIN(uf_min) ELSE 'Várias' END AS uf,
            SUM(fat_rs) AS fat_rs,
            SUM(fat_kg) AS fat_kg,
            SUM(CASE WHEN fat_rs > 0 THEN 1 ELSE 0 END) AS meses_com_compra,
            MAX(CASE WHEN fat_rs > 0 THEN Data END) AS ultima_compra
        FROM mensal
        GROUP BY item_id
        HAVING MAX(CASE WHEN fat_rs > 0 THEN 1 ELSE 0 END) = 1
    """
    return sql, [start, end_exclusive, *where.params]


def _last(value: Any) -> tuple[bool, Any]:
    """Chave de ordenação crescente com vazio por último."""
    return (value is None, value if value is not None else 0)


def _tree_key(row: dict[str, Any]) -> tuple:
    return (
        _last(row["ordem_subtotal"]),
        _last(row["ordem_grupamento"]),
        _last(row["ordem_familia"]),
        row["familia"] or "",
    )


def sort_rows(
    rows: list[dict[str, Any]], ordering: str | None, metric: str
) -> list[dict[str, Any]] | None:
    """Linhas na ordem pedida; None = critério não reconhecido."""
    kg = lambda row: float(row["fat_kg"] or 0)  # noqa: E731
    rs = lambda row: float(row["fat_rs"] or 0)  # noqa: E731
    within = rs if metric == "fat_rs" else kg

    if not ordering:
        return sorted(rows, key=lambda row: (_tree_key(row), -within(row), row["produto"] or ""))

    text = normalize_term(ordering)
    if any(word in text for word in ("FAMILIA", "ARVORE", "PADRAO")):
        return sorted(rows, key=lambda row: (_tree_key(row), -within(row), row["produto"] or ""))
    if any(word in text for word in ("DESCRI", "NOME", "ALFAB")):
        return sorted(
            rows, key=lambda row: row["produto"] or row["familia"] or row["grupamento"] or ""
        )
    if "ULTIMA" in text or "RECENTE" in text:
        return sorted(
            rows, key=lambda row: (str(row["ultima_compra"] or ""), kg(row)), reverse=True
        )
    if "FREQ" in text or "MESES" in text:
        return sorted(rows, key=lambda row: (row["meses_com_compra"] or 0, kg(row)), reverse=True)
    if "PARTICIP" in text:
        value = rs if ("R$" in text or "REAIS" in text) else within
        return sorted(rows, key=value, reverse=True)
    if any(word in text for word in ("R$", "REAIS", "VALOR", "FATURAMENTO", "FAT_RS")):
        return sorted(rows, key=rs, reverse=True)
    if any(word in text for word in ("KG", "VOLUME", "QUILO", "TON")):
        return sorted(rows, key=kg, reverse=True)
    return None


def shape_rows(rows: list[dict[str, Any]], level: str, months: int) -> tuple[dict[str, Any], bool]:
    """Bloco principal e se algum total não é positivo (participação sem sentido)."""
    total_rs = sum(float(row["fat_rs"] or 0) for row in rows)
    total_kg = sum(float(row["fat_kg"] or 0) for row in rows)
    lines = []
    for row in rows[:MAX_ROWS]:
        fat_rs = float(row["fat_rs"] or 0)
        fat_kg = float(row["fat_kg"] or 0)
        line = {
            "item_id": row["item_id"],
            "produto": row["produto"],
            "familia": row["familia"],
            "grupamento": row["grupamento"],
            "subtotal": row["subtotal"],
            "uf": row["uf"],
            "fat_kg": metric_value("fat_kg", 0, fat_kg),
            "fat_rs": metric_value("fat_rs", fat_rs, 0),
            "participacao_kg_pct": round(fat_kg / total_kg * 100, 2) if total_kg > 0 else None,
            "participacao_rs_pct": round(fat_rs / total_rs * 100, 2) if total_rs > 0 else None,
            "meses_com_compra": int(row["meses_com_compra"] or 0),
            "ultima_compra": str(row["ultima_compra"])[:7] if row["ultima_compra"] else None,
        }
        if level != "sku":
            del line["produto"]
        if level == "grupo":
            del line["familia"]
        lines.append(line)

    header = [
        {"id": "item_id", "rotulo": "Código" if level == "sku" else "Item", "unidade": None},
        {"id": "produto", "rotulo": "Produto", "unidade": None},
        {"id": "familia", "rotulo": "Família", "unidade": None},
        {"id": "grupamento", "rotulo": "Grupamento", "unidade": None},
        {"id": "subtotal", "rotulo": "Subtotal", "unidade": None},
        {"id": "uf", "rotulo": "UF", "unidade": None},
        {"id": "fat_kg", "rotulo": "FAT KG", "unidade": "KG"},
        {"id": "fat_rs", "rotulo": "FAT R$", "unidade": "R$"},
        {"id": "participacao_kg_pct", "rotulo": "Participação em KG", "unidade": "%"},
        {"id": "participacao_rs_pct", "rotulo": "Participação em R$", "unidade": "%"},
        {"id": "meses_com_compra", "rotulo": f"Meses com compra (de {months})", "unidade": None},
        {"id": "ultima_compra", "rotulo": "Última compra", "unidade": None},
    ]
    if level != "sku":
        header = [column for column in header if column["id"] != "produto"]
    if level == "grupo":
        header = [column for column in header if column["id"] != "familia"]
    return {"colunas": header, "linhas": lines}, total_rs <= 0 or total_kg <= 0


class ProductMix:
    operation_id = "OP11"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        level = values.get("nivel_produto") or "sku"
        if level not in LEVELS:
            return OperationResult.clarification(SUBGROUP_QUESTION)
        months = values.get("janela_meses") or 3
        metric = values.get("metrica_principal") or "ambas"
        include_current = bool(values.get("incluir_mes_atual"))

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        last_closed = last_closed_month(fetcher)
        reference = values.get("data_referencia") or date.today()
        start, end_exclusive = window(reference, months, last_closed, include_current)
        partial = has_open_month(fetcher, start, end_exclusive)

        sql, params = build_query(values, start, end_exclusive, scope, product)
        rows = sort_rows(fetcher.fetch(sql, tuple(params)), values.get("ordenacao"), metric)
        if rows is None:
            return OperationResult.clarification(ORDER_QUESTION.format(text=values["ordenacao"]))
        main_block, non_positive_total = shape_rows(rows, level, months)

        notices: list[Notice] = [
            Notice(
                "MIX_PRESENCA",
                "operacao",
                "Entra no mix o item com faturamento em R$ em ao menos um mês da janela. "
                "Bonificação soma no KG, mas sozinha não coloca o item no mix.",
            )
        ]
        if not rows:
            notices.append(
                Notice("SEM_COMPRA", "operacao", "Não há compra válida desse cliente na janela.")
            )
        if values.get("status_produto"):
            notices.append(
                Notice(
                    "STATUS_PRODUTO",
                    "operacao",
                    "A base do agente não traz a situação do produto (ativo, bloqueado, "
                    "substituído): o filtro não foi aplicado e o mix mostra todos os itens "
                    "comprados.",
                )
            )
        if non_positive_total and rows:
            notices.append(
                Notice(
                    "PARTICIPACAO",
                    "operacao",
                    "O total do mix não é positivo (devoluções superam vendas): "
                    "a participação não foi calculada.",
                )
            )
        if start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base começa em janeiro de 2025: os meses anteriores da janela não têm dado.",
                )
            )
        if partial:
            notices.append(
                Notice(
                    "TR02",
                    "regra_tempo",
                    "A janela inclui mês ainda não fechado: os valores desse mês são parciais.",
                )
            )
        if len(rows) > MAX_ROWS:
            notices.append(
                Notice("LIMITE", "resposta", f"Exibindo {MAX_ROWS} de {len(rows)} itens.")
            )
        return OperationResult(
            period=Period(
                start=start,
                end_exclusive=end_exclusive,
                partial=partial,
                last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
            ),
            main_block=main_block,
            notices=notices,
        )
