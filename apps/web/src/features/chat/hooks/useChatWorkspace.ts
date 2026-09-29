import {
  startTransition,
  useRef,
  useState,
  type ChangeEvent,
} from "react";

import type {
  ChatAttachment,
  ChatConversation,
  ChatConversationSummary,
} from "@leitesol/contracts";

import { queryChat } from "../../../shared/api";

import {
  chatFormSchema,
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

const createLocalConversation = (): ChatConversation => {
  const now = new Date().toISOString();

  return {
    id: `chat-${crypto.randomUUID()}`,
    title: "Nova consulta comercial",
    createdAt: now,
    updatedAt: now,
    status: "active",
    messages: [],
  };
};

const toConversationSummary = (
  conversation: ChatConversation,
): ChatConversationSummary => {
  const lastMessage =
    conversation.messages[conversation.messages.length - 1];

  return {
    id: conversation.id,
    title: conversation.title,
    lastMessagePreview:
      lastMessage?.content.slice(0, 96) ?? "Sem mensagens ainda.",
    updatedAt: conversation.updatedAt,
    status: conversation.status,
  };
};

export const useChatWorkspace = () => {
  const [activeChat, setActiveChat] =
    useState<ChatConversation | null>(null);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const chats: ChatConversationSummary[] = activeChat
    ? [toConversationSummary(activeChat)]
    : [];

  const openChat = async (chatId: string) => {
    if (!activeChat || activeChat.id !== chatId) {
      return;
    }

    setError("");
  };

  const handleCreateChat = async () => {
    setBusy(false);
    setError("");

    startTransition(() => {
      setActiveChat(null);
      setDraft("");
      setAttachments([]);
    });
  };

  const handleFileSelection = (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const selectedFiles = Array.from(
      event.target.files ?? [],
    ).map(buildAttachmentFromFile);

    if (selectedFiles.length === 0) {
      return;
    }

    setAttachments((currentAttachments) => [
      ...currentAttachments,
      ...selectedFiles,
    ]);

    event.target.value = "";
  };

  const removeAttachment = (attachmentId: string) => {
    setAttachments((currentAttachments) =>
      currentAttachments.filter(
        (attachment) => attachment.id !== attachmentId,
      ),
    );
  };

  const sendMessage = async () => {
    const parsed = chatFormSchema.safeParse({
      userId: "authenticated-user",
      message: draft,
    } satisfies ChatFormValues);

    if (!parsed.success) {
      setError(
        parsed.error.issues[0]?.message ??
          "Dados inválidos para envio.",
      );
      return;
    }

    if (!draft.trim() && attachments.length === 0) {
      return;
    }

    setBusy(true);
    setError("");

    try {
      const currentChat =
        activeChat ?? createLocalConversation();

      const userMessage = {
        id: `user-${crypto.randomUUID()}`,
        role: "user" as const,
        content: parsed.data.message,
        createdAt: new Date().toISOString(),
        attachments:
          attachments.length > 0 ? attachments : null,
      };

      const chatResponse = await queryChat(
        parsed.data.message,
      );

      const backendContent =
        chatResponse.data?.answer ??
        "Nenhuma resposta retornada.";

      const assistantMessage = {
        id: `assistant-${crypto.randomUUID()}`,
        role: "assistant" as const,
        content: backendContent,
        createdAt: new Date().toISOString(),
        attachments: null,
        sqlResult:
          chatResponse.data?.sqlResult ?? null,
      };

      const updatedConversation: ChatConversation = {
        ...currentChat,
        title:
          currentChat.messages.length === 0
            ? parsed.data.message.slice(0, 60)
            : currentChat.title,
        updatedAt: new Date().toISOString(),
        status: "active",
        messages: [
          ...currentChat.messages,
          userMessage,
          assistantMessage,
        ],
      };

      startTransition(() => {
        setActiveChat(updatedConversation);
        setDraft("");
        setAttachments([]);
      });
    } catch (requestError) {
      setError(
        (requestError as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };

  return {
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
  };
};