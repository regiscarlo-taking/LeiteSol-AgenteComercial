import type { BaseResponse, HealthStatus } from "@leitesol/contracts";

import { env } from "../config/env.js";

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
