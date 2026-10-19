"""Validação determinística dos parâmetros que a LLM extraiu da pergunta.

A LLM propõe; este módulo decide. Parâmetro obrigatório ausente ou valor
fora do domínio declarado em AGT_OPERACAO_PARAMETRO vira pergunta ao
usuário (RT07, D-A03), nunca um valor escolhido em silêncio.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from leitesol_agent.application.where_filters import validate_where_filters
from leitesol_agent.domain.models import Operation, Parameter


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
    if operation.operation_id == "OP12" and raw.get("comparar_mes_a_mes") is True:
        result.values["comparar_mes_a_mes"] = True
    relative_comparison_window = (
        operation.operation_id == "OP12"
        and _parse_int(raw.get("janela_meses")) is not None
    )
    for parameter in operation.parameters:
        if operation.operation_id == "OP17" and parameter.name == "janela_meses":
            continue
        if (
            relative_comparison_window
            and parameter.name in {"periodo_inicio", "periodo_fim"}
        ):
            continue
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
            # O domínio mistura caixas (fat_rs | SKU|FAMILIA): compara sem caixa.
            normalized = str(value).strip().lower()
            if normalized not in {option.lower() for option in parameter.enum_values}:
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

    if operation.operation_id == "OP17":
        raw_window = raw.get("janela_meses")
        if isinstance(raw_window, str):
            raw_window = raw_window.strip() or None
        if raw_window is None:
            result.values["janela_meses"] = 12
        else:
            window = _parse_int(raw_window)
            if window in {3, 6, 9, 12}:
                result.values["janela_meses"] = window
            else:
                result.questions.append(
                    "A série mensal aceita janelas de 3, 6, 9 ou 12 meses. "
                    "Qual você quer consultar?"
                )
    if relative_comparison_window:
        result.values["janela_meses"] = _parse_int(raw["janela_meses"])

    # Pergunta repetida (ex.: início e fim ausentes) aparece uma vez só.
    where_filters, filter_questions = validate_where_filters(raw.get("where"))
    if where_filters:
        result.values["where"] = where_filters
    result.questions.extend(filter_questions)
    result.questions = list(dict.fromkeys(result.questions))
    return result
