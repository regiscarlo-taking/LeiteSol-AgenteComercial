import type { BaseResponse } from "@leitesol/contracts";

export const createBaseResponse = <TData>({
  data,
  error = null,
  message,
  metadata = null,
  statusCode,
  traceId,
}: {
  data: TData | null;
  error?: string | null;
  message: string;
  metadata?: Record<string, unknown> | null;
  statusCode: number;
  traceId: string;
}): BaseResponse<TData> => ({
  data,
  statusCode,
  message,
  error,
  success: !error && statusCode < 400,
  traceId,
  timestamp: new Date().toISOString(),
  metadata,
});
