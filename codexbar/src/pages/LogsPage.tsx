import { useEffect, useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { Theme } from "../theme";

interface LogEntry {
  time: string;
  type: string;
  msg: string;
}

export default function LogsPage({ t }: { t: Theme }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<string>("all");

  const loadLogs = useCallback(async () => {
    try {
      const raw = await invoke<string>("read_logs");
      const lines = raw.split("\n").filter(Boolean).reverse().slice(0, 200);
      const parsed: LogEntry[] = lines.map(line => {
        const m = line.match(/^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] \[(\w+)\] (.+)$/);
        if (m) return { time: m[1], type: m[2], msg: m[3] };
        const m2 = line.match(/^(.+?)\s+(refreshed|skipped|switched|cooled|refresh-all)\b(.*)$/i);
        if (m2) return { time: "", type: m2[2].toLowerCase(), msg: line };
        return { time: "", type: "info", msg: line };
      });
      setLogs(parsed);
    } catch {
      setLogs([]);
    }
  }, []);

  useEffect(() => { loadLogs(); const id = setInterval(loadLogs, 15_000); return () => clearInterval(id); }, [loadLogs]);

  const filtered = filter === "all" ? logs : logs.filter(l => l.type.includes(filter));
  const typeColor = (type: string) => {
    if (type.includes("refresh")) return t.accent;
    if (type.includes("switch")) return "#60a5fa";
    if (type.includes("cool")) return "#2BA0C0";
    if (type.includes("error") || type.includes("fail")) return "#E0524D";
    return t.muted;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 20, fontWeight: 700 }}>日志</span>
        <span style={{ fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{logs.length} 条</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          {["all", "refresh", "switch", "cool"].map(f => (
            <span key={f} onClick={() => setFilter(f)} style={{
              fontSize: 10, padding: "3px 8px", borderRadius: 6, cursor: "pointer",
              background: filter === f ? t.accent : t.ghostBg,
              color: filter === f ? t.accentText : t.ghostText,
              border: `1px solid ${filter === f ? t.accent : t.ghostBorder}`,
            }}>{f === "all" ? "全部" : f}</span>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", fontSize: 11, fontFamily: "'JetBrains Mono'", lineHeight: 1.7 }}>
        {filtered.length === 0 && <div style={{ color: t.muted, textAlign: "center", marginTop: 40 }}>暂无日志</div>}
        {filtered.map((l, i) => (
          <div key={i} style={{ display: "flex", gap: 8, padding: "2px 0", borderBottom: `1px solid ${t.divider}` }}>
            {l.time && <span style={{ color: t.muted, flexShrink: 0, width: 90 }}>{l.time}</span>}
            <span style={{ color: typeColor(l.type), fontWeight: 600, flexShrink: 0, width: 60 }}>{l.type}</span>
            <span style={{ color: t.text2, flex: 1, wordBreak: "break-all" }}>{l.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
