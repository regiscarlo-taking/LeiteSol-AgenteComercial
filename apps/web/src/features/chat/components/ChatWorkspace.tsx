import "../../../app/App.css";

import { useChatWorkspace } from "../hooks/useChatWorkspace";

export const ChatWorkspace = () => {
  const {
    activeChat,
    attachments,
    backendStatus,
    busy,
    chats,
    draft,
    entityName,
    entityResult,
    error,
    fileInputRef,
    formatTime,
    gatewayStatus,
    handleCreateChat,
    handleQueryEntity,
    handleFileSelection,
    loadLocalContext,
    openChat,
    removeAttachment,
    sendMessage,
    setDraft,
    setEntityName,
    setUserId,
    userId,
  } = useChatWorkspace();

  return (
    <main className="workspace-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <p className="eyebrow">LeiteSol Agent Hub</p>
          <h1>Converse com a operação comercial</h1>
          <p>
            O gateway já está mockando o fluxo do agente para você desenhar a experiência antes de
            ligar um provedor real.
          </p>
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

        <div className="identity-panel">
          <label>
            Usuário
            <input
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              placeholder="id do usuário"
            />
          </label>
          <button type="button" className="secondary-action" onClick={() => void loadLocalContext()} disabled={busy}>
            Conectar ao gateway
          </button>
        </div>

        <section className="query-panel">
          <div>
            <p className="eyebrow">Consulta Fabric</p>
            <strong>Consultar entidade</strong>
          </div>
          <div className="query-controls">
            <input
              value={entityName}
              onChange={(event) => setEntityName(event.target.value)}
              placeholder="agt_operacao ou dim_cliente"
              aria-label="Nome da entidade"
            />
            <button type="button" className="secondary-action" onClick={() => void handleQueryEntity()} disabled={busy}>
              Consultar
            </button>
          </div>
          {entityResult ? (
            <div className="query-result">
              {entityResult.sql ? <code>{entityResult.sql}</code> : null}
              <div className="result-table-wrap">
                <table>
                  <thead>
                    <tr>{entityResult.columns.map((column) => <th key={column}>{column}</th>)}</tr>
                  </thead>
                  <tbody>
                    {entityResult.rows.map((row, index) => (
                      <tr key={`${entityResult.entity}-${index}`}>
                        {entityResult.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <small>{entityResult.rowCount} linhas retornadas</small>
            </div>
          ) : null}
        </section>

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
            <span>JSON only via gateway</span>
            <span>Anexos ainda mockados</span>
            <span>{error || "Pronto para experimentar o fluxo inicial."}</span>
          </div>
        </footer>
      </section>
    </main>
  );
};
