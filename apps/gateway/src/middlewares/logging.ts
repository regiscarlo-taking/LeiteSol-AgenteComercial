import type { NextFunction, Request, Response } from "express";
import { randomUUID } from "node:crypto";

import { persistGatewayLog } from "../services/backend-client.js";
import { clearAuthCookies } from "./session.js";

export const loggingMiddleware = (
  request: Request,
  response: Response,
  next: NextFunction,
) => {
  const startedAt = performance.now();
  const traceId = randomUUID();

  response.locals.traceId = traceId;
  request.headers["x-request-id"] = traceId;
  response.setHeader("X-Request-ID", traceId);

  const originalJson = response.json.bind(response);
  response.json = ((body: unknown) => {
    if (response.statusCode === 401) {
      clearAuthCookies(response);
    }
    return originalJson(body);
  }) as Response["json"];

  response.on("finish", () => {
    const durationMs = performance.now() - startedAt;
    const severity =
      response.statusCode >= 500
        ? "error"
        : response.statusCode >= 400
          ? "warning"
          : "info";
    const record = {
      traceId,
      timestamp: new Date().toISOString(),
      severity,
      request: {
        method: request.method,
        path: request.path,
      },
      response: {
        statusCode: response.statusCode,
        durationMs: Number(durationMs.toFixed(2)),
      },
    } as const;
    const logMethod =
      severity === "error" ? console.error : severity === "warning" ? console.warn : console.info;
    logMethod(JSON.stringify(record));
    void persistGatewayLog(record).catch(() => {
      console.warn(
        JSON.stringify({
          traceId,
          severity: "warning",
          message: "Gateway log could not be forwarded to the API.",
        }),
      );
    });
  });

  next();
};
