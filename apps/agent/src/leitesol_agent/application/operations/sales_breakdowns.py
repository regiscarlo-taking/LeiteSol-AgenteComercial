"""Análises determinísticas por produto e localização, com dimensões fechadas."""

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
from leitesol_agent.domain.models import Notice, Operation, Parameter, Period, Scope

OPERATION_ID = "APP_SALES_BREAKDOWN"
INTENT_ID = "analisar_vendas_por_produto_ou_regiao"
DIMENSIONS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "produto": (("p.ProdutoId", "produto_id", "Código do produto"),
                ("p.Produto", "produto", "Produto")),
    "regiao": (("c.UF", "uf", "UF cadastral"),),
    "produto_por_regiao": (
        ("c.UF", "uf", "UF cadastral"),
        ("p.ProdutoId", "produto_id", "Código do produto"),
        ("p.Produto", "produto", "Produto"),
    ),
}
GEOGRAPHIES = {
    "uf": ("c.UF", "uf", "UF cadastral"),
    "regiao": ("c.Regiao", "regiao", "Região"),
    "municipio": ("c.Municipio", "municipio", "Município"),
}
WINDOWS = frozenset({3, 6, 9, 12})
DEFAULT_TOP = 20
DEFAULT_TOP_PER_REGION = 5


def local_analysis_operation() -> Operation:
    return Operation(
        operation_id=OPERATION_ID,
        skill_id="SK_LOCAL_ANALYTICS",
        intent_id=INTENT_ID,
        technical_name="analisar_vendas_por_produto_ou_regiao",
        business_intent=(
            "Somar FAT KG ou FAT R$ por produto, por UF/região/município, ou por produto "
            "dentro de cada UF. Produto usa ranking Top 20; produto por UF mostra Top 5 "
            "por UF. Pedido explícito por região usa Regiao (ESTADOS.REGIAO) ligada à "
            "UF cadastral do cliente; quando não especificar o nível, usar UF. Janela "
            "padrão: as últimas 3 competências fechadas. Não é comparação histórica."
        ),
        alerts=(
            "A atribuição geográfica usa o cadastro do cliente; não representa a UF registrada "
            "na transação. Análise regional histórica é a operação OP16."
        ),
        parameters=(
            Parameter(
                "dimensao",
                "enum",
                True,
                "produto|regiao|produto_por_regiao",
                None,
                "agrupamento do resultado",
            ),
            Parameter(
                "nivel_geografico",
                "enum",
                False,
                "uf|regiao|municipio",
                "uf",
                "nível geográfico",
            ),
            Parameter(
                "metrica",
                "enum",
                False,
                "fat_kg|fat_rs|ambas",
                "fat_kg",
                "métrica de ordenação e exibição",
            ),
            Parameter("periodo_inicio", "date", False, "AAAA-MM-DD", None, "início do período"),
            Parameter("periodo_fim", "date", False, "AAAA-MM-DD", None, "fim do período"),
            Parameter(
                "data_referencia",
                "date",
                False,
                "AAAA-MM-DD",
                None,
                "data que ancora a janela de competências fechadas",
            ),
            Parameter(
                "janela_meses",
                "int",
                False,
                "3|6|9|12",
                "3",
                "competências fechadas quando não houver período explícito",
            ),
            Parameter("top_n", "int", False, ">0", None, "limite do ranking solicitado"),
            Parameter(
                "filtro_produto",
                "string",
                False,
                "produto, família, grupamento ou subtotal cadastrado",
                None,
                "filtro de produto",
            ),
        ),
        examples=(
            "Quais produtos venderam mais?",
            "Quais regiões venderam mais em volume?",
            "Quais produtos foram mais vendidos em cada UF?",
            "Qual o faturamento por região nos últimos 6 meses?",
        ),
    )


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
        return month_start(start_requested), month_end_exclusive(end_requested)
    if last_closed is None:
        return None
    reference = values.get("data_referencia")
    anchor = month_start(reference) if reference else month_start(last_closed)
    if anchor > month_start(last_closed):
        anchor = month_start(last_closed)
    window = values.get("janela_meses", 3)
    months = months_back(anchor, window)
    return months[0], month_end_exclusive(months[-1])


def _dimension_columns(
    dimension: str, geography: str
) -> tuple[tuple[str, str, str], ...]:
    if dimension == "regiao":
        return (GEOGRAPHIES[geography],)
    if dimension == "produto_por_regiao":
        return (GEOGRAPHIES["uf"], *DIMENSIONS["produto_por_regiao"][1:])
    return DIMENSIONS[dimension]


def build_query(
    values: dict[str, Any],
    start: date,
    end_exclusive: date,
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any], tuple[tuple[str, str, str], ...]]:
    dimension = values["dimensao"]
    columns = _dimension_columns(dimension, values.get("nivel_geografico") or "uf")
    expressions = tuple(expression for expression, _, _ in columns)
    dimension_aliases = tuple(column_id for _, column_id, _ in columns)
    select_dims = ", ".join(
        f"{expression} AS {column_id}" for expression, column_id, _ in columns
    )
    group_by = ", ".join(expressions)
    rank_tie_break = ", ".join(dimension_aliases)
    where = universe_where(values, scope, product)
    metrics = values.get("metrica") or "fat_kg"
    aggregations = f"SUM({FAT_KG}) AS fat_kg, SUM({FAT_RS}) AS fat_rs"
    rank_column = "fat_rs" if metrics == "fat_rs" else "fat_kg"
    partition = "PARTITION BY uf " if dimension == "produto_por_regiao" else ""
    limit = ""
    params: list[Any] = [start, end_exclusive, *where.params]
    if dimension == "produto_por_regiao":
        top_n = values.get("top_n") or DEFAULT_TOP_PER_REGION
        limit = "WHERE posicao <= ?"
        params.append(top_n)
    elif dimension == "produto":
        top_n = values.get("top_n") or DEFAULT_TOP
        limit = "WHERE posicao <= ?"
        params.append(top_n)
    order_by = "uf, posicao" if dimension == "produto_por_regiao" else "posicao"

    sql = f"""
        WITH base AS (
            SELECT {select_dims},
                   {aggregations}
            {UNIVERSE_FROM}
            WHERE f.Data >= ? AND f.Data < ?
{where.sql}            GROUP BY {group_by}
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                {partition}ORDER BY {rank_column} DESC, {rank_tie_break}
            ) AS posicao
            FROM base
        )
        SELECT * FROM ranked
        {limit}
        ORDER BY {order_by}
    """
    return sql, params, columns


class SalesBreakdowns:
    operation_id = OPERATION_ID

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        dimension = values["dimensao"]
        if dimension not in DIMENSIONS:
            return OperationResult.clarification(
                "Escolha uma análise por produto, por região ou por produto dentro de cada UF."
            )
        metric = values.get("metrica") or "fat_kg"
        if metric not in {"fat_kg", "fat_rs", "ambas"}:
            return OperationResult.clarification("A métrica aceita FAT KG, FAT R$ ou ambas.")
        if dimension == "regiao" and (values.get("nivel_geografico") or "uf") not in GEOGRAPHIES:
            return OperationResult.clarification("Escolha UF, região ou município.")
        window = values.get("janela_meses", 3)
        if window not in WINDOWS and not values.get("periodo_inicio"):
            return OperationResult.clarification(
                "A janela padrão aceita 3, 6, 9 ou 12 competências fechadas."
            )

        last_closed = last_closed_month(fetcher)
        period_range = _period(values, last_closed)
        if period_range is None:
            return OperationResult.clarification(
                "Informe início e fim do período, ou peça uma janela de 3, 6, 9 ou 12 meses."
            )
        start, end_exclusive = period_range
        if last_closed and end_exclusive > month_end_exclusive(last_closed):
            return OperationResult.clarification(
                "Este resumo considera apenas competências fechadas. "
                "Informe um período até a última competência fechada."
            )

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))
        sql, params, columns = build_query(values, start, end_exclusive, scope, product)
        rows = fetcher.fetch(sql, tuple(params))

        metrics = ("fat_rs", "fat_kg") if metric == "ambas" else (metric,)
        lines = []
        for row in rows:
            line = {column_id: row.get(column_id) for _, column_id, _ in columns}
            line["posicao"] = row["posicao"]
            for name in metrics:
                line[name] = metric_value(
                    name,
                    float(row["fat_rs"] or 0),
                    float(row["fat_kg"] or 0),
                )
            lines.append(line)

        result_columns = [
            {"id": column_id, "rotulo": label, "unidade": None}
            for _, column_id, label in columns
        ]
        result_columns.append({"id": "posicao", "rotulo": "Posição", "unidade": None})
        result_columns.extend(
            {"id": name, "rotulo": METRICS[name][0], "unidade": METRICS[name][1]}
            for name in metrics
        )
        notices = []
        if start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base começa em janeiro de 2025; as competências anteriores não têm dados.",
                )
            )
        return OperationResult(
            period=Period(
                start=start,
                end_exclusive=end_exclusive,
                partial=False,
                last_closed_month=last_closed.strftime("%Y-%m") if last_closed else None,
            ),
            main_block={"colunas": result_columns, "linhas": lines},
            notices=notices,
        )
