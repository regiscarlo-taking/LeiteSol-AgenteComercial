import { Router } from "express";

import type { CreateChartRequest } from "@leitesol/contracts";

import {
  fetchBackendChart,
  fetchBackendChatQuery,
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
      response.status(400).json({ message: "Question is required." });
      return;
    }

    const result = await fetchBackendChatQuery(
      response.locals.traceId,
      question,
      request.header("authorization"),
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
