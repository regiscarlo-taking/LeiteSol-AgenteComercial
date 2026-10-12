"""Converte resultados tabulares em especificações de gráficos sem consultar dados."""

import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

ChartType = Literal["bar", "line", "pie"]
RequestedChartType = Literal["auto", "bar", "line", "pie"]


class ChartDataError(ValueError):
    """O resultado tabular não pode ser representado pelo gráfico solicitado."""


@dataclass(frozen=True, slots=True)
class ChartSeries:
    name: str
    values: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class ChartSpecification:
    chart_type: ChartType
    title: str
    categories: tuple[str, ...]
    series: tuple[ChartSeries, ...]
    x_axis_label: str
    y_axis_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chartType": self.chart_type,
            "title": self.title,
            "categories": list(self.categories),
            "series": [
                {"name": series.name, "values": list(series.values)} for series in self.series
            ],
            "xAxis": {"label": self.x_axis_label, "dataKey": "category"},
            "yAxis": {"label": self.y_axis_label},
        }


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _resolve_chart_type(requested: RequestedChartType, category_column: str) -> ChartType:
    if requested != "auto":
        return requested
    category = _normalize(category_column)
    temporal_markers = ("mes", "ano", "data", "competencia", "periodo")
    return "line" if any(marker in category for marker in temporal_markers) else "bar"


def _number(value: Any, *, column: str, row_index: int) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ChartDataError(
            f"Coluna '{column}', linha {row_index}: valor booleano não é numérico."
        )
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ChartDataError(
            f"Coluna '{column}', linha {row_index}: valor não numérico."
        ) from None
    if not number.is_finite():
        raise ChartDataError(f"Coluna '{column}', linha {row_index}: valor numérico inválido.")
    return float(number)


def build_chart_specification(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    category_column: str,
    value_columns: list[str],
    chart_type: RequestedChartType = "auto",
    title: str | None = None,
) -> ChartSpecification:
    """Valida as colunas e preserva a ordem e os valores do resultado original."""
    if not columns:
        raise ChartDataError("Informe as colunas do resultado.")
    if len(columns) != len(set(columns)):
        raise ChartDataError("O resultado contém nomes de coluna duplicados.")
    if category_column not in columns:
        raise ChartDataError(f"Coluna de categoria '{category_column}' não existe no resultado.")
    if not value_columns:
        raise ChartDataError("Informe pelo menos uma coluna numérica para o gráfico.")
    if len(value_columns) != len(set(value_columns)):
        raise ChartDataError("A mesma coluna numérica foi informada mais de uma vez.")
    missing = [column for column in value_columns if column not in columns]
    if missing:
        raise ChartDataError(f"Colunas numéricas não encontradas: {', '.join(missing)}.")
    if category_column in value_columns:
        raise ChartDataError("A coluna de categoria não pode ser usada como série numérica.")

    resolved_type = _resolve_chart_type(chart_type, category_column)
    if resolved_type == "pie" and len(value_columns) != 1:
        raise ChartDataError("O gráfico de pizza aceita exatamente uma série numérica.")
    categories: list[str] = []
    series_values: dict[str, list[float | None]] = {column: [] for column in value_columns}
    for index, row in enumerate(rows, start=1):
        if category_column not in row:
            raise ChartDataError(
                f"A linha {index} não contém a coluna de categoria '{category_column}'."
            )
        category = row[category_column]
        categories.append("(sem valor)" if category is None else str(category))
        for column in value_columns:
            if column not in row:
                raise ChartDataError(f"A linha {index} não contém a coluna '{column}'.")
            series_values[column].append(_number(row[column], column=column, row_index=index))

    chart_title = (title or "").strip() or f"{', '.join(value_columns)} por {category_column}"
    if len(chart_title) > 160:
        raise ChartDataError("O título do gráfico deve ter no máximo 160 caracteres.")
    return ChartSpecification(
        chart_type=resolved_type,
        title=chart_title,
        categories=tuple(categories),
        series=tuple(
            ChartSeries(name=column, values=tuple(values))
            for column, values in series_values.items()
        ),
        x_axis_label=category_column,
        y_axis_label=", ".join(value_columns),
    )
