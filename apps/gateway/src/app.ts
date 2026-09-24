import cors from "cors";
import express from "express";
import rateLimit from "express-rate-limit";
import type { NextFunction, Request, Response } from "express";

import { env } from "./config/env.js";
import { healthcheckMiddleware } from "./middlewares/healthcheck.js";
import { loggingMiddleware } from "./middlewares/logging.js";
import { securityHeadersMiddleware } from "./middlewares/security.js";
import { chatsRouter } from "./routes/chats.js";
import { authRouter } from "./routes/auth.js";
import { fabricRouter } from "./routes/fabric.js";
import { healthRouter } from "./routes/health.js";
import { createBaseResponse } from "./shared/contracts.js";
import { BackendRequestError } from "./services/backend-client.js";

export const createApp = () => {
  const app = express();
  app.disable("x-powered-by");

  app.use(loggingMiddleware);
  app.use(securityHeadersMiddleware);
  app.use(healthcheckMiddleware);
  app.use(
    rateLimit({
      windowMs: 60_000,
      max: 60,
      standardHeaders: true,
      legacyHeaders: false,
      message: {
        data: null,
        error: "Too many requests. Please retry later.",
        message: "Rate limit exceeded.",
        statusCode: 429,
        success: false,
        traceId: "gateway-rate-limit",
        timestamp: new Date().toISOString(),
      },
    }),
  );
  app.use(
    cors({
      origin: env.corsOrigins,
      credentials: true,
    }),
  );
  app.use(express.json());

  app.use("/api", healthRouter);
  app.use("/api", authRouter);
  app.use("/api", chatsRouter);
  app.use("/api", fabricRouter);

  app.use((error: Error, _request: Request, response: Response, _next: NextFunction) => {
    const statusCode = error instanceof BackendRequestError ? error.statusCode : 502;
    response.status(statusCode).json(
      createBaseResponse({
        data: null,
        error: error.message,
        message: "Gateway failed to process the request.",
        statusCode,
        traceId: response.locals.traceId ?? "gateway-error",
      }),
    );
  });

  return app;
};
