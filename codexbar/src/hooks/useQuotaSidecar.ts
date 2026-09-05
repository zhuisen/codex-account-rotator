import { useState, useEffect, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getSettings } from "../pages/SettingsPage";

/**
 * 「读 sidecar → 过期才重取」这套取数循环的**唯一实现**。grok 与 agy 共用。
 *
 * ★★ 抽出来的理由不是"看着像"，是这里面有两处**踩坑换来的**逻辑，抄一份就等于
 * 把修复放进两个地方等着漂移（本仓已经记过一次三副本漂移的账）：
 *   ① `primed` 把初始化 effect 永久锁住；
 *   ② 所以再次 `enabled` 时必须靠 `wasEnabled` 补一次保鲜检查 ——
 *      少了它，**钻出去再钻回来这个页面就再也不更新**（`useTraffic` 踩过一模一样的洞，
 *      当时被永远开着的心跳兜住，直到心跳可以关才暴露）。
 *
 * ★ 唯一**不**共用的是频次策略：调用方传 `freshMs`。
 *   grok 要联网打 xAI（10min）；agy 是本机 loopback、零额度消耗（可以短得多）。
 *   把它写死在这里，就等于强迫两条成本完全不同的链路用同一个节流。
 */

/** 只是"到点看一眼岁数"，不到期不取，所以 30s 节拍 ≠ 30s 请求一次。 */
const TICK_MS = 30 * 1000;

/** 与 `useTraffic` 共用设置页那一个开关：用户关掉「后台自动刷新」时，这里也只在手动 ↻ 时取。
 *  ★ 每次 tick 现读，不在 effect 建立时读一次（两个 webview 的 localStorage 不互通）。 */
function autoRefreshEnabled(): boolean {
  try { return getSettings().autoRefresh !== false; } catch { return true; }
}

/** sidecar 的最低要求：一个成败都会写、因而单调的时间戳。`adopt` 的比较全靠它。 */
export interface HasFetchedAt { fetched_at: number }

export interface QuotaSidecar<T> {
  snap: T | null;
  busy: boolean;
  /** 读 sidecar 本身失败（IO 层）。**注意这与「额度读不到」是两回事** ——
   *  后者是 snapshot 里正常返回的降级数据（`reason` 字段），不是错误。 */
  err: string | null;
  refresh: () => void;
}

export function useQuotaSidecar<T extends HasFetchedAt>(cfg: {
  /** Tauri 命令：只读 sidecar，不起子进程。 */
  readCmd: string;
  /** Tauri 命令：真的去取一次。 */
  runCmd: string;
  /** 多新才算新鲜。见文件头 —— 这是唯一不共用的策略。 */
  freshMs: number;
  enabled?: boolean;
}): QuotaSidecar<T> {
  const { readCmd, runCmd, freshMs, enabled = true } = cfg;
  const [snap, setSnap] = useState<T | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const running = useRef(false);

  const parse = (raw: string | null): T | null => {
    if (!raw) return null;
    try { return JSON.parse(raw) as T; } catch { return null; }
  };

  /** 只采纳更新的数据。`fetched_at` **成败都会写**，所以它是单调的，可以直接比。 */
  const adopt = useCallback((d: T | null) => {
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
        const cached = parse(await invoke<string | null>(readCmd));
        if (cached && Date.now() - cached.fetched_at * 1000 <= freshMs) { adopt(cached); return; }
      }
      adopt(parse(await invoke<string>(runCmd)));
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [adopt, readCmd, runCmd, freshMs]);

  // 首次进入：先读盘（立刻有数），过期才补取。
  const primed = useRef(false);
  useEffect(() => {
    if (!enabled || primed.current) return;
    primed.current = true;
    let alive = true;
    invoke<string | null>(readCmd)
      .then((raw) => {
        if (!alive) return;
        const cached = parse(raw);
        adopt(cached);
        const age = cached ? Date.now() - cached.fetched_at * 1000 : Infinity;
        if (age > freshMs) void fetchQuota();
      })
      .catch(() => { if (alive) void fetchQuota(); });
    return () => { alive = false; };
  }, [enabled, adopt, fetchQuota, readCmd, freshMs]);

  const snapRef = useRef<T | null>(null);
  snapRef.current = snap;

  const refreshIfStale = useCallback((maxAgeMs: number = freshMs) => {
    const f = snapRef.current?.fetched_at;
    if (f == null || Date.now() - f * 1000 > maxAgeMs) void fetchQuota();
  }, [fetchQuota, freshMs]);

  /**
   * ★ 再次进入时补一次保鲜检查。**不是冗余** —— 上面那个初始化 effect 被 `primed`
   * 永久锁住，而调用方是 `enabled: drill === "grok"` 这种。钻出去再钻回来时 `enabled`
   * 重新为真，但 `primed.current` 已是 true，effect 直接 return。见文件头 ②。
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
