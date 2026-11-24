import { randomUUID } from "node:crypto";

import type {
  ChatAttachment,
  ChatConversation,
  ChatConversationSummary,
  ChatMessage,
  CreateChatRequest,
  SendChatMessageRequest,
} from "@leitesol/contracts";

const nowIso = () => new Date().toISOString();

const toSummary = (conversation: ChatConversation): ChatConversationSummary => {
  const lastMessage = conversation.messages[conversation.messages.length - 1];

  return {
    id: conversation.id,
    title: conversation.title,
    lastMessagePreview: lastMessage?.content.slice(0, 96) ?? "Sem mensagens ainda.",
    updatedAt: conversation.updatedAt,
    status: conversation.status,
  };
};

const buildAssistantReply = (content: string, attachments: ChatAttachment[]): string => {
  const topic = content.trim() || "novo contexto comercial";
  const attachmentLine =
    attachments.length > 0
      ? `Arquivos recebidos: ${attachments.map((attachment) => attachment.name).join(", ")}.`
      : "Nenhum arquivo foi anexado nesta mensagem.";

  return [
    "Fluxo mockado conectado com sucesso.",
    `Entendi que voce quer explorar: "${topic}".`,
    attachmentLine,
    "Proximo passo sugerido: transformar esta pergunta em um caso de uso do agent, com contexto, memoria curta e resposta estruturada para o time comercial.",
  ].join("\n\n");
};

const createMessage = ({
  role,
  content,
  attachments = [],
}: {
  role: ChatMessage["role"];
  content: string;
  attachments?: ChatAttachment[];
}): ChatMessage => ({
  id: randomUUID(),
  role,
  content,
  createdAt: nowIso(),
  attachments: attachments.length > 0 ? attachments : null,
});

const seedConversation = ({
  title,
  suggestedPrompts,
  messages,
}: {
  title: string;
  suggestedPrompts: string[];
  messages: ChatMessage[];
}): ChatConversation => {
  const timestamp = nowIso();

  return {
    id: randomUUID(),
    title,
    createdAt: timestamp,
    updatedAt: timestamp,
    status: "active",
    suggestedPrompts,
    messages,
  };
};

const conversations = new Map<string, ChatConversation>(
  [
    seedConversation({
      title: "Estrutura inicial do agente",
      suggestedPrompts: [
        "Quais contratos precisamos entre web, gateway e agent?",
        "Como eu separo intent, contexto e resposta comercial?",
        "Quais dados minimos eu devo guardar por conversa?",
      ],
      messages: [
        createMessage({
          role: "assistant",
          content:
            "Bem-vindo. Esta tela ja esta conectada ao gateway com dados mockados para voce experimentar o fluxo do futuro agent comercial.",
        }),
      ],
    }),
    seedConversation({
      title: "Roteamento gateway x API",
      suggestedPrompts: [
        "Quando uma mensagem deve ir para a API e quando deve ir para o agent?",
        "Como versionar os endpoints publicos?",
      ],
      messages: [
        createMessage({
          role: "user",
          content: "O gateway deve decidir o destino pela rota ou pelo corpo do JSON?",
        }),
        createMessage({
          role: "assistant",
          content:
            "Pela rota e pelo contrato publico. O corpo do JSON nao deve decidir o roteamento principal.",
        }),
      ],
    }),
  ].map((conversation) => [conversation.id, conversation]),
);

export const listChatConversations = (): ChatConversationSummary[] =>
  [...conversations.values()]
    .map(toSummary)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));

export const getChatConversation = (chatId: string): ChatConversation | null =>
  conversations.get(chatId) ?? null;

export const createChatConversation = (payload: CreateChatRequest | null | undefined): ChatConversation => {
  const initialPrompt = payload?.initialPrompt?.trim() ?? "";
  const title = payload?.title?.trim() || initialPrompt.slice(0, 42) || "Nova conversa";
  const starterAssistantMessage = createMessage({
    role: "assistant",
    content:
      "Conversa criada. Envie sua pergunta comercial, anexe arquivos se quiser, e o gateway podera encaminhar este fluxo para o agent no proximo passo.",
  });

  const conversation: ChatConversation = {
    id: randomUUID(),
    title,
    createdAt: nowIso(),
    updatedAt: nowIso(),
    status: "draft",
    suggestedPrompts: [
      "Quero montar meu primeiro prompt comercial.",
      "Como devo estruturar um briefing de cliente?",
      "Quais arquivos valem a pena anexar para enriquecer a resposta?",
    ],
    messages: initialPrompt
      ? [createMessage({ role: "user", content: initialPrompt }), starterAssistantMessage]
      : [starterAssistantMessage],
  };

  conversations.set(conversation.id, conversation);
  return conversation;
};

export const appendChatMessage = (
  chatId: string,
  payload: SendChatMessageRequest,
): ChatConversation | null => {
  const conversation = conversations.get(chatId);

  if (!conversation) {
    return null;
  }

  const attachments = (payload.attachments ?? []).map((attachment) => ({
    ...attachment,
    status: "reviewed" as const,
  }));

  const userMessage = createMessage({
    role: "user",
    content: payload.content.trim(),
    attachments,
  });
  const assistantReply = createMessage({
    role: "assistant",
    content: buildAssistantReply(payload.content, attachments),
  });

  const updatedConversation: ChatConversation = {
    ...conversation,
    title:
      conversation.messages.length <= 1 && payload.content.trim().length > 0
        ? payload.content.trim().slice(0, 42)
        : conversation.title,
    updatedAt: assistantReply.createdAt,
    status: "active",
    messages: [...conversation.messages, userMessage, assistantReply],
  };

  conversations.set(chatId, updatedConversation);
  return updatedConversation;
};
