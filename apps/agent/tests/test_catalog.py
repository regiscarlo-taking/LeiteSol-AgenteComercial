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

    assert {operation.operation_id for operation in enriched.operations} == {
        "APP_SALES_BREAKDOWN",
        "APP_PRICE_PER_KG",
    }


def test_catalog_includes_general_price_per_kg_operation() -> None:
    catalog = _with_application_operations(Catalog(operations=(), transversal_rules={}))

    operation = catalog.by_intent("consultar_preco_medio_geral_por_kg")

    assert operation is not None
    assert operation.operation_id == "APP_PRICE_PER_KG"
    assert operation.parameters[0].default == "6"
