import { useEffect, useState } from "react";
import type { Persona, Restaurant } from "../types/domain";
import { apiRequest, BACKEND_BASE_URL } from "../api/httpClient";

// Filtros de período e status alinhados com o backend
const PERIOD_OPTIONS = [
  { value: "week", label: "Essa semana" },
  { value: "month", label: "Esse mês" },
  { value: "all", label: "Todo o período" },
] as const;

const STATUS_OPTIONS = [
  { value: "all", label: "Todos" },
  { value: "success", label: "Sucesso" },
  { value: "fail", label: "Falha" },
] as const;

export function ReportsTab() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);

  const [period, setPeriod] = useState<string>("week");
  const [status, setStatus] = useState<string>("all");
  const [personaId, setPersonaId] = useState<string>("");
  const [restaurantId, setRestaurantId] = useState<string>("");

  const [loadingMeta, setLoadingMeta] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadMeta() {
      try {
        setLoadingMeta(true);
        setError(null);
        const [persons, rests] = await Promise.all([
          apiRequest<Persona[]>("/proxy/personas/"),
          apiRequest<Restaurant[]>("/proxy/restaurants/"),
        ]);
        setPersonas(persons || []);
        setRestaurants(rests || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro ao carregar dados para relatórios");
      } finally {
        setLoadingMeta(false);
      }
    }
    loadMeta();
  }, []);

  function buildDownloadUrl() {
    const params = new URLSearchParams();
    if (period) params.set("period", period);
    if (status) params.set("status", status);
    if (personaId) params.set("persona_id", personaId);
    if (restaurantId) params.set("restaurant_id", restaurantId);
    return `${BACKEND_BASE_URL}/reports/messages.xlsx?${params.toString()}`;
  }

  async function handleDownload() {
    const url = buildDownloadUrl();

    try {
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`Falha ao gerar relatório (HTTP ${res.status})`);
      }

      const blob = await res.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = "messages_report.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao baixar relatório");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Relatórios</h2>
      </div>

      {loadingMeta && <div className="text-xs text-slate-400">Carregando dados...</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">Período</label>
          <select
            className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-sm"
            value={period}
            onChange={e => setPeriod(e.target.value)}
          >
            {PERIOD_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">Status</label>
          <select
            className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-sm"
            value={status}
            onChange={e => setStatus(e.target.value)}
          >
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">Persona</label>
          <select
            className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-sm"
            value={personaId}
            onChange={e => setPersonaId(e.target.value)}
          >
            <option value="">Todas</option>
            {personas.map(p => (
              <option key={p.id} value={String(p.id)}>
                {p.name} (@{p.instagram_username})
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">Restaurante</label>
          <select
            className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-sm"
            value={restaurantId}
            onChange={e => setRestaurantId(e.target.value)}
          >
            <option value="">Todos</option>
            {restaurants.map(r => (
              <option key={r.id} value={String(r.id)}>
                {r.name || r.instagram_username} (@{r.instagram_username})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <button
          onClick={handleDownload}
          className="px-4 py-2 rounded-md text-sm font-medium border bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-700"
        >
          Baixar XLSX
        </button>
      </div>
    </div>
  );
}
