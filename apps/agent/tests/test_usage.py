from datetime import date
from typing import Any

import httpx
import pytest
from leitesol_agent.domain.models import Catalog, Operation
from leitesol_agent.domain.usage import UsageMeter
from leitesol_agent.infrastructure import gemini
from leitesol_agent.infrastructure.gemini import GeminiLanguageModel

OPERATION = Operation("OP12", "SK", "comparar", "comparar_vendas", "Comparar vendas", None)


def fake_post(payload: dict[str, Any]):
    def post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    return post


def test_meter_adds_up_the_calls_of_one_question(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gemini.httpx,
        "post",
        fake_post(
            {
                "candidates": [{"content": {"parts": [{"text": '{"intencao_id": "comparar"}'}]}}],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 10,
                    "thoughtsTokenCount": 5,
                },
            }
        ),
    )
    meter = UsageMeter()
    llm = GeminiLanguageModel("key", "gemini-test", meter)

    assert llm.classify_intent("vendas?", Catalog((OPERATION,), {})) == "comparar"
    llm.extract_parameters("vendas?", OPERATION, date(2026, 9, 30))

    usage = meter.snapshot()
    assert (usage.model, usage.calls) == ("gemini-test", 2)
    assert (usage.input_tokens, usage.output_tokens) == (200, 30)


def test_response_without_usage_metadata_is_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gemini.httpx,
        "post",
        fake_post({"candidates": [{"content": {"parts": [{"text": '{"intencao_id": null}'}]}}]}),
    )
    meter = UsageMeter()

    GeminiLanguageModel("key", "gemini-test", meter).classify_intent("?", Catalog((OPERATION,), {}))

    assert meter.snapshot().calls == 0
