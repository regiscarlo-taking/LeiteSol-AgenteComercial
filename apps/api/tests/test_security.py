import asyncio

import httpx
import pytest

from leitesol_api import main
from leitesol_api.infrastructure.auth import TokenData, verify_token
from leitesol_api.infrastructure.fabric import (
    CATALOG_ENTITIES,
    EntityNotAllowedError,
    FabricSqlConnection,
)
from leitesol_api.infrastructure.settings import Settings
from leitesol_api.interfaces.http.routes import measures

ENTRA = {"entra_tenant_id": "tenant", "entra_api_audience": "api://leitesol"}

FORBIDDEN_TABLES = (
    "AGT_GESTAO_SKILL",
    "AGT_GESTAO_OPERACAO",
    "AGT_GESTAO_MEDIDA",
    "AGT_GESTAO_DIMENSAO",
    "AGT_GESTAO_RELACIONAMENTO",
    "AGT_GESTAO_MAPA_CAMPO",
    "AGT_GESTAO_PENDENCIA",
    "vw_hierarquia_equipe",
    "vw_rls_alcance",
)


def request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


@pytest.mark.parametrize("table", FORBIDDEN_TABLES)
def test_forbidden_entities_are_not_in_allowlist(table: str) -> None:
    assert table not in {entity.table for entity in CATALOG_ENTITIES}


@pytest.mark.parametrize(
    "name",
    ["agt_gestao_operacao", "hierarquia_equipe", "rls_alcance", "AGT_GESTAO_PENDENCIA"],
)
def test_forbidden_entities_are_rejected(name: str) -> None:
    with pytest.raises(EntityNotAllowedError):
        FabricSqlConnection._get_entity(name)


def test_inspection_routes_do_not_exist_outside_development(monkeypatch) -> None:
    monkeypatch.setattr(measures, "get_settings", lambda: Settings(environment="staging", **ENTRA))
    main.app.dependency_overrides[verify_token] = lambda: TokenData(username="test")
    try:
        entities = request(main.app, "GET", "/fabric/entities")
        query = request(main.app, "POST", "/fabric/query", json={"entity": "dim_cliente"})
    finally:
        main.app.dependency_overrides.clear()

    assert entities.status_code == 404
    assert query.status_code == 404


def test_docs_are_not_published_in_production(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(environment="production", **ENTRA),
    )
    app = main.create_app()

    assert request(app, "GET", "/docs").status_code == 404
    assert request(app, "GET", "/openapi.json").status_code == 404


def test_refresh_token_is_not_accepted_in_query_string() -> None:
    response = request(main.app, "POST", "/token/refresh?refresh_token=abc")

    assert response.status_code == 422
