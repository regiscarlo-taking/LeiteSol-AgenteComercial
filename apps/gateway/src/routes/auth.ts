import { Router } from "express";

import { authenticateBackend, BackendRequestError } from "../services/backend-client.js";

export const authRouter = Router();

authRouter.post("/auth/token", async (request, response, next) => {
  try {
    const { username, password } = request.body as {
      username?: unknown;
      password?: unknown;
    };

    if (typeof username !== "string" || typeof password !== "string") {
      response.status(400).json({ message: "Usuário e senha são obrigatórios." });
      return;
    }

    const token = await authenticateBackend(
      { username, password },
      response.locals.traceId,
    );
    response.json(token);
  } catch (error) {
    if (error instanceof BackendRequestError) {
      response.status(error.statusCode).json({ message: error.message });
      return;
    }
    next(error);
  }
});