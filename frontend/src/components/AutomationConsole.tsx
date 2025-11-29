import { useEffect, useRef, useState } from "react";

interface AutomationStats {
  total: number;
  success: number;
  fail: number;
}

interface AutomationEvent {
  type: string;
  [key: string]: any;
}

export function AutomationConsole() {
  const [connected, setConnected] = useState(false);
  const [stats, setStats] = useState<AutomationStats>({ total: 0, success: 0, fail: 0 });
  const [lines, setLines] = useState<string[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const wsUrl = (import.meta as any).env.VITE_DATABASE_WS_URL || "ws://localhost:8080/automation/ws";
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onclose = () => {
      setConnected(false);
    };

    ws.onerror = () => {
      setConnected(false);
    };

    ws.onmessage = (event) => {
      try {
        const data: AutomationEvent = JSON.parse(event.data);

        if (data.stats && typeof data.stats === "object") {
          setStats({
            total: data.stats.total ?? 0,
            success: data.stats.success ?? 0,
            fail: data.stats.fail ?? 0,
          });
        }

        const applyEvent = (ev: AutomationEvent) => {
          if (ev.type === "dm_log") {
            const ts = ev.sent_at ? new Date(ev.sent_at).toLocaleTimeString() : "";
            const status = ev.success ? "OK" : "FAIL";
            const rest = ev.restaurant || {};
            const persona = ev.persona || {};
            const phrase = ev.phrase || {};

            const line =
              `[${ts}] ${status} ` +
              `restaurante=@${rest.instagram_username || "?"} (id=${rest.id ?? "?"}, bloco=${rest.bloco ?? "-"}, nome=${rest.name ?? "?"}) | ` +
              `persona=@${persona.instagram_username || "?"} (id=${persona.id ?? "?"}, nome=${persona.name ?? "?"}) | ` +
              `frase#${phrase.id ?? "?"}: ${String(phrase.text || "").slice(0, 80)}`;

            setLines((prev) => {
              const next = [...prev, line];
              if (next.length > 50) next.shift();
              return next;
            });
          } else if (ev.type === "system_log") {
            const ts = ev.created_at
              ? new Date(typeof ev.created_at === "number" ? ev.created_at * 1000 : ev.created_at).toLocaleTimeString()
              : "";
            const level = ev.level || "INFO";
            const loggerName = ev.logger || "";
            const msg = String(ev.message ?? "");

            const line = `[${ts}] ${level}${loggerName ? ` ${loggerName}` : ""} - ${msg}`;

            setLines((prev) => {
              const next = [...prev, line];
              if (next.length > 50) next.shift();
              return next;
            });
          }
        };

        if (data.type === "history" && Array.isArray(data.items)) {
          for (const item of data.items as AutomationEvent[]) {
            applyEvent(item);
          }
        } else {
          applyEvent(data);
        }
      } catch {
        // ignora mensagens inválidas
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="mt-4 border border-slate-800 rounded-md bg-slate-950/70 text-xs font-mono">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 bg-slate-900/70">
        <div className="flex gap-4">
          <span className="font-semibold">Console de Automação</span>
          <span>Total Enviado (neste ciclo): {stats.total}</span>
          <span className="text-emerald-400">Sucesso: {stats.success}</span>
          <span className="text-red-400">Falha: {stats.fail}</span>
        </div>
        <span className={connected ? "text-emerald-400" : "text-red-400"}>
          {connected ? "WS conectado" : "WS desconectado"}
        </span>
      </div>
      <div
        ref={containerRef}
        className="max-h-64 overflow-auto px-3 py-2 whitespace-pre-wrap wrap-break-word"
      >
        {lines.length === 0 && (
          <div className="text-slate-500">Aguardando eventos de automação...</div>
        )}
        {lines.map((line, idx) => (
          <div key={idx}>{line}</div>
        ))}
      </div>
    </div>
  );
}
