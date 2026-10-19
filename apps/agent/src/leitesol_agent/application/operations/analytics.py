"""Cálculos e peças compartilhadas pelas operações OP02-OP10, OP15, OP16 e OP19-OP22.

Tudo o que classifica (média, curva ABC, frequência, ticket, índice sazonal,
critérios de potencial, giro) é função pura: recebe números, devolve números
ou rótulos. O SQL de cada operação só agrega; a regra de negócio fica aqui,
coberta por teste unitário sem banco.

Regra ainda não homologada com a área comercial não some nem vira certeza:
a operação que a usa anexa `open_rule_notice`, com o código REGRA_EM_ABERTO,
dizendo o que falta fechar. Valor líquido negativo (devolução maior que
venda) recebe `negative_notice` enquanto a P-NEGATIVO estiver aberta.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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
    as_date,
    product_filter,
    product_question,
    round_kg,
    round_money,
    universe_where,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Period, Scope

OPEN_RULE = "REGRA_EM_ABERTO"

# nivel_produto do catálogo (já em minúsculas pela validação) -> (chave, rótulo).
# "subgrupo" não tem nível na árvore comercial (subtotal -> grupamento ->
# família) e vira pergunta, como na OP11.
PRODUCT_LEVELS: dict[str, tuple[str, str]] = {
    "sku": ("p.ProdutoId", "MAX(p.Produto)"),
    "familia": ("p.Familia", "MAX(p.Familia)"),
    "grupo": ("p.Grupamento", "MAX(p.Grupamento)"),
}
# granularidade_cliente -> (chave, rótulo, texto da visão). Rede = agrupamento
# do Power BI (GRUPO_AJUSTADO_2), padrão como no ranking (D-A63).
CLIENT_ENTITIES: dict[str, tuple[str, str, str]] = {
    "cliente_loja": ("c.ClienteId", "MAX(c.RazaoSocial)", "cliente + loja"),
    "cnpj": ("c.CNPJ", "MAX(c.RazaoSocial)", "CNPJ"),
    "rede": ("c.Rede", "MAX(c.RedeNome)", "rede (agrupamento do Power BI)"),
}
SUBGROUP_QUESTION = (
    "A árvore comercial tem três níveis: subtotal, grupamento e família. "
    "Quer a análise por produto (SKU), por família ou por grupamento?"
)


# ---------------------------------------------------------------------------
# Avisos
# ---------------------------------------------------------------------------


def open_rule_notice(detail: str) -> Notice:
    """Ressalva de regra ainda não fechada por completo com a área comercial."""
    return Notice(
        OPEN_RULE,
        "regra_pendente",
        "Regra ainda não fechada por completo com a área comercial: "
        f"{detail} O resultado é informativo até a homologação.",
    )


def negative_notice(count: int) -> Notice:
    return Notice(
        "VALOR_NEGATIVO",
        "regra_pendente",
        f"{count} item(ns) com valor líquido negativo (devolução maior que venda) no período. "
        "O tratamento de negativos nesta análise ainda não foi homologado com a área comercial.",
    )


def partial_notice(
    text: str = "O mês analisado ainda não fechou: o valor dele é parcial.",
) -> Notice:
    return Notice("TR02", "regra_tempo", text)


def history_notice(text: str) -> Notice:
    return Notice("BASE2025", "base_historica", text)


def limit_notice(shown: int, total: int, noun: str = "linhas") -> Notice:
    return Notice("LIMITE", "resposta", f"Exibindo {shown} de {total} {noun}.")


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def months_between(start: date, end: date) -> int:
    """Competências de `start` até `end` (end - start, em meses)."""
    return (end.year - start.year) * 12 + end.month - start.month


def month_range(start: date, end_exclusive: date) -> list[date]:
    months: list[date] = []
    current = month_start(start)
    while current < end_exclusive:
        months.append(current)
        current = add_months(current, 1)
    return months


def reference_month(requested: date | None, last_closed: date | None) -> date | None:
    """Competência pedida ou, sem pedido, a última fechada (TR01)."""
    if requested is not None:
        return month_start(requested)
    return month_start(last_closed) if last_closed else None


def closed_anchor(requested: date | None, last_closed: date | None) -> date | None:
    """Última competência de uma janela de meses fechados, nunca além da última fechada."""
    if last_closed is None:
        return None
    anchor = month_start(requested) if requested else month_start(last_closed)
    return min(anchor, month_start(last_closed))


def month_text(value: date | None) -> str | None:
    return value.strftime("%Y-%m") if value else None


# ---------------------------------------------------------------------------
# Comparações
# ---------------------------------------------------------------------------


def variation_pct(current: float, reference: float) -> float | None:
    """Variação percentual; referência zero não gera percentual (RT24)."""
    if not reference:
        return None
    return round((current - reference) / abs(reference) * 100, 2)


def compare_literal(current: float, reference: float) -> str:
    """Igualdade literal, sem tolerância: acima, igual ou abaixo."""
    if current > reference:
        return "acima"
    if current < reference:
        return "abaixo"
    return "igual"


def direction(current: float, reference: float) -> str:
    """Rótulo de variação para comparações contra o ano anterior."""
    return {"acima": "crescimento", "abaixo": "queda", "igual": "igual"}[
        compare_literal(current, reference)
    ]


def average(total: float, months: int) -> float:
    """Média com denominador FIXO: mês sem movimento conta como zero."""
    return total / months if months else 0.0


def product_trend_status(reference: float, mean: float) -> str:
    """OP04: status do produto no mês de referência contra a própria média."""
    if mean == 0 and reference == 0:
        return "Sem movimento"
    if mean == 0:
        return "Movimento atual sem base histórica"
    if reference > mean:
        return "Crescimento"
    if reference < mean:
        return "Queda"
    return "Estabilidade"


TREND_ORDER = {
    "Queda": 0,
    "Crescimento": 1,
    "Estabilidade": 2,
    "Movimento atual sem base histórica": 3,
    "Sem movimento": 4,
}


# ---------------------------------------------------------------------------
# Curva ABC (OP05)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AbcLine:
    item_id: str
    value: float
    share: float | None = None
    cumulative: float | None = None
    abc_class: str = "sem_participacao"


def abc_curve(items: Iterable[tuple[str, float]]) -> tuple[list[AbcLine], float]:
    """Curva ABC como no Power BI (AIC-285, D-A60, D-A62).

    Ordena por valor decrescente (desempate pelo código); participação sobre o
    total LÍQUIDO; a classe sai do acumulado ANTERIOR ao item (< 80% A, < 95%
    B, resto C), então quem cruza o limite fica na classe de cima. Zero fica
    fora da ordenação contributiva ("sem_participacao"); negativo vai para o
    fim, em C, e reduz o total. Total <= 0: não divide, ninguém é classificado.
    """
    lines = [AbcLine(item_id, float(value)) for item_id, value in items]
    total = sum(line.value for line in lines)
    contributing = [line for line in lines if line.value != 0]
    contributing.sort(key=lambda line: (-line.value, line.item_id))
    zeros = sorted((line for line in lines if line.value == 0), key=lambda line: line.item_id)
    if total <= 0:
        for line in contributing:
            line.abc_class = "sem_base"
        return [*contributing, *zeros], total

    running = 0.0
    for line in contributing:
        before = running / total * 100
        running += line.value
        line.share = round(line.value / total * 100, 2)
        line.cumulative = round(running / total * 100, 2)
        if line.value < 0:
            line.abc_class = "C"
        elif before < 80:
            line.abc_class = "A"
        elif before < 95:
            line.abc_class = "B"
        else:
            line.abc_class = "C"
    for line in zeros:
        line.share = 0.0
    return [*contributing, *zeros], total


# ---------------------------------------------------------------------------
# Frequência e recência (OP06)
# ---------------------------------------------------------------------------


def frequency_class(months_with_purchase: int) -> str:
    """Faixas do Power BI (ClassificacaoCliente, AIC-286, D-A60)."""
    if months_with_purchase >= 9:
        return "Mensal"
    if months_with_purchase >= 6:
        return "Bimestral"
    if months_with_purchase >= 4:
        return "Trimestral"
    if months_with_purchase >= 2:
        return "Semestral"
    return "Ocasional"


def recency(last_purchase: date | None, reference: date) -> int | None:
    """Competências completas entre a última compra e a competência de referência."""
    if last_purchase is None:
        return None
    return months_between(month_start(last_purchase), month_start(reference))


# ---------------------------------------------------------------------------
# Ticket médio (OP07)
# ---------------------------------------------------------------------------

TICKET_TOLERANCE_PCT = 2.0


def ticket(fat_rs: float, fat_kg: float) -> float | None:
    """R$/kg com os componentes somados antes da divisão; KG <= 0 não divide."""
    if fat_kg <= 0:
        return None
    return round(fat_rs / fat_kg, 4)


def classify_ticket(current: float | None, previous: float | None) -> tuple[float | None, str]:
    """Variação e classe pela tolerância de ±2% com os limites dentro da faixa estável."""
    if current is None or previous is None or previous == 0:
        return None, "nao_calculavel"
    change = round((current - previous) / previous * 100, 2)
    if change < -TICKET_TOLERANCE_PCT:
        return change, "queda"
    if change > TICKET_TOLERANCE_PCT:
        return change, "ascensao"
    return change, "estavel"


def split_halves(months: Sequence[date]) -> tuple[list[date], list[date]]:
    """Duas metades cronológicas; mês excedente vai para a SEGUNDA metade."""
    cut = len(months) // 2
    return list(months[:cut]), list(months[cut:])


# ---------------------------------------------------------------------------
# Sazonalidade (OP08)
# ---------------------------------------------------------------------------


def coverage_label(months_observed: int) -> str:
    if months_observed < 12:
        return "historico_insuficiente"
    if months_observed < 24:
        return "perfil_descritivo"
    if months_observed < 36:
        return "indicio_sazonal"
    return "indice_sazonal_consolidado"


@dataclass(slots=True)
class SeasonalProfile:
    by_month: dict[int, dict[str, Any]] = field(default_factory=dict)
    complete_years: list[int] = field(default_factory=list)
    years_without_base: list[int] = field(default_factory=list)


def seasonal_profile(
    series: dict[date, tuple[float, float]], max_years: int = 3
) -> SeasonalProfile:
    """Índice sazonal em duas etapas (07-08).

    1) índice do mês no ano = FAT R$ do mês / média mensal do PRÓPRIO ano;
    2) índice sazonal = média dos índices daquele mês entre os anos completos
       (12 competências), limitados aos `max_years` mais recentes.
    Sem ano completo, o índice fica None e a tabela mostra a média descritiva
    do mês (R$ e KG) sobre o que existe. KG nunca entra no índice de R$.
    """
    years: dict[int, dict[int, tuple[float, float]]] = {}
    for month, values in series.items():
        years.setdefault(month.year, {})[month.month] = values
    complete = sorted(year for year, months in years.items() if len(months) == 12)
    complete = complete[-max_years:]

    profile = SeasonalProfile(complete_years=complete)
    indexes: dict[int, list[float]] = {month: [] for month in range(1, 13)}
    for year in complete:
        yearly_mean = sum(values[0] for values in years[year].values()) / 12
        if yearly_mean == 0:
            profile.years_without_base.append(year)
            continue
        for month, values in years[year].items():
            indexes[month].append(values[0] / yearly_mean)

    for month in range(1, 13):
        observed = [values for key, values in series.items() if key.month == month]
        rs_mean = sum(values[0] for values in observed) / len(observed) if observed else None
        kg_mean = sum(values[1] for values in observed) / len(observed) if observed else None
        index = round(sum(indexes[month]) / len(indexes[month]), 4) if indexes[month] else None
        profile.by_month[month] = {
            "indice": index,
            "competencias": len(observed),
            "media_fat_rs": rs_mean,
            "media_fat_kg": kg_mean,
        }
    return profile


# ---------------------------------------------------------------------------
# Potencial de crescimento (OP19)
# ---------------------------------------------------------------------------

FREQUENCY_THRESHOLD = 0.70


def growth_criteria(
    months_with_purchase: int,
    window: int,
    distinct_mix: int,
    first_half_kg: float,
    second_half_kg: float,
    half: int,
) -> dict[str, Any]:
    """Os três critérios cumulativos da OP19 (frequência, mix, tendência em KG)."""
    frequency = months_with_purchase / window if window else 0.0
    first_mean = first_half_kg / half if half else 0.0
    second_mean = second_half_kg / half if half else 0.0
    growth = variation_pct(second_mean, first_mean)
    meets_frequency = frequency > FREQUENCY_THRESHOLD
    meets_mix = distinct_mix > 1
    meets_trend = second_mean > first_mean
    return {
        "frequencia": round(frequency * 100, 2),
        "media_kg_semestre_1": first_mean,
        "media_kg_semestre_2": second_mean,
        "crescimento_pct": growth,
        "criterio_frequencia": meets_frequency,
        "criterio_mix": meets_mix,
        "criterio_tendencia": meets_trend,
        "candidato": meets_frequency and meets_mix and meets_trend,
    }


# ---------------------------------------------------------------------------
# Baixo giro (OP21)
# ---------------------------------------------------------------------------


def turnover_status(
    month_current: float,
    month_previous: float,
    accumulated_current: float,
    accumulated_previous: float,
    is_new: bool,
) -> str:
    """Baixo giro só com queda nas DUAS comparações; uma só = resultado misto."""
    if is_new:
        return "novo/sem historico suficiente"
    month_fall = month_current < month_previous
    accumulated_fall = accumulated_current < accumulated_previous
    if month_fall and accumulated_fall:
        return "baixo_giro"
    if month_fall or accumulated_fall:
        return "resultado_misto"
    return "sem_queda"


# ---------------------------------------------------------------------------
# Séries mensais
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Series:
    """Uma entidade (cliente, produto, região...) com a série mensal R$ e KG."""

    key: tuple[Any, ...]
    labels: dict[str, Any] = field(default_factory=dict)
    months: dict[date, tuple[float, float]] = field(default_factory=dict)

    def value(self, month: date, metric: str) -> float:
        rs, kg = self.months.get(month, (0.0, 0.0))
        return rs if metric == "fat_rs" else kg

    def total(self, months: Iterable[date], metric: str) -> float:
        return sum(self.value(month, metric) for month in months)

    def purchase_months(self, months: Iterable[date]) -> list[date]:
        """Competências com compra válida (FAT R$ > 0 no mês)."""
        return [month for month in months if self.value(month, "fat_rs") > 0]


def monthly_query(
    values: dict[str, Any],
    scope: Scope,
    start: date,
    end_exclusive: date,
    keys: Sequence[tuple[str, str]],
    labels: Sequence[tuple[str, str]] = (),
    product: tuple[str, list[Any]] | None = None,
    extra: Sequence[tuple[str, list[Any]]] = (),
    joins: str = "",
) -> tuple[str, list[Any]]:
    """SQL de FAT R$ e FAT KG por chave e competência, no universo comum."""
    where = universe_where(values, scope, product)
    for clause, params in extra:
        where.add(clause, *params)
    key_select = "".join(f"{expr} AS {alias}, " for expr, alias in keys)
    label_select = "".join(f"{expr} AS {alias}, " for expr, alias in labels)
    group = "".join(f"{expr}, " for expr, _ in keys)
    sql = f"""
        SELECT {key_select}{label_select}f.Data AS competencia,
               SUM({FAT_RS}) AS fat_rs,
               SUM({FAT_KG}) AS fat_kg
        {UNIVERSE_FROM}
        {joins}
        WHERE f.Data >= ? AND f.Data < ?
{where.sql}        GROUP BY {group}f.Data
    """
    return sql, [start, end_exclusive, *where.params]


def pivot(
    rows: Iterable[dict[str, Any]],
    key_aliases: Sequence[str],
    label_aliases: Sequence[str] = (),
) -> dict[tuple[Any, ...], Series]:
    """Linhas (chave, competência, R$, KG) -> uma Series por chave."""
    result: dict[tuple[Any, ...], Series] = {}
    for row in rows:
        key = tuple(row[alias] for alias in key_aliases)
        series = result.get(key)
        if series is None:
            series = Series(key, {alias: row.get(alias) for alias in label_aliases})
            result[key] = series
        month = month_start(as_date(row["competencia"]))
        rs, kg = series.months.get(month, (0.0, 0.0))
        series.months[month] = (
            rs + float(row["fat_rs"] or 0),
            kg + float(row["fat_kg"] or 0),
        )
    return result


def resolve_product(
    fetcher: SqlFetcher, values: dict[str, Any], names: Sequence[str] = ("filtro_produto",)
) -> tuple[tuple[str, list[Any]] | None, OperationResult | None]:
    """Combina os filtros de produto presentes (RT35); termo desconhecido vira pergunta."""
    clauses: list[str] = []
    params: list[Any] = []
    for name in names:
        text = values.get(name)
        if not text:
            continue
        resolved = product_filter(fetcher, text)
        if resolved is None:
            return None, OperationResult.clarification(product_question(text))
        clauses.append(resolved[0])
        params.extend(resolved[1])
    if not clauses:
        return None, None
    return (" AND ".join(clauses), params), None


def product_level(values: dict[str, Any]) -> tuple[tuple[str, str] | None, OperationResult | None]:
    level = values.get("nivel_produto") or "sku"
    if level not in PRODUCT_LEVELS:
        return None, OperationResult.clarification(SUBGROUP_QUESTION)
    return PRODUCT_LEVELS[level], None


def window_months(anchor: date, count: int) -> tuple[list[date], date, date]:
    """`count` competências terminando em `anchor`: (meses, início, fim exclusivo)."""
    months = months_back(anchor, count)
    return months, months[0], month_end_exclusive(months[-1])


def metric_round(metric: str, value: float) -> float | int:
    if metric == "fat_rs":
        return round_money(value)
    if metric == "fat_tons":
        return round(value / 1000, 3)
    return round_kg(value)


def metrics_for(choice: str | None, default: str = "ambas") -> list[str]:
    """Métricas exibidas: 'ambas' = R$ e KG separados; tons deriva do KG."""
    choice = choice or default
    if choice == "ambas":
        return ["fat_rs", "fat_kg"]
    return [choice]


def source_metric(metric: str) -> str:
    """fat_tons é KG / 1000: a série guardada é a de KG."""
    return "fat_kg" if metric == "fat_tons" else metric


def column(column_id: str, label: str, unit: str | None = None) -> dict[str, Any]:
    return {"id": column_id, "rotulo": label, "unidade": unit}


def build_period(
    start: date,
    end_exclusive: date,
    last_closed_value: date | None,
    comparison: tuple[date, date] | None = None,
    partial: bool = False,
) -> Period:
    return Period(
        start=start,
        end_exclusive=end_exclusive,
        comparison_start=comparison[0] if comparison else None,
        comparison_end_exclusive=comparison[1] if comparison else None,
        partial=partial,
        last_closed_month=month_text(last_closed_value),
    )


def commercial_filter(values: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """filtros_comerciais: código ou nome de vendedor ou de gestor (sempre dentro da alçada)."""
    text = (values.get("filtros_comerciais") or "").strip()
    if not text:
        return []
    upper = text.upper()
    return [
        (
            "(c.RCAAtual = ? OR UPPER(r.Representante) = ? OR r.GestorId = ? OR UPPER(r.Gestor) = ?)",
            [text, upper, text, upper],
        )
    ]
