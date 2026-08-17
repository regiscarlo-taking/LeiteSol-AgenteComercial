import { startTransition, useEffect, useRef, useState } from "react";

import type {
  BaseResponse,
  ChatAttachment,
  ChatConversation,
  ChatConversationSummary,
  HealthStatus,
} from "@leitesol/contracts";

import {
  createChat,
  getBackendHealth,
  getChat,
  getGatewayHealth,
  listChats,
  sendChatMessage,
} from "../shared/api";
import "./App.css";

const formatTime = (value: string): string =>
  new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));

const buildAttachmentFromFile = (file: File): ChatAttachment => ({
  id: `attachment-${crypto.randomUUID()}`,
  name: file.name,
  mimeType: file.type || "application/octet-stream",
  sizeInBytes: file.size,
  status: "attached",
});

const toConversationSummary = (conversation: ChatConversation): ChatConversationSummary => {
  const lastMessage = conversation.messages[conversation.messages.length - 1];

  return {
    id: conversation.id,
    title: conversation.title,
    lastMessagePreview: lastMessage?.content.slice(0, 96) ?? "Sem mensagens ainda.",
    updatedAt: conversation.updatedAt,
    status: conversation.status,
  };
};

export const App = () => {
  const [gatewayStatus, setGatewayStatus] = useState<BaseResponse<HealthStatus> | null>(null);
  const [backendStatus, setBackendStatus] = useState<BaseResponse<HealthStatus> | null>(null);
  const [chats, setChats] = useState<ChatConversationSummary[]>([]);
  const [activeChat, setActiveChat] = useState<ChatConversation | null>(null);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void Promise.all([getGatewayHealth(), getBackendHealth(), listChats()])
      .then(async ([gatewayHealth, backendHealth, chatList]) => {
        setGatewayStatus(gatewayHealth);
        setBackendStatus(backendHealth);
        setChats(chatList.data ?? []);

        if ((chatList.data?.length ?? 0) > 0) {
          const firstChat = await getChat(chatList.data![0].id);
          setActiveChat(firstChat.data);
        }
      })
      .catch((requestError: Error) => {
        setError(requestError.message);
      });
  }, []);

  const openChat = async (chatId: string) => {
    setBusy(true);
    setError("");

    try {
      const response = await getChat(chatId);
      startTransition(() => {
        setActiveChat(response.data);
      });
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateChat = async () => {
    setBusy(true);
    setError("");

    try {
      const response = await createChat();
      const conversation = response.data;

      if (!conversation) {
        throw new Error("Nao foi possivel iniciar a nova conversa.");
      }

      startTransition(() => {
        setActiveChat(conversation);
        setChats((currentChats) => [toConversationSummary(conversation), ...currentChats]);
        setDraft("");
        setAttachments([]);
      });
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleFileSelection = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files ?? []).map(buildAttachmentFromFile);

    if (selectedFiles.length === 0) {
      return;
    }

    setAttachments((currentAttachments) => [...currentAttachments, ...selectedFiles]);
    event.target.value = "";
  };

  const removeAttachment = (attachmentId: string) => {
    setAttachments((currentAttachments) =>
      currentAttachments.filter((attachment) => attachment.id !== attachmentId),
    );
  };

  const handleSend = async () => {
    if (!draft.trim() && attachments.length === 0) {
      return;
    }

    setBusy(true);
    setError("");

    try {
      const currentChat =
        activeChat ??
        (
          await createChat({
            title: "Nova conversa",
          })
        ).data;

      if (!currentChat) {
        throw new Error("Nao foi possivel preparar a conversa para envio.");
      }

      const response = await sendChatMessage({
        chatId: currentChat.id,
        content: draft,
        attachments,
      });
      const updatedConversation = response.data?.conversation;

      if (!updatedConversation) {
        throw new Error("Nao foi possivel atualizar a conversa.");
      }

      startTransition(() => {
        setActiveChat(updatedConversation);
        setChats((currentChats) => {
          const nextSummary = toConversationSummary(updatedConversation);
          const remainingChats = currentChats.filter((chat) => chat.id !== updatedConversation.id);
          return [nextSummary, ...remainingChats];
        });
        setDraft("");
        setAttachments([]);
      });
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="workspace-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <p className="eyebrow">LeiteSol Agent Hub</p>
          <h1>Converse com a operacao comercial</h1>
          <p>
            O gateway ja esta mockando o fluxo do agent para voce desenhar a experiencia antes
            de ligar um provedor real.
          </p>
          <button className="primary-action" type="button" onClick={handleCreateChat} disabled={busy}>
            Nova conversa
          </button>
        </div>

        <section className="sidebar-section">
          <div className="section-header">
            <h2>Conversas</h2>
            <span>{chats.length}</span>
          </div>

          <div className="chat-list">
            {chats.map((chat) => (
              <button
                key={chat.id}
                className={`chat-list-item ${activeChat?.id === chat.id ? "is-active" : ""}`}
                type="button"
                onClick={() => void openChat(chat.id)}
              >
                <strong>{chat.title}</strong>
                <span>{chat.lastMessagePreview}</span>
                <small>{formatTime(chat.updatedAt)}</small>
              </button>
            ))}
          </div>
        </section>
      </aside>

      <section className="chat-stage">
        <header className="chat-header">
          <div>
            <p className="eyebrow">Gateway first</p>
            <h2>{activeChat?.title ?? "Assistente comercial"}</h2>
          </div>

          <div className="status-strip">
            <div className="status-pill">
              <span className="status-dot is-online" />
              Gateway {gatewayStatus?.data?.status ?? "loading"}
            </div>
            <div className="status-pill">
              <span className="status-dot is-online" />
              API {backendStatus?.data?.status ?? "loading"}
            </div>
          </div>
        </header>

        <div className="chat-board">
          {activeChat ? (
            <div className="message-stream">
              {activeChat.messages.map((message) => (
                <article key={message.id} className={`message-card role-${message.role}`}>
                  <div className="message-meta">
                    <strong>{message.role === "assistant" ? "LeiteSol AI" : "Voce"}</strong>
                    <span>{formatTime(message.createdAt)}</span>
                  </div>

                  <p>{message.content}</p>

                  {message.attachments && message.attachments.length > 0 ? (
                    <div className="attachment-row">
                      {message.attachments.map((attachment) => (
                        <span key={attachment.id} className="attachment-chip readonly">
                          {attachment.name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <p className="eyebrow">Primeiro passo</p>
              <h3>Crie uma conversa e comece a desenhar seu fluxo comercial</h3>
              <p>
                Voce pode mockar perguntas, anexar arquivos e sentir como o gateway vai orquestrar
                as mensagens antes do agent real entrar em cena.
              </p>
            </div>
          )}
        </div>

        {activeChat?.suggestedPrompts && activeChat.suggestedPrompts.length > 0 ? (
          <div className="suggestion-row">
            {activeChat.suggestedPrompts.map((suggestion) => (
              <button
                key={suggestion}
                className="suggestion-pill"
                type="button"
                onClick={() => setDraft(suggestion)}
              >
                {suggestion}
              </button>
            ))}
          </div>
        ) : null}

        <footer className="composer-shell">
          {attachments.length > 0 ? (
            <div className="attachment-row">
              {attachments.map((attachment) => (
                <button
                  key={attachment.id}
                  className="attachment-chip"
                  type="button"
                  onClick={() => removeAttachment(attachment.id)}
                >
                  {attachment.name}
                </button>
              ))}
            </div>
          ) : null}

          <div className="composer-box">
            <button
              className="tool-button"
              type="button"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Anexar arquivo"
            >
              +
            </button>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={handleFileSelection}
            />

            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Escreva sua pergunta comercial, cole contexto ou simule um briefing de cliente."
              rows={1}
            />

            <button className="primary-action send-button" type="button" onClick={() => void handleSend()} disabled={busy}>
              Enviar
            </button>
          </div>

          <div className="composer-hint">
            <span>JSON only via gateway</span>
            <span>Anexos ainda mockados</span>
            <span>{error || "Pronto para experimentar o fluxo inicial."}</span>
          </div>
        </footer>
      </section>
    </main>
  );
};
