import { Router } from "express";

import type { CreateChartRequest } from "@leitesol/contracts";

import {
  fetchBackendChart,
  fetchBackendChat,
  fetchBackendChatQuery,
  fetchBackendChats,
} from "../services/backend-client.js";

export const chatsRouter = Router();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

const isChartRequest = (value: unknown): value is CreateChartRequest => {
  if (!isRecord(value)) {
    return false;
  }

  const validChartType =
    value.chartType === undefined ||
    value.chartType === "auto" ||
    value.chartType === "bar" ||
    value.chartType === "line" ||
    value.chartType === "pie";
  const validTitle =
    value.title === undefined || value.title === null || typeof value.title === "string";
  const validRows =
    Array.isArray(value.rows) &&
    value.rows.every((row) => isRecord(row));

  return (
    isStringArray(value.columns) &&
    isStringArray(value.valueColumns) &&
    typeof value.categoryColumn === "string" &&
    validRows &&
    validChartType &&
    validTitle
  );
};

// Mesmo formato que a API aceita: chat-<uuid> ou outro id sem espaço/barra.
const isChatId = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);

// Histórico do usuário logado; a API filtra pelo dono do token.
chatsRouter.get("/chats", async (request, response, next) => {
  try {
    const result = await fetchBackendChats(
      response.locals.traceId,
      request.header("authorization"),
    );
    response.status(result.statusCode).json(result);
  } catch (error) {
    next(error);
  }
});

chatsRouter.get("/chats/:chatId", async (request, response, next) => {
  try {
    if (!isChatId(request.params.chatId)) {
      response.status(404).json({ message: "Chat not found." });
      return;
    }
    const result = await fetchBackendChat(
      response.locals.traceId,
      request.params.chatId,
      request.header("authorization"),
    );
    response.status(result.statusCode).json(result);
  } catch (error) {
    next(error);
  }
});

chatsRouter.post("/chat/query", async (request, response, next) => {
  try {
    const body = request.body as {
      question?: unknown;
      chatId?: unknown;
      data?: {
        question?: unknown;
        chatId?: unknown;
      } | null;
    };
    const question = body.data?.question ?? body.question;
    const rawChatId = body.data?.chatId ?? body.chatId;

    if (typeof question !== "string" || !question.trim()) {
      response.status(400).json({ message: "Question is required." });
      return;
    }

    if (rawChatId != null && !isChatId(rawChatId)) {
      response.status(400).json({ message: "Invalid chat id." });
      return;
    }
    const chatId = isChatId(rawChatId) ? rawChatId : undefined;

    const result = await fetchBackendChatQuery(
      response.locals.traceId,
      question,
      request.header("authorization"),
      chatId,
    );
    const logMethod =
      result.statusCode >= 500
        ? console.error
        : result.statusCode >= 400
          ? console.warn
          : console.info;
    logMethod(
      JSON.stringify({
        event: "chat_exchange",
        traceId: response.locals.traceId,
        question,
        response: {
          statusCode: result.statusCode,
          answer: result.data?.answer ?? null,
          sqlResult: result.data?.sqlResult ?? null,
        },
      }),
    );
    response.status(result.statusCode).json(result);
  } catch (error) {
    next(error);
  }
});

chatsRouter.post("/chat/chart", async (request, response, next) => {
  try {
    const body = request.body as { data?: unknown } | undefined;
    const chart = body?.data ?? request.body;
    if (!isChartRequest(chart)) {
      response.status(400).json({ message: "Chart data is required." });
      return;
    }

    const result = await fetchBackendChart(
      response.locals.traceId,
      chart,
      request.header("authorization"),
    );
    response.status(result.statusCode).json(result);
  } catch (error) {
    next(error);
  }
});
