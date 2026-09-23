import { Router } from "express";

import { fetchBackendEntity, fetchBackendMeasures } from "../services/backend-client.js";

export const fabricRouter = Router();

fabricRouter.get("/fabric/measures", async (request, response, next) => {
  try {
    const measures = await fetchBackendMeasures(
      response.locals.traceId,
      request.header("authorization"),
    );
    response.status(measures.statusCode).json(measures);
  } catch (error) {
    next(error);
  }
});

fabricRouter.post("/fabric/query", async (request, response, next) => {
  try {
    const { entity, limit = 100 } = request.body as {
      entity?: unknown;
      limit?: unknown;
    };

    if (typeof entity !== "string" || entity.trim().length === 0) {
      response.status(400).json({ message: "Entity é obrigatória." });
      return;
    }

    const result = await fetchBackendEntity(
      response.locals.traceId,
      { entity, limit: typeof limit === "number" ? limit : 100 },
      request.header("authorization"),
    );
    response.status(result.statusCode).json(result);
  } catch (error) {
    next(error);
  }
});