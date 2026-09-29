import { Router } from "express";

import { fetchBackendChatQuery } from "../services/backend-client.js";

export const chatsRouter = Router();

const getCookie = (
  cookieHeader: string | undefined,
  name: string,
): string | undefined => {
  if (!cookieHeader) {
    return undefined;
  }

  const cookies = cookieHeader.split(";");

  for (const cookie of cookies) {
    const [key, ...valueParts] = cookie.trim().split("=");

    if (key === name) {
      return decodeURIComponent(valueParts.join("="));
    }
  }

  return undefined;
};

chatsRouter.post("/chat/query", async (request, response, next) => {
  try {
    const body = request.body as {
      question?: unknown;
      data?: {
        question?: unknown;
      } | null;
    };

    const question = body.data?.question ?? body.question;

    if (typeof question !== "string" || !question.trim()) {
      response.status(400).json({
        message: "Question is required.",
      });
      return;
    }

    const accessToken = getCookie(
      request.headers.cookie,
      "access_token",
    );

    if (!accessToken) {
      response.status(401).json({
        message: "Authentication required.",
      });
      return;
    }

    const result = await fetchBackendChatQuery(
      response.locals.traceId,
      question,
      `Bearer ${accessToken}`,
    );

    response.status(result.statusCode).json(result);
  } catch (error) {
    next(error);
  }
});