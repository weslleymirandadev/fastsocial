import { useEffect, useState } from "react";
import type { Persona } from "../types/domain";
import { fetchPersonas, createPersona, createPersonasBulk, updatePersona, deletePersona } from "../api/personasApi";

export function PersonasTab() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [newPersona, setNewPersona] = useState({
    name: "",
    instagram_username: "",
    instagram_password: "",
  });
  const [editingPersona, setEditingPersona] = useState<Persona | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [updating, setUpdating] = useState(false);

  function resetMessages() {
    setError(null);
    setSuccess(null);
  }

  async function loadPersonas(force?: boolean) {
    resetMessages();
    setLoading(true);
    try {
      const data = await fetchPersonas({ force });
      setPersonas(data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar personas");
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

      const idxName = cols.indexOf("name");
      const idxUsername = cols.indexOf("instagram_username");
      const idxPassword = cols.indexOf("instagram_password");

      if (idxUsername === -1 || idxPassword === -1) {
        throw new Error("CSV deve conter as colunas instagram_username e instagram_password");
      }

      const current = await fetchPersonas({ force: true });
      const existing = new Set(
        (current || []).map((p) => p.instagram_username.trim().toLowerCase().replace(/^@/, ""))
      );

      let created = 0;
      let skipped = 0;
      const toCreate: {
        name: string;
        instagram_username: string;
        instagram_password: string;
      }[] = [];

      for (const row of rows) {
        const parts = row.split(",").map((c) => c.trim());
        const rawUsername = parts[idxUsername];
        const password = parts[idxPassword];
        if (!rawUsername || !password) {
          skipped++;
          continue;
        }
        const username = rawUsername.toLowerCase().replace(/^@/, "").trim();
        if (!username || existing.has(username)) {
          skipped++;
          continue;
        }

        const name = idxName >= 0 ? parts[idxName] || username : username;

        toCreate.push({ name, instagram_username: username, instagram_password: password });
        existing.add(username);
        created++;
      }

      await createPersonasBulk(toCreate);

      setSuccess(
        `Importação concluída. Criadas: ${created}, ignoradas (duplicadas/inválidas): ${skipped}`
      );
      await loadPersonas(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao importar CSV de personas");
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  }

  useEffect(() => {
    loadPersonas(false);
  }, []);

  async function handleCreate() {
    resetMessages();
    setLoading(true);
    setCreating(true);
    try {
      const payload = {
        name: newPersona.name,
        instagram_username: newPersona.instagram_username.toLowerCase().replace(/^@/, "").trim(),
        instagram_password: newPersona.instagram_password
      }
      await createPersona(payload);
      setSuccess("Persona criada");
      setNewPersona({ name: "", instagram_username: "", instagram_password: "" });
      await loadPersonas();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar persona");
    } finally {
      setLoading(false);
      setCreating(false);
    }
  }

  async function handleUpdate() {
    if (!editingPersona) return;
    resetMessages();
    setLoading(true);
    setUpdating(true);
    try {
      await updatePersona(editingPersona.id, {
        name: editingPersona.name,
        instagram_username: editingPersona.instagram_username,
        instagram_password: editingPersona.instagram_password,
      });
      setSuccess("Persona atualizada");
      setEditingPersona(null);
      await loadPersonas();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao atualizar persona");
    } finally {
      setLoading(false);
      setUpdating(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Remover persona? Esse processo é irreversível.")) return;
    resetMessages();
    setLoading(true);
    try {
      await deletePersona(id);
      setSuccess("Persona removida");
      await loadPersonas();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao remover persona");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Personas</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadPersonas(true)}
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
          <h3 className="text-sm font-medium text-slate-200">Nova persona</h3>
          <div className="space-y-2 text-sm">
            <input
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              placeholder="Instagram username"
              value={newPersona.instagram_username}
              onChange={(e) => setNewPersona({ ...newPersona, instagram_username: e.target.value })}
            />
            <input
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              placeholder="Nome interno (ex: Maria_Sudeste)"
              value={newPersona.name}
              onChange={(e) => setNewPersona({ ...newPersona, name: e.target.value })}
            />
            <input
              type="password"
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              placeholder="Senha"
              value={newPersona.instagram_password}
              onChange={(e) => setNewPersona({ ...newPersona, instagram_password: e.target.value })}
            />
            <button
              onClick={handleCreate}
              disabled={creating}
              className={`mt-1 px-3 py-1 rounded-md bg-emerald-600 text-sm font-medium${
                creating ? " cursor-not-allowed opacity-50" : " hover:bg-emerald-500"
              }`}
            >
              {creating ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium text-slate-200">Lista</h3>
          <div className="max-h-80 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800 text-sm">
            {personas.map((p) => (
              <div key={p.id} className="px-2 py-2 flex items-center justify-between gap-2">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-slate-400">@{p.instagram_username}</div>
                </div>
                <div className="flex gap-1 text-xs">
                  <button
                    className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700"
                    onClick={() => setEditingPersona(p)}
                  >
                    Editar
                  </button>
                  <button
                    className="px-2 py-0.5 rounded bg-red-700 hover:bg-red-600"
                    onClick={() => handleDelete(p.id)}
                  >
                    Excluir
                  </button>
                </div>
              </div>
            ))}
            {personas.length === 0 && (
              <div className="px-3 py-4 text-xs text-slate-500">Nenhuma persona cadastrada.</div>
            )}
          </div>
        </div>
      </div>

      {editingPersona && (
        <div className="mt-4 border border-slate-700 rounded-md p-3 space-y-2 text-sm bg-slate-900/60">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">Editar persona #{editingPersona.id}</h3>
            <button
              className="text-xs text-slate-400 hover:text-slate-200"
              onClick={() => setEditingPersona(null)}
            >
              Fechar
            </button>
          </div>
          <div className="grid md:grid-cols-3 gap-2">
            <input
              className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              value={editingPersona.name}
              onChange={(e) => setEditingPersona({ ...editingPersona, name: e.target.value })}
            />
            <input
              className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              value={editingPersona.instagram_username}
              onChange={(e) =>
                setEditingPersona({ ...editingPersona, instagram_username: e.target.value })
              }
            />
            <input
              type="password"
              className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              value={editingPersona.instagram_password}
              onChange={(e) =>
                setEditingPersona({ ...editingPersona, instagram_password: e.target.value })
              }
            />
          </div>
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
      )}
    </div>
  );
}
