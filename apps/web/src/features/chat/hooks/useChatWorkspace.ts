import { startTransition, useRef, useState } from "react";

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
  getGatewayHealth,
  getChat,
  listChats,
  listMeasures,
} from "../../../shared/api";
import {
  buildBackendChatReply,
  chatFormSchema,
  toChatSendCommand,
  type ChatFormValues,
} from "../domain/chat-form";

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

export const useChatWorkspace = () => {
  const [gatewayStatus, setGatewayStatus] = useState<BaseResponse<HealthStatus> | null>(null);
  const [backendStatus, setBackendStatus] = useState<BaseResponse<HealthStatus> | null>(null);
  const [chats, setChats] = useState<ChatConversationSummary[]>([]);
  const [activeChat, setActiveChat] = useState<ChatConversation | null>(null);
  const [userId, setUserId] = useState("user-001");
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadLocalContext = async () => {
    setBusy(true);
    setError("");

    try {
      const [gatewayHealth, backendHealth, chatList] = await Promise.all([
        getGatewayHealth(),
        getBackendHealth(),
        listChats(),
      ]);

      setGatewayStatus(gatewayHealth);
      setBackendStatus(backendHealth);
      setChats(chatList.data ?? []);

      const chatItems = chatList.data ?? [];

      if (chatItems.length > 0) {
        const firstChat = chatItems[0];
        const detail = await getChat(firstChat.id);
        setActiveChat(detail.data ?? null);
      }
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusy(false);
    }
  };

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
        throw new Error("Não foi possível iniciar a nova conversa.");
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

  const sendMessage = async () => {
    const parsed = chatFormSchema.safeParse({
      userId,
      message: draft,
    } satisfies ChatFormValues);

    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Dados inválidos para envio.");
      return;
    }

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
            title: `Conversa de ${parsed.data.userId}`,
          })
        ).data;

      if (!currentChat) {
        throw new Error("Não foi possível preparar a conversa para envio.");
      }

      const command = toChatSendCommand({
        userId: parsed.data.userId,
        message: parsed.data.message,
        attachments,
      });

      const measuresResponse = await listMeasures();
      const measures = measuresResponse.data ?? [];
      const backendContent = buildBackendChatReply(command.content, measures);

      const nextMessages = [
        ...currentChat.messages,
        {
          id: `user-${crypto.randomUUID()}`,
          role: "user" as const,
          content: command.content,
          createdAt: new Date().toISOString(),
          attachments: command.attachments.length > 0 ? command.attachments : null,
        },
        {
          id: `assistant-${crypto.randomUUID()}`,
          role: "assistant" as const,
          content: backendContent,
          createdAt: new Date().toISOString(),
          attachments: null,
        },
      ];

      const updatedConversation: typeof currentChat = {
        ...currentChat,
        title: currentChat.title || `Conversa de ${parsed.data.userId}`,
        updatedAt: new Date().toISOString(),
        status: "active",
        messages: nextMessages,
      };

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

  return {
    activeChat,
    attachments,
    backendStatus,
    busy,
    chats,
    draft,
    error,
    fileInputRef,
    formatTime,
    gatewayStatus,
    handleCreateChat,
    handleFileSelection,
    loadLocalContext,
    openChat,
    removeAttachment,
    sendMessage,
    setDraft,
    setUserId,
    userId,
  };
};
