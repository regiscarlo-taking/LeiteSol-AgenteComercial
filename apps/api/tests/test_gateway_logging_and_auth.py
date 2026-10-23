import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import HTTPException
from leitesol_api import main
from leitesol_api.infrastructure import auth
from leitesol_api.infrastructure.gateway_log import record_gateway_request
from leitesol_api.infrastructure.settings import Settings
from leitesol_api.interfaces.http.routes import gateway_logs
from leitesol_api.interfaces.schemas import GatewayLogRecord


class FakeStore:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def append_line(self, name: str, line: str) -> None:
        self.lines.append((name, line))


def gateway_log(severity: str = "info") -> GatewayLogRecord:
    return GatewayLogRecord(
        traceId=str(uuid4()),
        timestamp=datetime(2026, 10, 12, tzinfo=UTC),
        severity=severity,
        request={"method": "POST", "path": "/api/chat/query"},
        response={"statusCode": 200, "durationMs": 20.5},
    )


def test_gateway_log_writes_all_severities_to_one_blob() -> None:
    store = FakeStore()

    for severity in ("info", "warning", "error"):
        record_gateway_request(
            gateway_log(severity),
            Settings(gateway_log_to_blob=True),
            store,
        )

    assert [name for name, _ in store.lines] == ["gateway/logs.jsonl"] * 3
    assert [json.loads(line)["severity"] for _, line in store.lines] == [
        "info",
        "warning",
        "error",
    ]
    assert all("body" not in line for _, line in store.lines)


def test_gateway_blob_write_logs_success_with_trace_and_blob_name(caplog) -> None:
    caplog.set_level(logging.INFO, logger="leitesol.api.gateway")
    store = FakeStore()
    record = gateway_log()

    record_gateway_request(
        record,
        Settings(gateway_log_to_blob=True),
        store,
    )

    blob_events = [
        json.loads(item.message.removeprefix("gateway_log_blob_write "))
        for item in caplog.records
        if item.message.startswith("gateway_log_blob_write ")
    ]
    assert len(blob_events) == 1
    assert blob_events[0]["event"] == "gateway_log_blob_write"
    assert blob_events[0]["trace_id"] == record.trace_id
    assert blob_events[0]["result"] == "written"
    assert blob_events[0]["blob"] == "gateway/logs.jsonl"
    assert blob_events[0]["duration_ms"] >= 0


def test_gateway_blob_write_logs_azure_error_diagnostics_without_raising(caplog) -> None:
    class StorageFailure(RuntimeError):
        error_code = "AuthorizationPermissionMismatch"
        status_code = 403
        response = type(
            "StorageResponse",
            (),
            {"headers": {"x-ms-request-id": "azure-request-123"}},
        )()

    class FailingStore(FakeStore):
        def append_line(self, name: str, line: str) -> None:
            raise StorageFailure("do not log this raw response body")

    record = gateway_log()

    record_gateway_request(
        record,
        Settings(gateway_log_to_blob=True),
        FailingStore(),
    )

    blob_events = [
        json.loads(item.message.removeprefix("gateway_log_blob_write "))
        for item in caplog.records
        if item.message.startswith("gateway_log_blob_write ")
    ]
    assert blob_events == [
        {
            "event": "gateway_log_blob_write",
            "trace_id": record.trace_id,
            "result": "failed",
            "error_type": "StorageFailure",
            "error_code": "AuthorizationPermissionMismatch",
            "status_code": 403,
            "storage_request_id": "azure-request-123",
            "duration_ms": blob_events[0]["duration_ms"],
        }
    ]
    assert blob_events[0]["duration_ms"] >= 0
    assert "do not log this raw response body" not in caplog.text


def test_gateway_blob_write_logs_when_storage_persistence_is_disabled(caplog) -> None:
    caplog.set_level(logging.INFO, logger="leitesol.api.gateway")
    record_gateway_request(gateway_log(), Settings(gateway_log_to_blob=False))

    blob_events = [
        json.loads(item.message.removeprefix("gateway_log_blob_write "))
        for item in caplog.records
        if item.message.startswith("gateway_log_blob_write ")
    ]
    assert len(blob_events) == 1
    assert blob_events[0]["event"] == "gateway_log_blob_write"
    assert blob_events[0]["result"] == "skipped"
    assert blob_events[0]["reason"] == "blob_logging_disabled"


def test_gateway_log_ingestion_requires_shared_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_logs,
        "get_settings",
        lambda: Settings(api_key="shared-test-key"),
    )
    accepted: list[str] = []
    monkeypatch.setattr(
        gateway_logs,
        "record_gateway_request",
        lambda record, settings: accepted.append(record.trace_id),
    )
    record = gateway_log()

    gateway_logs.ingest_gateway_log(record, "shared-test-key")

    assert accepted == [record.trace_id]
    with pytest.raises(HTTPException) as error:
        gateway_logs.ingest_gateway_log(record, "incorrect")
    assert error.value.status_code == 401


def test_local_access_token_expires_after_twenty_minutes(monkeypatch) -> None:
    settings = Settings(
        auth_mode="local",
        jwt_secret_key="test-secret-that-is-long-enough-for-tests",
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    token = auth.create_access_token("test-user")
    claims = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])

    assert claims["exp"] - claims["iat"] == auth.ACCESS_TOKEN_TTL_SECONDS
    assert auth.verify_token(token).expires_at == claims["exp"]


def test_local_access_token_is_rejected_after_twenty_minute_maximum_age(monkeypatch) -> None:
    settings = Settings(
        auth_mode="local",
        jwt_secret_key="test-secret-that-is-long-enough-for-tests",
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "test-user",
            "type": "access",
            "iat": int((now - timedelta(minutes=21)).timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as error:
        auth.verify_token(token)
    assert error.value.status_code == 401


def test_session_endpoint_returns_validated_token_deadline(monkeypatch) -> None:
    settings = Settings(
        auth_mode="local",
        jwt_secret_key="test-secret-that-is-long-enough-for-tests",
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    token = auth.create_access_token("test-user")

    async def get_session() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://localhost",
        ) as client:
            return await client.get(
                "/auth/session",
                headers={"Authorization": f"Bearer {token}"},
            )

    response = asyncio.run(get_session())

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert isinstance(response.json()["expiresAt"], int)
