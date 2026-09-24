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

export interface EntityQueryRequest {
  entity: string;
  limit: number;
}

export interface SqlResultResponse {
  entity: string;
  sql?: string | null;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
}

export interface ChatQueryResponse {
  answer: string;
  sqlResult: SqlResultResponse;
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

export const fetchBackendEntity = async (
  traceId: string,
  query: EntityQueryRequest,
  authorization?: string,
): Promise<BaseResponse<SqlResultResponse>> => {
  const response = await fetch(`${env.backendUrl}/fabric/query`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": env.backendApiKey,
      "x-request-id": traceId,
      ...(authorization ? { authorization } : {}),
    },
    body: JSON.stringify(query),
  });

  const payload = (await response.json().catch(() => null)) as BaseResponse<SqlResultResponse> | null;
  if (!payload) {
    throw new Error(`Backend unavailable: ${response.status}`);
  }
  return payload;
};

export const fetchBackendChatQuery = async (
  traceId: string,
  question: string,
  authorization?: string,
): Promise<BaseResponse<ChatQueryResponse>> => {
  const response = await fetch(`${env.backendUrl}/chat/query`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-request-id": traceId,
      ...(authorization ? { authorization } : {}),
    },
    body: JSON.stringify({ question }),
  });
  const payload = (await response.json().catch(() => null)) as BaseResponse<ChatQueryResponse> | null;
  if (!payload) throw new Error(`Backend unavailable: ${response.status}`);
  return payload;
};
