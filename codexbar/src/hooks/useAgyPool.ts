import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { AgyQuota, AgySnapshot } from "../agy";

/** 池里一个号（`.agy-pool.json` 的一条）。 */
export interface AgyPoolAccount {
  sub: string;
  label: string;
  email?: string | null;
  /** 云端按账号读到的额度。★ **只有 5h 窗口** —— 周窗口只有本机 RPC 有，
   *  而那条只看得到当值那个号（见 `toSnapshot`）。 */
  quota?: Record<string, { remaining: number; reset: string; models?: string[] }> | null;
  quota_err?: string | null;
  quota_at?: number | null;
}

interface PoolFile {
  accounts?: Record<string, Omit<AgyPoolAccount, "sub">>;
  /** 上次我们看到的当值号。★ 名字带 `_seen` 是因为它**可能过时** ——
   *  用户在 agy 里 `/logout` 换了号而没跑我们的命令时，下次 `quota` 才会纠正。 */
  live_seen?: string | null;
}

/**
 * 把云端那份按账号的额度，翻成卡片认识的 `AgySnapshot` 形状。
 *
 * ★★ **只造 5h 那一格，绝不补一个假的周格。** 云端 `fetchAvailableModels` 给的
 *   `remainingFraction` 实测就是 5h 窗口（0.9566 与本机 RPC 的 `gemini-5h` 95.66 逐位相同）；
 *   周窗口它根本不返回。补一格「周 100%」会让每张卡都显示满格周额度 ——
 *   而上游那个字段的缺省值恰好也是 1.0，这条链路上「没有」和「满格」只隔一个默认值。
 *   不造那一格，卡片按槽位补一行等高空行，用户看到的是"这里没有数"，那是真话。
 */
function toSnapshot(a: AgyPoolAccount): AgySnapshot {
  const groups = Object.entries(a.quota ?? {}).map(([k, v]) => ({
    name: k === "claude" ? "Claude / GPT" : "Gemini Models",
    buckets: [{
      bucket_id: `${k}-5h`,
      window: "5h",
      remaining_percent: Math.round(v.remaining * 1000) / 10,
      reset_at: Math.round(Date.parse(v.reset) / 1000),
    }],
  }));
  const ok = groups.length > 0 && !a.quota_err;
  return {
    schema: 1, fetched_at: a.quota_at ?? 0, available: ok,
    // ★ 失败时 `quota` 恒 `null`（不是空对象）—— 卡片据此走降级态而不是画一条满格的条。
    reason: ok ? null : "network_error", detail: a.quota_err ?? null, pid: null,
    quota: ok ? ({ groups } as unknown as AgyQuota) : null,
    last_good: null,
  };
}

/**
 * agy 账号池。→ 每个号一张卡所需的一切。
 *
 * ★ 只读盘，不主动联网：`refresh()` 才会跑 `agy-rotate quota`（零消耗，但要往云端发请求）。
 *   与 grok/agy 额度同一条纪律 —— 总览一打开就联网不是这个 app 的做法。
 */
export function useAgyPool(enabled: boolean): {
  accounts: AgyPoolAccount[];
  liveSub: string | null;
  /** 当值号的那张 `AgySnapshot`（含**周**窗口）——它只能来自本机 RPC。 */
  snapshotOf: (a: AgyPoolAccount, liveSnap: AgySnapshot | null) => AgySnapshot;
  busy: boolean;
  err: string | null;
  refresh: () => void;
  switchTo: (label: string) => void;
  switching: string | null;
} {
  const [accounts, setAccounts] = useState<AgyPoolAccount[]>([]);
  const [liveSub, setLiveSub] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const running = useRef(false);

  const read = useCallback(async () => {
    try {
      const raw = await invoke<string | null>("read_agy_pool");
      if (!raw) { setAccounts([]); setLiveSub(null); return; }
      const p = JSON.parse(raw) as PoolFile;
      setAccounts(Object.entries(p.accounts ?? {})
        .map(([sub, a]) => ({ sub, ...a }))
        // ★ 按 label 排，不按额度：位置一变，用户就得重新找他的号。
        //   "该用哪个"由「当前」徽章回答，不由顺序回答（同账号卡那条）。
        .sort((x, y) => (x.label || "").localeCompare(y.label || "")));
      setLiveSub(p.live_seen ?? null);
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    }
  }, []);

  useEffect(() => { if (enabled) void read(); }, [enabled, read]);

  const refresh = useCallback(() => {
    if (running.current) return;
    running.current = true;
    setBusy(true); setErr(null);
    void invoke<string>("run_agy_rotate", { args: ["quota"] })
      .then(() => read())
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => { running.current = false; setBusy(false); });
  }, [read]);

  const switchTo = useCallback((label: string) => {
    setSwitching(label);
    void invoke<string>("run_agy_rotate", { args: ["switch", label] })
      .then(() => read())
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => setSwitching(null));
  }, [read]);

  const snapshotOf = useCallback((a: AgyPoolAccount, liveSnap: AgySnapshot | null) =>
    // ★ 当值号优先用**本机 RPC** 那份：只有它带周窗口，而周窗口是真实存在的额度。
    //   本机那份不可用时退回云端的 5h —— 少一行，不是编一行。
    (a.sub === liveSub && liveSnap?.available ? liveSnap : toSnapshot(a)), [liveSub]);

  return { accounts, liveSub, snapshotOf, busy, err, refresh, switchTo, switching };
}
