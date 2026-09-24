"""Peças comuns às operações: universo, filtros, produto, calendário e métricas.

Toda operação de faturamento parte do mesmo universo - fato + produto +
cliente, só Produto Acabado (RT13), sem cadastro de exterior (RT14) e dentro
da carteira do usuário (RT34) - e aceita os mesmos filtros opcionais. Manter
isso num lugar só garante que duas operações nunca respondam sobre universos
diferentes para a mesma pergunta.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from leitesol_api.application.operations.base import SqlFetcher, normalize_term
from leitesol_api.domain.agent import Scope

# Início da base histórica da vw_fato_faturamento (Data >= 2025-01-01).
HISTORY_START = date(2025, 1, 1)

FAT_RS = "f.Vendas_R - f.Dev_R"
FAT_KG = "f.Vendas_Kg + f.Bonif_Kg - f.Dev_Kg"

UNIVERSE_FROM = """
    FROM [IA_COMERCIAL].[vw_fato_faturamento] f
    JOIN [IA_COMERCIAL].[vw_dim_produto] p ON p.ProdutoId = f.ProdutoId
    JOIN [IA_COMERCIAL].[vw_dim_cliente] c ON c.ClienteId = f.ClienteId
    LEFT JOIN [IA_COMERCIAL].[vw_dim_representante] r ON r.RepresentanteId = f.VendedorId
"""

METRICS = {
    "fat_rs": ("FAT R$", "R$"),
    "fat_kg": ("FAT KG", "KG"),
    "fat_tons": ("FAT TONS", "t"),
}

LAST_CLOSED_SQL = """
    SELECT MAX(CASE WHEN MesFechado = 1 THEN Data END) AS UltimaFechada
    FROM [IA_COMERCIAL].[vw_dim_calendario]
"""

OPEN_MONTHS_SQL = """
    SELECT MAX(CASE WHEN MesFechado = 0 THEN 1 ELSE 0 END) AS TemParcial
    FROM [IA_COMERCIAL].[vw_dim_calendario]
    WHERE Data >= ? AND Data < ?
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
class Where:
    """Cláusulas AND e seus parâmetros, na ordem em que aparecem no SQL."""

    clauses: list[str] = field(default_factory=list)
    params: list[Any] = field(default_factory=list)

    def add(self, clause: str, *params: Any) -> None:
        self.clauses.append(clause)
        self.params.extend(params)

    @property
    def sql(self) -> str:
        return "".join(f"  AND {clause}\n" for clause in self.clauses)


def round_money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_kg(value: float) -> int:
    # RT16: KG sem casas decimais, 0,5 sobe - para bater com o painel.
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def metric_value(name: str, fat_rs: float, fat_kg: float) -> float | int:
    if name == "fat_rs":
        return round_money(fat_rs)
    if name == "fat_kg":
        return round_kg(fat_kg)
    return round(fat_kg / 1000, 3)


def month_label(value: date) -> str:
    return value.strftime("%Y-%m")


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


def product_question(text: str) -> str:
    return (
        f'Não reconheci "{text}" como produto, família ou termo de produto cadastrado. '
        "Pode indicar o produto de outra forma?"
    )


def universe_where(
    values: dict[str, Any],
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> Where:
    """Universo comum + filtros opcionais presentes em `values`."""
    where = Where()
    where.add("p.FlagProdutoAcabado = 1")
    where.add("c.FlagExterior = 0")
    if not scope.sees_everything:
        sellers = sorted(scope.sellers)
        where.add(f"f.VendedorId IN ({', '.join('?' for _ in sellers)})", *sellers)

    if values.get("uf"):
        where.add("c.UF = ?", values["uf"].strip().upper())
    if values.get("municipio"):
        where.add("UPPER(c.Municipio) = ?", normalize_term(values["municipio"]))
    if values.get("segmento"):
        where.add(
            "(c.SegmentoCodigo = ? OR UPPER(c.SegmentoDescricao) = ?)",
            values["segmento"].strip(),
            normalize_term(values["segmento"]),
        )
    if values.get("vendedor_rca"):
        where.add(
            "(f.VendedorId = ? OR UPPER(r.Representante) = ?)",
            values["vendedor_rca"].strip(),
            normalize_term(values["vendedor_rca"]),
        )
    if values.get("cliente_rede"):
        clause, params = client_filter(values["cliente_rede"])
        where.add(clause, *params)
    if values.get("cliente_loja"):
        value = values["cliente_loja"].strip()
        where.add("(c.ClienteId = ? OR c.ClienteCodigo = ?)", value, value)
    if values.get("rede_id"):
        value = values["rede_id"].strip()
        where.add("(c.Rede = ? OR c.GrupoVendaCodigo = ?)", value, value)
    if product:
        where.add(product[0], *product[1])
    return where


def as_date(value: Any) -> date:
    """Data vinda do driver (date, datetime ou texto ISO, conforme o caminho)."""
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return value if type(value) is date else value.date()


def last_closed_month(fetcher: SqlFetcher) -> date | None:
    rows = fetcher.fetch(LAST_CLOSED_SQL)
    value = rows[0]["UltimaFechada"] if rows else None
    return as_date(value) if value is not None else None


def has_open_month(fetcher: SqlFetcher, start: date, end_exclusive: date) -> bool:
    rows = fetcher.fetch(OPEN_MONTHS_SQL, (start, end_exclusive))
    return bool(rows and rows[0]["TemParcial"])
