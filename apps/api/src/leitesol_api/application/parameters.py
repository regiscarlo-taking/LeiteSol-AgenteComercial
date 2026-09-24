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
    text = value.strip()
    # Parâmetro de competência vem como AAAA-MM: vale o primeiro dia do mês.
    if len(text) == 7:
        text = f"{text}-01"
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if number > 0 else None


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in {"S", "SIM", "TRUE", "1"}:
        return True
    if text in {"N", "NAO", "NÃO", "FALSE", "0"}:
        return False
    return None


def _missing_question(parameter: Parameter) -> str:
    description = parameter.description or parameter.name
    if parameter.kind == "date" and (parameter.domain or "").startswith("AAAA-MM-DD"):
        # Mesma pergunta para início e fim: sai uma vez só na deduplicação.
        return "Qual período você quer consultar? Informe o mês/ano de início e de fim."
    if parameter.kind == "date":
        return "Qual mês você quer analisar? Informe o mês e o ano."
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
                value = parameter.default
            else:
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
        elif parameter.kind == "int":
            number = _parse_int(value)
            if number is None:
                result.questions.append(_missing_question(parameter))
                continue
            result.values[parameter.name] = number
        elif parameter.kind == "bool":
            flag = _parse_bool(value)
            if flag is None:
                result.questions.append(_missing_question(parameter))
                continue
            result.values[parameter.name] = flag
        else:
            result.values[parameter.name] = str(value)

    # Pergunta repetida (ex.: início e fim ausentes) aparece uma vez só.
    result.questions = list(dict.fromkeys(result.questions))
    return result
