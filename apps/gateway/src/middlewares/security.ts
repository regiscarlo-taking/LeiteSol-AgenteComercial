import type { NextFunction, Request, Response } from "express";

export const securityHeadersMiddleware = (_request: Request, response: Response, next: NextFunction) => {
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("X-Frame-Options", "DENY");
  response.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  response.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  response.setHeader("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none';");
  next();
};
