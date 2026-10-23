import type {
  BaseResponse,
  ChartSpecification,
  ChatConversation,
  ChatConversationSummary,
  CreateChartRequest,
  HealthStatus,
  Measure,
} from "@leitesol/contracts";

import { env } from "../config/env.js";

export interface BackendTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface BackendSessionResponse {
  authenticated: boolean;
  expiresAt: number;
}

export interface GatewayLogRecord {
  traceId: string;
  timestamp: string;
  severity: "info" | "warning" | "error";
  request: {
    method: string;
    path: string;
  };
  response: {
    statusCode: number;
    durationMs: number;
  };
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
  sql: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
}

export interface ChatQueryResponse {
  answer: string;
  sqlResult: SqlResultResponse;
  chatId: string;
}

export class BackendRequestError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number,
  ) {
    super(message);
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isBackendEnvelope = (value: unknown): value is BaseResponse<unknown> =>
  isRecord(value) &&
  "data" in value &&
  typeof value.statusCode === "number" &&
  typeof value.message === "string" &&
  typeof value.success === "boolean" &&
  typeof value.traceId === "string" &&
  typeof value.timestamp === "string";

const readBackendEnvelope = async <T>(
  response: Response,
): Promise<BaseResponse<T>> => {
  const payload: unknown = await response.json().catch(() => null);
  if (isBackendEnvelope(payload)) {
    return { ...payload, data: payload.data as T | null };
  }

  if (response.status === 401) {
    throw new BackendRequestError("Authentication required.", 401);
  }
  throw new BackendRequestError(
    `Backend returned an invalid response: ${response.status}`,
    response.status,
  );
};

const requestBackend = async (
  url: string,
  options?: RequestInit,
): Promise<Response> => {
  try {
    return await fetch(url, options);
  } catch {
    throw new BackendRequestError(
      "A API não está acessível. Inicie a API e confirme BACKEND_URL.",
      503,
    );
  }
};

const authorizationHeader = (
  authorization?: string,
): Record<string, string> =>
  authorization
    ? {
        Authorization: authorization,
      }
    : {};

export const authenticateBackend = async (
  credentials: LoginCredentials,
  traceId: string,
): Promise<BackendTokenResponse> => {
  const response = await requestBackend(
    `${env.backendUrl}/token`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-request-id": traceId,
      },
      body: JSON.stringify(credentials),
    },
  );

  if (!response.ok) {
    throw new BackendRequestError(
      "Usuário ou senha inválidos.",
      response.status,
    );
  }

  return (await response.json()) as BackendTokenResponse;
};

export const validateBackendSession = async (
  traceId: string,
  authorization: string,
): Promise<BackendSessionResponse | null> => {
  const response = await requestBackend(`${env.backendUrl}/auth/session`, {
    headers: {
      "x-api-key": env.backendApiKey,
      "x-request-id": traceId,
      ...authorizationHeader(authorization),
    },
  });

  if (response.status === 401) {
    return null;
  }

  const payload = (await response.json().catch(() => null)) as
    | BackendSessionResponse
    | null;
  if (!response.ok || !payload?.authenticated || !Number.isFinite(payload.expiresAt)) {
    throw new BackendRequestError(
      `Backend session validation failed: ${response.status}`,
      response.status,
    );
  }
  return payload;
};

export const persistGatewayLog = async (
  record: GatewayLogRecord,
): Promise<"forwarded" | "skipped_missing_api_key"> => {
  if (!env.backendApiKey) {
    return "skipped_missing_api_key";
  }

  const response = await requestBackend(`${env.backendUrl}/internal/gateway-logs`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": env.backendApiKey,
      "x-request-id": record.traceId,
    },
    body: JSON.stringify(record),
  });

  if (!response.ok) {
    throw new BackendRequestError(
      `Gateway log ingestion failed: ${response.status}`,
      response.status,
    );
  }
  return "forwarded";
};

export const fetchBackendHealth = async (
  traceId: string,
  authorization?: string,
): Promise<BaseResponse<HealthStatus>> => {
  const response = await requestBackend(
    `${env.backendUrl}/health`,
    {
      headers: {
        "x-api-key": env.backendApiKey,
        "x-request-id": traceId,
        ...authorizationHeader(authorization),
      },
    },
  );

  if (!response.ok) {
    throw new BackendRequestError(
      `Backend unavailable: ${response.status}`,
      response.status,
    );
  }

  return (await response.json()) as BaseResponse<HealthStatus>;
};

export const fetchBackendMeasures = async (
  traceId: string,
  authorization?: string,
): Promise<BaseResponse<Measure[]>> => {
  const response = await requestBackend(
    `${env.backendUrl}/fabric/measures`,
    {
      headers: {
        "x-api-key": env.backendApiKey,
        "x-request-id": traceId,
        ...authorizationHeader(authorization),
      },
    },
  );

  return readBackendEnvelope<Measure[]>(response);
};

export const fetchBackendEntity = async (
  traceId: string,
  query: EntityQueryRequest,
  authorization?: string,
): Promise<BaseResponse<SqlResultResponse>> => {
  const response = await requestBackend(
    `${env.backendUrl}/fabric/query`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": env.backendApiKey,
        "x-request-id": traceId,
        ...authorizationHeader(authorization),
      },
      body: JSON.stringify(query),
    },
  );

  return readBackendEnvelope<SqlResultResponse>(response);
};

export const fetchBackendChatQuery = async (
  traceId: string,
  question: string,
  authorization?: string,
  chatId?: string,
): Promise<BaseResponse<ChatQueryResponse>> => {
  const response = await requestBackend(
    `${env.backendUrl}/chat/query`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-request-id": traceId,
        ...authorizationHeader(authorization),
      },
      body: JSON.stringify({
        question,
        ...(chatId ? { chatId } : {}),
      }),
    },
  );

  return readBackendEnvelope<ChatQueryResponse>(response);
};

export const fetchBackendChats = async (
  traceId: string,
  authorization?: string,
): Promise<BaseResponse<ChatConversationSummary[]>> => {
  const response = await requestBackend(`${env.backendUrl}/chats`, {
    headers: {
      "x-request-id": traceId,
      ...authorizationHeader(authorization),
    },
  });

  return readBackendEnvelope<ChatConversationSummary[]>(response);
};

export const fetchBackendChat = async (
  traceId: string,
  chatId: string,
  authorization?: string,
): Promise<BaseResponse<ChatConversation>> => {
  const response = await requestBackend(
    `${env.backendUrl}/chats/${encodeURIComponent(chatId)}`,
    {
      headers: {
        "x-request-id": traceId,
        ...authorizationHeader(authorization),
      },
    },
  );

  return readBackendEnvelope<ChatConversation>(response);
};

export const fetchBackendChart = async (
  traceId: string,
  chart: CreateChartRequest,
  authorization?: string,
): Promise<BaseResponse<ChartSpecification>> => {
  const response = await requestBackend(`${env.backendUrl}/chat/chart`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-request-id": traceId,
      ...authorizationHeader(authorization),
    },
    body: JSON.stringify(chart),
  });

  return readBackendEnvelope<ChartSpecification>(response);
};