import type { BaseRequest, BaseResponse } from "@leitesol/contracts";

type RequestMetadata = Record<string, unknown>;
type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface CreateBaseRequestParams<TData, TMetadata> {
  data?: TData | null;
  metadata?: TMetadata | null;
  traceId?: string | null;
  timestamp?: string | null;
}

interface ApiRequestOptions<TResponseData, TRequestData, TRequestMetadata, TResponseMetadata> {
  url: string;
  method?: HttpMethod;
  data?: TRequestData | null;
  metadata?: TRequestMetadata | null;
  headers?: HeadersInit;
  errorMessage: string;
}

const createTraceId = (): string => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const createBaseRequest = <
  TData = unknown,
  TMetadata = RequestMetadata,
>({
  data = null,
  metadata = null,
  traceId = createTraceId(),
  timestamp = new Date().toISOString(),
}: CreateBaseRequestParams<TData, TMetadata> = {}): BaseRequest<TData, TMetadata> => ({
  data,
  metadata,
  traceId,
  timestamp,
});

const canSendBody = (method: HttpMethod): boolean => method !== "GET";

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

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
}: ApiRequestOptions<TResponseData, TRequestData, TRequestMetadata, TResponseMetadata>): Promise<
  BaseResponse<TResponseData, TResponseMetadata>
> => {
  return executeWithRetry(async () => {
    const baseRequest = createBaseRequest<TRequestData, TRequestMetadata>({
      data,
      metadata,
    });

    const response = await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
        "X-Request-ID": baseRequest.traceId ?? "",
        ...(canSendBody(method) ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: canSendBody(method) ? JSON.stringify(baseRequest) : undefined,
    });

    const payload = (await response.json().catch(() => null)) as BaseResponse<
      TResponseData,
      TResponseMetadata
    > | null;

    if (!payload) {
      throw new Error(`${errorMessage} A resposta recebida nao segue o contrato esperado.`);
    }

    if (!response.ok || !payload.success) {
      throw new Error(payload.error ?? payload.message ?? errorMessage);
    }

    return payload;
  });
};
