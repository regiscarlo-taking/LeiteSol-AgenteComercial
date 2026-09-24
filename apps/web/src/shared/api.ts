import type { BaseResponse, ChatSqlResult, HealthStatus, Measure } from "@leitesol/contracts";
import type {
  ChatAttachment,
  ChatConversation,
  ChatConversationSummary,
  CreateChatRequest,
  SendChatMessageResult,
} from "@leitesol/contracts";

import { requestApi } from "./http";
import { getValidAccessToken } from "./auth-session";

export interface AuthToken {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export type SqlResult = ChatSqlResult;

export interface ChatQueryResult {
  answer: string;
  sqlResult: SqlResult;
}

export const authenticate = async (username: string, password: string): Promise<AuthToken> => {
  const response = await fetch("/api/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    throw new Error("Usuário ou senha inválidos.");
  }

  return (await response.json()) as AuthToken;
};

export const queryChat = async (question: string): Promise<BaseResponse<ChatQueryResult>> =>
  requestApi<ChatQueryResult, { question: string }>({
    url: "/api/chat/query",
    method: "POST",
    headers: {
      Authorization: `Bearer ${getValidAccessToken() ?? ""}`,
    },
    data: { question },
    errorMessage: "Nao foi possivel processar a pergunta no Gemini.",
  });

export const getGatewayHealth = async (): Promise<BaseResponse<HealthStatus>> =>
  requestApi<HealthStatus>({
    url: "/health/live",
    errorMessage: "Nao foi possivel consultar a saude do gateway.",
  });

export const getBackendHealth = async (): Promise<BaseResponse<HealthStatus>> =>
  requestApi<HealthStatus>({
    url: "/api/health",
    errorMessage: "Nao foi possivel consultar a saude do backend.",
  });

export const listMeasures = async (): Promise<BaseResponse<Measure[]>> =>
  requestApi<Measure[]>({
    url: "/api/fabric/measures",
    headers: {
      Authorization: `Bearer ${getValidAccessToken() ?? ""}`,
    },
    errorMessage: "Nao foi possivel carregar as medidas do Fabric.",
  });

export const queryEntity = async (entity: string, limit = 100): Promise<BaseResponse<SqlResult>> =>
  requestApi<SqlResult, { entity: string; limit: number }>({
    url: "/api/fabric/query",
    method: "POST",
    headers: {
      Authorization: `Bearer ${getValidAccessToken() ?? ""}`,
    },
    data: { entity, limit },
    errorMessage: "Nao foi possivel consultar a entidade do Fabric.",
  });

export const listChats = async (): Promise<BaseResponse<ChatConversationSummary[]>> =>
  requestApi<ChatConversationSummary[]>({
    url: "/api/chats",
    errorMessage: "Nao foi possivel carregar a lista de conversas.",
  });

export const getChat = async (chatId: string): Promise<BaseResponse<ChatConversation>> =>
  requestApi<ChatConversation>({
    url: `/api/chats/${chatId}`,
    errorMessage: "Nao foi possivel carregar a conversa selecionada.",
  });

export const createChat = async (
  payload: CreateChatRequest = {},
): Promise<BaseResponse<ChatConversation>> =>
  requestApi<ChatConversation, CreateChatRequest>({
    url: "/api/chats",
    method: "POST",
    data: payload,
    errorMessage: "Nao foi possivel criar uma nova conversa.",
  });

export const sendChatMessage = async ({
  chatId,
  content,
  attachments,
}: {
  chatId: string;
  content: string;
  attachments: ChatAttachment[];
}): Promise<BaseResponse<SendChatMessageResult>> =>
  requestApi<SendChatMessageResult, { content: string; attachments: ChatAttachment[] }>({
    url: `/api/chats/${chatId}/messages`,
    method: "POST",
    data: {
      content,
      attachments,
    },
    errorMessage: "Nao foi possivel enviar a mensagem.",
  });
