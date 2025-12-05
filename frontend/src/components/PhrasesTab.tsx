import { useEffect, useState } from "react";
import type { Phrase } from "../types/domain";
import { fetchPhrases, createPhrase, createPhrasesBulk, updatePhrase, deletePhrase } from "../api/phrasesApi";

export function PhrasesTab() {
  const [phrases, setPhrases] = useState<Phrase[]>([]);
  const [newPhrase, setNewPhrase] = useState({ text: "", order: 0 });
  const [editingPhrase, setEditingPhrase] = useState<Phrase | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [updating, setUpdating] = useState(false);

  function resetMessages() {
    setError(null);
    setSuccess(null);
  }

  async function loadPhrases(force?: boolean) {
    resetMessages();
    setLoading(true);
    try {
      const data = await fetchPhrases({ force });
      const list = data || [];
      setPhrases(list);

      // Calcula o próximo índice disponível para nova frase (maior order + 1, começando em 0)
      let maxOrder = -1;
      for (const ph of list) {
        if (typeof ph.order === "number" && ph.order > maxOrder) {
          maxOrder = ph.order;
        }
      }
      const nextOrder = maxOrder + 1;
      setNewPhrase((prev) => ({ ...prev, order: nextOrder }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar frases");
    } finally {
      setLoading(false);
    }
  }

  async function handleImportCsv(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    resetMessages();
    setLoading(true);

    try {
      const text = await file.text();
      const lines = text
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean);

      if (lines.length === 0) {
        throw new Error("CSV vazio");
      }

      const [header, ...rows] = lines;
      const cols = header.split(",").map((c) => c.trim());

      const idxText = cols.indexOf("Frase");

      if (idxText === -1) {
        throw new Error("CSV deve conter a coluna Frase");
      }

      const current = await fetchPhrases({ force: true });
      const existing = new Set(
        (current || []).map((ph) => `${(ph.text || "").trim()}::${ph.order ?? ""}`)
      );

      // Calcula o maior índice de ordem já existente e começa do próximo,
      // garantindo que o primeiro índice seja 0 quando não houver frases.
      let maxOrder = -1;
      for (const ph of current || []) {
        if (typeof ph.order === "number" && ph.order > maxOrder) {
          maxOrder = ph.order;
        }
      }
      let nextOrder = maxOrder + 1;

      let created = 0;
      let skipped = 0;
      const toCreate: {
        text: string;
        order: number;
      }[] = [];

      for (const row of rows) {
        const parts = row.split(",").map((c) => c.trim());
        const phraseText = parts[idxText];
        if (!phraseText) {
          skipped++;
          continue;
        }
        const order = nextOrder;
        const key = `${phraseText.trim()}::${order}`;
        if (existing.has(key)) {
          skipped++;
          continue;
        }

        toCreate.push({ text: phraseText, order });
        existing.add(key);
        nextOrder++;
        created++;
      }

      await createPhrasesBulk(toCreate);

      setSuccess(
        `Importação concluída. Criadas: ${created}, ignoradas (duplicadas/inválidas): ${skipped}`
      );
      await loadPhrases(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao importar CSV de frases");
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  }

  useEffect(() => {
    loadPhrases(false);
  }, []);

  async function handleCreate() {
    resetMessages();
    setLoading(true);
    setCreating(true);
    try {
      await createPhrase(newPhrase);
      setSuccess("Frase criada");
      // Limpa apenas o texto; o próximo índice será recalculado em loadPhrases
      setNewPhrase((prev) => ({ ...prev, text: "" }));
      await loadPhrases();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar frase");
    } finally {
      setLoading(false);
      setCreating(false);
    }
  }

  async function handleUpdate() {
    if (!editingPhrase) return;
    resetMessages();
    setLoading(true);
    setUpdating(true);
    try {
      await updatePhrase(editingPhrase.id, {
        text: editingPhrase.text,
        order: editingPhrase.order ?? undefined,
      });
      setSuccess("Frase atualizada");
      setEditingPhrase(null);
      await loadPhrases();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao atualizar frase");
    } finally {
      setLoading(false);
      setUpdating(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Remover frase? Esse processo é irreversível.")) return;
    resetMessages();
    setLoading(true);
    try {
      await deletePhrase(id);
      setSuccess("Frase removida");
      await loadPhrases();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao remover frase");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Frases</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadPhrases(true)}
            className="px-3 py-1 text-xs rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-600"
          >
            Recarregar
          </button>
          <label className="text-xs px-3 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-600 cursor-pointer">
            Importar CSV
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={handleImportCsv}
            />
          </label>
        </div>
      </div>

      {loading && <div className="text-xs text-slate-400">Carregando...</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}
      {success && <div className="text-xs text-emerald-400">{success}</div>}

      <div className="grid md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-slate-200">Nova frase</h3>
          <div className="space-y-2 text-sm">
            <textarea
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1 min-h-20 text-xs"
              placeholder="Texto da DM"
              value={newPhrase.text}
              onChange={(e) => setNewPhrase((prev) => ({ ...prev, text: e.target.value }))}
            />
            <div className="flex items-center gap-2">
              <input
                type="number"
                className="w-24 rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                placeholder="Ordem"
                value={newPhrase.order}
                onChange={(e) =>
                  setNewPhrase((prev) => ({ ...prev, order: Number(e.target.value) || 1 }))
                }
              />
              <button
                onClick={handleCreate}
                disabled={creating}
                className={`px-3 py-1 rounded-md bg-emerald-600 text-xs font-medium${
                  creating ? " cursor-not-allowed opacity-50" : " hover:bg-emerald-500"
                }`}
              >
                {creating ? "Salvando..." : "Salvar"}
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium text-slate-200">Lista</h3>
          <div className="max-h-80 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800 text-sm">
            {phrases.map((ph) => (
              <div key={ph.id} className="px-2 py-2 flex items-start justify-between gap-2">
                <div className="text-xs space-y-1">
                  <div className="flex items-center gap-2">
                    <div className="font-semibold">#{ph.order ?? "-"}</div>
                  </div>
                  <div className="text-slate-300 whitespace-pre-wrap wrap-break-word line-clamp-1 max-w-full">{ph.text}</div>
                </div>
                <div className="flex flex-col gap-1 text-xs">
                  <button
                    className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700"
                    onClick={() => setEditingPhrase(ph)}
                  >
                    Editar
                  </button>
                  <button
                    className="px-2 py-0.5 rounded bg-red-700 hover:bg-red-600"
                    onClick={() => handleDelete(ph.id)}
                  >
                    Excluir
                  </button>
                </div>
              </div>
            ))}
            {phrases.length === 0 && (
              <div className="px-3 py-4 text-xs text-slate-500">Nenhuma frase cadastrada.</div>
            )}
          </div>
        </div>
      </div>

      {editingPhrase && (
        <div className="mt-4 border border-slate-700 rounded-md p-3 space-y-2 text-sm bg-slate-900/60">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">Editar frase #{editingPhrase.id}</h3>
            <button
              className="text-xs text-slate-400 hover:text-slate-200"
              onClick={() => setEditingPhrase(null)}
            >
              Fechar
            </button>
          </div>
          <textarea
            className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1 min-h-20 text-xs"
            value={editingPhrase.text}
            onChange={(e) => setEditingPhrase({ ...editingPhrase, text: e.target.value })}
          />
          <div className="flex items-center gap-2">
            <input
              type="number"
              className="w-24 rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
              value={editingPhrase.order ?? ""}
              onChange={(e) =>
                setEditingPhrase({
                  ...editingPhrase,
                  order: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
            <button
              onClick={handleUpdate}
              disabled={updating}
              className={`px-3 py-1 rounded-md bg-emerald-600 text-xs font-medium${
                updating ? " cursor-not-allowed opacity-50" : " hover:bg-emerald-500"
              }`}
            >
              {updating ? "Atualizando..." : "Atualizar"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
