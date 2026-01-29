import { useEffect, useState, useMemo } from "react";
import type { Restaurant } from "../types/domain";
import { fetchRestaurants, createRestaurant, createRestaurantsBulk, updateRestaurant, deleteRestaurant, deleteAllRestaurants } from "../api/restaurantsApi";

export function RestaurantsTab() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [newRestaurant, setNewRestaurant] = useState({ instagram_username: "", name: "", bloco: "", cliente: false });
  const [editingRestaurant, setEditingRestaurant] = useState<Restaurant | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [importProgress, setImportProgress] = useState<{
    total: number;
    processed: number;
    created: number;
    skipped: number;
  } | null>(null);

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

  const filteredRestaurants = useMemo(() => {
    if (!searchQuery.trim()) return restaurants;
    const query = searchQuery.toLowerCase();
    return restaurants.filter(
      (r) =>
        r.instagram_username.toLowerCase().includes(query) ||
        (r.name && r.name.toLowerCase().includes(query))
    );
  }, [restaurants, searchQuery]);

  const clientes = useMemo(() => filteredRestaurants.filter((r) => r.cliente), [filteredRestaurants]);
  const naoClientes = useMemo(() => filteredRestaurants.filter((r) => !r.cliente), [filteredRestaurants]);

  async function handleDeleteAllRestaurants() {
    resetMessages();
    const ok = window.confirm(
      "ATENÇÃO: isso vai deletar TODOS os restaurantes (e logs relacionados) do banco. Essa ação é irreversível.\n\nDeseja continuar?"
    );
    if (!ok) return;

    setLoading(true);
    try {
      const result = await deleteAllRestaurants();
      const data = await fetchRestaurants({ force: true });
      setRestaurants(data || []);
      setSuccess(`Restaurantes removidos: ${result?.deleted ?? 0}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao deletar todos os restaurantes");
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

      // Pula a primeira linha (banner irrelevante) e usa a segunda como header
      if (lines.length < 2) {
        throw new Error("CSV deve ter pelo menos 2 linhas (banner + header)");
      }

      const [banner, header, ...rows] = lines;
      const cols = header.split(",").map((c) => c.trim());

      // Busca case-insensitive e com espaços
      const idxUsername = cols.findIndex((c) => c.trim().toUpperCase().includes("INSTAGRAM"));
      const idxName = cols.findIndex((c) => c.trim().toUpperCase().includes("RESTAURANTE"));
      const idxBloco = cols.findIndex((c) => c.trim().toLowerCase().includes("bloco"));
      const idxCliente = cols.findIndex((c) => c.trim().toLowerCase().includes("cliente"));

      if (idxUsername === -1) {
        throw new Error(`CSV deve conter a coluna INSTAGRAM. Colunas encontradas: ${cols.join(", ")}`);
      }

      if (idxName === -1) {
        throw new Error("CSV deve conter a coluna RESTAURANTE");
      }

      // Coluna Bloco é opcional - se não existir, o backend atribuirá automaticamente
      // if (idxBloco === -1) {
      //   throw new Error("CSV deve conter a coluna Bloco");
      // }

      const current = await fetchRestaurants({ force: true });
      const existing = new Set(
        (current || []).map((r) => r.instagram_username.trim().toLowerCase().replace(/^@/, ""))
      );

      let totalToCreate = 0;
      let skipped = 0;
      let toCreate: {
        instagram_username: string;
        name: string;
        bloco?: number;
        cliente: boolean;
      }[] = [];

      // Função para parsear CSV corretamente respeitando aspas e quebras de linha
      function parseCSVLine(line: string): string[] {
        const result: string[] = [];
        let current = "";
        let inQuotes = false;
        
        for (let i = 0; i < line.length; i++) {
          const char = line[i];
          
          if (char === '"') {
            if (inQuotes && line[i + 1] === '"') {
              // Aspas duplas escapadas
              current += '"';
              i++; // Pula o próximo caractere
            } else {
              // Toggle aspas
              inQuotes = !inQuotes;
            }
          } else if (char === ',' && !inQuotes) {
            // Vírgula fora de aspas = separador de campo
            result.push(current);
            current = "";
          } else {
            current += char;
          }
        }
        
        // Adiciona o último campo
        result.push(current);
        return result;
      }

      for (const row of rows) {
        // Parseia a linha respeitando aspas
        const parts = parseCSVLine(row);
        
        // Garante que temos pelo menos o número mínimo de colunas esperadas
        const maxIdx = Math.max(
          idxUsername, 
          idxName >= 0 ? idxName : -1, 
          idxBloco >= 0 ? idxBloco : -1,
          idxCliente >= 0 ? idxCliente : -1
        );
        if (parts.length <= maxIdx) {
          skipped++;
          continue;
        }
        
        const rawUsername = parts[idxUsername] || "";
        if (!rawUsername || rawUsername.trim() === "") {
          skipped++;
          continue;
        }
        
        // Remove aspas, quebras de linha, @, parênteses, /, www.instagram.com/, faz split por espaços e pega apenas o primeiro índice
        let username = rawUsername.trim()
          .replace(/^["']+|["']+$/g, "") // Remove aspas no início e fim
          .replace(/\r?\n/g, "") // Remove quebras de linha
          .replace(/^www\.instagram\.com\//i, "") // Remove www.instagram.com/
          .replace(/^instagram\.com\//i, "") // Remove instagram.com/
          .replace(/^@/, "") // Remove @
          .replace(/[()]/g, "") // Remove parênteses
          .replace(/\/+$/, "") // Remove / no final
          .split(" ")[0] // Split por espaços e pega primeiro termo
          .trim();
        
        if (!username) {
          skipped++;
          continue;
        }
        
        username = username.toLowerCase();
        
        // Só ignora se já existir exatamente esse username
        if (existing.has(username)) {
          skipped++;
          continue;
        }

        const name = idxName >= 0 ? (parts[idxName] || "").trim().replace(/^["']+|["']+$/g, "").replace(/\r?\n/g, "") : "";
        
        // Bloco é opcional - se não existir no CSV, o backend atribuirá automaticamente
        const blocoRaw = idxBloco >= 0 ? (parts[idxBloco] || "").trim() : "";
        const bloco = blocoRaw && !isNaN(parseInt(blocoRaw, 10)) ? parseInt(blocoRaw, 10) : undefined;
        
        // Lê campo cliente do CSV (se existir), caso contrário usa false como padrão
        let cliente = false;
        if (idxCliente >= 0 && parts[idxCliente]) {
          const clienteRaw = parts[idxCliente].trim().replace(/^["']+|["']+$/g, "").toLowerCase();
          cliente = clienteRaw === "sim" || clienteRaw === "yes" || clienteRaw === "true" || clienteRaw === "1" || clienteRaw === "s";
        }

        // Se bloco não foi fornecido, não inclui no payload - o backend atribuirá automaticamente
        const restaurantData: {
          instagram_username: string;
          name: string;
          bloco?: number;
          cliente: boolean;
        } = {
          instagram_username: username,
          name,
          cliente,
        };
        
        // Só inclui bloco se foi fornecido no CSV
        if (typeof bloco === "number" && !isNaN(bloco)) {
          restaurantData.bloco = bloco;
        }
        
        toCreate.push(restaurantData);
        existing.add(username);
        totalToCreate++;
      }

      // TODO: REMOVER - Filtro temporário para teste: limita a 400 restaurantes
      const TEST_LIMIT = 50;
      if (toCreate.length > TEST_LIMIT) {
        const originalCount = toCreate.length;
        toCreate = toCreate.slice(0, TEST_LIMIT);
        console.log(`[TESTE] Limitando importação: ${originalCount} → ${TEST_LIMIT} restaurantes`);
      }

      if (toCreate.length === 0) {
        setSuccess(`Nenhum restaurante novo para criar. Ignorados (duplicados/inválidos): ${skipped}`);
        setLoading(false);
        event.target.value = "";
        return;
      }

      // Processa em chunks para melhor feedback e não travar a UI
      const CHUNK_SIZE = 200; // Processa 200 por vez no frontend, o backend processa em batches de 100
      let totalCreated = 0;
      let totalSkipped = skipped;
      
      setImportProgress({
        total: toCreate.length,
        processed: 0,
        created: 0,
        skipped: skipped,
      });

      for (let i = 0; i < toCreate.length; i += CHUNK_SIZE) {
        const chunk = toCreate.slice(i, i + CHUNK_SIZE);
        
        try {
          const result = await createRestaurantsBulk(chunk);
          
          if (result) {
            totalCreated += result.created || 0;
            totalSkipped += result.skipped || 0;
          }
          
          // Atualiza progresso
          setImportProgress({
            total: toCreate.length,
            processed: Math.min(i + CHUNK_SIZE, toCreate.length),
            created: totalCreated,
            skipped: totalSkipped,
          });
          
          // Pequeno delay para não sobrecarregar o servidor
          if (i + CHUNK_SIZE < toCreate.length) {
            await new Promise(resolve => setTimeout(resolve, 100));
          }
        } catch (error) {
          console.error(`Erro ao processar chunk ${i}-${i + CHUNK_SIZE}:`, error);
          // Continua processando os próximos chunks mesmo se um falhar
        }
      }

      setImportProgress(null);
      setSuccess(
        `Importação concluída. Criados: ${totalCreated}, ignorados (duplicados/inválidos): ${totalSkipped}`
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
        cliente: newRestaurant.cliente,
      });
      setSuccess("Restaurante criado");
      setNewRestaurant({ instagram_username: "", name: "", bloco: "", cliente: false });
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
        cliente: boolean;
      } = {
        instagram_username: editingRestaurant.instagram_username,
        name: editingRestaurant.name ?? "",
        cliente: editingRestaurant.cliente,
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

  function renderRestaurantList(list: Restaurant[], emptyMessage: string) {
    return (
      <div className="max-h-80 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800 text-sm">
        {list.map((r) => (
          <div key={r.id} className="px-2 py-2 flex items-center justify-between gap-2">
            <div>
              <div className="font-medium">@{r.instagram_username}</div>
              <div className="text-xs text-slate-400">
                {r.name || "(sem nome)"} {r.bloco !== null && r.bloco !== undefined ? `• Bloco ${r.bloco}` : "• Sem bloco"}
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
        {list.length === 0 && (
          <div className="px-3 py-4 text-xs text-slate-500">{emptyMessage}</div>
        )}
      </div>
    );
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
          <button
            onClick={handleDeleteAllRestaurants}
            className="px-3 py-1 text-xs rounded-md bg-red-950 hover:bg-red-900 border border-red-800 text-red-200"
            disabled={loading || creating || updating}
            title="Deleta todos os restaurantes"
          >
            Deletar tudo
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
      {importProgress && (
        <div className="text-xs text-slate-300 space-y-1 p-3 bg-slate-900 border border-slate-700 rounded-md">
          <div className="flex items-center justify-between">
            <span>Importando restaurantes...</span>
            <span>{importProgress.processed} / {importProgress.total}</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-2">
            <div
              className="bg-emerald-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${(importProgress.processed / importProgress.total) * 100}%` }}
            />
          </div>
          <div className="text-xs text-slate-400">
            Criados: {importProgress.created} • Ignorados: {importProgress.skipped}
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-1 gap-6">
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
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={newRestaurant.cliente}
                onChange={(e) => setNewRestaurant({ ...newRestaurant, cliente: e.target.checked })}
                className="rounded"
              />
              <span className="text-xs">Cliente</span>
            </label>
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

        <div className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-200">Buscar</h3>
            </div>
            <input
              type="text"
              className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-sm"
              placeholder="Buscar por nome ou username..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div className="space-y-4 grid md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-slate-200">Clientes ({clientes.length})</h3>
              {renderRestaurantList(clientes, "Nenhum cliente cadastrado.")}
            </div>

            <div className="space-y-2">
              <h3 className="text-sm font-medium text-slate-200">Não Clientes ({naoClientes.length})</h3>
              {renderRestaurantList(naoClientes, "Nenhum não cliente cadastrado.")}
            </div>
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
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={editingRestaurant.cliente}
              onChange={(e) => setEditingRestaurant({ ...editingRestaurant, cliente: e.target.checked })}
              className="rounded"
            />
            <span className="text-xs">Cliente</span>
          </label>
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
