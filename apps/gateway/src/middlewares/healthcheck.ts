// Avoid depending on external @types/express in this file to prevent
// "Cannot find module 'express' or its corresponding type declarations"
// errors in environments where those types are not installed.
// Define minimal local types sufficient for this middleware.
type Request = {
  path: string;
  // allow indexing for any other properties used elsewhere
  [key: string]: any;
};

type Response = {
  locals: { traceId?: string } & { [key: string]: any };
  status: (code: number) => Response;
  json: (body: any) => Response;
  [key: string]: any;
};

type NextFunction = () => void;

import { createBaseResponse } from "../shared/contracts.js";

export const healthcheckMiddleware = (request: Request, response: Response, next: NextFunction) => {
  if (request.path !== "/health/live") {
    next();
    return;
  }

  response.status(200).json(
    createBaseResponse({
      data: {
        service: "leitesol-gateway",
        status: "healthy",
        version: "v1",
      },
      message: "Gateway liveness check completed.",
      statusCode: 200,
      traceId: response.locals.traceId ?? "gateway-health",
    }),
  );
};
