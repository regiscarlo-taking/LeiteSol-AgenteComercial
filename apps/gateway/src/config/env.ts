import { existsSync } from "node:fs";
import { resolve } from "node:path";

const localEnvFile = [
  resolve(process.cwd(), ".env"),
  resolve(process.cwd(), "..", "..", ".env"),
].find(existsSync);

if (localEnvFile) {
  process.loadEnvFile(localEnvFile);
}

const parsePort = (value: string | undefined, fallback: number): number => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
};

const parseList = (value: string | undefined, fallback: string[]): string[] => {
  if (!value) {
    return fallback;
  }

  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
};

export const env = {
  backendUrl: process.env.BACKEND_URL ?? "http://localhost:5000",
  backendApiKey: process.env.BACKEND_API_KEY ?? "",
  corsOrigins: parseList(process.env.CORS_ORIGINS, ["http://localhost:3000"]),
  port: parsePort(process.env.PORT, 3001),
};
