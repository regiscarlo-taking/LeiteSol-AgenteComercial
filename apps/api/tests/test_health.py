import asyncio

import httpx
from leitesol_api.main import app


async def get_response(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        return await client.get(path)


def test_read_health() -> None:
    response = asyncio.run(get_response("/health"))

    assert response.status_code == 200
    payload = response.json()

    assert payload["statusCode"] == 200
    assert payload["success"] is True
    assert payload["data"] == {
        "service": "leitesol-api",
        "status": "healthy",
        "version": "v1",
    }


def test_liveness_health_middleware() -> None:
    response = asyncio.run(get_response("/health/live"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "healthy"
    assert payload["statusCode"] == 200


def test_key_vault_secret_route_is_not_public() -> None:
    assert "/azure/key-vault/secrets/{secret_name}" not in app.openapi()["paths"]
