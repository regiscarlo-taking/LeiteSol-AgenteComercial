"""Histórico das conversas do usuário, no schema IA_APP do Warehouse.

Tabelas e permissão em 17_historico_conversa.sql (repositório de
documentação do projeto). O modelo é só de inserção: o Warehouse derruba
UPDATE/DELETE concorrentes na mesma tabela, INSERT não. Por isso a data de
atualização é a da última mensagem e o título é a primeira pergunta.

Guarda o texto da pergunta e o da resposta, nunca a tabela de resultado,
token ou SQL. Toda leitura filtra pelo dono; conversa de outro usuário
responde como inexistente.
"""

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from leitesol_api.infrastructure.auth import TokenData

logger = logging.getLogger("leitesol.api.conversation_history")

# Ids aceitos: os da tela (chat-<uuid>) e os gerados aqui. Nada de espaço,
# barra ou aspas - o id volta na URL e no log.
CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONTENT_MAX_BYTES = 8000
TITLE_MAX_CHARS = 60
PREVIEW_MAX_CHARS = 120
LIST_LIMIT = 50


class HistoryConnection(Protocol):
    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...

    def execute(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None: ...


@dataclass(frozen=True, slots=True)
class Exchange:
    """Uma pergunta e a resposta dada a ela."""

    conversation_id: str
    owner: str
    question: str
    answer: str
    correlation_id: str
    operation_id: str | None
    status: str


def owner_of(user: TokenData) -> str:
    """Dono da conversa: o e-mail do token; no login local, o nome do usuário."""
    return (user.email or user.username).strip().lower()


def new_conversation_id() -> str:
    return f"chat-{uuid.uuid4()}"


def is_valid_conversation_id(value: str) -> bool:
    return bool(CONVERSATION_ID.match(value))


def cut_bytes(text: str, limit: int = CONTENT_MAX_BYTES) -> str:
    """Corta em `limit` bytes UTF-8 sem partir caractere (varchar do Warehouse é UTF-8)."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ConversationHistory:
    def __init__(self, connection: HistoryConnection) -> None:
        self._connection = connection

    def record(self, exchange: Exchange, now: datetime | None = None) -> bool:
        """Grava pergunta + resposta; devolve False se a conversa é de outro dono."""
        moment = (now or datetime.now(UTC)).replace(tzinfo=None)
        rows = self._connection.fetch(
            "SELECT Usuario FROM IA_APP.CONVERSA WHERE ConversaId = ?",
            (exchange.conversation_id,),
        )
        if rows and rows[0]["Usuario"] != exchange.owner:
            return False

        last = self._connection.fetch(
            "SELECT ISNULL(MAX(Sequencia), 0) AS Ultima "
            "FROM IA_APP.CONVERSA_MENSAGEM WHERE ConversaId = ? AND Usuario = ?",
            (exchange.conversation_id, exchange.owner),
        )
        sequence = int(last[0]["Ultima"] or 0) if last else 0

        statements: list[tuple[str, tuple[Any, ...]]] = []
        if not rows:
            statements.append(
                (
                    "INSERT INTO IA_APP.CONVERSA (ConversaId, Usuario, Titulo, CriadaEm) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        exchange.conversation_id,
                        exchange.owner,
                        cut_bytes(exchange.question.strip()[:TITLE_MAX_CHARS], 200),
                        moment,
                    ),
                )
            )
        message_sql = (
            "INSERT INTO IA_APP.CONVERSA_MENSAGEM (MensagemId, ConversaId, Usuario, "
            "Sequencia, Papel, Conteudo, CriadaEm, CorrelationId, OperacaoId, StatusResposta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        statements.append(
            (
                message_sql,
                (
                    f"user-{uuid.uuid4()}",
                    exchange.conversation_id,
                    exchange.owner,
                    sequence + 1,
                    "user",
                    cut_bytes(exchange.question),
                    moment,
                    exchange.correlation_id,
                    None,
                    None,
                ),
            )
        )
        statements.append(
            (
                message_sql,
                (
                    f"assistant-{uuid.uuid4()}",
                    exchange.conversation_id,
                    exchange.owner,
                    sequence + 2,
                    "assistant",
                    cut_bytes(exchange.answer),
                    moment,
                    exchange.correlation_id,
                    exchange.operation_id,
                    exchange.status,
                ),
            )
        )
        self._connection.execute(statements)
        return True

    def list_for(self, owner: str) -> list[dict[str, Any]]:
        rows = self._connection.fetch(
            f"""
            WITH ultima AS (
                SELECT m.ConversaId, m.Conteudo, m.CriadaEm,
                       ROW_NUMBER() OVER (PARTITION BY m.ConversaId ORDER BY m.Sequencia DESC) AS n
                FROM IA_APP.CONVERSA_MENSAGEM m
                WHERE m.Usuario = ?
            )
            SELECT TOP ({LIST_LIMIT}) c.ConversaId, c.Titulo, c.CriadaEm,
                   u.Conteudo AS UltimaMensagem,
                   COALESCE(u.CriadaEm, c.CriadaEm) AS AtualizadaEm
            FROM IA_APP.CONVERSA c
            LEFT JOIN ultima u ON u.ConversaId = c.ConversaId AND u.n = 1
            WHERE c.Usuario = ?
            ORDER BY COALESCE(u.CriadaEm, c.CriadaEm) DESC
            """,
            (owner, owner),
        )
        return [
            {
                "id": row["ConversaId"],
                "title": row["Titulo"],
                "lastMessagePreview": (row["UltimaMensagem"] or "")[:PREVIEW_MAX_CHARS],
                "updatedAt": _iso(row["AtualizadaEm"]),
                "status": "active",
            }
            for row in rows
        ]

    def get_for(self, owner: str, conversation_id: str) -> dict[str, Any] | None:
        header = self._connection.fetch(
            "SELECT ConversaId, Titulo, CriadaEm FROM IA_APP.CONVERSA "
            "WHERE ConversaId = ? AND Usuario = ?",
            (conversation_id, owner),
        )
        if not header:
            return None
        messages = self._connection.fetch(
            "SELECT MensagemId, Papel, Conteudo, CriadaEm, OperacaoId "
            "FROM IA_APP.CONVERSA_MENSAGEM WHERE ConversaId = ? AND Usuario = ? "
            "ORDER BY Sequencia",
            (conversation_id, owner),
        )
        created = _iso(header[0]["CriadaEm"])
        return {
            "id": header[0]["ConversaId"],
            "title": header[0]["Titulo"],
            "createdAt": created,
            "updatedAt": _iso(messages[-1]["CriadaEm"]) if messages else created,
            "status": "active",
            "messages": [
                {
                    "id": message["MensagemId"],
                    "role": message["Papel"],
                    "content": message["Conteudo"],
                    "createdAt": _iso(message["CriadaEm"]),
                    # A tabela de resultado não é guardada: ao reabrir, a
                    # resposta volta só como texto.
                    "sqlResult": None,
                }
                for message in messages
            ],
        }


def record_safely(history: ConversationHistory, exchange: Exchange) -> None:
    """Roda depois da resposta; falha ao gravar vira aviso no log, nunca erro na tela."""
    try:
        if not history.record(exchange):
            logger.warning(
                "Conversation owned by another user, not recorded correlation_id=%s",
                exchange.correlation_id,
            )
    except Exception:
        logger.warning(
            "Conversation record failed correlation_id=%s", exchange.correlation_id, exc_info=True
        )
