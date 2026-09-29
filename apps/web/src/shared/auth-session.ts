export const authExpiredEvent = "leitesol-auth-expired";

export const notifySessionExpired = (): void => {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(authExpiredEvent));
  }
};