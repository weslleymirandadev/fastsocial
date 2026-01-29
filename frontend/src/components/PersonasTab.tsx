import { useEffect, useState, useMemo } from "react";
import type { Persona } from "../types/domain";
import { fetchPersonas, createPersona, createPersonasBulk, updatePersona, deletePersona, deleteAllPersonas } from "../api/personasApi";

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

  async function handleDeleteAllPersonas() {
    resetMessages();
    const ok = window.confirm(
      "ATENÇÃO: isso vai deletar TODAS as personas (e logs/inbox relacionados) do banco. Essa ação é irreversível.\n\nDeseja continuar?"
    );
    if (!ok) return;

    setLoading(true);
    try {
      const result = await deleteAllPersonas();
      const data = await fetchPersonas({ force: true });
      setPersonas(data || []);
      setSuccess(`Personas removidas: ${result?.deleted ?? 0}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao deletar todas as personas");
    } finally {
      setLoading(false);
    }
  }

  // Função auxiliar para fazer parse de CSV corretamente, lidando com aspas
  function parseCSVLine(line: string): string[] {
    const result: string[] = [];
    let current = "";
    let inQuotes = false;
    
    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      
      if (char === '"') {
        if (inQuotes && line[i + 1] === '"') {
          // Aspas duplas dentro de campo entre aspas (escape)
          current += '"';
          i++; // Pula o próximo caractere
        } else {
          // Toggle do estado de aspas
          inQuotes = !inQuotes;
        }
      } else if (char === ',' && !inQuotes) {
        // Vírgula fora de aspas = separador de campo
        result.push(current.trim());
        current = "";
      } else {
        current += char;
      }
    }
    
    // Adiciona o último campo
    result.push(current.trim());
    return result;
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

      // Primeira linha deve ser o header
      const header = lines[0];
      const cols = parseCSVLine(header).map((c) => c.trim());

      // Valida formato específico: deve conter "Nome", "Instagram" e "Senha Instagram"
      const idxName = cols.findIndex((c) => c.toLowerCase() === "nome");
      const idxInstagram = cols.findIndex((c) => c.toLowerCase() === "instagram");
      const idxPassword = cols.findIndex((c) => c.toLowerCase().includes("senha") && c.toLowerCase().includes("instagram"));

      if (idxName === -1) {
        throw new Error("CSV deve conter a coluna 'Nome'");
      }
      if (idxInstagram === -1) {
        throw new Error("CSV deve conter a coluna 'Instagram'");
      }
      if (idxPassword === -1) {
        throw new Error("CSV deve conter a coluna 'Senha Instagram'");
      }

      // Valida que é o formato esperado (pelo menos deve ter essas colunas)
      const expectedFormat = "Sequência,Nome,Instagram,Data última utilização,Bloco de Clientes,Modelo do Celular,Número do Celular,Senha Instagram";
      const headerNormalized = header.toLowerCase().replace(/\s+/g, " ");
      
      // Verifica se o header contém as colunas esperadas (não precisa ser exatamente igual devido a variações)
      const hasExpectedColumns = 
        headerNormalized.includes("nome") &&
        headerNormalized.includes("instagram") &&
        headerNormalized.includes("senha");

      if (!hasExpectedColumns) {
        throw new Error(`Formato de CSV inválido. Esperado formato: ${expectedFormat}`);
      }

      const rows = lines.slice(1); // Pula o header

      const current = await fetchPersonas({ force: true });
      const existing = new Set(
        (current || []).map((p) => p.instagram_username.trim().toLowerCase().replace(/^@/, ""))
      );

      let totalToCreate = 0;
      let skipped = 0;
      const toCreate: {
        name: string;
        instagram_username: string;
        instagram_password: string;
      }[] = [];

      for (const row of rows) {
        if (!row.trim()) continue; // Pula linhas vazias
        
        const parts = parseCSVLine(row);
        
        // Extrai os campos específicos
        const name = parts[idxName]?.trim() || "";
        const rawInstagram = parts[idxInstagram]?.trim() || "";
        const password = parts[idxPassword]?.trim() || "";

        // Remove aspas se existirem
        const cleanName = name.replace(/^["']|["']$/g, "").trim();
        const cleanInstagram = rawInstagram.replace(/^["']|["']$/g, "").trim();
        const cleanPassword = password.replace(/^["']|["']$/g, "").trim();

        // Valida campos obrigatórios
        if (!cleanInstagram || !cleanPassword) {
          skipped++;
          continue;
        }

        // Processa username: remove @ e converte para lowercase
        const username = cleanInstagram.toLowerCase().replace(/^@/, "").trim();
        
        if (!username || existing.has(username)) {
          skipped++;
          continue;
        }

        // Usa o nome do CSV ou o username como fallback
        const finalName = cleanName || username;

        toCreate.push({ 
          name: finalName, 
          instagram_username: username, 
          instagram_password: cleanPassword 
        });
        existing.add(username);
        totalToCreate++;
      }

      if (toCreate.length === 0) {
        setSuccess(`Nenhuma persona nova para criar. Ignoradas (duplicadas/inválidas): ${skipped}`);
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
          const result = await createPersonasBulk(chunk);
          
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
        `Importação concluída. Criadas: ${totalCreated}, ignoradas (duplicadas/inválidas): ${totalSkipped}`
      );
      await loadPersonas(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao importar CSV de personas");
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  }

  const filteredPersonas = useMemo(() => {
    if (!searchQuery.trim()) return personas;
    const query = searchQuery.toLowerCase();
    return personas.filter(
      (p) =>
        p.name.toLowerCase().includes(query) ||
        p.instagram_username.toLowerCase().includes(query)
    );
  }, [personas, searchQuery]);

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
          <button
            onClick={handleDeleteAllPersonas}
            className="px-3 py-1 text-xs rounded-md bg-red-950 hover:bg-red-900 border border-red-800 text-red-200"
            disabled={loading || creating || updating}
            title="Deleta todas as personas"
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
            <span>Importando personas...</span>
            <span>{importProgress.processed} / {importProgress.total}</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-2">
            <div
              className="bg-emerald-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${(importProgress.processed / importProgress.total) * 100}%` }}
            />
          </div>
          <div className="text-xs text-slate-400">
            Criadas: {importProgress.created} • Ignoradas: {importProgress.skipped}
          </div>
        </div>
      )}

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
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-slate-200">Lista</h3>
          </div>
          <input
            type="text"
            className="w-full rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-sm mb-2"
            placeholder="Buscar por nome ou username..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <div className="max-h-80 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800 text-sm">
            {filteredPersonas.map((p) => (
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
            {filteredPersonas.length === 0 && (
              <div className="px-3 py-4 text-xs text-slate-500">
                {personas.length === 0 ? "Nenhuma persona cadastrada." : "Nenhuma persona encontrada."}
              </div>
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
