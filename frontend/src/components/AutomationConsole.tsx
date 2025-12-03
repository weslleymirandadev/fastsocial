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
              data.items.forEach(handleDmLog);
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
      // Update stats if available
      if (event.stats) {
        updateStats(event.stats);
      }

      // Format the log line
      const ts = event.sent_at ? new Date(event.sent_at).toLocaleTimeString() : "";
      const status = event.success ? "OK" : "FAIL";
      const rest = event.restaurant || {};
      const persona = event.persona || {};
      const phrase = event.phrase || {};

      const line =
        `[${ts}] ${status} ` +
        `restaurante=@${rest.instagram_username || "?"} (id=${rest.id ?? "?"}, bloco=${rest.bloco ?? "-"}, nome=${rest.name ?? "?"}) | ` +
        `persona=@${persona.instagram_username || "?"} (id=${persona.id ?? "?"}, nome=${persona.name ?? "?"}) | ` +
        `frase#${phrase.id ?? "?"}: ${String(phrase.text || "").slice(0, 80)}`;

      // Add to log lines
      setLines(prev => {
        const next = [...prev, line];
        return next.slice(-50); // Keep only the last 50 lines
      });
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
