import { Router } from "express";

import {
  BackendRequestError,
  persistWebLog,
  type GatewayLogRecord,
} from "../services/backend-client.js";

export const webLogsRouter = Router();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isWebLogRecord = (value: unknown): value is GatewayLogRecord => {
  if (!isRecord(value) || !isRecord(value.request) || !isRecord(value.response)) {
    return false;
  }

  const { request, response } = value;
  return (
    typeof value.traceId === "string" &&
    value.traceId.length > 0 &&
    value.traceId.length <= 64 &&
    typeof value.timestamp === "string" &&
    Number.isFinite(Date.parse(value.timestamp)) &&
    (value.severity === "info" || value.severity === "warning" || value.severity === "error") &&
    typeof request.method === "string" &&
    ["GET", "POST", "PUT", "PATCH", "DELETE"].includes(request.method) &&
    typeof request.path === "string" &&
    request.path.startsWith("/") &&
    request.path.length <= 2048 &&
    !request.path.includes("?") &&
    !request.path.includes("#") &&
    Number.isInteger(response.statusCode) &&
    Number(response.statusCode) >= 100 &&
    Number(response.statusCode) <= 599 &&
    typeof response.durationMs === "number" &&
    Number.isFinite(response.durationMs) &&
    response.durationMs >= 0
  );
};

webLogsRouter.post("/client-logs", async (request, response, next) => {
  if (!isWebLogRecord(request.body)) {
    response.status(400).json({ message: "Invalid web log record." });
    return;
  }

  try {
    await persistWebLog(request.body);
    response.status(202).json({ accepted: true });
  } catch (error) {
    if (error instanceof BackendRequestError) {
      response.status(error.statusCode).json({ message: error.message });
      return;
    }
    next(error);
  }
});
