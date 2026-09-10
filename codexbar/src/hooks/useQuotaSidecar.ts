import { useState, useEffect, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
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

/** ★ 同一个 `runCmd` 的在途请求。第二个调用方**等同一个 promise**，不再起第二个子进程。 */
const _inflight = new Map<string, Promise<unknown>>();
/** ★ 同一个 `runCmd` 的所有实例。取到结果后广播，保证同一屏上的两块永远同一份数据。 */
const _subs = new Map<string, Set<(d: unknown) => void>>();

/**
 * 让某个 sidecar 的所有实例**立刻重取**。
 *
 * ★★ 给「改了配置，用量的口径就变了」用（2026-09-10）：停用/启用/删除一个中转站之后，
 *    用量块对它的状态陈述与 KPI 最长 **5 分钟**与事实相反 —— 页面上写着"已停用"，
 *    而同一屏的 KPI 里还加着它的余额。配置动作是**用户刚做的**，
 *    这时候的陈旧不是"数据有延迟"，是"我刚点的东西没生效"。
 */
export function invalidateSidecar(runCmd: string): void {
  _inflight.delete(runCmd);
  void invoke<string>(runCmd, { force: true })
    .then((raw) => {
      try {
        const d = JSON.parse(raw);
        for (const fn of _subs.get(runCmd) ?? []) fn(d);
      } catch { /* 形状坏了让 DOM 闸去发现 */ }
    })
    .catch(() => { /* 取不到就保持旧值 —— 比清空好，见 monitor.collect 的"只增不减" */ });
}

export function useQuotaSidecar<T extends HasFetchedAt>(cfg: {
  /** Tauri 命令：只读 sidecar，不起子进程。 */
  readCmd: string;
  /** Tauri 命令：真的去取一次。 */
  runCmd: string;
  /** 多新才算新鲜。见文件头 —— 这是唯一不共用的策略。 */
  freshMs: number;
  enabled?: boolean;
  /** ★★ 可选的**推送**通道（Phase 5，agy 用）。后端有别人（采样器）在写 sidecar 时，
   *  这里只要"被通知一声再读一次"，**不发任何 RPC**。
   *  没有它的话 UI 只在自己轮询到点时才前进，而轮询只在 `enabled` 的页面上跑 ——
   *  用户切走再回来最坏要等一整个 `freshMs`。 */
  updateEvent?: string;
}): QuotaSidecar<T> {
  const { readCmd, runCmd, freshMs, enabled = true, updateEvent } = cfg;
  const [snap, setSnap] = useState<T | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const parse = (raw: string | null): T | null => {
    if (!raw) return null;
    try { return JSON.parse(raw) as T; } catch { return null; }
  };

  /** 只采纳更新的数据。`fetched_at` **成败都会写**，所以它是单调的，可以直接比。 */
  const adopt = useCallback((d: T | null) => {
    if (!d) return;
    setSnap((prev) => (prev && prev.fetched_at >= d.fetched_at ? prev : d));
  }, []);

  // ★★ 同一个 `runCmd` 的所有实例**共享一次取数**（2026-09-10 修）。
  //    「总览」的中转站卡与「AI用量信息」的用量块各挂一个 `useRelayUsage()`，
  //    而 in-flight 守卫原来是 `useRef`（**每个实例一份**）⇒ 两边各起一次
  //    python 子进程、各打一次外网；手动 ↻ 更糟：`force:true` 让 Rust 的 300s
  //    合并窗口失效，两块于是拿到两份不同时刻的快照，**同一屏上的两个数最多差 5 分钟**。
  //    订阅表让所有实例采纳**同一份**结果 —— 这同时解决"一块刷新了另一块还是旧的"。
  useEffect(() => {
    const subs = _subs.get(runCmd) ?? new Set();
    subs.add(adopt as (d: unknown) => void);
    _subs.set(runCmd, subs);
    return () => { subs.delete(adopt as (d: unknown) => void); };
  }, [runCmd, adopt]);

  const fetchQuota = useCallback(async (force = false) => {
    const pending = _inflight.get(runCmd);
    if (pending) { await pending; return; }
    setBusy(true);
    setErr(null);
    const job = (async () => {
      if (!force) {
        const cached = parse(await invoke<string | null>(readCmd));
        if (cached && Date.now() - cached.fetched_at * 1000 <= freshMs) return cached;
      }
      // ★★ **手动 ↻ 必须传 `force`。** 不传的话 Rust 侧命中合并窗口(relay 是 300s)
      //    直接回旧 sidecar —— 按钮转一圈、数字纹丝不动,而"刚点过"和"没点中"
      //    在 UI 上一模一样。relay 的 hook docstring 承诺了这个行为,原来它不存在。
      //    ⚠️ Tauri 会忽略命令未声明的参数,所以对 grok/agy 无害。
      return parse(await invoke<string>(runCmd, { force: true }));
    })();
    _inflight.set(runCmd, job);
    try {
      const d = await job;
      // ★ 广播给**所有**实例，不只是发起的那个。
      for (const fn of _subs.get(runCmd) ?? []) fn(d);
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    } finally {
      _inflight.delete(runCmd);
      setBusy(false);
    }
  }, [readCmd, runCmd, freshMs]);

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

  // ★★ 推送通道（Phase 5）。**只读 sidecar，不 `run`** —— 数据已经被别人（采样器）
  //    取好了，再发一次 RPC 就把"省下一次外部调用"这件事本身抵消掉。
  //    `adopt` 按 `fetched_at` 单调采纳，所以重复/乱序的事件都是安全的。
  //    ★ 不受 `enabled` 约束:推送是**别人**在推，收下一条已经取好的数据没有成本，
  //      而受约束的话就退回"只在有人看这一页时才前进"——那正是要修的东西。
  useEffect(() => {
    if (!updateEvent) return;
    let un: (() => void) | undefined;
    let dead = false;
    void listen(updateEvent, () => {
      invoke<string | null>(readCmd)
        .then((raw) => { adopt(parse(raw)); })
        .catch(() => { /* 推送来了但读失败:轮询兜底,不打断 */ });
    }).then((f) => { if (dead) f(); else un = f; });
    return () => { dead = true; un?.(); };
  }, [updateEvent, readCmd, adopt]);

  return { snap, busy, err, refresh: () => void fetchQuota(true) };
}
