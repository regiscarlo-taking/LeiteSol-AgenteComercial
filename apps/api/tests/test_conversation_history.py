import asyncio
from datetime import datetime
from typing import Any

import httpx
import pytest
from leitesol_agent.application.answer_question import AnswerQuestion
from leitesol_agent.application.operations import OPERATION_HANDLERS
from leitesol_agent.domain.models import Scope
from leitesol_api import main
from leitesol_api.infrastructure.auth import TokenData, verify_token
from leitesol_api.infrastructure.conversation_history import (
    ConversationHistory,
    Exchange,
    cut_bytes,
    owner_of,
    record_safely,
)
from leitesol_api.infrastructure.fabric import FabricConnectionError, FabricSqlConnection
from leitesol_api.interfaces.http.routes import chats, questions
from test_agent import FakeCatalog, FakeFetcher, FakeLLM, FixedScope

ANA = "ana@leitesol.com.br"
BIA = "bia@leitesol.com.br"


class MemoryWarehouse:
    """Responde às consultas fixas do histórico sobre listas em memória."""

    def __init__(self) -> None:
        self.conversations: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.writes: list[list[tuple[str, tuple[Any, ...]]]] = []

    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if sql.startswith("SELECT Usuario FROM IA_APP.CONVERSA "):
            return [
                {"Usuario": c["Usuario"]}
                for c in self.conversations
                if c["ConversaId"] == params[0]
            ]
        if "MAX(Sequencia)" in sql:
            seqs = [m["Sequencia"] for m in self._messages(*params)]
            return [{"Ultima": max(seqs, default=0)}]
        if "WITH ultima" in sql:
            owner = params[1]
            rows = []
            for c in self.conversations:
                if c["Usuario"] != owner:
                    continue
                own = self._messages(c["ConversaId"], owner)
                last = own[-1] if own else None
                rows.append(
                    {
                        "ConversaId": c["ConversaId"],
                        "Titulo": c["Titulo"],
                        "CriadaEm": c["CriadaEm"],
                        "UltimaMensagem": last["Conteudo"] if last else None,
                        "AtualizadaEm": last["CriadaEm"] if last else c["CriadaEm"],
                    }
                )
            return sorted(rows, key=lambda row: row["AtualizadaEm"], reverse=True)
        if sql.startswith("SELECT ConversaId, Titulo, CriadaEm FROM IA_APP.CONVERSA"):
            return [
                c
                for c in self.conversations
                if c["ConversaId"] == params[0] and c["Usuario"] == params[1]
            ]
        if sql.startswith("SELECT MensagemId"):
            return self._messages(*params)
        raise AssertionError(f"consulta inesperada: {sql}")

    def execute(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        self.writes.append(statements)
        for sql, params in statements:
            if sql.startswith("INSERT INTO IA_APP.CONVERSA ("):
                keys = ("ConversaId", "Usuario", "Titulo", "CriadaEm")
                self.conversations.append(dict(zip(keys, params, strict=True)))
            else:
                keys = (
                    "MensagemId",
                    "ConversaId",
                    "Usuario",
                    "Sequencia",
                    "Papel",
                    "Conteudo",
                    "CriadaEm",
                    "CorrelationId",
                    "OperacaoId",
                    "StatusResposta",
                )
                self.messages.append(dict(zip(keys, params, strict=True)))

    def _messages(self, conversation_id: str, owner: str) -> list[dict[str, Any]]:
        return sorted(
            (
                m
                for m in self.messages
                if m["ConversaId"] == conversation_id and m["Usuario"] == owner
            ),
            key=lambda m: m["Sequencia"],
        )


def exchange(
    conversation_id: str = "chat-1", owner: str = ANA, question: str = "Faturamento de julho?"
) -> Exchange:
    return Exchange(
        conversation_id=conversation_id,
        owner=owner,
        question=question,
        answer="Resumo.",
        correlation_id="corr-1",
        operation_id="OP12",
        status="respondida",
    )


def test_first_exchange_opens_the_conversation_and_appends_two_messages() -> None:
    warehouse = MemoryWarehouse()
    history = ConversationHistory(warehouse)

    assert history.record(exchange(), now=datetime(2026, 10, 14, 10, 0))
    assert history.record(exchange(question="E agosto?"), now=datetime(2026, 10, 14, 10, 5))

    assert [c["Titulo"] for c in warehouse.conversations] == ["Faturamento de julho?"]
    assert [(m["Sequencia"], m["Papel"]) for m in warehouse.messages] == [
        (1, "user"),
        (2, "assistant"),
        (3, "user"),
        (4, "assistant"),
    ]
    assistant = warehouse.messages[1]
    assert (assistant["OperacaoId"], assistant["StatusResposta"]) == ("OP12", "respondida")
    # Só inserção: nada de UPDATE/DELETE, que o Warehouse derruba sob concorrência.
    assert all(
        sql.startswith("INSERT INTO IA_APP.") for batch in warehouse.writes for sql, _ in batch
    )


def test_conversation_of_another_owner_is_not_touched() -> None:
    warehouse = MemoryWarehouse()
    history = ConversationHistory(warehouse)
    history.record(exchange(owner=ANA))

    assert history.record(exchange(owner=BIA)) is False
    assert len(warehouse.messages) == 2
    assert history.get_for(BIA, "chat-1") is None
    assert history.list_for(BIA) == []


def test_reading_returns_only_the_owner_conversations_in_the_screen_contract() -> None:
    warehouse = MemoryWarehouse()
    history = ConversationHistory(warehouse)
    history.record(exchange("chat-a"), now=datetime(2026, 10, 14, 9, 0))
    history.record(
        exchange("chat-b", question="Top 20 clientes?"), now=datetime(2026, 10, 14, 11, 0)
    )
    history.record(exchange("chat-c", owner=BIA))

    listed = history.list_for(ANA)
    assert [c["id"] for c in listed] == ["chat-b", "chat-a"]
    assert listed[0] == {
        "id": "chat-b",
        "title": "Top 20 clientes?",
        "lastMessagePreview": "Resumo.",
        "updatedAt": "2026-10-14T11:00:00",
        "status": "active",
    }

    chat = history.get_for(ANA, "chat-a")
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["sqlResult"] is None


def test_content_is_cut_in_bytes_without_breaking_a_character() -> None:
    text = "ç" * 5000  # 2 bytes cada
    cut = cut_bytes(text)
    assert len(cut.encode("utf-8")) <= 8000
    assert cut == "ç" * 4000


def test_failure_to_record_never_raises() -> None:
    class Broken(MemoryWarehouse):
        def execute(self, statements):
            raise FabricConnectionError("fora do ar")

    record_safely(ConversationHistory(Broken()), exchange())


def test_owner_is_the_lowercase_email_or_the_local_username() -> None:
    assert owner_of(TokenData(username="oid", email="Ana@Leitesol.com.br")) == ANA
    assert owner_of(TokenData(username="admin")) == "admin"


def test_connection_refuses_writes_outside_ia_app() -> None:
    connection = FabricSqlConnection(
        server="s",
        database="d",
        driver="x",
        authentication="a",
        client_id="c",
        tenant_id="t",
        client_secret="p",
        timeout=1,
    )
    with pytest.raises(FabricConnectionError):
        connection.execute([("INSERT INTO IA_COMERCIAL.AGT_MEDIDA VALUES (?)", (1,))])
    with pytest.raises(FabricConnectionError):
        connection.execute([("DELETE FROM IA_APP.CONVERSA", ())])


# ---------------------------------------------------------------- rotas


def call(
    method: str, url: str, warehouse: MemoryWarehouse | None, email: str = ANA, **kwargs
) -> httpx.Response:
    use_case = AnswerQuestion(
        catalog=FakeCatalog(),
        scopes=FixedScope(Scope(sees_everything=True)),
        llm=FakeLLM(None),
        fetcher=FakeFetcher(),
        handlers=OPERATION_HANDLERS,
    )
    main.app.dependency_overrides[verify_token] = lambda: TokenData(
        username="t", email=email, full_access=True
    )
    main.app.dependency_overrides[questions.answer_question_factory] = lambda: lambda: use_case
    main.app.dependency_overrides[chats.conversation_history_factory] = lambda: (
        ConversationHistory(warehouse) if warehouse is not None else None
    )

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            return await client.request(method, url, **kwargs)

    try:
        return asyncio.run(send())
    finally:
        main.app.dependency_overrides.clear()


def test_chat_query_returns_the_chat_id_and_records_after_answering() -> None:
    warehouse = MemoryWarehouse()

    first = call("POST", "/chat/query", warehouse, json={"question": "pedidos em aberto?"})
    chat_id = first.json()["data"]["chatId"]
    assert chat_id.startswith("chat-")
    call("POST", "/chat/query", warehouse, json={"question": "e devoluções?", "chatId": chat_id})

    assert len(warehouse.conversations) == 1
    assert [m["Conteudo"] for m in warehouse.messages if m["Papel"] == "user"] == [
        "pedidos em aberto?",
        "e devoluções?",
    ]
    assert {m["StatusResposta"] for m in warehouse.messages if m["Papel"] == "assistant"} == {
        "fora_de_escopo"
    }


def test_chat_query_keeps_working_with_history_off() -> None:
    response = call(
        "POST", "/chat/query", None, json={"question": "pedidos em aberto?", "chatId": "chat-x"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["chatId"] == "chat-x"


def test_chat_query_rejects_a_malformed_chat_id() -> None:
    response = call("POST", "/chat/query", None, json={"question": "oi", "chatId": "../x y"})
    assert response.status_code == 422


def test_chats_routes_only_show_the_logged_user() -> None:
    warehouse = MemoryWarehouse()
    ConversationHistory(warehouse).record(exchange("chat-ana"))

    assert [c["id"] for c in call("GET", "/chats", warehouse).json()["data"]] == ["chat-ana"]
    assert call("GET", "/chats/chat-ana", warehouse).status_code == 200
    assert call("GET", "/chats", warehouse, email=BIA).json()["data"] == []
    assert call("GET", "/chats/chat-ana", warehouse, email=BIA).status_code == 404


def test_chats_routes_with_history_off() -> None:
    assert call("GET", "/chats", None).json()["data"] == []
    assert call("GET", "/chats/chat-1", None).status_code == 404
