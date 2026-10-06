"""Validação e compilação de filtros WHERE sobre campos conhecidos das views."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from leitesol_agent.application.operations.base import normalize_term

FilterKind = Literal["text", "number", "boolean"]


@dataclass(frozen=True, slots=True)
class FilterField:
    key: str
    view: str
    label: str
    expression: str
    kind: FilterKind = "text"


@dataclass(frozen=True, slots=True)
class WhereFilter:
    field: str
    operator: str
    value: str | Decimal | bool | tuple[str | Decimal | bool, ...] | None


FILTER_FIELDS: dict[str, FilterField] = {
    field.key: field
    for field in (
        FilterField(
            "fato.vendedor_id", "vw_fato_faturamento", "código do vendedor da venda", "f.VendedorId"
        ),
        FilterField("fato.uf_venda", "vw_fato_faturamento", "UF registrada na venda", "f.UFVenda"),
        FilterField("cliente.id", "vw_dim_cliente", "código do cliente/loja", "c.ClienteId"),
        FilterField(
            "cliente.codigo", "vw_dim_cliente", "código comercial do cliente", "c.ClienteCodigo"
        ),
        FilterField("cliente.loja", "vw_dim_cliente", "loja do cliente", "c.Loja"),
        FilterField("cliente.nome", "vw_dim_cliente", "razão social do cliente", "c.RazaoSocial"),
        FilterField("cliente.cnpj", "vw_dim_cliente", "CNPJ do cliente", "c.CNPJ"),
        FilterField("cliente.cnpj_raiz", "vw_dim_cliente", "raiz do CNPJ", "c.CNPJRaiz"),
        FilterField("cliente.rede_id", "vw_dim_cliente", "código da rede", "c.Rede"),
        FilterField("cliente.rede", "vw_dim_cliente", "nome da rede", "c.RedeNome"),
        FilterField("cliente.uf", "vw_dim_cliente", "UF do cadastro do cliente", "c.UF"),
        FilterField(
            "cliente.regiao", "vw_dim_cliente", "região do cadastro do cliente", "c.Regiao"
        ),
        FilterField(
            "cliente.municipio", "vw_dim_cliente", "município do cadastro do cliente", "c.Municipio"
        ),
        FilterField(
            "cliente.segmento_codigo", "vw_dim_cliente", "código do segmento", "c.SegmentoCodigo"
        ),
        FilterField(
            "cliente.segmento", "vw_dim_cliente", "descrição do segmento", "c.SegmentoDescricao"
        ),
        FilterField(
            "cliente.rca_atual", "vw_dim_cliente", "responsável atual pela carteira", "c.RCAAtual"
        ),
        FilterField(
            "cliente.ativo", "vw_dim_cliente", "situação cadastral do cliente", "c.ClienteAtivo"
        ),
        FilterField("produto.id", "vw_dim_produto", "código do produto", "p.ProdutoId"),
        FilterField("produto.nome", "vw_dim_produto", "nome do produto", "p.Produto"),
        FilterField(
            "produto.subtotal", "vw_dim_produto", "subtotal da árvore comercial", "p.Subtotal"
        ),
        FilterField(
            "produto.grupamento", "vw_dim_produto", "grupamento da árvore comercial", "p.Grupamento"
        ),
        FilterField(
            "produto.familia", "vw_dim_produto", "família da árvore comercial", "p.Familia"
        ),
        FilterField("produto.marca", "vw_dim_produto", "marca do produto", "p.Marca"),
        FilterField("produto.embalagem", "vw_dim_produto", "tipo de embalagem", "p.TipoEmbalagem"),
        FilterField(
            "produto.peso_volume_unitario",
            "vw_dim_produto",
            "peso/volume unitário do produto",
            "p.PesoVolumeUnitario",
            "number",
        ),
        FilterField(
            "vendedor.id", "vw_dim_representante", "código do representante", "r.RepresentanteId"
        ),
        FilterField(
            "vendedor.nome", "vw_dim_representante", "nome do representante", "r.Representante"
        ),
        FilterField(
            "vendedor.papel_comercial",
            "vw_dim_representante",
            "papel comercial",
            "r.PapelComercial",
        ),
        FilterField(
            "vendedor.gestor_id", "vw_dim_representante", "código do gestor atual", "r.GestorId"
        ),
        FilterField("vendedor.gestor", "vw_dim_representante", "nome do gestor atual", "r.Gestor"),
        FilterField("vendedor.uf", "vw_dim_representante", "UF do representante", "r.UF"),
        FilterField(
            "vendedor.ativo",
            "vw_dim_representante",
            "situação cadastral do representante",
            "r.Ativo",
        ),
    )
}

FILTER_OPERATORS: dict[str, frozenset[str]] = {
    "text": frozenset({"eq", "ne", "contains", "starts_with", "in", "is_null"}),
    "number": frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null"}),
    "boolean": frozenset({"eq", "ne", "is_null"}),
}

MAX_FILTERS = 8
MAX_TEXT_LENGTH = 200
MAX_IN_VALUES = 20


def filter_fields_for_prompt() -> str:
    return "\n".join(
        f"- {field.key}: {field.label} (view {field.view}; tipo {field.kind}; "
        f"operadores: {', '.join(sorted(FILTER_OPERATORS[field.kind]))})"
        for field in FILTER_FIELDS.values()
    )


def _parse_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"S", "SIM", "TRUE", "1", "ATIVO"}:
            return True
        if normalized in {"N", "NAO", "NÃO", "FALSE", "0", "INATIVO"}:
            return False
    if value in (0, 1):
        return bool(value)
    return None


def _parse_value(value: Any, kind: FilterKind) -> str | Decimal | bool | None:
    if kind == "boolean":
        return _parse_boolean(value)
    if kind == "number":
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() else None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text if text and len(text) <= MAX_TEXT_LENGTH else None


def validate_where_filters(raw_filters: Any) -> tuple[list[WhereFilter], list[str]]:
    """Valida filtros propostos pela LLM; erros pedem esclarecimento, nunca são ignorados."""
    if raw_filters is None:
        return [], []
    if not isinstance(raw_filters, list):
        return [], [
            "Não consegui interpretar os filtros. Informe o campo e o valor que deseja filtrar."
        ]
    if len(raw_filters) > MAX_FILTERS:
        return [], [f"Posso aplicar no máximo {MAX_FILTERS} filtros por consulta."]

    filters: list[WhereFilter] = []
    questions: list[str] = []
    for raw in raw_filters:
        if not isinstance(raw, Mapping):
            questions.append(
                "Não consegui interpretar um dos filtros. Informe novamente o campo e o valor."
            )
            continue

        field_key = raw.get("campo")
        operator = raw.get("operador")
        field = FILTER_FIELDS.get(field_key) if isinstance(field_key, str) else None
        if field is None:
            questions.append(
                "Não reconheci um dos campos do filtro. Informe um campo comercial como cliente, "
                "rede, produto, vendedor, UF ou segmento."
            )
            continue
        if not isinstance(operator, str) or operator not in FILTER_OPERATORS[field.kind]:
            questions.append(f"Não consegui interpretar o operador do filtro para {field.label}.")
            continue

        value = raw.get("valor")
        if operator == "is_null":
            parsed = _parse_boolean(value)
            if parsed is None:
                questions.append(
                    f"Para o filtro de {field.label}, indique se o valor deve estar vazio."
                )
                continue
            filters.append(WhereFilter(field.key, operator, parsed))
            continue

        if operator == "in":
            if not isinstance(value, list) or not 1 <= len(value) <= MAX_IN_VALUES:
                questions.append(
                    f"Informe de 1 a {MAX_IN_VALUES} valores para o filtro de {field.label}."
                )
                continue
            parsed_values: list[str | Decimal | bool] = []
            has_invalid_value = False
            for item in value:
                parsed = _parse_value(item, field.kind)
                if parsed is None:
                    has_invalid_value = True
                else:
                    parsed_values.append(parsed)
            if has_invalid_value:
                questions.append(f"Um dos valores do filtro de {field.label} é inválido.")
                continue
            filters.append(WhereFilter(field.key, operator, tuple(parsed_values)))
            continue

        parsed = _parse_value(value, field.kind)
        if parsed is None:
            questions.append(f"Informe um valor válido para o filtro de {field.label}.")
            continue
        filters.append(WhereFilter(field.key, operator, parsed))

    return filters, list(dict.fromkeys(questions))


def compile_where_filters(filters: Any) -> tuple[list[str], list[Any]]:
    """Compila somente identificadores/operações locais; todos os valores são parâmetros SQL."""
    if not isinstance(filters, (list, tuple)):
        raise ValueError("Validated WHERE filters must be a list.")

    clauses: list[str] = []
    params: list[Any] = []
    for item in filters:
        if not isinstance(item, WhereFilter):
            raise ValueError("WHERE filter was not validated.")
        field = FILTER_FIELDS.get(item.field)
        if field is None or item.operator not in FILTER_OPERATORS[field.kind]:
            raise ValueError("Unknown validated WHERE filter.")
        expression = field.expression

        if item.operator == "is_null":
            clauses.append(f"{expression} IS {'NULL' if item.value else 'NOT NULL'}")
        elif item.operator in {"contains", "starts_with"}:
            value = normalize_term(str(item.value))
            if item.operator == "contains":
                clauses.append(f"CHARINDEX(?, UPPER({expression})) > 0")
                params.append(value)
            else:
                clauses.append(f"LEFT(UPPER({expression}), LEN(?)) = ?")
                params.extend((value, value))
        elif item.operator == "in":
            values = item.value
            if not isinstance(values, tuple) or not values:
                raise ValueError("Validated IN filter must have values.")
            placeholders = ", ".join("?" for _ in values)
            if field.kind == "text":
                clauses.append(f"UPPER({expression}) IN ({placeholders})")
                params.extend(normalize_term(str(value)) for value in values)
            else:
                clauses.append(f"{expression} IN ({placeholders})")
                params.extend(values)
        else:
            sql_operator = {
                "eq": "=",
                "ne": "<>",
                "gt": ">",
                "gte": ">=",
                "lt": "<",
                "lte": "<=",
            }[item.operator]
            if field.kind == "text":
                clauses.append(f"UPPER({expression}) {sql_operator} ?")
                params.append(normalize_term(str(item.value)))
            else:
                clauses.append(f"{expression} {sql_operator} ?")
                params.append(item.value)

    return clauses, params
