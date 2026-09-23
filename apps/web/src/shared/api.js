import { requestApi } from "./http";
export const authenticate = async (username, password) => {
    const response = await fetch("/api/auth/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
        throw new Error("Usuário ou senha inválidos.");
    }
    return (await response.json());
};
export const queryChat = async (question) => requestApi({
    url: "/api/chat/query",
    method: "POST",
    headers: {
        Authorization: `Bearer ${localStorage.getItem("leitesol_access_token") ?? ""}`,
    },
    data: { question },
    errorMessage: "Nao foi possivel processar a pergunta no Gemini.",
});
export const getGatewayHealth = async () => requestApi({
    url: "/health/live",
    errorMessage: "Nao foi possivel consultar a saude do gateway.",
});
export const getBackendHealth = async () => requestApi({
    url: "/api/health",
    errorMessage: "Nao foi possivel consultar a saude do backend.",
});
export const listMeasures = async () => requestApi({
    url: "/api/fabric/measures",
    headers: {
        Authorization: `Bearer ${localStorage.getItem("leitesol_access_token") ?? ""}`,
    },
    errorMessage: "Nao foi possivel carregar as medidas do Fabric.",
});
export const queryEntity = async (entity, limit = 100) => requestApi({
    url: "/api/fabric/query",
    method: "POST",
    headers: {
        Authorization: `Bearer ${localStorage.getItem("leitesol_access_token") ?? ""}`,
    },
    data: { entity, limit },
    errorMessage: "Nao foi possivel consultar a entidade do Fabric.",
});
export const listChats = async () => requestApi({
    url: "/api/chats",
    errorMessage: "Nao foi possivel carregar a lista de conversas.",
});
export const getChat = async (chatId) => requestApi({
    url: `/api/chats/${chatId}`,
    errorMessage: "Nao foi possivel carregar a conversa selecionada.",
});
export const createChat = async (payload = {}) => requestApi({
    url: "/api/chats",
    method: "POST",
    data: payload,
    errorMessage: "Nao foi possivel criar uma nova conversa.",
});
export const sendChatMessage = async ({ chatId, content, attachments, }) => requestApi({
    url: `/api/chats/${chatId}/messages`,
    method: "POST",
    data: {
        content,
        attachments,
    },
    errorMessage: "Nao foi possivel enviar a mensagem.",
});
