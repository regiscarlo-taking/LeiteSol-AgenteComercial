import type { NextFunction, Request, Response } from "express";

export const accessTokenCookie = "access_token";
export const refreshTokenCookie = "refresh_token";

export const cookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

export const getAccessToken = (request: Request): string | undefined => {
  const cookieHeader = request.headers.cookie;
  if (!cookieHeader) {
    return undefined;
  }

  for (const cookie of cookieHeader.split(";")) {
    const [name, ...valueParts] = cookie.trim().split("=");
    if (name !== accessTokenCookie) {
      continue;
    }

    try {
      const value = decodeURIComponent(valueParts.join("="));
      return value || undefined;
    } catch {
      return undefined;
    }
  }

  return undefined;
};

export const clearAuthCookies = (response: Response): void => {
  response.clearCookie(accessTokenCookie, cookieOptions);
  response.clearCookie(refreshTokenCookie, cookieOptions);
};

export const requireSessionCookie = (
  request: Request,
  response: Response,
  next: NextFunction,
): void => {
  const accessToken = getAccessToken(request);
  if (!accessToken) {
    clearAuthCookies(response);
    response.status(401).json({ message: "Authentication required." });
    return;
  }

  request.headers.authorization = `Bearer ${accessToken}`;
  next();
};
