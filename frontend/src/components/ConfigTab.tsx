import { useEffect, useState } from "react";
import { fetchConfig, fetchAllConfigs, saveConfigs } from "../api/configApi";

type ConfigKey = "rest_days" | "wait_min_seconds" | "wait_max_seconds";
type ConfigKeyCliente = "rest_days_cliente" | "wait_min_seconds_cliente" | "wait_max_seconds_cliente";

const DEFAULTS: Record<ConfigKey, string> = {
  rest_days: "2",
  wait_min_seconds: "5",
  wait_max_seconds: "15",
};

const DEFAULTS_CLIENTE: Record<ConfigKeyCliente, string> = {
  rest_days_cliente: "2",
  wait_min_seconds_cliente: "5",
  wait_max_seconds_cliente: "15",
};

const DESCRIPTIONS: Record<ConfigKey, string> = {
  rest_days: "Quantidade de dias de descanso entre ciclos de automação (padrão 2 dias).",
  wait_min_seconds: "Tempo mínimo, em segundos, antes de enviar uma mensagem (padrão 5s).",
  wait_max_seconds: "Tempo máximo, em segundos, antes de enviar uma mensagem (padrão 15s).",
};

const DESCRIPTIONS_CLIENTE: Record<ConfigKeyCliente, string> = {
  rest_days_cliente: "Quantidade de dias de descanso entre ciclos de automação para clientes (padrão 2 dias).",
  wait_min_seconds_cliente: "Tempo mínimo, em segundos, antes de enviar uma mensagem para clientes (padrão 5s).",
  wait_max_seconds_cliente: "Tempo máximo, em segundos, antes de enviar uma mensagem para clientes (padrão 15s).",
};

const LABELS: Record<ConfigKey, string> = {
  rest_days: "Dias de descanso (rest_days)",
  wait_min_seconds: "Espera mínima (segundos) (wait_min_seconds)",
  wait_max_seconds: "Espera máxima (segundos) (wait_max_seconds)",
};

const LABELS_CLIENTE: Record<ConfigKeyCliente, string> = {
  rest_days_cliente: "Dias de descanso - Clientes (rest_days_cliente)",
  wait_min_seconds_cliente: "Espera mínima (segundos) - Clientes (wait_min_seconds_cliente)",
  wait_max_seconds_cliente: "Espera máxima (segundos) - Clientes (wait_max_seconds_cliente)",
};

export function ConfigTab() {
  const [values, setValues] = useState<Record<ConfigKey, string>>({
    rest_days: DEFAULTS.rest_days,
    wait_min_seconds: DEFAULTS.wait_min_seconds,
    wait_max_seconds: DEFAULTS.wait_max_seconds,
  });
  const [valuesCliente, setValuesCliente] = useState<Record<ConfigKeyCliente, string>>({
    rest_days_cliente: DEFAULTS_CLIENTE.rest_days_cliente,
    wait_min_seconds_cliente: DEFAULTS_CLIENTE.wait_min_seconds_cliente,
    wait_max_seconds_cliente: DEFAULTS_CLIENTE.wait_max_seconds_cliente,
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
    const nextValuesCliente: Record<ConfigKeyCliente, string> = { ...DEFAULTS_CLIENTE };

    try {
      const all = await fetchAllConfigs();
      
      // Carrega configurações de não clientes
      nextValues.rest_days = all["rest_days"]?.value ?? DEFAULTS.rest_days;
      nextValues.wait_min_seconds = all["wait_min_seconds"]?.value ?? DEFAULTS.wait_min_seconds;
      nextValues.wait_max_seconds = all["wait_max_seconds"]?.value ?? DEFAULTS.wait_max_seconds;

      // Carrega configurações de clientes (se existirem, caso contrário usa defaults)
      nextValuesCliente.rest_days_cliente = all["rest_days_cliente"]?.value ?? DEFAULTS_CLIENTE.rest_days_cliente;
      nextValuesCliente.wait_min_seconds_cliente = all["wait_min_seconds_cliente"]?.value ?? DEFAULTS_CLIENTE.wait_min_seconds_cliente;
      nextValuesCliente.wait_max_seconds_cliente = all["wait_max_seconds_cliente"]?.value ?? DEFAULTS_CLIENTE.wait_max_seconds_cliente;
    } catch {
      // fallback: keep defaults
    }

    setValues(nextValues);
    setValuesCliente(nextValuesCliente);
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
        // Configurações de não clientes
        rest_days: { value: values.rest_days, description: DESCRIPTIONS.rest_days },
        wait_min_seconds: {
          value: values.wait_min_seconds,
          description: DESCRIPTIONS.wait_min_seconds,
        },
        wait_max_seconds: {
          value: values.wait_max_seconds,
          description: DESCRIPTIONS.wait_max_seconds,
        },
        // Configurações de clientes
        rest_days_cliente: { value: valuesCliente.rest_days_cliente, description: DESCRIPTIONS_CLIENTE.rest_days_cliente },
        wait_min_seconds_cliente: {
          value: valuesCliente.wait_min_seconds_cliente,
          description: DESCRIPTIONS_CLIENTE.wait_min_seconds_cliente,
        },
        wait_max_seconds_cliente: {
          value: valuesCliente.wait_max_seconds_cliente,
          description: DESCRIPTIONS_CLIENTE.wait_max_seconds_cliente,
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

  function handleChangeCliente(key: ConfigKeyCliente, newValue: string) {
    setValuesCliente((prev) => ({ ...prev, [key]: newValue }));
  }

  function renderConfigSection(
    title: string,
    keys: ConfigKey[] | ConfigKeyCliente[],
    currentValues: Record<string, string>,
    labels: Record<string, string>,
    descriptions: Record<string, string>,
    onChange: (key: string, value: string) => void
  ) {
    return (
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-slate-200 border-b border-slate-800 pb-2">{title}</h3>
        {keys.map((key) => (
          <div
            key={key}
            className="border border-slate-800 rounded-md p-3 bg-slate-900/50 space-y-2"
          >
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-300 font-semibold">{labels[key]}</label>
              <input
                className="w-40 rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
                value={currentValues[key]}
                onChange={(e) => onChange(key, e.target.value)}
              />
            </div>
            <div className="text-[11px] text-slate-400">{descriptions[key]}</div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Configurações</h2>
      </div>

      {loading && <div className="text-xs text-slate-400">Carregando...</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}
      {success && <div className="text-xs text-emerald-400">{success}</div>}

      <div className="space-y-6 text-sm grid md:grid-cols-2 gap-6">
        {renderConfigSection(
          "Não Clientes",
          ["rest_days", "wait_min_seconds", "wait_max_seconds"] as ConfigKey[],
          values,
          LABELS,
          DESCRIPTIONS,
          (key, value) => handleChange(key as ConfigKey, value)
        )}

        {renderConfigSection(
          "Clientes",
          ["rest_days_cliente", "wait_min_seconds_cliente", "wait_max_seconds_cliente"] as ConfigKeyCliente[],
          valuesCliente,
          LABELS_CLIENTE,
          DESCRIPTIONS_CLIENTE,
          (key, value) => handleChangeCliente(key as ConfigKeyCliente, value)
        )}

        <button
          onClick={handleSaveAll}
          disabled={loading}
          className={`px-3 py-1 rounded-md bg-emerald-600 text-xs font-medium${
            loading ? " cursor-not-allowed opacity-50" : " hover:bg-emerald-500"
          }`}
        >
          {loading ? "Salvando..." : "Salvar todas as configurações"}
        </button>

        <div className="text-[11px] text-slate-500 mt-2">
          Essas configs são lidas pelo backend para controlar dias de descanso e intervalo aleatório
          entre envios. Defaults: rest_days=2, wait_min_seconds=5, wait_max_seconds=15.
        </div>
      </div>
    </div>
  );
}
