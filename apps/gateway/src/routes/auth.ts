import { Router } from "express";

import {
  authenticateBackend,
  BackendRequestError,
} from "../services/backend-client.js";

export const authRouter = Router();

const accessTokenCookie = "access_token";
const refreshTokenCookie = "refresh_token";

const cookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

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

    response.cookie(
      accessTokenCookie,
      token.access_token,
      {
        ...cookieOptions,
        maxAge: token.expires_in * 1000,
      },
    );

    response.cookie(
      refreshTokenCookie,
      token.refresh_token,
      cookieOptions,
    );

    response.status(200).json({
      authenticated: true,
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

authRouter.get("/auth/session", (request, response) => {
  const accessToken = request.headers.cookie
    ?.split(";")
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith(`${accessTokenCookie}=`))
    ?.split("=")
    .slice(1)
    .join("=");

  if (!accessToken) {
    response.status(401).json({
      authenticated: false,
    });
    return;
  }

  response.status(200).json({
    authenticated: true,
  });
});

authRouter.post("/auth/logout", (_request, response) => {
  response.clearCookie(accessTokenCookie, cookieOptions);
  response.clearCookie(refreshTokenCookie, cookieOptions);

  response.status(200).json({
    authenticated: false,
  });
});