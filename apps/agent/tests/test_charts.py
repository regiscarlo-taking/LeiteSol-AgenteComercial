import pytest
from leitesol_agent.application.charts import ChartDataError, build_chart_specification


def test_chart_spec_automatically_uses_a_line_for_monthly_categories() -> None:
    specification = build_chart_specification(
        columns=["Competência", "FAT R$"],
        rows=[
            {"Competência": "2026-01", "FAT R$": 1200},
            {"Competência": "2026-02", "FAT R$": "1350.50"},
        ],
        category_column="Competência",
        value_columns=["FAT R$"],
    )

    assert specification.chart_type == "line"
    assert specification.categories == ("2026-01", "2026-02")
    assert specification.to_dict()["series"] == [
        {"name": "FAT R$", "values": [1200.0, 1350.5]}
    ]
    assert specification.to_dict()["xAxis"] == {
        "label": "Competência",
        "dataKey": "category",
    }


def test_chart_spec_uses_a_bar_for_ranked_categories() -> None:
    specification = build_chart_specification(
        columns=["Cliente", "FAT KG"],
        rows=[{"Cliente": "Mercado Sol", "FAT KG": 80}],
        category_column="Cliente",
        value_columns=["FAT KG"],
    )

    assert specification.chart_type == "bar"


def test_chart_spec_keeps_missing_measure_as_a_gap() -> None:
    specification = build_chart_specification(
        columns=["UF", "FAT R$"],
        rows=[{"UF": "SP", "FAT R$": None}],
        category_column="UF",
        value_columns=["FAT R$"],
        chart_type="bar",
    )

    assert specification.series[0].values == (None,)


@pytest.mark.parametrize(
    ("category", "values", "rows", "message"),
    [
        ("Missing", ["FAT R$"], [{"UF": "SP", "FAT R$": 1}], "não existe"),
        ("UF", ["Missing"], [{"UF": "SP", "FAT R$": 1}], "não encontradas"),
        ("UF", ["FAT R$"], [{"UF": "SP", "FAT R$": "abc"}], "não numérico"),
    ],
)
def test_chart_spec_rejects_invalid_columns_and_values(
    category: str,
    values: list[str],
    rows: list[dict[str, object]],
    message: str,
) -> None:
    with pytest.raises(ChartDataError, match=message):
        build_chart_specification(
            columns=["UF", "FAT R$"],
            rows=rows,
            category_column=category,
            value_columns=values,
        )


def test_pie_chart_requires_exactly_one_numeric_series() -> None:
    with pytest.raises(ChartDataError, match="exatamente uma"):
        build_chart_specification(
            columns=["UF", "FAT R$", "FAT KG"],
            rows=[],
            category_column="UF",
            value_columns=["FAT R$", "FAT KG"],
            chart_type="pie",
        )
