import type { BaseResponse, HealthStatus, Measure } from "@leitesol/contracts";

import { env } from "../config/env.js";

export interface BackendTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export class BackendRequestError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number,
  ) {
    super(message);
  }
}

export const authenticateBackend = async (
  credentials: LoginCredentials,
  traceId: string,
): Promise<BackendTokenResponse> => {
  const response = await fetch(`${env.backendUrl}/token`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-request-id": traceId,
    },
    body: JSON.stringify(credentials),
  });

  if (!response.ok) {
    throw new BackendRequestError("Usuário ou senha inválidos.", response.status);
  }

  return (await response.json()) as BackendTokenResponse;
};

export const fetchBackendHealth = async (traceId: string): Promise<BaseResponse<HealthStatus>> => {
  const response = await fetch(`${env.backendUrl}/health`, {
    headers: {
      "x-api-key": env.backendApiKey,
      "x-request-id": traceId,
    },
  });

  if (!response.ok) {
    throw new Error(`Backend unavailable: ${response.status}`);
  }

  return (await response.json()) as BaseResponse<HealthStatus>;
};

export const fetchBackendMeasures = async (
  traceId: string,
  authorization?: string,
): Promise<BaseResponse<Measure[]>> => {
  const response = await fetch(`${env.backendUrl}/fabric/measures`, {
    headers: {
      "x-api-key": env.backendApiKey,
      "x-request-id": traceId,
      ...(authorization ? { authorization } : {}),
    },
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as BaseResponse<Measure[]> | null;
    if (payload) {
      return payload;
    }
    throw new Error(`Backend unavailable: ${response.status}`);
  }

  return (await response.json()) as BaseResponse<Measure[]>;
};
