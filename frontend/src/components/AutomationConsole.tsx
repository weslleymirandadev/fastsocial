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
      console.log("WebSocket connected");
    };

    ws.onclose = () => {
      setConnected(false);
      console.log("WebSocket disconnected");
      // Try to reconnect after a delay
      setTimeout(() => {
        console.log("Attempting to reconnect...");
        ws.close();
        const newWs = new WebSocket(wsUrl);
        ws.onopen = newWs.onopen;
        ws.onclose = newWs.onclose;
        ws.onerror = newWs.onerror;
        ws.onmessage = newWs.onmessage;
      }, 5000);
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setConnected(false);
    };

    ws.onmessage = (event) => {
      try {
        const data: AutomationEvent = JSON.parse(event.data);
        
        // Handle different types of messages
        switch (data.type) {
          case "dm_log":
            handleDmLog(data);
            break;
          case "system_log":
            handleSystemLog(data);
            break;
          case "stats":
            updateStats(data.stats);
            break;
          case "history":
            if (Array.isArray(data.items)) {
              data.items.forEach((item: any) => {
                if (!item || typeof item !== "object") return;
                if (item.type === "system_log") {
                  handleSystemLog(item);
                } else if (item.type === "dm_log") {
                  handleDmLog(item);
                } else if (item.type === "stats" && item.stats) {
                  updateStats(item.stats);
                }
              });
            }
            break;
          default:
            console.log("Unknown message type:", data.type, data);
        }
      } catch (error) {
        console.error("Error processing WebSocket message:", error, event.data);
      }
    };

    const updateStats = (newStats: any) => {
      if (newStats && typeof newStats === "object") {
        setStats(prev => ({
          total: newStats.total ?? prev.total,
          success: newStats.success ?? prev.success,
          fail: newStats.fail ?? prev.fail,
        }));
      }
    };

    const handleDmLog = (event: any) => {
      // Para dm_log, usamos apenas para atualizar as estatísticas,
      // sem adicionar linhas no console (console fica para system_log).
      if (event.stats) {
        updateStats(event.stats);
      }
    };

    const handleSystemLog = (event: any) => {
      const ts = event.created_at
        ? new Date(typeof event.created_at === "number" ? event.created_at * 1000 : event.created_at).toLocaleTimeString()
        : "";
      const level = event.level || "INFO";
      const loggerName = event.logger || "";
      const msg = String(event.message || "");

      const line = `[${ts}] ${level}${loggerName ? ` ${loggerName}` : ""} - ${msg}`;

      // Add to log lines
      setLines(prev => {
        const next = [...prev, line];
        return next.slice(-50); // Keep only the last 50 lines
      });
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
