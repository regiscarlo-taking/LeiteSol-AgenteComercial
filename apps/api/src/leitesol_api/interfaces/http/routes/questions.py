import logging
from collections.abc import Callable
from functools import lru_cache

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from leitesol_api.application.answer_question import AnswerQuestion
from leitesol_api.application.operations import OPERATION_HANDLERS
from leitesol_api.domain.agent import AgentResponse, ResponseStatus
from leitesol_api.infrastructure.auth import TokenData, verify_token
from leitesol_api.infrastructure.catalog import CatalogRepository
from leitesol_api.infrastructure.fabric import FabricConnectionError, build_fabric_connection
from leitesol_api.infrastructure.gemini import GeminiError, get_gemini_client
from leitesol_api.infrastructure.scope import ScopeResolver
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload

router = APIRouter(tags=["agente"], dependencies=[Depends(verify_token)])
logger = logging.getLogger("leitesol.api.http.questions")


class QuestionRequest(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)


@lru_cache(maxsize=1)
def _catalog_repository() -> CatalogRepository:
    settings = get_settings()
    return CatalogRepository(
        build_fabric_connection(settings), ttl_seconds=settings.catalog_cache_seconds
    )


def get_answer_question() -> AnswerQuestion:
    fetcher = build_fabric_connection(get_settings())
    return AnswerQuestion(
        catalog=_catalog_repository(),
        scopes=ScopeResolver(fetcher),
        llm=get_gemini_client(),
        fetcher=fetcher,
        handlers=OPERATION_HANDLERS,
    )


def answer_question_factory() -> Callable[[], AnswerQuestion]:
    """Dependência sobrescrevível nos testes; a construção roda dentro da rota."""
    return get_answer_question


@router.post("/perguntas")
def ask(
    body: QuestionRequest,
    request: Request,
    user: TokenData = Depends(verify_token),
    build_use_case: Callable[[], AnswerQuestion] = Depends(answer_question_factory),
) -> JSONResponse:
    correlation_id = getattr(request.state, "request_id", None) or "sem-correlation-id"
    try:
        # Montado aqui, e não como Depends, para que falha de Key Vault/Gemini
        # na construção também vire o envelope de erro.
        use_case = build_use_case()
        response = use_case.execute(
            question=body.pergunta,
            email=user.email,
            full_access=user.full_access,
            correlation_id=correlation_id,
        )
        status_code = 200
    except Exception as error:
        # Falha técnica (Fabric, Gemini, Key Vault): mensagem genérica e o
        # correlation_id para achar o detalhe no log (contrato §6, status erro).
        known = isinstance(error, (FabricConnectionError, GeminiError))
        logger.log(
            logging.WARNING if known else logging.ERROR,
            "Question failed correlation_id=%s",
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
        data=response.to_contract(),
        message=f"Pergunta processada: {response.status.value}.",
        status_code=status_code,
        trace_id=correlation_id,
    )
    return JSONResponse(status_code=status_code, content=payload)
