"""Resolve o NOME de cliente ou rede digitado na pergunta para o código da rede.

O filtro de cliente (common.client_filter) acha código, CNPJ e rede, mas por
nome só casava a descrição EXATA do grupo de venda. Na conferência de 19-10
(sql/45) isso deixou sem resposta quatro dos sete nomes usados no Power BI:
"G Barbosa" (grupo "G BARBOSA /CENCOSUD") e Granfood, Megatop e Atacado
Ideal, que não têm grupo de venda - a rede deles é a raiz do CNPJ.

Ordem da busca, sempre dentro da carteira do usuário (RT34):
1. nome igual à descrição do grupo de venda;
2. nome igual ao nome da rede (RedeNome = DESCR NOME AJUST do Power BI);
3. trecho do nome na rede, na razão social ou no nome fantasia.
Uma rede só -> o valor do parâmetro vira "rede:<código>" (o client_filter
filtra só pela rede, sem confundir com código de cliente) e a resposta avisa
como o nome foi entendido. Várias -> pergunta qual, sem escolher sozinho
(RT07). Nenhuma -> pergunta outra forma de identificar o cliente.

Texto sem letra (código, CNPJ) não passa por aqui: segue para o client_filter.
"""

from dataclasses import dataclass, field
from typing import Any

from leitesol_agent.application.operations.base import SqlFetcher, normalize_term
from leitesol_agent.application.operations.common import REDE_PREFIX
from leitesol_agent.domain.models import Notice, Scope

# Parâmetros do catálogo que identificam cliente ou rede.
CLIENT_KEYS = ("cliente_rede", "escopo_cliente", "cliente_loja")
MAX_OPTIONS = 8

EXACT_SQL = """
    SELECT c.Rede AS rede,
           MAX(c.RedeNome) AS nome,
           COUNT(*) AS lojas,
           MAX(CASE WHEN UPPER(c.GrupoVendaDescricao) = ? THEN 1 ELSE 0 END) AS grupo_exato
    FROM [IA_COMERCIAL].[vw_dim_cliente] c
    WHERE c.FlagExterior = 0
      AND (UPPER(c.GrupoVendaDescricao) = ? OR UPPER(c.RedeNome) = ?)
{scope}    GROUP BY c.Rede
"""
PARTIAL_SQL = """
    SELECT c.Rede AS rede,
           MAX(c.RedeNome) AS nome,
           COUNT(*) AS lojas
    FROM [IA_COMERCIAL].[vw_dim_cliente] c
    WHERE c.FlagExterior = 0
      AND (UPPER(c.RedeNome) LIKE ? ESCAPE '\\'
           OR UPPER(c.RazaoSocial) LIKE ? ESCAPE '\\'
           OR UPPER(c.NomeFantasia) LIKE ? ESCAPE '\\')
{scope}    GROUP BY c.Rede
"""


@dataclass(slots=True)
class ClientResolution:
    notices: list[Notice] = field(default_factory=list)
    question: str | None = None


def is_name(text: Any) -> bool:
    return isinstance(text, str) and any(char.isalpha() for char in text)


def _scope_clause(scope: Scope) -> tuple[str, list[Any]]:
    if scope.sees_everything:
        return "", []
    sellers = sorted(scope.sellers)
    return f"      AND c.RCAAtual IN ({', '.join('?' for _ in sellers)})\n", sellers


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")
    return f"%{escaped}%"


def _label(row: dict[str, Any]) -> str:
    name = str(row["nome"] or "").strip() or "sem nome"
    return f"{name} (rede {str(row['rede']).strip()}, {int(row['lojas'] or 0)} loja(s))"


def _options_question(text: str, rows: list[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: (-int(row["lojas"] or 0), str(row["rede"])))
    shown = "; ".join(_label(row) for row in ordered[:MAX_OPTIONS])
    more = f" e mais {len(ordered) - MAX_OPTIONS}" if len(ordered) > MAX_OPTIONS else ""
    return (
        f'Encontrei mais de um cliente para "{text}": {shown}{more}. '
        "Qual deles? Pode responder com o código da rede."
    )


def resolve_name(
    fetcher: SqlFetcher, text: str, scope: Scope
) -> tuple[dict[str, Any] | None, str | None]:
    """(rede encontrada, None) ou (None, pergunta ao usuário)."""
    term = normalize_term(text)
    scope_sql, scope_params = _scope_clause(scope)

    exact = fetcher.fetch(EXACT_SQL.format(scope=scope_sql), (term, term, term, *scope_params))
    by_group = [row for row in exact if row.get("grupo_exato")]
    for candidates in (by_group, exact):
        if len(candidates) == 1:
            return candidates[0], None
        if len(candidates) > 1:
            return None, _options_question(text, candidates)

    pattern = _like(term)
    partial = fetcher.fetch(
        PARTIAL_SQL.format(scope=scope_sql), (pattern, pattern, pattern, *scope_params)
    )
    if len(partial) == 1:
        return partial[0], None
    if partial:
        return None, _options_question(text, partial)
    return None, (
        f'Não encontrei o cliente ou a rede "{text}" na sua carteira. '
        "Pode informar o código do cliente, o CNPJ ou outro nome?"
    )


def resolve_client_names(
    fetcher: SqlFetcher, values: dict[str, Any], scope: Scope
) -> ClientResolution:
    """Troca, em `values`, o nome de cliente/rede pelo código da rede encontrada."""
    resolution = ClientResolution()
    for key in CLIENT_KEYS:
        text = values.get(key)
        if not is_name(text):
            continue
        found, question = resolve_name(fetcher, text, scope)
        if question:
            resolution.question = question
            return resolution
        values[key] = REDE_PREFIX + str(found["rede"]).strip()
        resolution.notices.append(
            Notice(
                "CLIENTE_RESOLVIDO",
                "parametro",
                f'"{text}" foi entendido como {_label(found)}. Se não for esse, informe o código do cliente.',
            )
        )
    return resolution
