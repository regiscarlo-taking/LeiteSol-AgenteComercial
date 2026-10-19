"""OP22 - sugerir_expansao_mix (skill Mix e Portfólio).

Regra do catálogo (22-07): janela de 24 competências fechadas. Só se
comparam clientes do MESMO segmento atual e da MESMA UF. O cliente compra um
grupamento quando tem FAT R$ > 0 nele na janela. Pista = cliente que compra
o grupamento de origem e não compra o complementar, desde que o
complementar seja comprado por outros clientes do mesmo segmento/UF.
Resultado: Top 20 de pistas comerciais, não decisão automática.

Descartado em 22-07: a meta "compra 20% do portfólio, potencial de 60%" -
não há universo, denominador nem metodologia para esse percentual.

Em aberto (P09): o mapa de grupamentos complementares não foi homologado; o
par vem da pergunta do usuário.
"""

from typing import Any

from leitesol_agent.application.operations.analytics import (
    CLIENT_ENTITIES,
    build_period,
    closed_anchor,
    column,
    history_notice,
    metric_round,
    month_text,
    open_rule_notice,
    window_months,
)
from leitesol_agent.application.operations.base import OperationResult, SqlFetcher, normalize_term
from leitesol_agent.application.operations.common import (
    FAT_KG,
    FAT_RS,
    HISTORY_START,
    UNIVERSE_FROM,
    last_closed_month,
    universe_where,
)
from leitesol_agent.domain.models import Notice, Scope

GROUPS_SQL = """
    SELECT DISTINCT Grupamento AS grupamento
    FROM [IA_COMERCIAL].[vw_dim_produto]
    WHERE FlagProdutoAcabado = 1 AND Grupamento IS NOT NULL
"""
UNCLASSIFIED_SEGMENTS = {"ND", "OUTRO", "OUTROS", "SEM SEGMENTO"}


def match_group(text: str, groups: list[str]) -> str | None:
    wanted = normalize_term(text)
    return next((group for group in groups if normalize_term(group) == wanted), None)


def build_query(
    values: dict[str, Any],
    scope: Scope,
    start: Any,
    end_exclusive: Any,
    entity: tuple[str, str, str],
    origin: str,
    complement: str,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope)
    key, label, _ = entity
    sql = f"""
        SELECT {key} AS entidade_id,
               {label} AS entidade,
               MAX(c.SegmentoDescricao) AS segmento,
               MAX(c.UF) AS uf,
               SUM(CASE WHEN p.Grupamento = ? THEN {FAT_RS} ELSE 0 END) AS origem_rs,
               SUM(CASE WHEN p.Grupamento = ? THEN {FAT_RS} ELSE 0 END) AS complemento_rs,
               SUM({FAT_RS}) AS fat_rs,
               SUM({FAT_KG}) AS fat_kg
        {UNIVERSE_FROM}
        WHERE f.Data >= ? AND f.Data < ?
{where.sql}        GROUP BY {key}
    """
    return sql, [origin, complement, start, end_exclusive, *where.params]


def shape(
    rows: list[dict[str, Any]], priority: str, top_n: int
) -> tuple[dict[str, Any], dict[str, int]]:
    peers = [row for row in rows if float(row["complemento_rs"] or 0) > 0]
    leads = [
        row
        for row in rows
        if float(row["origem_rs"] or 0) > 0 and float(row["complemento_rs"] or 0) <= 0
    ]
    stats = {"clientes": len(rows), "compradores_complemento": len(peers), "pistas": len(leads)}
    if not peers:
        leads = []
    proportion = round(len(peers) / len(rows) * 100, 2) if rows else None
    lines = [
        {
            "entidade_id": row["entidade_id"],
            "entidade": row["entidade"],
            "segmento": row["segmento"],
            "uf": row["uf"],
            "fat_rs": metric_round("fat_rs", float(row["fat_rs"] or 0)),
            "fat_kg": metric_round("fat_kg", float(row["fat_kg"] or 0)),
            "origem_rs": metric_round("fat_rs", float(row["origem_rs"] or 0)),
            "pares_compradores": len(peers),
            "proporcao_pares_pct": proportion,
        }
        for row in leads
    ]
    for metric in ("fat_rs", "fat_kg"):
        ordered = sorted(
            lines, key=lambda line, metric=metric: (-line[metric], str(line["entidade_id"]))
        )
        for position, line in enumerate(ordered, start=1):
            line[f"posicao_{metric.split('_')[1]}"] = position
    lines.sort(key=lambda line: (-line[priority], str(line["entidade_id"])))
    header = [
        column("posicao_rs", "Posição por R$"),
        column("posicao_kg", "Posição por KG"),
        column("entidade_id", "Código"),
        column("entidade", "Cliente / rede"),
        column("segmento", "Segmento"),
        column("uf", "UF"),
        column("fat_rs", "FAT R$ na janela", "R$"),
        column("fat_kg", "FAT KG na janela", "KG"),
        column("origem_rs", "FAT R$ no grupamento de origem", "R$"),
        column("pares_compradores", "Clientes do mesmo segmento/UF que compram o complementar"),
        column("proporcao_pares_pct", "Proporção dos pares compradores", "%"),
    ]
    return {"colunas": header, "linhas": lines[:top_n]}, stats


class MixExpansion:
    operation_id = "OP22"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        if normalize_term(values["segmento"]) in UNCLASSIFIED_SEGMENTS:
            return OperationResult.clarification(
                "Clientes sem segmento definido (ND ou OUTRO) não entram na comparação entre pares. "
                "Qual segmento você quer analisar?"
            )
        groups = [str(row["grupamento"]) for row in fetcher.fetch(GROUPS_SQL)]
        origin = match_group(values["agrupamento_origem"], groups)
        complement = match_group(values["agrupamento_complementar"], groups)
        if origin is None or complement is None:
            missing = (
                values["agrupamento_origem"]
                if origin is None
                else values["agrupamento_complementar"]
            )
            return OperationResult.clarification(
                f'Não reconheci o grupamento "{missing}". Grupamentos disponíveis: {", ".join(sorted(groups))}.'
            )
        if origin == complement:
            return OperationResult.clarification(
                "O grupamento complementar precisa ser diferente do de origem."
            )

        last_closed = last_closed_month(fetcher)
        anchor = closed_anchor(None, last_closed)
        if anchor is None:
            return OperationResult.clarification("Não há competência fechada para analisar.")
        months, start, end_exclusive = window_months(anchor, values.get("periodo_meses") or 24)
        granularity = values.get("granularidade_cliente") or "rede"
        entity = CLIENT_ENTITIES.get(granularity, CLIENT_ENTITIES["rede"])
        sql, params = build_query(values, scope, start, end_exclusive, entity, origin, complement)
        rows = fetcher.fetch(sql, tuple(params))
        top_n = values.get("top_n") or 20
        main_block, stats = shape(rows, values.get("metrica_priorizacao") or "fat_rs", top_n)

        notices: list[Notice] = [
            Notice(
                "OP22_LEITURA",
                "operacao",
                f"Pistas comerciais por {entity[2]}: clientes de {values['segmento']} em "
                f"{values['uf'].upper()} que compram {origin} e não compram {complement} entre "
                f"{month_text(months[0])} e {month_text(months[-1])}. {stats['compradores_complemento']} de "
                f"{stats['clientes']} clientes comparáveis compram {complement}. É pista para decisão "
                "comercial, não recomendação automática, e não calcula cobertura de portfólio "
                "(a meta '20% para 60%' foi descartada por falta de base de cálculo).",
            ),
            open_rule_notice(
                "o mapa de grupamentos complementares não foi homologado; o par analisado é o "
                "informado na pergunta."
            ),
        ]
        if not stats["compradores_complemento"]:
            notices.append(
                Notice(
                    "OP22_SEM_PARES",
                    "resposta",
                    f"Nenhum cliente comparável compra {complement}: não há evidência para sugerir a expansão.",
                )
            )
        if start < HISTORY_START:
            notices.append(
                history_notice(
                    f"A base começa em janeiro de 2025: a janela de {len(months)} meses tem só parte com dado."
                )
            )
        return OperationResult(
            period=build_period(start, end_exclusive, last_closed),
            main_block=main_block,
            notices=notices,
        )
