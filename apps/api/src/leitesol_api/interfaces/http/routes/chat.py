import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from leitesol_agent.application.answer_question import AnswerQuestion
from leitesol_agent.domain.models import AgentResponse, ResponseStatus

from leitesol_api.infrastructure.auth import TokenData, verify_token
from leitesol_api.infrastructure.fabric import FabricConnectionError
from leitesol_api.infrastructure.gemini import GeminiError
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.infrastructure.usage_log import record_usage
from leitesol_api.interfaces.http.routes.questions import answer_question_factory
from leitesol_api.interfaces.responses import build_response_payload
from leitesol_api.interfaces.schemas import ChatQueryRequest

# A tela conversa por esta rota. Ela usa o mesmo fluxo do POST /perguntas
# (operação do catálogo, parâmetros validados, alçada, resposta redigida a
# partir do resultado) e só adapta a saída ao formato que a tela já lê:
# texto em `answer` e a tabela principal em `sqlResult`.
router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(verify_token)])
logger = logging.getLogger("leitesol.api.http.chat")

MAIN_TABLE = "resultado"


def to_chat_payload(response: AgentResponse) -> dict[str, Any]:
    contract = response.to_contract()
    text = contract["pergunta_ao_usuario"] or contract["narrativa"] or ""
    notices = [notice["texto"] for notice in contract["avisos"] if notice.get("texto")]
    if notices and response.status == ResponseStatus.ANSWERED:
        text = "\n\n".join([text, *notices]) if text else "\n\n".join(notices)

    table = (contract["dados"] or {}).get("principal") or {}
    header = table.get("colunas") or []
    labels = [column["rotulo"] for column in header]
    rows = [
        {column["rotulo"]: line.get(column["id"]) for column in header}
        for line in table.get("linhas") or []
    ]
    operation = contract["operacao"] or {}
    return {
        "answer": text,
        "sqlResult": {
            "entity": operation.get("nome_tecnico") or MAIN_TABLE,
            "sql": None,
            "columns": labels,
            "rows": rows,
            "rowCount": len(rows),
        },
    }


@router.post("/query")
def query_chat(
    question: ChatQueryRequest,
    request: Request,
    user: TokenData = Depends(verify_token),
    build_use_case: Callable[[], AnswerQuestion] = Depends(answer_question_factory),
) -> JSONResponse:
    correlation_id = getattr(request.state, "request_id", None) or "sem-correlation-id"
    try:
        response = build_use_case().execute(
            question=question.question,
            email=user.email,
            full_access=user.full_access,
            correlation_id=correlation_id,
        )
        record_usage(response, get_settings())
        status_code = 200
    except Exception as error:
        known = isinstance(error, (FabricConnectionError, GeminiError))
        logger.log(
            logging.WARNING if known else logging.ERROR,
            "Chat query failed correlation_id=%s",
            correlation_id,
            exc_info=not known,
        )
        response = AgentResponse(
            correlation_id=correlation_id,
            status=ResponseStatus.ERROR,
            narrative="Não foi possível responder agora. Tente de novo em instantes.",
        )
        status_code = 503

    payload = build_response_payload(
        data=to_chat_payload(response),
        message=f"Pergunta processada: {response.status.value}.",
        status_code=status_code,
        metadata={"status": response.status.value},
        trace_id=correlation_id,
    )
    return JSONResponse(status_code=status_code, content=payload)
