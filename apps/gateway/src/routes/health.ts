import { Router } from "express";

import { fetchBackendHealth } from "../services/backend-client.js";

export const healthRouter = Router();

healthRouter.get("/health", async (_request, response, next) => {
  try {
    const status = await fetchBackendHealth(response.locals.traceId);
    response.status(status.statusCode).json(status);
  } catch (error) {
    next(error);
  }
});
