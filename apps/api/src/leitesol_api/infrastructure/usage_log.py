"""Registro do consumo da LLM por pergunta.

Guarda quanto cada pergunta gastou, e nada do que foi perguntado ou
respondido: sem texto, sem e-mail, sem valor de faturamento. O
correlation_id liga o registro ao log técnico da requisição.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from leitesol_agent.domain.models import AgentResponse

from leitesol_api.infrastructure.settings import Settings

logger = logging.getLogger("leitesol.api.usage")


class AppendStore(Protocol):
    def append_line(self, name: str, line: str) -> None: ...


def build_usage_record(
    response: AgentResponse, settings: Settings, now: datetime | None = None
) -> dict[str, Any] | None:
    usage = response.usage
    if usage is None or usage.calls == 0:
        return None
    record: dict[str, Any] = {
        "momento": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "correlation_id": response.correlation_id,
        "status": response.status.value,
        "operacao": response.operation.operation_id if response.operation else None,
        "modelo": usage.model,
        "chamadas": usage.calls,
        "tokens_entrada": usage.input_tokens,
        "tokens_saida": usage.output_tokens,
    }
    if settings.gemini_input_price_per_mtok or settings.gemini_output_price_per_mtok:
        record["custo_estimado"] = round(
            usage.input_tokens * settings.gemini_input_price_per_mtok / 1_000_000
            + usage.output_tokens * settings.gemini_output_price_per_mtok / 1_000_000,
            6,
        )
    return record


def record_usage(
    response: AgentResponse, settings: Settings, store: AppendStore | None = None
) -> None:
    """Nunca derruba a resposta: falha ao registrar vira só um aviso no log."""
    try:
        record = build_usage_record(response, settings)
        if record is None:
            return
        line = json.dumps(record, ensure_ascii=False)
        logger.info("llm_usage %s", line)
        if not settings.usage_log_to_blob:
            return
        if store is None:
            from leitesol_api.infrastructure.azure_storage import get_blob_storage_gateway

            store = get_blob_storage_gateway()
        # Um arquivo por dia: uso/AAAA-MM-DD.jsonl.
        store.append_line(f"uso/{record['momento'][:10]}.jsonl", line)
    except Exception:
        logger.warning(
            "Usage record failed correlation_id=%s", response.correlation_id, exc_info=True
        )
