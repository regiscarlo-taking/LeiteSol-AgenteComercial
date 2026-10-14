from leitesol_agent.domain.models import Catalog
from leitesol_agent.infrastructure.catalog import _with_application_operations


def test_catalog_includes_fixed_local_product_and_region_analysis() -> None:
    catalog = _with_application_operations(Catalog(operations=(), transversal_rules={}))

    operation = catalog.by_intent("analisar_vendas_por_produto_ou_regiao")

    assert operation is not None
    assert operation.operation_id == "APP_SALES_BREAKDOWN"
    assert {parameter.name for parameter in operation.parameters} >= {
        "dimensao",
        "nivel_geografico",
        "metrica",
        "janela_meses",
    }


def test_catalog_adds_local_analysis_only_once() -> None:
    catalog = Catalog(operations=(), transversal_rules={})

    enriched = _with_application_operations(_with_application_operations(catalog))

    assert len(enriched.operations) == 1
