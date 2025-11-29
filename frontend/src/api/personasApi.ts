import { apiRequest } from "./httpClient";
import type { Persona } from "../types/domain";

let personasCache: Persona[] | null = null;

export async function fetchPersonas(options?: { force?: boolean }): Promise<Persona[]> {
  if (!options?.force && personasCache) {
    return personasCache;
  }
  const data = await apiRequest<Persona[]>("/proxy/personas/");
  personasCache = data || [];
  return personasCache;
}

export async function createPersona(payload: {
  name: string;
  instagram_username: string;
  instagram_password: string;
}): Promise<void> {
  await apiRequest("/proxy/personas/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  personasCache = null;
}

export async function createPersonasBulk(payloads: {
  name: string;
  instagram_username: string;
  instagram_password: string;
}[]): Promise<void> {
  if (payloads.length === 0) return;
  await apiRequest("/personas/bulk", {
    method: "POST",
    body: JSON.stringify(payloads),
  });
  personasCache = null;
}

export async function updatePersona(id: number, payload: {
  name: string;
  instagram_username: string;
  instagram_password: string;
}): Promise<void> {
  await apiRequest(`/proxy/personas/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  personasCache = null;
}

export async function deletePersona(id: number): Promise<void> {
  await apiRequest(`/proxy/personas/${id}`, { method: "DELETE" });
  personasCache = null;
}
