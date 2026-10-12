import { Router } from "express";

import {
  authenticateBackend,
  BackendRequestError,
  validateBackendSession,
} from "../services/backend-client.js";
import {
  accessTokenCookie,
  clearAuthCookies,
  cookieOptions,
  getAccessToken,
} from "../middlewares/session.js";

export const authRouter = Router();

const maxSessionAgeMs = 20 * 60 * 1000;

authRouter.post("/auth/login", async (request, response, next) => {
  try {
    const { username, password } = request.body as {
      username?: unknown;
      password?: unknown;
    };

    if (
      typeof username !== "string" ||
      typeof password !== "string"
    ) {
      response.status(400).json({
        message: "Usuário e senha são obrigatórios.",
      });
      return;
    }

    const token = await authenticateBackend(
      {
        username,
        password,
      },
      response.locals.traceId,
    );

    clearAuthCookies(response);
    response.cookie(
      accessTokenCookie,
      token.access_token,
      {
        ...cookieOptions,
        maxAge: Math.min(token.expires_in * 1000, maxSessionAgeMs),
      },
    );

    response.status(200).json({
      authenticated: true,
      expiresAt: Date.now() + Math.min(token.expires_in * 1000, maxSessionAgeMs),
    });
  } catch (error) {
    if (error instanceof BackendRequestError) {
      response
        .status(error.statusCode)
        .json({
          message: error.message,
        });
      return;
    }

    next(error);
  }
});

authRouter.get("/auth/session", async (request, response, next) => {
  const accessToken = getAccessToken(request);
  if (!accessToken) {
    response.status(401).json({
      authenticated: false,
    });
    return;
  }

  try {
    const session = await validateBackendSession(
      response.locals.traceId,
      `Bearer ${accessToken}`,
    );
    if (!session) {
      clearAuthCookies(response);
      response.status(401).json({ authenticated: false });
      return;
    }

    const expiresAt = Math.min(
      session.expiresAt * 1000,
      Date.now() + maxSessionAgeMs,
    );
    response.status(200).json({ authenticated: true, expiresAt });
  } catch (error) {
    next(error);
  }
});

authRouter.post("/auth/logout", (_request, response) => {
  clearAuthCookies(response);

  response.status(200).json({
    authenticated: false,
  });
});