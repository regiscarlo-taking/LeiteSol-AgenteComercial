from fastapi.testclient import TestClient

from leitesol_api.main import app


def test_read_health() -> None:
    client = TestClient(app)

    response = client.get("/health")

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
    client = TestClient(app)

    response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "healthy"
    assert payload["statusCode"] == 200
