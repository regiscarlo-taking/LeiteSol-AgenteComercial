import type { BaseResponse, HealthStatus } from "@leitesol/contracts";
import type {
  ChatAttachment,
  ChatConversation,
  ChatConversationSummary,
  CreateChatRequest,
  SendChatMessageResult,
} from "@leitesol/contracts";

import { requestApi } from "./http";

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
