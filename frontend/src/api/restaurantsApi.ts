import { apiRequest } from "./httpClient";
import type { Restaurant } from "../types/domain";

let restaurantsCache: Restaurant[] | null = null;

export async function fetchRestaurants(options?: { force?: boolean }): Promise<Restaurant[]> {
  if (!options?.force && restaurantsCache) {
    return restaurantsCache;
  }
  const data = await apiRequest<Restaurant[]>("/proxy/restaurants/");
  restaurantsCache = data || [];
  return restaurantsCache;
}

export async function createRestaurant(payload: {
  instagram_username: string;
  name: string;
  bloco?: number;
  cliente: boolean;
}): Promise<void> {
  await apiRequest("/proxy/restaurants/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  restaurantsCache = null;
}

export async function createRestaurantsBulk(payloads: {
  instagram_username: string;
  name: string;
  bloco?: number;
  cliente: boolean;
}[]): Promise<{ created: number; skipped: number; created_items?: any[]; errors?: any[] } | void> {
  if (payloads.length === 0) return;
  const result = await apiRequest<{ created: number; skipped: number; created_items?: any[]; errors?: any[] }>("/restaurants/bulk", {
    method: "POST",
    body: JSON.stringify(payloads),
  });
  restaurantsCache = null;
  return result;
}

export async function updateRestaurant(id: number, payload: {
  instagram_username: string;
  name?: string | null;
  bloco?: number;
  cliente: boolean;
}): Promise<void> {
  await apiRequest(`/proxy/restaurants/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  restaurantsCache = null;
}

export async function deleteRestaurant(id: number): Promise<void> {
  await apiRequest(`/proxy/restaurants/${id}`, { method: "DELETE" });
  restaurantsCache = null;
}
