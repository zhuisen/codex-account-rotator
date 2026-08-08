import { useState, useEffect, useCallback, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import { type Theme, modelColor } from "../theme";
import AreaChart, { type Series } from "../components/AreaChart";

interface ModelBucket { total: number; turns: number }
interface DayBucket {
  input: number; output: number; reasoning: number; cached: number; total: number; turns: number;
  models?: Record<string, ModelBucket>;
}
interface TokensPayload {
  days: Record<string, DayBucket>;
  scan: { scanned: number; reused: number };
}

const fmt = (n: number): string =>
  n >= 1e9 ? `${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M`
  : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(Math.round(n));

const RANGES = [7, 14, 30, 90] as const;
type Mode = "total" | "models";

/**
 * 全池 token 消耗。
 *
 * ★ 数据源是 codex 自写的 rollout（`token_count` 事件），读本地文件，**不联网、不消耗额度**。
 *   与额度百分比是两套东西：百分比是服务端配额进度，这里是真实烧掉的 token 量。
 * ★ 逐轮累加 `last_token_usage` 而非 `total_token_usage`（后者是会话累计，跨事件求和会重复计数）。
 * ★ 模型按 **ordinal 顺序** 归属到最近一次 `turn_context`：实测 310 个文件里有 5 个在会话中途换过
 *   模型，按会话整体归会错。
 * ★ rollout **不记账号**，所以只能全池合计、拆不到单号。
 */
export default function TokensPage({ t }: { t: Theme }): React.ReactElement {
  const [data, setData] = useState<TokensPayload | null>(null);
  const [days, setDays] = useState<number>(14);
  const [mode, setMode] = useState<Mode>("models");
  const [hover, setHover] = useState<number | null>(null);
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

  const { labels, buckets, models, total, turns, outTot } = useMemo(() => {
    const entries = Object.entries(data?.days ?? {}).sort(([a], [b]) => a.localeCompare(b));
    const agg: Record<string, number> = {};
    for (const [, v] of entries) {
      for (const [m, b] of Object.entries(v.models ?? {})) agg[m] = (agg[m] ?? 0) + b.total;
    }
    return {
      labels: entries.map(([d]) => d),
      buckets: entries.map(([, v]) => v),
      // 大的画在下面：堆叠图里最厚的带贴基线才稳定，否则细带被夹在中间来回跳
      models: Object.entries(agg).sort((a, b) => b[1] - a[1]).map(([m, v]) => ({ m, v })),
      total: entries.reduce((s, [, v]) => s + v.total, 0),
      turns: entries.reduce((s, [, v]) => s + v.turns, 0),
      outTot: entries.reduce((s, [, v]) => s + v.output, 0),
    };
  }, [data]);

  const series: Series[] = mode === "models"
    ? models.map(({ m }) => ({ key: m, color: modelColor(m), values: buckets.map(b => b.models?.[m]?.total ?? 0) }))
    : [{ key: "total", color: t.accent, values: buckets.map(b => b.total) }];

  const hv = hover != null ? buckets[hover] : null;

  const Seg = <T extends string | number>({ opts, cur, on }: { opts: readonly T[]; cur: T; on: (v: T) => void }) => (
    <div style={{ display: "flex", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`, borderRadius: 8 }}>
      {opts.map(o => (
        <span key={String(o)} onClick={() => on(o)} style={{
          padding: "3px 11px", borderRadius: 6, fontSize: 11, cursor: "pointer", userSelect: "none",
          fontFamily: "'JetBrains Mono'", transition: "background .2s, color .2s",
          color: cur === o ? t.accentText : t.muted, background: cur === o ? t.accent : "transparent",
        }}>{typeof o === "number" ? `${o}d` : o === "models" ? "分模型" : "总量"}</span>
      ))}
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span style={{ fontSize: 20, fontWeight: 700 }}>Token 消耗</span>
        <span style={{ fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>全池合计 · 读本地 rollout,不消耗额度</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <Seg opts={["models", "total"] as const} cur={mode} on={setMode} />
          <Seg opts={RANGES} cur={days} on={setDays} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 22, padding: "10px 14px", marginBottom: 10, borderRadius: 10,
                    background: t.cardBg, border: `1px solid ${t.cardBorder}` }}>
        {([["合计 token", fmt(total)], ["请求轮数", turns.toLocaleString()],
           ["日均", fmt(total / Math.max(1, labels.length))],
           ["单轮均", fmt(total / Math.max(1, turns))],
           ["输出占比", total ? `${(outTot / total * 100).toFixed(1)}%` : "—"],
           ["模型数", String(models.length)]] as const).map(([k, v]) => (
          <div key={k}>
            <div style={{ fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'", letterSpacing: ".08em" }}>{k}</div>
            <div style={{ fontSize: 17, fontWeight: 700, fontVariantNumeric: "tabular-nums", marginTop: 2 }}>{v}</div>
          </div>
        ))}
        <div style={{ marginLeft: "auto", alignSelf: "flex-end", fontSize: 9.5, color: t.faint, fontFamily: "'JetBrains Mono'" }}>
          {hv ? `${labels[hover!]} · ${fmt(hv.total)} · ${hv.turns} 轮`
              : data ? `解析 ${data.scan.scanned} / 缓存 ${data.scan.reused}` : ""}
        </div>
      </div>

      {err && <div style={{ fontSize: 11, color: "#E0524D", marginBottom: 8 }}>✗ {err}</div>}
      {busy && !data && <div style={{ fontSize: 12, color: t.muted }}>首次扫描 rollout 中(约 10s,之后走缓存)…</div>}

      {!!labels.length && (
        <AreaChart labels={labels} series={series} stacked={mode === "models"} height={230}
                   fmt={fmt} muted={t.muted} grid={t.divider} onHover={setHover} />
      )}

      {/* 图例 = 模型排行，兼作数据表 */}
      {mode === "models" && !!models.length && (
        <div style={{ marginTop: 12, overflow: "auto" }}>
          {models.map(({ m, v }) => {
            const mt = buckets.reduce((s, b) => s + (b.models?.[m]?.turns ?? 0), 0);
            return (
              <div key={m} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10.5, padding: "2px 0" }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: modelColor(m), flexShrink: 0 }} />
                <span style={{ width: 132, fontFamily: "'JetBrains Mono'", color: t.text2 }}>{m}</span>
                <div style={{ flex: 1, height: 6, borderRadius: 3, background: t.barTrack, overflow: "hidden" }}>
                  <div style={{ width: `${v / (models[0]?.v || 1) * 100}%`, height: "100%", background: modelColor(m) }} />
                </div>
                <span style={{ width: 58, textAlign: "right", fontFamily: "'JetBrains Mono'", fontVariantNumeric: "tabular-nums" }}>{fmt(v)}</span>
                <span style={{ width: 46, textAlign: "right", fontFamily: "'JetBrains Mono'", color: t.muted }}>{(v / (total || 1) * 100).toFixed(1)}%</span>
                <span style={{ width: 54, textAlign: "right", fontFamily: "'JetBrains Mono'", color: t.faint }}>{mt.toLocaleString()}轮</span>
              </div>
            );
          })}
        </div>
      )}
      {mode === "total" && (
        <div style={{ marginTop: 10, fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
          曲线 = 每日 token 总量。切到「分模型」看堆叠构成。
        </div>
      )}
    </div>
  );
}
