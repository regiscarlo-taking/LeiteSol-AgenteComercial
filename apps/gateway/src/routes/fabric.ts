import { Router } from "express";

import { fetchBackendMeasures } from "../services/backend-client.js";

export const fabricRouter = Router();

fabricRouter.get("/fabric/measures", async (_request, response, next) => {
  try {
    const measures = await fetchBackendMeasures(response.locals.traceId);
    response.status(measures.statusCode).json(measures);
  } catch (error) {
    next(error);
  }
});