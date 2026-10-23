import type { NextFunction, Request, Response } from "express";
import { randomUUID } from "node:crypto";

import {
  BackendRequestError,
  persistGatewayLog,
} from "../services/backend-client.js";
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
    const forwardingStartedAt = performance.now();
    void persistGatewayLog(record)
      .then((result) => {
        const skipped = result === "skipped_missing_api_key";
        const event = {
          event: "gateway_log_forward",
          traceId,
          severity: skipped ? "warning" : "info",
          result: skipped ? "skipped" : "forwarded",
          reason: skipped ? "backend_api_key_missing" : undefined,
          durationMs: Number(
            (performance.now() - forwardingStartedAt).toFixed(2),
          ),
        };
        (skipped ? console.warn : console.info)(JSON.stringify(event));
      })
      .catch((error: unknown) => {
        const statusCode =
          error instanceof BackendRequestError ? error.statusCode : undefined;
        const severity =
          statusCode !== undefined && statusCode < 500 ? "warning" : "error";
        const event = {
          event: "gateway_log_forward",
          traceId,
          severity,
          result: "failed",
          statusCode,
          errorType:
            error instanceof Error ? error.constructor.name : "UnknownError",
          durationMs: Number(
            (performance.now() - forwardingStartedAt).toFixed(2),
          ),
        };
        (severity === "error" ? console.error : console.warn)(
          JSON.stringify(event),
        );
      });
  });

  next();
};
