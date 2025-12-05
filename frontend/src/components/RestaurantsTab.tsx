import { useEffect, useState } from "react";
import type { Restaurant } from "../types/domain";
import { fetchRestaurants, createRestaurant, createRestaurantsBulk, updateRestaurant, deleteRestaurant } from "../api/restaurantsApi";

export function RestaurantsTab() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [newRestaurant, setNewRestaurant] = useState({ instagram_username: "", name: "", bloco: "" });
  const [editingRestaurant, setEditingRestaurant] = useState<Restaurant | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [updating, setUpdating] = useState(false);

  function resetMessages() {
    setError(null);
    setSuccess(null);
  }

  async function loadRestaurants(force?: boolean) {
    resetMessages();
    setLoading(true);
    try {
      const data = await fetchRestaurants({ force });
      setRestaurants(data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar restaurantes");
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

      const idxUsername = cols.indexOf("INSTAGRAM");
      const idxName = cols.indexOf("RESTAURANTE");
      const idxBloco = cols.indexOf("Bloco");

      if (idxUsername === -1) {
        throw new Error("CSV deve conter a coluna INSTAGRAM");
      }

      if (idxName === -1) {
        throw new Error("CSV deve conter a coluna RESTAURANTE");
      }

      if (idxBloco === -1) {
        throw new Error("CSV deve conter a coluna Bloco");
      }

      const current = await fetchRestaurants({ force: true });
      const existing = new Set(
        (current || []).map((r) => r.instagram_username.trim().toLowerCase().replace(/^@/, ""))
      );

      let created = 0;
      let skipped = 0;
      const toCreate: {
        instagram_username: string;
        name: string;
        bloco?: number;
      }[] = [];

      for (const row of rows) {
        const parts = row.split(",").map((c) => c.trim());
        const rawUsername = parts[idxUsername];
        if (!rawUsername) {
          skipped++;
          continue;
        }
        const username = rawUsername.toLowerCase().replace(/^@/, "");
        if (!username || existing.has(username)) {
          skipped++;
          continue;
        }

        const name = idxName >= 0 ? parts[idxName] : "";
        const blocoRaw = idxBloco >= 0 ? parts[idxBloco] : "";
        const bloco = blocoRaw ? parseInt(blocoRaw, 10) : undefined;

        toCreate.push({
          instagram_username: username,
          name,
          ...(typeof bloco === "number" ? { bloco } : {}),
        });
        existing.add(username);
        created++;
      }

      await createRestaurantsBulk(toCreate);

      setSuccess(
        `Importação concluída. Criados: ${created}, ignorados (duplicados/inválidos): ${skipped}`
      );
      await loadRestaurants(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao importar CSV de restaurantes");
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  }

  useEffect(() => {
    loadRestaurants(false);
  }, []);

  async function handleCreate() {
    resetMessages();
    setLoading(true);
    setCreating(true);
    try {
      const blocoStr = newRestaurant.bloco.trim();
      const bloco = blocoStr ? parseInt(blocoStr, 10) : undefined;

      await createRestaurant({
        instagram_username: newRestaurant.instagram_username,
        name: newRestaurant.name,
        ...(typeof bloco === "number" ? { bloco } : {}),
      });
      setSuccess("Restaurante criado");
      setNewRestaurant({ instagram_username: "", name: "", bloco: "" });
      await loadRestaurants();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar restaurante");
    } finally {
      setLoading(false);
      setCreating(false);
    }
  }

  async function handleUpdate() {
    if (!editingRestaurant) return;
    resetMessages();
    setLoading(true);
    setUpdating(true);
    try {
      const payload: {
        instagram_username: string;
        name?: string | null;
        bloco?: number;
      } = {
        instagram_username: editingRestaurant.instagram_username,
        name: editingRestaurant.name ?? "",
      };

      if (typeof editingRestaurant.bloco === "number") {
        payload.bloco = editingRestaurant.bloco;
      }

      await updateRestaurant(editingRestaurant.id, payload);
      setSuccess("Restaurante atualizado");
      setEditingRestaurant(null);
      await loadRestaurants();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao atualizar restaurante");
    } finally {
      setLoading(false);
      setUpdating(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Remover restaurante? Esse processo é irreversível.")) return;
    resetMessages();
    setLoading(true);
    try {
      await deleteRestaurant(id);
      setSuccess("Restaurante removido");
      await loadRestaurants();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao remover restaurante");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Restaurantes</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadRestaurants(true)}
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
          <h3 className="text-sm font-medium text-slate-200">Novo restaurante</h3>
          <div className="space-y-2 text-sm">
            <input
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              placeholder="instagram_username"
              value={newRestaurant.instagram_username}
              onChange={(e) => setNewRestaurant({ ...newRestaurant, instagram_username: e.target.value })}
            />
            <input
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              placeholder="Nome"
              value={newRestaurant.name}
              onChange={(e) => setNewRestaurant({ ...newRestaurant, name: e.target.value })}
            />
            <input
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              placeholder="Bloco"
              value={newRestaurant.bloco}
              onChange={(e) => setNewRestaurant({ ...newRestaurant, bloco: e.target.value })}
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
            {restaurants.map((r) => (
              <div key={r.id} className="px-2 py-2 flex items-center justify-between gap-2">
                <div>
                  <div className="font-medium">@{r.instagram_username}  {`• bloco ${r.bloco}`}</div>
                  <div className="text-xs text-slate-400">
                    {r.name || "(sem nome)"}
                  </div>
                </div>
                <div className="flex gap-1 text-xs">
                  <button
                    className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700"
                    onClick={() => setEditingRestaurant(r)}
                  >
                    Editar
                  </button>
                  <button
                    className="px-2 py-0.5 rounded bg-red-700 hover:bg-red-600"
                    onClick={() => handleDelete(r.id)}
                  >
                    Excluir
                  </button>
                </div>
              </div>
            ))}
            {restaurants.length === 0 && (
              <div className="px-3 py-4 text-xs text-slate-500">Nenhum restaurante cadastrado.</div>
            )}
          </div>
        </div>
      </div>

      {editingRestaurant && (
        <div className="mt-4 border border-slate-700 rounded-md p-3 space-y-2 text-sm bg-slate-900/60">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">Editar restaurante #{editingRestaurant.id}</h3>
            <button
              className="text-xs text-slate-400 hover:text-slate-200"
              onClick={() => setEditingRestaurant(null)}
            >
              Fechar
            </button>
          </div>
          <div className="grid md:grid-cols-3 gap-2">
            <input
              className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              value={editingRestaurant.instagram_username}
              onChange={(e) =>
                setEditingRestaurant({ ...editingRestaurant, instagram_username: e.target.value })
              }
            />
            <input
              className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              value={editingRestaurant.name ?? ""}
              onChange={(e) => setEditingRestaurant({ ...editingRestaurant, name: e.target.value })}
            />
            <input
              className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1"
              value={editingRestaurant.bloco ?? ""}
              onChange={(e) =>
                setEditingRestaurant({
                  ...editingRestaurant,
                  bloco: e.target.value ? parseInt(e.target.value, 10) : null,
                })
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
