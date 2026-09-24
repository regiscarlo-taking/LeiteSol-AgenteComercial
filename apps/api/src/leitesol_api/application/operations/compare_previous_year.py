"""OP12 - comparar_ano_anterior (skill SK02).

Regra do catálogo: período obrigatório, sem período padrão; o mesmo intervalo
deslocado em -1 ano, com limites fechado-aberto; os mesmos filtros nos dois
anos; base zero no ano anterior não gera percentual (RT24).

Os números saem de T-SQL sobre as views do Warehouse, com as fórmulas das
medidas do catálogo (AGT_MEDIDA): FAT R$ = vendas - devoluções; FAT KG =
vendas + bonificação - devoluções; FAT TONS = FAT KG / 1000.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from leitesol_api.application.operations.base import (
    OperationResult,
    SqlFetcher,
    add_years,
    month_end_exclusive,
    month_start,
    normalize_term,
)
from leitesol_api.domain.agent import Notice, Period, Scope

# Início da base histórica da vw_fato_faturamento (Data >= 2025-01-01).
HISTORY_START = date(2025, 1, 1)
MAX_ROWS = 50

# granularidade -> colunas (expressão SQL, id da coluna, rótulo). A UF do
# cadastro acompanha o detalhamento por cliente e por município (RT25).
GRANULARITY_COLUMNS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "total": (),
    "cliente": (
        ("c.ClienteId", "cliente_id", "Código"),
        ("c.RazaoSocial", "cliente", "Cliente"),
        ("c.UF", "uf", "UF"),
    ),
    "produto": (("p.ProdutoId", "produto_id", "Código"), ("p.Produto", "produto", "Produto")),
    "vendedor": (
        ("f.VendedorId", "vendedor_id", "Código"),
        ("r.Representante", "vendedor", "Vendedor"),
    ),
    "uf": (("c.UF", "uf", "UF"),),
    "municipio": (("c.UF", "uf", "UF"), ("c.Municipio", "municipio", "Município")),
    "segmento": (
        ("c.SegmentoCodigo", "segmento_id", "Código"),
        ("c.SegmentoDescricao", "segmento", "Segmento"),
    ),
}

METRICS = {
    "fat_rs": ("FAT R$", "R$"),
    "fat_kg": ("FAT KG", "KG"),
    "fat_tons": ("FAT TONS", "t"),
}

CALENDAR_SQL = """
    SELECT
        MAX(CASE WHEN MesFechado = 1 THEN Data END) AS UltimaFechada,
        MAX(CASE WHEN Data >= ? AND Data < ? AND MesFechado = 0 THEN 1 ELSE 0 END) AS TemParcial
    FROM [IA_COMERCIAL].[vw_dim_calendario]
"""

PRODUCT_TERMS_SQL = """
    SELECT DISTINCT TermoNormalizado
    FROM [IA_COMERCIAL].[vw_produto_termo]
    WHERE TermoNormalizado IN ({placeholders})
"""

PRODUCT_TREE_SQL = """
    SELECT TOP 1 1 AS Existe
    FROM [IA_COMERCIAL].[vw_dim_produto]
    WHERE UPPER(Familia) = ? OR UPPER(Grupamento) = ? OR UPPER(Subtotal) = ?
"""

STOPWORDS = frozenset({"DE", "DO", "DA", "DOS", "DAS", "EM", "E", "O", "A"})


@dataclass(slots=True)
class QueryPlan:
    sql: str
    params: list[Any] = field(default_factory=list)
    columns: tuple[tuple[str, str, str], ...] = ()


def _round_money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_kg(value: float) -> int:
    # RT16: KG sem casas decimais, 0,5 sobe - para bater com o painel.
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def resolve_period(values: dict[str, Any]) -> tuple[Period, bool]:
    """Normaliza para competências inteiras (RT17) e desloca -1 ano (TR06).

    Devolve o período e se houve ajuste do que o usuário pediu.
    """
    start_requested: date = values["periodo_inicio"]
    end_requested: date = values["periodo_fim"]
    if end_requested < start_requested:
        start_requested, end_requested = end_requested, start_requested
    start = month_start(start_requested)
    end_exclusive = month_end_exclusive(end_requested)
    adjusted = start != start_requested or date.fromordinal(end_exclusive.toordinal() - 1) != end_requested
    return (
        Period(
            start=start,
            end_exclusive=end_exclusive,
            comparison_start=add_years(start, -1),
            comparison_end_exclusive=add_years(end_exclusive, -1),
        ),
        adjusted,
    )


def product_filter(fetcher: SqlFetcher, text: str) -> tuple[str, list[Any]] | None:
    """Filtro de produto por lista fechada (RT35). None = termo fora da lista."""
    node = normalize_term(text)
    if fetcher.fetch(PRODUCT_TREE_SQL, (node, node, node)):
        return "(UPPER(p.Familia) = ? OR UPPER(p.Grupamento) = ? OR UPPER(p.Subtotal) = ?)", [
            node,
            node,
            node,
        ]

    terms = sorted({term for term in node.split() if term not in STOPWORDS})
    if not terms:
        return None
    placeholders = ", ".join("?" for _ in terms)
    known = {
        row["TermoNormalizado"]
        for row in fetcher.fetch(PRODUCT_TERMS_SQL.format(placeholders=placeholders), tuple(terms))
    }
    if set(terms) - known:
        return None
    return (
        "p.ProdutoId IN (SELECT t.ProdutoId FROM [IA_COMERCIAL].[vw_produto_termo] t "
        f"WHERE t.TermoNormalizado IN ({placeholders}) "
        "GROUP BY t.ProdutoId HAVING COUNT(DISTINCT t.TermoNormalizado) = ?)",
        [*terms, len(terms)],
    )


def build_query(
    values: dict[str, Any],
    period: Period,
    scope: Scope,
    extra_filters: list[tuple[str, list[Any]]] | None = None,
) -> QueryPlan:
    granularity = values.get("granularidade") or "total"
    columns = GRANULARITY_COLUMNS.get(granularity, ())
    select_dims = "".join(f"{expr} AS {col_id}, " for expr, col_id, _ in columns)
    group_by = ", ".join(expr for expr, _, _ in columns)

    current = "f.Data >= ? AND f.Data < ?"
    previous = "f.Data >= ? AND f.Data < ?"
    current_params = [period.start, period.end_exclusive]
    previous_params = [period.comparison_start, period.comparison_end_exclusive]

    sql = f"""
        SELECT {select_dims}
            SUM(CASE WHEN {current} THEN f.Vendas_R - f.Dev_R ELSE 0 END) AS fat_rs_atual,
            SUM(CASE WHEN {previous} THEN f.Vendas_R - f.Dev_R ELSE 0 END) AS fat_rs_anterior,
            SUM(CASE WHEN {current} THEN f.Vendas_Kg + f.Bonif_Kg - f.Dev_Kg ELSE 0 END) AS fat_kg_atual,
            SUM(CASE WHEN {previous} THEN f.Vendas_Kg + f.Bonif_Kg - f.Dev_Kg ELSE 0 END) AS fat_kg_anterior
        FROM [IA_COMERCIAL].[vw_fato_faturamento] f
        JOIN [IA_COMERCIAL].[vw_dim_produto] p ON p.ProdutoId = f.ProdutoId
        JOIN [IA_COMERCIAL].[vw_dim_cliente] c ON c.ClienteId = f.ClienteId
        LEFT JOIN [IA_COMERCIAL].[vw_dim_representante] r ON r.RepresentanteId = f.VendedorId
        WHERE (({current}) OR ({previous}))
          AND p.FlagProdutoAcabado = 1
          AND c.FlagExterior = 0
    """
    params: list[Any] = [
        *current_params,
        *previous_params,
        *current_params,
        *previous_params,
        *current_params,
        *previous_params,
    ]

    if not scope.sees_everything:
        sellers = sorted(scope.sellers)
        sql += f"  AND f.VendedorId IN ({', '.join('?' for _ in sellers)})\n"
        params.extend(sellers)

    if values.get("uf"):
        sql += "  AND c.UF = ?\n"
        params.append(values["uf"].strip().upper())
    if values.get("municipio"):
        sql += "  AND UPPER(c.Municipio) = ?\n"
        params.append(normalize_term(values["municipio"]))
    if values.get("segmento"):
        sql += "  AND (c.SegmentoCodigo = ? OR UPPER(c.SegmentoDescricao) = ?)\n"
        params.extend([values["segmento"].strip(), normalize_term(values["segmento"])])
    if values.get("vendedor_rca"):
        sql += "  AND (f.VendedorId = ? OR UPPER(r.Representante) = ?)\n"
        params.extend([values["vendedor_rca"].strip(), normalize_term(values["vendedor_rca"])])
    if values.get("cliente_rede"):
        clause, clause_params = client_filter(values["cliente_rede"])
        sql += f"  AND {clause}\n"
        params.extend(clause_params)
    for clause, clause_params in extra_filters or []:
        sql += f"  AND {clause}\n"
        params.extend(clause_params)

    if group_by:
        sql += f"GROUP BY {group_by}\n"
    return QueryPlan(sql=sql, params=params, columns=columns)


def client_filter(text: str) -> tuple[str, list[Any]]:
    digits = "".join(char for char in text if char.isdigit())
    cnpj = "REPLACE(REPLACE(REPLACE(c.CNPJ, '.', ''), '/', ''), '-', '')"
    if len(digits) == 14:
        return f"{cnpj} = ?", [digits]
    if len(digits) == 8:
        return "c.CNPJRaiz = ?", [digits]
    value = text.strip()
    return (
        "(c.ClienteId = ? OR c.ClienteCodigo = ? OR c.Rede = ? OR UPPER(c.GrupoVendaDescricao) = ?)",
        [value, value, value, normalize_term(value)],
    )


def shape_rows(
    rows: list[dict[str, Any]],
    columns: tuple[tuple[str, str, str], ...],
    metric: str,
    situation: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Monta o bloco principal e o de exceções (base zero, RT24)."""
    metrics = list(METRICS) if metric == "ambas" else [metric]
    # Métrica que decide ordem, situação e exceção quando o usuário pediu "ambas".
    lead = "fat_rs" if metric == "ambas" else metric

    shaped: list[dict[str, Any]] = []
    zero_base: list[dict[str, Any]] = []
    for row in rows:
        values = {
            "fat_rs": (float(row["fat_rs_atual"] or 0), float(row["fat_rs_anterior"] or 0)),
            "fat_kg": (float(row["fat_kg_atual"] or 0), float(row["fat_kg_anterior"] or 0)),
        }
        values["fat_tons"] = (values["fat_kg"][0] / 1000, values["fat_kg"][1] / 1000)

        line: dict[str, Any] = {col_id: row.get(col_id) for _, col_id, _ in columns}
        for name in metrics:
            current, previous = values[name]
            if name == "fat_rs":
                current, previous = _round_money(current), _round_money(previous)
            elif name == "fat_kg":
                current, previous = _round_kg(current), _round_kg(previous)
            else:
                current, previous = round(current, 3), round(previous, 3)
            line[f"{name}_atual"] = current
            line[f"{name}_anterior"] = previous
            line[f"{name}_variacao_abs"] = round(current - previous, 3)
            line[f"{name}_variacao_pct"] = (
                round((current - previous) / previous * 100, 2) if previous else None
            )

        variation = line[f"{lead}_variacao_abs"]
        if situation == "crescimento" and variation <= 0:
            continue
        if situation == "queda" and variation >= 0:
            continue
        if situation == "igual" and variation != 0:
            continue
        if not line[f"{lead}_anterior"]:
            zero_base.append(line)
        else:
            shaped.append(line)

    shaped.sort(key=lambda line: abs(line[f"{lead}_variacao_abs"]), reverse=True)
    total = len(shaped)

    header = [{"id": col_id, "rotulo": label, "unidade": None} for _, col_id, label in columns]
    for name in metrics:
        label, unit = METRICS[name]
        header.extend(
            [
                {"id": f"{name}_atual", "rotulo": f"{label} atual", "unidade": unit},
                {"id": f"{name}_anterior", "rotulo": f"{label} ano anterior", "unidade": unit},
                {"id": f"{name}_variacao_abs", "rotulo": f"Variação {label}", "unidade": unit},
                {"id": f"{name}_variacao_pct", "rotulo": f"Variação {label} %", "unidade": "%"},
            ]
        )

    exceptions = (
        [{"motivo": "Base do ano anterior igual a zero", "linhas": zero_base}] if zero_base else []
    )
    return {"colunas": header, "linhas": shaped[:MAX_ROWS]}, exceptions, total


class CompareWithPreviousYear:
    operation_id = "OP12"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        period, adjusted = resolve_period(values)
        notices: list[Notice] = []

        extra_filters: list[tuple[str, list[Any]]] = []
        if values.get("filtro_produto"):
            resolved = product_filter(fetcher, values["filtro_produto"])
            if resolved is None:
                return OperationResult.clarification(
                    f'Não reconheci "{values["filtro_produto"]}" como produto, família ou '
                    "termo de produto cadastrado. Pode indicar o produto de outra forma?"
                )
            extra_filters.append(resolved)

        calendar = fetcher.fetch(CALENDAR_SQL, (period.start, period.end_exclusive))
        last_closed = calendar[0]["UltimaFechada"] if calendar else None
        partial = bool(calendar and calendar[0]["TemParcial"])
        period = Period(
            start=period.start,
            end_exclusive=period.end_exclusive,
            comparison_start=period.comparison_start,
            comparison_end_exclusive=period.comparison_end_exclusive,
            partial=partial,
            last_closed_month=str(last_closed)[:7] if last_closed else None,
        )

        plan = build_query(values, period, scope, extra_filters)
        rows = fetcher.fetch(plan.sql, tuple(plan.params))
        main_block, exceptions, total = shape_rows(
            rows,
            plan.columns,
            values.get("metrica") or "ambas",
            values.get("situacao") or "todas",
        )

        if adjusted:
            notices.append(
                Notice(
                    "RT17",
                    "regra_transversal",
                    "O período foi ajustado para meses completos: o faturamento é consolidado por mês.",
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
        if period.comparison_start and period.comparison_start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base histórica começa em janeiro de 2025: antes disso não há dado para comparar.",
                )
            )
        if exceptions:
            notices.append(
                Notice(
                    "RT24",
                    "regra_transversal",
                    "Itens sem faturamento no ano anterior ficam em bloco separado, sem percentual.",
                )
            )
        if total > MAX_ROWS:
            notices.append(
                Notice(
                    "LIMITE",
                    "resposta",
                    f"Exibindo as {MAX_ROWS} maiores variações de {total} linhas.",
                )
            )

        return OperationResult(
            period=period,
            main_block=main_block,
            exceptions=exceptions,
            notices=notices,
        )
