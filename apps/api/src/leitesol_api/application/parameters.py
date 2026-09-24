"""Validação determinística dos parâmetros que a LLM extraiu da pergunta.

A LLM propõe; este módulo decide. Parâmetro obrigatório ausente ou valor
fora do domínio declarado em AGT_OPERACAO_PARAMETRO vira pergunta ao
usuário (RT07, D-A03), nunca um valor escolhido em silêncio.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from leitesol_api.domain.agent import Operation, Parameter


@dataclass(slots=True)
class ValidatedParameters:
    values: dict[str, Any] = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.questions


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _missing_question(parameter: Parameter) -> str:
    description = parameter.description or parameter.name
    if parameter.kind == "date":
        # Mesma pergunta para início e fim: sai uma vez só na deduplicação.
        return "Qual período você quer consultar? Informe o mês/ano de início e de fim."
    if parameter.enum_values:
        return f"{description}: escolha entre {', '.join(parameter.enum_values)}."
    return f"Informe {description.lower()}."


def validate_parameters(operation: Operation, raw: dict[str, Any]) -> ValidatedParameters:
    result = ValidatedParameters()
    for parameter in operation.parameters:
        value = raw.get(parameter.name)
        if isinstance(value, str):
            value = value.strip() or None

        if value is None:
            if parameter.required:
                result.questions.append(_missing_question(parameter))
                continue
            if parameter.default:
                result.values[parameter.name] = parameter.default
            continue

        if parameter.kind == "date":
            parsed = _parse_date(value)
            if parsed is None:
                result.questions.append(_missing_question(parameter))
                continue
            result.values[parameter.name] = parsed
        elif parameter.kind == "enum":
            normalized = str(value).strip().lower()
            if normalized not in parameter.enum_values:
                result.questions.append(_missing_question(parameter))
                continue
            result.values[parameter.name] = normalized
        else:
            result.values[parameter.name] = str(value)

    # Pergunta repetida (ex.: início e fim ausentes) aparece uma vez só.
    result.questions = list(dict.fromkeys(result.questions))
    return result
