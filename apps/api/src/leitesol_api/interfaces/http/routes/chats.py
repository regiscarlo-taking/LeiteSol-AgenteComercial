import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from leitesol_api.infrastructure.auth import TokenData, verify_token
from leitesol_api.infrastructure.conversation_history import (
    ConversationHistory,
    is_valid_conversation_id,
    owner_of,
)
from leitesol_api.infrastructure.fabric import FabricConnectionError, build_fabric_connection
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload

# Histórico das conversas do usuário logado: só as dele, sempre. Conversa de
# outro dono responde 404, igual a uma que não existe.
router = APIRouter(prefix="/chats", tags=["chat"], dependencies=[Depends(verify_token)])
logger = logging.getLogger("leitesol.api.http.chats")


def get_conversation_history() -> ConversationHistory | None:
    settings = get_settings()
    if not settings.conversation_history_enabled:
        return None
    return ConversationHistory(build_fabric_connection(settings))


def conversation_history_factory() -> ConversationHistory | None:
    """Dependência sobrescrevível nos testes."""
    return get_conversation_history()


def _payload(request: Request, data, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_response_payload(
            data=data,
            message=message,
            status_code=status_code,
            trace_id=getattr(request.state, "request_id", None),
        ),
    )


@router.get("")
def list_chats(
    request: Request,
    user: TokenData = Depends(verify_token),
    history: ConversationHistory | None = Depends(conversation_history_factory),
) -> JSONResponse:
    if history is None:
        return _payload(request, [], "Histórico de conversas desligado.", 200)
    try:
        chats = history.list_for(owner_of(user))
    except FabricConnectionError:
        return _payload(request, None, "Não foi possível carregar as conversas.", 503)
    return _payload(request, chats, "Conversas do usuário.", 200)


@router.get("/{chat_id}")
def get_chat(
    chat_id: str,
    request: Request,
    user: TokenData = Depends(verify_token),
    history: ConversationHistory | None = Depends(conversation_history_factory),
) -> JSONResponse:
    if history is None or not is_valid_conversation_id(chat_id):
        return _payload(request, None, "Conversa não encontrada.", 404)
    try:
        chat = history.get_for(owner_of(user), chat_id)
    except FabricConnectionError:
        return _payload(request, None, "Não foi possível carregar a conversa.", 503)
    if chat is None:
        return _payload(request, None, "Conversa não encontrada.", 404)
    return _payload(request, chat, "Conversa do usuário.", 200)
