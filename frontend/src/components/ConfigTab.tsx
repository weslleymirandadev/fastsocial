import { useEffect, useState } from "react";
import { fetchConfig, fetchAllConfigs, saveConfigs } from "../api/configApi";

type ConfigKey = "rest_days" | "wait_min_seconds" | "wait_max_seconds";

const DEFAULTS: Record<ConfigKey, string> = {
  rest_days: "2",
  wait_min_seconds: "5",
  wait_max_seconds: "15",
};

const DESCRIPTIONS: Record<ConfigKey, string> = {
  rest_days: "Quantidade de dias de descanso entre ciclos de automação (padrão 2 dias).",
  wait_min_seconds: "Tempo mínimo, em segundos, antes de enviar uma mensagem (padrão 5s).",
  wait_max_seconds: "Tempo máximo, em segundos, antes de enviar uma mensagem (padrão 15s).",
};

const LABELS: Record<ConfigKey, string> = {
  rest_days: "Dias de descanso (rest_days)",
  wait_min_seconds: "Espera mínima (segundos) (wait_min_seconds)",
  wait_max_seconds: "Espera máxima (segundos) (wait_max_seconds)",
};

export function ConfigTab() {
  const [values, setValues] = useState<Record<ConfigKey, string>>({
    rest_days: DEFAULTS.rest_days,
    wait_min_seconds: DEFAULTS.wait_min_seconds,
    wait_max_seconds: DEFAULTS.wait_max_seconds,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function resetMessages() {
    setError(null);
    setSuccess(null);
  }

  async function loadAllConfigs() {
    resetMessages();
    setLoading(true);

    const nextValues: Record<ConfigKey, string> = { ...DEFAULTS };

    try {
      const all = await fetchAllConfigs();
      nextValues.rest_days = all["rest_days"]?.value ?? DEFAULTS.rest_days;
      nextValues.wait_min_seconds = all["wait_min_seconds"]?.value ?? DEFAULTS.wait_min_seconds;
      nextValues.wait_max_seconds = all["wait_max_seconds"]?.value ?? DEFAULTS.wait_max_seconds;
    } catch {
      // fallback: keep defaults
    }

    setValues(nextValues);
    setSuccess("Configurações carregadas");
    setLoading(false);
  }

  useEffect(() => {
    // Carrega valores já salvos (ou defaults) na montagem
    void loadAllConfigs();
  }, []);

  async function handleSaveAll() {
    resetMessages();
    setLoading(true);
    try {
      const payload: Record<string, { value: string; description?: string }> = {
        rest_days: { value: values.rest_days, description: DESCRIPTIONS.rest_days },
        wait_min_seconds: {
          value: values.wait_min_seconds,
          description: DESCRIPTIONS.wait_min_seconds,
        },
        wait_max_seconds: {
          value: values.wait_max_seconds,
          description: DESCRIPTIONS.wait_max_seconds,
        },
      };

      await saveConfigs(payload);
      setSuccess("Configurações salvas");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao salvar configurações");
    } finally {
      setLoading(false);
    }
  }

  function handleChange(key: ConfigKey, newValue: string) {
    setValues((prev) => ({ ...prev, [key]: newValue }));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Configurações</h2>
      </div>

      {loading && <div className="text-xs text-slate-400">Carregando...</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}
      {success && <div className="text-xs text-emerald-400">{success}</div>}

      <div className="space-y-4 text-sm">
        {(["rest_days", "wait_min_seconds", "wait_max_seconds"] as ConfigKey[]).map((key) => (
          <div
            key={key}
            className="border border-slate-800 rounded-md p-3 bg-slate-900/50 space-y-2"
          >
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-300 font-semibold">{LABELS[key]}</label>
              <input
                className="w-40 rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
                value={values[key]}
                onChange={(e) => handleChange(key, e.target.value)}
              />
            </div>
            <div className="text-[11px] text-slate-400">{DESCRIPTIONS[key]}</div>
          </div>
        ))}

        <button
          onClick={handleSaveAll}
          disabled={loading}
          className={`px-3 py-1 rounded-md bg-emerald-600 text-xs font-medium${
            loading ? " cursor-not-allowed opacity-50" : " hover:bg-emerald-500"
          }`}
        >
          {loading ? "Salvando..." : "Salvar configurações"}
        </button>

        <div className="text-[11px] text-slate-500 mt-2">
          Essas configs são lidas pelo backend para controlar dias de descanso e intervalo aleatório
          entre envios. Defaults: rest_days=2, wait_min_seconds=5, wait_max_seconds=15.
        </div>
      </div>
    </div>
  );
}