const accessTokenKey = "leitesol_access_token";
const refreshTokenKey = "leitesol_refresh_token";
export const authExpiredEvent = "leitesol-auth-expired";

interface JwtPayload {
  exp?: unknown;
}

const isBrowser = (): boolean => typeof window !== "undefined";

const notifySessionExpired = (): void => {
  if (isBrowser()) {
    window.dispatchEvent(new Event(authExpiredEvent));
  }
};

export const clearAuthSession = (notify = false): void => {
  if (!isBrowser()) return;

  localStorage.removeItem(accessTokenKey);
  localStorage.removeItem(refreshTokenKey);
  if (notify) notifySessionExpired();
};

export const saveAuthSession = (accessToken: string, refreshToken: string): void => {
  localStorage.setItem(accessTokenKey, accessToken);
  localStorage.setItem(refreshTokenKey, refreshToken);
};

const readTokenExpiration = (token: string): number | null => {
  try {
    const encodedPayload = token.split(".")[1];
    if (!encodedPayload) return null;
    const payload = JSON.parse(atob(encodedPayload.replace(/-/g, "+").replace(/_/g, "/"))) as JwtPayload;
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
};

export const getValidAccessToken = (): string | null => {
  if (!isBrowser()) return null;

  const token = localStorage.getItem(accessTokenKey);
  if (!token) return null;

  const expiresAt = readTokenExpiration(token);
  if (expiresAt === null || expiresAt <= Math.floor(Date.now() / 1000)) {
    clearAuthSession(true);
    return null;
  }

  return token;
};

export const hasValidAuthSession = (): boolean => Boolean(getValidAccessToken());
