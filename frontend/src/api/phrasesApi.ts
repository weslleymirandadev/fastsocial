import { apiRequest } from "./httpClient";
import type { Phrase } from "../types/domain";

let phrasesCache: Phrase[] | null = null;

export async function fetchPhrases(options?: { force?: boolean }): Promise<Phrase[]> {
  if (!options?.force && phrasesCache) {
    return phrasesCache;
  }
  const data = await apiRequest<Phrase[]>("/proxy/phrases/");
  phrasesCache = data || [];
  return phrasesCache;
}

export async function createPhrase(payload: {
  text: string;
  order: number;
  cliente: boolean;
}): Promise<void> {
  await apiRequest("/proxy/phrases/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  phrasesCache = null;
}

export async function createPhrasesBulk(payloads: {
  text: string;
  order: number;
  cliente: boolean;
}[]): Promise<{ created: number; skipped: number; created_items?: any[]; errors?: any[] } | void> {
  if (payloads.length === 0) return;
  const result = await apiRequest<{ created: number; skipped: number; created_items?: any[]; errors?: any[] }>("/phrases/bulk", {
    method: "POST",
    body: JSON.stringify(payloads),
  });
  phrasesCache = null;
  return result;
}

export async function updatePhrase(id: number, payload: {
  text: string;
  order?: number | null;
  cliente: boolean;
}): Promise<void> {
  await apiRequest(`/proxy/phrases/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  phrasesCache = null;
}

export async function deletePhrase(id: number): Promise<void> {
  await apiRequest(`/proxy/phrases/${id}`, { method: "DELETE" });
  phrasesCache = null;
}
