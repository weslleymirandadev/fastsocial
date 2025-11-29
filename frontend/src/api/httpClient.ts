export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE" | "PATCH";

export interface ApiRequestOptions extends RequestInit {
  method?: HttpMethod;
}

const BACKEND_BASE_URL = "http://localhost:8000";

export async function apiRequest<T = unknown>(
  path: string,
  options?: ApiRequestOptions,
): Promise<T> {
  const res = await fetch(`${BACKEND_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options && options.headers),
    },
    ...options,
  });

  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    let message = `Erro HTTP ${res.status}`;
    if (data && typeof data === "object") {
      const anyData = data as any;
      if (typeof anyData.detail === "string") {
        message = anyData.detail;
      } else {
        try {
          message = JSON.stringify(data);
        } catch {
          // mantém mensagem padrão
        }
      }
    } else if (typeof data === "string" && data.trim()) {
      message = data;
    }
    throw new Error(message);
  }

  return data as T;
}
