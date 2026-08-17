import type { NextFunction, Request, Response } from "express";
import { randomUUID } from "node:crypto";

export const loggingMiddleware = (request: Request, response: Response, next: NextFunction) => {
  const startedAt = performance.now();
  const traceId = request.header("x-request-id") ?? randomUUID();

  response.locals.traceId = traceId;
  response.setHeader("X-Request-ID", traceId);

  response.on("finish", () => {
    const durationMs = performance.now() - startedAt;
    console.info(
      `[gateway] traceId=${traceId} method=${request.method} path=${request.originalUrl} status=${response.statusCode} durationMs=${durationMs.toFixed(2)}`,
    );
  });

  next();
};
