import asyncio

import httpx
from leitesol_api import main
from leitesol_api.infrastructure.auth import TokenData, verify_token


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_create_chart_returns_a_chart_ready_json_specification() -> None:
    main.app.dependency_overrides[verify_token] = lambda: TokenData(username="test")
    try:
        response = request(
            "POST",
            "/chat/chart",
            json={
                "columns": ["Competência", "FAT R$"],
                "rows": [
                    {"Competência": "2026-01", "FAT R$": 100},
                    {"Competência": "2026-02", "FAT R$": 120},
                ],
                "categoryColumn": "Competência",
                "valueColumns": ["FAT R$"],
            },
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["chartType"] == "line"
    assert body["data"]["categories"] == ["2026-01", "2026-02"]
    assert body["data"]["series"] == [{"name": "FAT R$", "values": [100.0, 120.0]}]


def test_create_chart_returns_a_validation_error_for_invalid_values() -> None:
    main.app.dependency_overrides[verify_token] = lambda: TokenData(username="test")
    try:
        response = request(
            "POST",
            "/chat/chart",
            json={
                "columns": ["UF", "FAT R$"],
                "rows": [{"UF": "SP", "FAT R$": "not numeric"}],
                "categoryColumn": "UF",
                "valueColumns": ["FAT R$"],
            },
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert "não numérico" in response.json()["error"]


def test_create_chart_requires_authentication() -> None:
    response = request(
        "POST",
        "/chat/chart",
        json={
            "columns": ["UF", "FAT R$"],
            "rows": [],
            "categoryColumn": "UF",
            "valueColumns": ["FAT R$"],
        },
    )

    assert response.status_code == 401
