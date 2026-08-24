import { useState, useEffect, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { GrokSnapshot } from "../grok";
import { getSettings } from "../pages/SettingsPage";

/**
 * grok 周额度的取数 hook。**形状照 `useTraffic`，但不复用它本体** ——
 * 那套语义整个绑在 `TrafficData.generated_at` + `.traffic-latest.json` 上，
 * 且它的错误路径是把 err 截成 200 字符字符串（对本模块正是要避免的折叠）。
 *
 * ★★ 与 `useTraffic` 的关键差别：**这条会联网。**
 * `useTraffic` 扫的是本机盘（零额度消耗、不联网、不碰凭证），这条要拿 grok 的 bearer 打 xAI。
 * 所以频次上加了四道闸，任何一道都不能省：
 *   ① 只在钻进 grok 详情页时 `enabled`（总览页不联网）
 *   ② 快照新鲜度 `FRESH_MS = 10min`
 *   ③ `document.visibilityState` 门（没人看时零请求）
 *   ④ Rust 侧 `GROK_COALESCE_SECS = 300` 双检
 * 周窗口是 10080 分钟，每 1% ≈ 100 分钟 —— 10 分钟粒度已经远超需要。
 */
const FRESH_MS = 10 * 60 * 1000;
/** 只是"到点看一眼岁数"，不到期不取，所以 30s 节拍 ≠ 30s 请求一次。 */
const TICK_MS = 30 * 1000;

/** 与 `useTraffic` 共用设置页那一个开关：用户关掉「后台自动刷新」时，这里也只在手动 ↻ 时取。
 *  ★ 每次 tick 现读，不在 effect 建立时读一次（两个 webview 的 localStorage 不互通）。 */
function autoRefreshEnabled(): boolean {
  try { return getSettings().autoRefresh !== false; } catch { return true; }
}

export function useGrokQuota(opts: { enabled?: boolean } = {}): {
  snap: GrokSnapshot | null;
  busy: boolean;
  /** 读 sidecar 本身失败（IO 层）。**注意这与「额度读不到」是两回事** ——
   *  后者在 `snap.accounts[].reason` 里，是正常返回的降级数据，不是错误。 */
  err: string | null;
  refresh: () => void;
} {
  const { enabled = true } = opts;
  const [snap, setSnap] = useState<GrokSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const running = useRef(false);

  const parse = (raw: string | null): GrokSnapshot | null => {
    if (!raw) return null;
    try { return JSON.parse(raw) as GrokSnapshot; } catch { return null; }
  };

  /** 只采纳更新的数据。`fetched_at` **成败都会写**，所以它是单调的，可以直接比。 */
  const adopt = useCallback((d: GrokSnapshot | null) => {
    if (!d) return;
    setSnap((prev) => (prev && prev.fetched_at >= d.fetched_at ? prev : d));
  }, []);

  const fetchQuota = useCallback(async (force = false) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setErr(null);
    try {
      if (!force) {
        const cached = parse(await invoke<string | null>("read_grok_quota"));
        if (cached && Date.now() - cached.fetched_at * 1000 <= FRESH_MS) { adopt(cached); return; }
      }
      adopt(parse(await invoke<string>("run_grok_quota")));
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [adopt]);

  // 首次进入：先读盘（立刻有数），过期才补取。
  const primed = useRef(false);
  useEffect(() => {
    if (!enabled || primed.current) return;
    primed.current = true;
    let alive = true;
    invoke<string | null>("read_grok_quota")
      .then((raw) => {
        if (!alive) return;
        const cached = parse(raw);
        adopt(cached);
        const age = cached ? Date.now() - cached.fetched_at * 1000 : Infinity;
        if (age > FRESH_MS) void fetchQuota();
      })
      .catch(() => { if (alive) void fetchQuota(); });
    return () => { alive = false; };
  }, [enabled, adopt, fetchQuota]);

  const snapRef = useRef<GrokSnapshot | null>(null);
  snapRef.current = snap;

  const refreshIfStale = useCallback((maxAgeMs: number = FRESH_MS) => {
    const f = snapRef.current?.fetched_at;
    if (f == null || Date.now() - f * 1000 > maxAgeMs) void fetchQuota();
  }, [fetchQuota]);

  /**
   * ★ 再次进入时补一次保鲜检查。
   *
   * 不是冗余：上面那个初始化 effect 被 `primed` **永久**锁住，而调用方是
   * `useGrokQuota({ enabled: drill === "grok" })` —— 钻出去再钻回来时 `enabled` 重新为真，
   * 但 `primed.current` 已是 true，effect 直接 return，**第二次以后进这个页面就再也不更新**。
   * `useTraffic` 踩过一模一样的洞（那次被永远开着的心跳兜住了，直到心跳可以关才暴露）。
   */
  const wasEnabled = useRef(false);
  useEffect(() => {
    const entering = enabled && !wasEnabled.current;
    wasEnabled.current = enabled;
    if (entering && primed.current) refreshIfStale();
  }, [enabled, refreshIfStale]);

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => {
      if (!autoRefreshEnabled()) return;
      if (document.visibilityState === "visible") refreshIfStale();
    }, TICK_MS);
    return () => { clearInterval(id); };
  }, [enabled, refreshIfStale]);

  return { snap, busy, err, refresh: () => void fetchQuota(true) };
}
