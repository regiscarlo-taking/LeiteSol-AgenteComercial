import { Router } from "express";
import type { BaseRequest, CreateChatRequest, SendChatMessageRequest } from "@leitesol/contracts";

import {
  appendChatMessage,
  createChatConversation,
  getChatConversation,
  listChatConversations,
} from "../services/mock-chat-service.js";
import { createBaseResponse } from "../shared/contracts.js";

export const chatsRouter = Router();

chatsRouter.get("/chats", (_request, response) => {
  response.status(200).json(
    createBaseResponse({
      data: listChatConversations(),
      message: "Chat list loaded successfully.",
      statusCode: 200,
      traceId: response.locals.traceId ?? "gateway-chats",
    }),
  );
});

chatsRouter.post("/chats", (request, response) => {
  const payload = (request.body as BaseRequest<CreateChatRequest> | undefined)?.data;
  const conversation = createChatConversation(payload);

  response.status(201).json(
    createBaseResponse({
      data: conversation,
      message: "Chat created successfully.",
      statusCode: 201,
      traceId: response.locals.traceId ?? "gateway-chat-create",
    }),
  );
});

chatsRouter.get("/chats/:chatId", (request, response) => {
  const conversation = getChatConversation(request.params.chatId);

  if (!conversation) {
    response.status(404).json(
      createBaseResponse({
        data: null,
        error: "Chat not found.",
        message: "Chat not found.",
        statusCode: 404,
        traceId: response.locals.traceId ?? "gateway-chat-not-found",
      }),
    );
    return;
  }

  response.status(200).json(
    createBaseResponse({
      data: conversation,
      message: "Chat loaded successfully.",
      statusCode: 200,
      traceId: response.locals.traceId ?? "gateway-chat-detail",
    }),
  );
});

chatsRouter.post("/chats/:chatId/messages", (request, response) => {
  const payload = (request.body as BaseRequest<SendChatMessageRequest> | undefined)?.data;

  if (!payload || (!payload.content.trim() && (payload.attachments?.length ?? 0) === 0)) {
    response.status(400).json(
      createBaseResponse({
        data: null,
        error: "Message content or attachments are required.",
        message: "Invalid chat message payload.",
        statusCode: 400,
        traceId: response.locals.traceId ?? "gateway-chat-invalid-payload",
      }),
    );
    return;
  }

  const conversation = appendChatMessage(request.params.chatId, payload);

  if (!conversation) {
    response.status(404).json(
      createBaseResponse({
        data: null,
        error: "Chat not found.",
        message: "Chat not found.",
        statusCode: 404,
        traceId: response.locals.traceId ?? "gateway-chat-message-not-found",
      }),
    );
    return;
  }

  response.status(201).json(
    createBaseResponse({
      data: {
        conversation,
        reply: conversation.messages[conversation.messages.length - 1],
      },
      message: "Chat message processed successfully.",
      statusCode: 201,
      traceId: response.locals.traceId ?? "gateway-chat-message",
    }),
  );
});
