import "../../../app/App.css";

import { useChatWorkspace } from "../hooks/useChatWorkspace";
import { AgentAnswerView } from "./AgentAnswerView";

export const ChatWorkspace = () => {
  const {
    activeChat,
    attachments,
    busy,
    chats,
    draft,
    error,
    fileInputRef,
    formatTime,
    handleCreateChat,
    handleFileSelection,
    openChat,
    removeAttachment,
    sendMessage,
    setDraft,
  } = useChatWorkspace();

  return (
    <main className="workspace-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <p className="eyebrow">LeiteSol Agent Hub</p>
          <h1>Converse com a operação comercial</h1>
          <p>Faça perguntas em linguagem natural e consulte os dados comerciais com segurança.</p>
          <button className="primary-action" type="button" onClick={() => void handleCreateChat()} disabled={busy}>
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
            <p className="eyebrow">Assistente comercial</p>
            <h2>{activeChat?.title ?? "Assistente comercial"}</h2>
          </div>
        </header>

        <div className="chat-board">
          {activeChat ? (
            <div className="message-stream">
              {activeChat.messages.map((message) => (
                <article key={message.id} className={`message-card role-${message.role}`}>
                  <div className="message-meta">
                    <strong>{message.role === "assistant" ? "LeiteSol AI" : "Você"}</strong>
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

                  {message.agentAnswer ? <AgentAnswerView answer={message.agentAnswer} /> : null}

                  {message.sqlResult ? (
                    <section className="query-result">
                      {message.sqlResult.sql ? <code>{message.sqlResult.sql}</code> : null}
                      <div className="result-table-wrap">
                        <table>
                          <thead>
                            <tr>{message.sqlResult.columns.map((column) => <th key={column}>{column}</th>)}</tr>
                          </thead>
                          <tbody>
                            {message.sqlResult.rows.map((row, index) => (
                              <tr key={`${message.sqlResult?.entity}-${index}`}>
                                {message.sqlResult?.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <small>{message.sqlResult.rowCount} linhas retornadas</small>
                    </section>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <p className="eyebrow">Primeiro passo</p>
              <h3>Crie uma conversa e comece a desenhar seu fluxo comercial</h3>
              <p>
                Você pode mockar perguntas, anexar arquivos e sentir como o gateway vai orquestrar
                as mensagens antes do agente real entrar em cena.
              </p>
            </div>
          )}
        </div>

        {activeChat?.suggestedPrompts && activeChat.suggestedPrompts.length > 0 ? (
          <div className="suggestion-row">
            {activeChat.suggestedPrompts.map((suggestion) => (
              <button key={suggestion} className="suggestion-pill" type="button" onClick={() => setDraft(suggestion)}>
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

            <input ref={fileInputRef} type="file" multiple hidden onChange={handleFileSelection} />

            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Escreva sua pergunta comercial, cole contexto ou simule um briefing de cliente."
              rows={1}
            />

            <button className="primary-action send-button" type="button" onClick={() => void sendMessage()} disabled={busy}>
              Enviar
            </button>
          </div>

          <div className="composer-hint">
            <span>{error || "Pergunte sobre medidas, clientes, produtos ou faturamento."}</span>
          </div>
        </footer>
      </section>
    </main>
  );
};
