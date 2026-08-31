import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { startTransition, useEffect, useRef, useState } from "react";
import { createChat, getBackendHealth, getChat, getGatewayHealth, listChats, sendChatMessage, } from "../shared/api";
import "./App.css";
const formatTime = (value) => new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
}).format(new Date(value));
const buildAttachmentFromFile = (file) => ({
    id: `attachment-${crypto.randomUUID()}`,
    name: file.name,
    mimeType: file.type || "application/octet-stream",
    sizeInBytes: file.size,
    status: "attached",
});
const toConversationSummary = (conversation) => {
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
    const [gatewayStatus, setGatewayStatus] = useState(null);
    const [backendStatus, setBackendStatus] = useState(null);
    const [chats, setChats] = useState([]);
    const [activeChat, setActiveChat] = useState(null);
    const [draft, setDraft] = useState("");
    const [attachments, setAttachments] = useState([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const fileInputRef = useRef(null);
    useEffect(() => {
        void Promise.all([getGatewayHealth(), getBackendHealth(), listChats()])
            .then(async ([gatewayHealth, backendHealth, chatList]) => {
            setGatewayStatus(gatewayHealth);
            setBackendStatus(backendHealth);
            setChats(chatList.data ?? []);
            if ((chatList.data?.length ?? 0) > 0) {
                const firstChat = await getChat(chatList.data[0].id);
                setActiveChat(firstChat.data);
            }
        })
            .catch((requestError) => {
            setError(requestError.message);
        });
    }, []);
    const openChat = async (chatId) => {
        setBusy(true);
        setError("");
        try {
            const response = await getChat(chatId);
            startTransition(() => {
                setActiveChat(response.data);
            });
        }
        catch (requestError) {
            setError(requestError.message);
        }
        finally {
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
        }
        catch (requestError) {
            setError(requestError.message);
        }
        finally {
            setBusy(false);
        }
    };
    const handleFileSelection = (event) => {
        const selectedFiles = Array.from(event.target.files ?? []).map(buildAttachmentFromFile);
        if (selectedFiles.length === 0) {
            return;
        }
        setAttachments((currentAttachments) => [...currentAttachments, ...selectedFiles]);
        event.target.value = "";
    };
    const removeAttachment = (attachmentId) => {
        setAttachments((currentAttachments) => currentAttachments.filter((attachment) => attachment.id !== attachmentId));
    };
    const handleSend = async () => {
        if (!draft.trim() && attachments.length === 0) {
            return;
        }
        setBusy(true);
        setError("");
        try {
            const currentChat = activeChat ??
                (await createChat({
                    title: "Nova conversa",
                })).data;
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
        }
        catch (requestError) {
            setError(requestError.message);
        }
        finally {
            setBusy(false);
        }
    };
    return (_jsxs("main", { className: "workspace-shell", children: [_jsxs("aside", { className: "sidebar", children: [_jsxs("div", { className: "brand-card", children: [_jsx("p", { className: "eyebrow", children: "LeiteSol Agent Hub" }), _jsx("h1", { children: "Converse com a operacao comercial" }), _jsx("p", { children: "O gateway ja esta mockando o fluxo do agent para voce desenhar a experiencia antes de ligar um provedor real." }), _jsx("button", { className: "primary-action", type: "button", onClick: handleCreateChat, disabled: busy, children: "Nova conversa" })] }), _jsxs("section", { className: "sidebar-section", children: [_jsxs("div", { className: "section-header", children: [_jsx("h2", { children: "Conversas" }), _jsx("span", { children: chats.length })] }), _jsx("div", { className: "chat-list", children: chats.map((chat) => (_jsxs("button", { className: `chat-list-item ${activeChat?.id === chat.id ? "is-active" : ""}`, type: "button", onClick: () => void openChat(chat.id), children: [_jsx("strong", { children: chat.title }), _jsx("span", { children: chat.lastMessagePreview }), _jsx("small", { children: formatTime(chat.updatedAt) })] }, chat.id))) })] })] }), _jsxs("section", { className: "chat-stage", children: [_jsxs("header", { className: "chat-header", children: [_jsxs("div", { children: [_jsx("p", { className: "eyebrow", children: "Gateway first" }), _jsx("h2", { children: activeChat?.title ?? "Assistente comercial" })] }), _jsxs("div", { className: "status-strip", children: [_jsxs("div", { className: "status-pill", children: [_jsx("span", { className: "status-dot is-online" }), "Gateway ", gatewayStatus?.data?.status ?? "loading"] }), _jsxs("div", { className: "status-pill", children: [_jsx("span", { className: "status-dot is-online" }), "API ", backendStatus?.data?.status ?? "loading"] })] })] }), _jsx("div", { className: "chat-board", children: activeChat ? (_jsx("div", { className: "message-stream", children: activeChat.messages.map((message) => (_jsxs("article", { className: `message-card role-${message.role}`, children: [_jsxs("div", { className: "message-meta", children: [_jsx("strong", { children: message.role === "assistant" ? "LeiteSol AI" : "Voce" }), _jsx("span", { children: formatTime(message.createdAt) })] }), _jsx("p", { children: message.content }), message.attachments && message.attachments.length > 0 ? (_jsx("div", { className: "attachment-row", children: message.attachments.map((attachment) => (_jsx("span", { className: "attachment-chip readonly", children: attachment.name }, attachment.id))) })) : null] }, message.id))) })) : (_jsxs("div", { className: "empty-state", children: [_jsx("p", { className: "eyebrow", children: "Primeiro passo" }), _jsx("h3", { children: "Crie uma conversa e comece a desenhar seu fluxo comercial" }), _jsx("p", { children: "Voce pode mockar perguntas, anexar arquivos e sentir como o gateway vai orquestrar as mensagens antes do agent real entrar em cena." })] })) }), activeChat?.suggestedPrompts && activeChat.suggestedPrompts.length > 0 ? (_jsx("div", { className: "suggestion-row", children: activeChat.suggestedPrompts.map((suggestion) => (_jsx("button", { className: "suggestion-pill", type: "button", onClick: () => setDraft(suggestion), children: suggestion }, suggestion))) })) : null, _jsxs("footer", { className: "composer-shell", children: [attachments.length > 0 ? (_jsx("div", { className: "attachment-row", children: attachments.map((attachment) => (_jsx("button", { className: "attachment-chip", type: "button", onClick: () => removeAttachment(attachment.id), children: attachment.name }, attachment.id))) })) : null, _jsxs("div", { className: "composer-box", children: [_jsx("button", { className: "tool-button", type: "button", onClick: () => fileInputRef.current?.click(), "aria-label": "Anexar arquivo", children: "+" }), _jsx("input", { ref: fileInputRef, type: "file", multiple: true, hidden: true, onChange: handleFileSelection }), _jsx("textarea", { value: draft, onChange: (event) => setDraft(event.target.value), placeholder: "Escreva sua pergunta comercial, cole contexto ou simule um briefing de cliente.", rows: 1 }), _jsx("button", { className: "primary-action send-button", type: "button", onClick: () => void handleSend(), disabled: busy, children: "Enviar" })] }), _jsxs("div", { className: "composer-hint", children: [_jsx("span", { children: "JSON only via gateway" }), _jsx("span", { children: "Anexos ainda mockados" }), _jsx("span", { children: error || "Pronto para experimentar o fluxo inicial." })] })] })] })] }));
};
