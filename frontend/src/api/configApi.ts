import { apiRequest } from "./httpClient";

export interface ConfigItem {
  key: string;
  value: string;
  description?: string | null;
}

const configCache = new Map<string, ConfigItem>();

export async function fetchConfig(key: string): Promise<ConfigItem> {
  const cached = configCache.get(key);
  if (cached) {
    return cached;
  }
  const data = await apiRequest<ConfigItem>(`/proxy/config/`, {
    method: "POST",
    body: JSON.stringify({ key }),
  });
  configCache.set(key, data);
  return data;
}

export async function fetchAllConfigs(): Promise<Record<string, ConfigItem>> {
  const data = await apiRequest<Record<string, ConfigItem>>(`/proxy/config/`);
  return data;
}

export async function saveConfig(key: string, value: string, description: string): Promise<void> {
  const params = new URLSearchParams();
  params.set("value", value);
  if (description) {
    params.set("description", description);
  }
  await apiRequest(`/proxy/config/`, {
    method: "POST",
    body: JSON.stringify({ key, value, description }),
  });
  configCache.set(key, { key, value, description });
}

export async function saveConfigs(items: Record<string, string | { value: string; description?: string }>): Promise<void> {
  // Convert items into the expected upstream shape: value or {value, description}
  await apiRequest(`/proxy/config/`, {
    method: "POST",
    body: JSON.stringify(items),
  });

  // Update cache
  for (const [key, v] of Object.entries(items)) {
    if (typeof v === "string") {
      configCache.set(key, { key, value: v, description: "" });
    } else {
      configCache.set(key, { key, value: v.value, description: v.description ?? "" });
    }
  }
}
