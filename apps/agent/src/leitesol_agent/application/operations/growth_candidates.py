"""OP19 - identificar_clientes_com_potencial_crescimento (skill Comportamento de Compra).

Regra do catálogo (22-07): janela = 12 competências fechadas. Critérios
CUMULATIVOS: (1) compra em mais de 70% dos meses (ao menos 9 de 12);
(2) mais de um item com compra válida no nível do mix (padrão SKU);
(3) tendência crescente em KG = média dos últimos 6 meses > média dos
primeiros 6. O resultado é 'candidato heurístico a crescimento', nunca
score ou potencial comprovado. Cliente/CNPJ e rede são visões separadas.

Em aberto (P07): a fórmula da tendência é proposta técnica, e o nível
oficial do mix e a validação com clientes reais ainda não foram fechados.
"""

from typing import Any

from leitesol_agent.application.operations.analytics import (
    CLIENT_ENTITIES,
    build_period,
    closed_anchor,
    column,
    commercial_filter,
    growth_criteria,
    history_notice,
    metric_round,
    month_text,
    open_rule_notice,
    resolve_product,
    window_months,
)
from leitesol_agent.application.operations.base import OperationResult, SqlFetcher
from leitesol_agent.application.operations.common import (
    FAT_KG,
    FAT_RS,
    HISTORY_START,
    UNIVERSE_FROM,
    last_closed_month,
    universe_where,
)
from leitesol_agent.domain.models import Notice, Scope

MIX_LEVELS = {"sku": "p.ProdutoId", "familia": "p.Familia"}


def build_query(
    values: dict[str, Any],
    scope: Scope,
    start: Any,
    end_exclusive: Any,
    second_half: Any,
    window: int,
    entity: tuple[str, str, str],
    mix_key: str,
    product: tuple[str, list[Any]] | None,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope, product)
    for clause, params in commercial_filter(values):
        where.add(clause, *params)
    key, label, _ = entity
    sql = f"""
        WITH mensal AS (
            SELECT {key} AS entidade_id, f.Data,
                   {label} AS entidade,
                   MIN(c.UF) AS uf_min, MAX(c.UF) AS uf_max,
                   MAX(c.SegmentoDescricao) AS segmento,
                   SUM({FAT_RS}) AS fat_rs, SUM({FAT_KG}) AS fat_kg
            {UNIVERSE_FROM}
            WHERE f.Data >= ? AND f.Data < ?
{where.sql}            GROUP BY {key}, f.Data
        ),
        itens AS (
            SELECT entidade_id, COUNT(DISTINCT item_id) AS mix
            FROM (
                SELECT {key} AS entidade_id, {mix_key} AS item_id
                {UNIVERSE_FROM}
                WHERE f.Data >= ? AND f.Data < ?
{where.sql}                GROUP BY {key}, {mix_key}, f.Data
                HAVING SUM({FAT_RS}) > 0
            ) x
            GROUP BY entidade_id
        )
        SELECT m.entidade_id,
               MAX(m.entidade) AS entidade,
               CASE WHEN MIN(m.uf_min) = MAX(m.uf_max) THEN MIN(m.uf_min) ELSE 'Várias' END AS uf,
               MAX(m.segmento) AS segmento,
               SUM(CASE WHEN m.fat_rs > 0 THEN 1 ELSE 0 END) AS meses_com_compra,
               SUM(CASE WHEN m.Data < ? THEN m.fat_kg ELSE 0 END) AS kg_semestre_1,
               SUM(CASE WHEN m.Data >= ? THEN m.fat_kg ELSE 0 END) AS kg_semestre_2,
               SUM(m.fat_rs) AS fat_rs,
               SUM(m.fat_kg) AS fat_kg,
               MAX(i.mix) AS mix
        FROM mensal m
        LEFT JOIN itens i ON i.entidade_id = m.entidade_id
        GROUP BY m.entidade_id
        HAVING SUM(CASE WHEN m.fat_rs > 0 THEN 1 ELSE 0 END) * 1.0 / ? > 0.70
    """
    params = [
        start,
        end_exclusive,
        *where.params,
        start,
        end_exclusive,
        *where.params,
        second_half,
        second_half,
        window,
    ]
    return sql, params


def shape(rows: list[dict[str, Any]], window: int, top_n: int) -> tuple[dict[str, Any], int]:
    half = window // 2
    candidates = []
    for row in rows:
        criteria = growth_criteria(
            int(row["meses_com_compra"] or 0),
            window,
            int(row["mix"] or 0),
            float(row["kg_semestre_1"] or 0),
            float(row["kg_semestre_2"] or 0),
            half,
        )
        if not criteria["candidato"]:
            continue
        candidates.append(
            {
                "entidade_id": row["entidade_id"],
                "entidade": row["entidade"],
                "uf": row["uf"],
                "segmento": row["segmento"],
                "fat_rs": metric_round("fat_rs", float(row["fat_rs"] or 0)),
                "fat_kg": metric_round("fat_kg", float(row["fat_kg"] or 0)),
                "meses_com_compra": int(row["meses_com_compra"] or 0),
                "frequencia": criteria["frequencia"],
                "mix": int(row["mix"] or 0),
                "media_kg_semestre_1": metric_round("fat_kg", criteria["media_kg_semestre_1"]),
                "media_kg_semestre_2": metric_round("fat_kg", criteria["media_kg_semestre_2"]),
                "crescimento_pct": criteria["crescimento_pct"],
            }
        )
    candidates.sort(
        key=lambda line: (
            -(line["crescimento_pct"] or 0),
            -line["frequencia"],
            -line["mix"],
            str(line["entidade_id"]),
        )
    )
    for position, line in enumerate(candidates, start=1):
        line["posicao"] = position
    header = [
        column("posicao", "Posição descritiva"),
        column("entidade_id", "Código"),
        column("entidade", "Cliente / rede"),
        column("uf", "UF"),
        column("segmento", "Segmento"),
        column("fat_rs", "FAT R$ 12 meses", "R$"),
        column("fat_kg", "FAT KG 12 meses", "KG"),
        column("meses_com_compra", "Meses com compra"),
        column("frequencia", "Frequência", "%"),
        column("mix", "Itens distintos comprados"),
        column("media_kg_semestre_1", "Média KG 1º semestre", "KG"),
        column("media_kg_semestre_2", "Média KG 2º semestre", "KG"),
        column("crescimento_pct", "Crescimento entre semestres", "%"),
    ]
    return {"colunas": header, "linhas": candidates[:top_n]}, len(candidates)


class GrowthCandidates:
    operation_id = "OP19"

    def run(self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope) -> OperationResult:
        last_closed = last_closed_month(fetcher)
        anchor = closed_anchor(values.get("competencia_referencia"), last_closed)
        if anchor is None:
            return OperationResult.clarification(
                "Qual período você quer analisar? Informe o mês e o ano."
            )
        window = values.get("janela_meses") or 12
        months, start, end_exclusive = window_months(anchor, window)
        second_half = months[window // 2]

        product, question = resolve_product(fetcher, values)
        if question:
            return question
        granularity = values.get("granularidade_cliente") or "rede"
        entity = CLIENT_ENTITIES.get(granularity, CLIENT_ENTITIES["rede"])
        mix_key = MIX_LEVELS.get(values.get("nivel_mix") or "sku", MIX_LEVELS["sku"])
        sql, params = build_query(
            values, scope, start, end_exclusive, second_half, window, entity, mix_key, product
        )
        rows = fetcher.fetch(sql, tuple(params))
        top_n = values.get("top_n") or 20
        main_block, total = shape(rows, window, top_n)

        notices: list[Notice] = [
            Notice(
                "OP19_LEITURA",
                "operacao",
                f"Candidatos heurísticos a crescimento, por {entity[2]}, em {window} competências "
                f"({month_text(months[0])} a {month_text(months[-1])}): compra em mais de 70% dos meses, "
                "mais de um item no mix e média de KG do 2º semestre maior que a do 1º. Não é score nem "
                "potencial comprovado: a base não tem share, porte ou estoque do cliente.",
            ),
            open_rule_notice(
                "a fórmula da tendência (média do 2º semestre contra a do 1º) é proposta técnica, e o "
                "nível oficial do mix ainda não foi validado com clientes conhecidos pela área comercial."
            ),
            Notice(
                "OP19_TOTAL",
                "resposta",
                f"{total} candidato(s) atendem aos três critérios; exibindo até {top_n}.",
            ),
        ]
        if start < HISTORY_START:
            notices.append(
                history_notice("A base começa em janeiro de 2025: parte da janela não tem dado.")
            )
        return OperationResult(
            period=build_period(start, end_exclusive, last_closed),
            main_block=main_block,
            notices=notices,
        )
