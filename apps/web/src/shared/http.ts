import type { BaseRequest, BaseResponse } from "@leitesol/contracts";

import { notifySessionExpired } from "./auth-session";

type RequestMetadata = Record<string, unknown>;
type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

class ApiResponseError extends Error {}

interface CreateBaseRequestParams<TData, TMetadata> {
  data?: TData | null;
  metadata?: TMetadata | null;
  traceId?: string | null;
  timestamp?: string | null;
}

interface ApiRequestOptions<
  TResponseData,
  TRequestData,
  TRequestMetadata,
  TResponseMetadata,
> {
  url: string;
  method?: HttpMethod;
  data?: TRequestData | null;
  metadata?: TRequestMetadata | null;
  headers?: HeadersInit;
  errorMessage: string;
}

const createTraceId = (): string => {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }

  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const sendWebLog = (
  traceId: string,
  method: HttpMethod,
  path: string,
  statusCode: number,
  durationMs: number,
): void => {
  const severity =
    statusCode >= 500 ? "error" : statusCode >= 400 ? "warning" : "info";
  void fetch("/api/client-logs", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      traceId,
      timestamp: new Date().toISOString(),
      severity,
      request: { method, path },
      response: { statusCode, durationMs: Number(durationMs.toFixed(2)) },
    }),
  }).catch((error: unknown) => {
    console.warn("Não foi possível enviar o log técnico da web.", error);
  });
};

export const fetchWithWebLogging = async (
  url: string,
  init: RequestInit,
  traceId = createTraceId(),
): Promise<Response> => {
  const method = (init.method ?? "GET").toUpperCase() as HttpMethod;
  const path = new URL(url, window.location.origin).pathname;
  const startedAt = performance.now();

  try {
    const response = await fetch(url, init);
    if (path !== "/api/client-logs") {
      sendWebLog(traceId, method, path, response.status, performance.now() - startedAt);
    }
    return response;
  } catch (error) {
    if (path !== "/api/client-logs") {
      sendWebLog(traceId, method, path, 503, performance.now() - startedAt);
    }
    throw error;
  }
};

export const createBaseRequest = <
  TData = unknown,
  TMetadata = RequestMetadata,
>({
  data = null,
  metadata = null,
  traceId = createTraceId(),
  timestamp = new Date().toISOString(),
}: CreateBaseRequestParams<TData, TMetadata> = {}): BaseRequest<
  TData,
  TMetadata
> => ({
  data,
  metadata,
  traceId,
  timestamp,
});

const canSendBody = (method: HttpMethod): boolean => method !== "GET";

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

const executeWithRetry = async <T>(
  operation: () => Promise<T>,
  retries = 3,
  baseDelayMs = 250,
): Promise<T> => {
  let attempt = 0;

  while (true) {
    try {
      return await operation();
    } catch (error) {
      if (error instanceof ApiResponseError) {
        throw error;
      }
      if (attempt >= retries) {
        throw error;
      }

      const delayMs = baseDelayMs * 2 ** attempt;

      await wait(delayMs);

      attempt += 1;
    }
  }
};

export const requestApi = async <
  TResponseData,
  TRequestData = unknown,
  TRequestMetadata = RequestMetadata,
  TResponseMetadata = RequestMetadata,
>({
  url,
  method = "GET",
  data = null,
  metadata = null,
  headers,
  errorMessage,
}: ApiRequestOptions<
  TResponseData,
  TRequestData,
  TRequestMetadata,
  TResponseMetadata
>): Promise<BaseResponse<TResponseData, TResponseMetadata>> => {
  return executeWithRetry(async () => {
    const baseRequest = createBaseRequest<
      TRequestData,
      TRequestMetadata
    >({
      data,
      metadata,
    });

    const response = await fetchWithWebLogging(url, {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        "X-Request-ID": baseRequest.traceId ?? "",
        ...(canSendBody(method)
          ? { "Content-Type": "application/json" }
          : {}),
        ...headers,
      },
      body: canSendBody(method)
        ? JSON.stringify(baseRequest)
        : undefined,
    });

    const payload = (await response.json().catch(() => null)) as
      | BaseResponse<TResponseData, TResponseMetadata>
      | null;

    if (response.status === 401) {
      notifySessionExpired();
    }

    if (!payload) {
      throw new Error(
        `${errorMessage} A resposta recebida nao segue o contrato esperado.`,
      );
    }

    if (!response.ok || !payload.success) {
      throw new ApiResponseError(
        payload.error ??
          payload.message ??
          errorMessage,
      );
    }

    return payload;
  });
};