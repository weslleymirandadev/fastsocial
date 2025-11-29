import { useEffect, useState } from "react";
import type { BackendStatus } from "../types/domain";
import { fetchBackendStatus, startAutomation, stopAutomation } from "../api/automationApi";
import { AutomationConsole } from "./AutomationConsole";

export function AutomationTab() {
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function resetMessages() {
    setError(null);
    setSuccess(null);
  }

  async function loadStatus(force?: boolean) {
    resetMessages();
    setLoading(true);
    try {
      const data = await fetchBackendStatus({ force });
      setStatus(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar status do backend");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStatus(false);
  }, []);

  async function handleStart() {
    resetMessages();
    setLoading(true);
    try {
      await startAutomation();
      setSuccess("Automação iniciada");
      await loadStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao iniciar automação");
    } finally {
      setLoading(false);
    }
  }

  async function handleStop() {
    resetMessages();
    setLoading(true);
    try {
      await stopAutomation();
      setSuccess("Parada solicitada");
      await loadStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao parar automação");
    } finally {
      setLoading(false);
    }
  }

  const running = status?.loop_running;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Automação</h2>
        <button
          onClick={() => loadStatus(true)}
          className="px-3 py-1 text-sm rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-600"
        >
          Atualizar status
        </button>
      </div>

      {loading && <div className="text-xs text-slate-400">Carregando...</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}
      {success && <div className="text-xs text-emerald-400">{success}</div>}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div
          className={`px-3 py-1 rounded-full text-xs font-medium border ${
            running
              ? "bg-emerald-900/40 text-emerald-300 border-emerald-600"
              : "bg-slate-900 text-slate-300 border-slate-600"
          }`}
        >
          Sistema: {running ? "Rodando" : "Parado"}
        </div>
        <button
          onClick={handleStart}
          disabled={!!running}
          className={`px-3 py-1 rounded-md text-xs font-medium border ${
            running
              ? "bg-slate-800 text-slate-500 border-slate-700 cursor-not-allowed"
              : "bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-700"
          }`}
        >
          Iniciar
        </button>
        <button
          onClick={handleStop}
          disabled={!running}
          className={`px-3 py-1 rounded-md text-xs font-medium border ${
            !running
              ? "bg-slate-800 text-slate-500 border-slate-700 cursor-not-allowed"
              : "bg-red-700 hover:bg-red-600 text-white border-red-800"
          }`}
        >
          Parar
        </button>
      </div>

      <AutomationConsole />
    </div>
  );
}
