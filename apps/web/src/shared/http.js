const createTraceId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};
export const createBaseRequest = ({ data = null, metadata = null, traceId = createTraceId(), timestamp = new Date().toISOString(), } = {}) => ({
    data,
    metadata,
    traceId,
    timestamp,
});
const canSendBody = (method) => method !== "GET";
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const executeWithRetry = async (operation, retries = 3, baseDelayMs = 250) => {
    let attempt = 0;
    while (true) {
        try {
            return await operation();
        }
        catch (error) {
            if (attempt >= retries) {
                throw error;
            }
            const delayMs = baseDelayMs * 2 ** attempt;
            await wait(delayMs);
            attempt += 1;
        }
    }
};
export const requestApi = async ({ url, method = "GET", data = null, metadata = null, headers, errorMessage, }) => {
    return executeWithRetry(async () => {
        const baseRequest = createBaseRequest({
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
        const payload = (await response.json().catch(() => null));
        if (!payload) {
            throw new Error(`${errorMessage} A resposta recebida nao segue o contrato esperado.`);
        }
        if (!response.ok || !payload.success) {
            throw new Error(payload.error ?? payload.message ?? errorMessage);
        }
        return payload;
    });
};
