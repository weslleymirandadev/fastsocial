export type TabId = "restaurants" | "personas" | "phrases" | "config" | "automation" | "reports";

export interface Restaurant {
  id: number;
  instagram_username: string;
  name?: string | null;
  bloco?: number | null;
  cliente: boolean;
}

export interface Persona {
  id: number;
  name: string;
  instagram_username: string;
  instagram_password: string;
}

export interface Phrase {
  id: number;
  text: string;
  order?: number | null;
  cliente: boolean;
}

export interface BackendStatus {
  status: string;
  loop_running: boolean;
}
