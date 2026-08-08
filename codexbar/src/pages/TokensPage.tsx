import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { Theme } from "../theme";

interface DayBucket {
  input: number; output: number; reasoning: number; cached: number; total: number; turns: number;
}
interface TokensPayload {
  days: Record<string, DayBucket>;
  scan: { scanned: number; reused: number };
}

const fmt = (n: number): string =>
  n >= 1e9 ? `${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n);

const RANGES = [7, 14, 30, 90] as const;

/**
 * 全池 token 消耗。
 *
 * ★ 数据源是 codex 自己写的 rollout（`token_count` 事件），本地读文件，**不联网、不消耗额度** ——
 *   跟额度百分比是两套东西：百分比是服务端配额进度，这里是真实烧掉的 token 量。
 * ★ 逐轮累加 `last_token_usage` 而不是 `total_token_usage`：后者是会话累计，跨事件求和会重复计数。
 *   已验证单会话「逐轮 last 求和 == 末条 total」。
 * ★ rollout **不记账号**，所以只能是全池合计，拆不到某个号。这正是"总的消耗图"要的口径。
 */
export default function TokensPage({ t }: { t: Theme }) {
  const [data, setData] = useState<TokensPayload | null>(null);
  const [days, setDays] = useState<number>(14);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async (n: number) => {
    setBusy(true); setErr(null);
    try {
      const raw = await invoke<string>("run_rotate", { args: ["tokens", "--days", String(n), "--json"] });
      setData(JSON.parse(raw) as TokensPayload);
    } catch (e: unknown) {
      setErr(String(e).slice(0, 160));
    }
    setBusy(false);
  }, []);

  useEffect(() => { load(days); }, [days, load]);

  const entries = Object.entries(data?.days ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const peak = Math.max(1, ...entries.map(([, v]) => v.total));
  const total = entries.reduce((s, [, v]) => s + v.total, 0);
  const turns = entries.reduce((s, [, v]) => s + v.turns, 0);
  const outTot = entries.reduce((s, [, v]) => s + v.output, 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <span style={{ fontSize: 20, fontWeight: 700 }}>Token 消耗</span>
        <span style={{ fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
          全池合计 · 读本地 rollout,不消耗额度
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`, borderRadius: 8 }}>
          {RANGES.map(n => (
            <span key={n} onClick={() => setDays(n)} style={{
              padding: "3px 10px", borderRadius: 6, fontSize: 11, cursor: "pointer", userSelect: "none",
              fontFamily: "'JetBrains Mono'", transition: "background .2s, color .2s",
              color: days === n ? t.accentText : t.muted, background: days === n ? t.accent : "transparent",
            }}>{n}d</span>
          ))}
        </div>
      </div>

      {/* 汇总条 */}
      <div style={{ display: "flex", gap: 22, padding: "10px 14px", marginBottom: 12, borderRadius: 10,
                    background: t.cardBg, border: `1px solid ${t.cardBorder}` }}>
        {([["合计", fmt(total)], ["轮数", turns.toLocaleString()],
           ["日均", fmt(Math.round(total / Math.max(1, entries.length)))],
           ["单轮均", fmt(Math.round(total / Math.max(1, turns)))],
           ["输出占比", total ? `${(outTot / total * 100).toFixed(1)}%` : "—"]] as const).map(([k, v]) => (
          <div key={k}>
            <div style={{ fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'", letterSpacing: ".08em" }}>{k}</div>
            <div style={{ fontSize: 17, fontWeight: 700, fontVariantNumeric: "tabular-nums", marginTop: 2 }}>{v}</div>
          </div>
        ))}
        {data && (
          <div style={{ marginLeft: "auto", alignSelf: "flex-end", fontSize: 9.5, color: t.faint, fontFamily: "'JetBrains Mono'" }}>
            解析 {data.scan.scanned} / 缓存 {data.scan.reused}
          </div>
        )}
      </div>

      {err && <div style={{ fontSize: 11, color: "#E0524D", marginBottom: 8 }}>✗ {err}</div>}
      {busy && !data && <div style={{ fontSize: 12, color: t.muted }}>首次扫描 rollout 中(约 10s,之后走缓存)…</div>}

      {/* 每日堆叠条:input / output(含 reasoning)。刻意只分这两段 —— input 是上下文重发的大头,
          output 才是真正"生成"的量,把它们分开才看得出"是不是上下文太长在烧钱"。 */}
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column", gap: 3 }}>
        {entries.map(([d, v]) => {
          const w = v.total / peak * 100;
          const inPct = v.total ? v.input / v.total * 100 : 0;
          return (
            <div key={d} title={`${d}\ninput ${v.input.toLocaleString()} / output ${v.output.toLocaleString()} (含 reasoning ${v.reasoning.toLocaleString()})\n${v.turns} 轮`}
                 style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 46, fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'", flexShrink: 0 }}>{d.slice(5)}</span>
              <div style={{ flex: 1, height: 16, borderRadius: 3, background: t.barTrack, overflow: "hidden", display: "flex" }}>
                <div style={{ width: `${w}%`, height: "100%", display: "flex", transition: "width .5s cubic-bezier(.4,0,.2,1)" }}>
                  <div style={{ width: `${inPct}%`, background: t.accent, opacity: .55 }} />
                  <div style={{ flex: 1, background: t.accent }} />
                </div>
              </div>
              <span style={{ width: 58, textAlign: "right", fontSize: 10.5, fontWeight: 600, fontVariantNumeric: "tabular-nums", fontFamily: "'JetBrains Mono'" }}>{fmt(v.total)}</span>
              <span style={{ width: 42, textAlign: "right", fontSize: 9.5, color: t.faint, fontFamily: "'JetBrains Mono'" }}>{v.turns}轮</span>
            </div>
          );
        })}
        {!busy && !entries.length && <div style={{ fontSize: 12, color: t.muted }}>没有记录 — 检查 ~/.codex/sessions</div>}
      </div>

      <div style={{ display: "flex", gap: 14, marginTop: 8, fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
        <span><span style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: t.accent, opacity: .55, marginRight: 5, verticalAlign: -1 }} />input(每轮重发完整上下文)</span>
        <span><span style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: t.accent, marginRight: 5, verticalAlign: -1 }} />output(含 reasoning)</span>
      </div>
    </div>
  );
}
