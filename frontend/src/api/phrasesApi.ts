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
}[]): Promise<void> {
  if (payloads.length === 0) return;
  await apiRequest("/phrases/bulk", {
    method: "POST",
    body: JSON.stringify(payloads),
  });
  phrasesCache = null;
}

export async function updatePhrase(id: number, payload: {
  text: string;
  order?: number | null;
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
