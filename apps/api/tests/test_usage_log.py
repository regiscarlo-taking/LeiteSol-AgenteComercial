import json
from datetime import UTC, datetime

from leitesol_agent.domain.models import AgentResponse, Operation, ResponseStatus
from leitesol_agent.domain.usage import LlmUsage
from leitesol_api.infrastructure.settings import Settings
from leitesol_api.infrastructure.usage_log import build_usage_record, record_usage

OPERATION = Operation("OP12", "SK", "comparar", "comparar_vendas", "Comparar vendas", None)
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


class FakeStore:
    def __init__(self, fail: bool = False) -> None:
        self.lines: list[tuple[str, str]] = []
        self._fail = fail

    def append_line(self, name: str, line: str) -> None:
        if self._fail:
            raise RuntimeError("blob indisponível")
        self.lines.append((name, line))


def response(usage: LlmUsage | None) -> AgentResponse:
    return AgentResponse(
        correlation_id="abc",
        status=ResponseStatus.ANSWERED,
        operation=OPERATION,
        narrative="Faturamento de R$ 1.234,00 na carteira de fulano@leitesol.com.br",
        usage=usage,
    )


def test_record_has_tokens_and_no_content() -> None:
    settings = Settings(gemini_input_price_per_mtok=0.30, gemini_output_price_per_mtok=2.50)

    record = build_usage_record(response(LlmUsage("gemini-x", 3, 2000, 400)), settings, NOW)

    assert record == {
        "momento": "2026-09-30T12:00:00+00:00",
        "correlation_id": "abc",
        "status": "respondida",
        "operacao": "OP12",
        "modelo": "gemini-x",
        "chamadas": 3,
        "tokens_entrada": 2000,
        "tokens_saida": 400,
        "custo_estimado": 0.0016,
    }


def test_no_llm_call_means_no_record() -> None:
    assert build_usage_record(response(None), Settings(), NOW) is None
    assert build_usage_record(response(LlmUsage()), Settings(), NOW) is None


def test_blob_is_off_by_default() -> None:
    store = FakeStore()

    record_usage(response(LlmUsage("gemini-x", 1, 10, 5)), Settings(), store)

    assert store.lines == []


def test_blob_gets_one_line_per_question_in_a_daily_file() -> None:
    store = FakeStore()

    record_usage(response(LlmUsage("gemini-x", 1, 10, 5)), Settings(usage_log_to_blob=True), store)

    [(name, line)] = store.lines
    assert name.startswith("uso/") and name.endswith(".jsonl")
    assert "custo_estimado" not in json.loads(line)
    assert "leitesol.com.br" not in line


def test_blob_failure_does_not_break_the_answer() -> None:
    record_usage(
        response(LlmUsage("gemini-x", 1, 10, 5)),
        Settings(usage_log_to_blob=True),
        FakeStore(fail=True),
    )
