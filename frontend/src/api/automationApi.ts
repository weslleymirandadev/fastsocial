import { apiRequest } from "./httpClient";
import type { BackendStatus } from "../types/domain";

let statusCache: BackendStatus | null = null;

export async function fetchBackendStatus(options?: { force?: boolean }): Promise<BackendStatus> {
  if (!options?.force && statusCache) {
    return statusCache;
  }
  const data = await apiRequest<BackendStatus>("/");
  statusCache = data;
  return data;
}

export async function startAutomation(): Promise<void> {
  await apiRequest("/start/", { method: "POST" });
  statusCache = null;
}

export async function stopAutomationImmediate(): Promise<void> {
  await apiRequest("/stop-immediate/", { method: "POST" });
  statusCache = null;
}