import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import type { TrafficData, CacheMode } from "../traffic";
import { applyCacheMode } from "../traffic";
import { useCacheMode } from "./useCacheMode";

/**
 * 数据在这个岁数内算新鲜。**挂载、心跳、托盘弹出共用同一个概念**,只是托盘弹出用更紧的阈值
 * (用户主动点开就是想看现在的数)。
 *
 * ⚠️ 别再给挂载单独设一个更宽松的阈值:那样会出现「挂载时容忍 10 分钟旧、30 秒后心跳又按 2 分钟
 * 判定要重扫」—— 同一个"新鲜"两套标准,实测就是这么多扫了一次(2026-08-09)。
 */
const FRESH_MS = 2 * 60 * 1000;
/** 新鲜度检查的节拍。只是"到点看一眼岁数",不到期不扫,所以 30s 并不等于 30s 扫一次。 */
const TICK_MS = 30 * 1000;

/**
 * 流量数据的统一入口:**先画快照,再后台校验**(stale-while-revalidate)。
 *
 * 为什么不直接 `run_traffic`:那条路要起 python、读 10MB 增量缓存、stat 8500 个文件再重新聚合,
 * 实测热路径 **0.64~1.5s**(冷启动或刚用过 Claude Code 时更久)。这个代价**每次进页面都要付**,
 * 用户报的「token 页面新打开会有几秒的停顿」就是它。而菜单栏弹窗是"点一下就得出来"的东西,
 * 交接稿 §5 明写「弹窗只读缓存,不重复解析」。
 *
 * 所以 `run_traffic` 每次成功都会原子落一份**成品** `.traffic-latest.json`,这里先读它(一次 ~100KB
 * 文件读,无 python、无解析目录),立刻有图;只有快照**已过期**才在后台补扫。
 *
 * ★★ **两个 webview 共用数据、共用新鲜度规则,但各自决定何时要新数据**(用户 2026-08-11 定稿)。
 * 主窗口曾经是"进页面无条件重扫",于是「菜单栏刚自动刷新 → 点进主界面又刷一次」。现在:
 * - 同一条 `FRESH_MS` 规则 —— 对方 10 秒前扫的,这边直接采纳,不重扫。
 * - 扫完 `emit("traffic-updated")` 广播 —— 另一个窗口**读盘**(~1ms)而不是重扫(~1.4s)。
 *   两个窗口是独立 JS 上下文,连 localStorage 都不互通,只能走 Tauri 事件(同 `usePrivacy` 的范式)。
 * - 触发时机仍各自独立:菜单栏认 `menubar-shown`,主窗口认"进到用量页",各按自己的可见性跑心跳。
 * 最后一道保险在 Rust:`run_traffic` 有互斥锁 + 新鲜度双检,两边**同时**判定要扫时也只起一个 python。
 */
export function useTraffic(opts: { enabled?: boolean } = {}): {
  /**
   * **已按当前缓存口径重塑**的数据 —— 画面上一切 token 数与费用都该用它。
   * 重塑只在这一个出口做,下游读 `b.total` / `costOfBucket` 的 30 多处自动跟上。
   */
  data: TrafficData | null;
  /**
   * 未重塑的原始数据。**只给"解释这个口径拿掉了什么"的地方用**(缓存占比、四类构成),
   * 别拿它算展示用的合计 —— 那样就绕过了用户选的口径。
   */
  raw: TrafficData | null;
  cacheMode: CacheMode;
  /** 正在后台扫描。**有快照时不该拿它挡 UI** —— 那样就白做快照了。 */
  busy: boolean;
  err: string | null;
  /** 手动重扫(两处 `↻ 上次刷新 HH:MM` 按钮) */
  refresh: () => void;
  /** 只在数据比 `maxAgeMs` 还旧时才重扫。给"界面刚被看到"这类时刻用。 */
  refreshIfStale: (maxAgeMs?: number) => void;
} {
  const { enabled = true } = opts;
  const [data, setData] = useState<TrafficData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const running = useRef(false);

  const parse = (raw: string | null): TrafficData | null => {
    // 快照可能是上一个 PARSER_V 写的,或被中断写坏。解析失败当作没有,重扫即可自愈。
    if (!raw) return null;
    try { return JSON.parse(raw) as TrafficData; } catch { return null; }
  };
  /** 只在更新的数据上 setState —— 广播是双向的,自己发的那条也会收到 */
  const adopt = useCallback((d: TrafficData | null) => {
    if (!d) return;
    setData((prev) => (prev && prev.generated_at >= d.generated_at ? prev : d));
  }, []);

  /**
   * `force = true` 只给手动的 ↻ 用:用户明确要"现在重取",不看新鲜度。
   * 其余路径都先读一次盘 —— **另一个 webview 可能刚扫完**,那就省掉一次 1.4s 的重复扫描。
   */
  const scan = useCallback(async (force = false) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setErr(null);
    try {
      if (!force) {
        const snap = parse(await invoke<string | null>("read_traffic_snapshot"));
        if (snap && Date.now() - snap.generated_at * 1000 <= FRESH_MS) { adopt(snap); return; }
      }
      const raw = await invoke<string>("run_traffic", { args: ["--days", "90", "--json"] });
      adopt(parse(raw));
      // ★ 告诉另一个 webview:数据更新了,**去读盘,别自己再扫一遍**。
      //   两个窗口是独立 JS 上下文,localStorage 都不互通,只能走 Tauri 事件(同 usePrivacy 的范式)。
      void emit("traffic-updated");
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [adopt]);

  // 对方扫完 → 读盘采纳。一次 ~1ms 的文件读,不起 python。
  useEffect(() => {
    if (!enabled) return;
    const un = listen("traffic-updated", () => {
      void invoke<string | null>("read_traffic_snapshot").then((raw) => { adopt(parse(raw)); });
    });
    return () => { void un.then((f) => f()); };
  }, [enabled, adopt]);

  // ★ 只跑一次:`data` 一旦有值就不再重入。主窗口钻进平台详情页再返回、菜单栏来回切 Tab,
  //   都不该触发新的扫描。
  const primed = useRef(false);
  useEffect(() => {
    if (!enabled || primed.current) return;
    primed.current = true;
    let alive = true;
    invoke<string | null>("read_traffic_snapshot")
      .then((raw) => {
        if (!alive) return;
        let snap: TrafficData | null = null;
        if (raw) {
          // 快照可能是上一个 PARSER_V 写的,或被中断写坏。解析失败当作没有,重扫即可自愈。
          try { snap = JSON.parse(raw) as TrafficData; } catch { snap = null; }
        }
        adopt(snap);
        // ★ 两个窗口用**同一条**新鲜度规则。主窗口原来是 `revalidate: true` 无条件重扫,
        //   于是"菜单栏刚扫完 → 进主界面又扫一次"(用户 2026-08-11 报)。共用规则后,
        //   菜单栏 10 秒前扫过的数据,主窗口直接采纳。
        const age = snap ? Date.now() - snap.generated_at * 1000 : Infinity;
        if (age > FRESH_MS) void scan();
      })
      .catch(() => { if (alive) void scan(); });
    return () => { alive = false; };
  }, [enabled, adopt, scan]);

  // 岁数判断要读**最新**的 data,但不该让 `refreshIfStale` 每次 data 变就换引用(它挂在
  // 事件监听和定时器上,换引用 = 反复解绑重绑)。所以走 ref。
  const dataRef = useRef<TrafficData | null>(null);
  dataRef.current = data;

  const refreshIfStale = useCallback((maxAgeMs: number = FRESH_MS) => {
    const g = dataRef.current?.generated_at;
    if (g == null || Date.now() - g * 1000 > maxAgeMs) void scan();
  }, [scan]);

  /**
   * ★ 界面开着时的自动保鲜。
   *
   * 没有它就会出现用户 2026-08-09 报的「过了几十分钟还没刷新」:菜单栏 webview **只在 app 启动时
   * 挂载一次**(托盘 show/hide 不重建 webview),上面那个初始化 effect 被 `primed` 锁住之后
   * 再也不会跑,今日 Tab 的数字会一直冻在开机那一刻。
   *
   * 两条纪律:
   * - **只在页面真的可见时跑**。`document.hidden` 在窗口隐藏时为真,所以没人看的时候是零开销
   *   (一次扫描要 ~1.4s CPU + stat 8500 个文件,后台空转纯属浪费)。
   * - **tick 只是看一眼岁数**,没过 `FRESH_MS` 就什么都不做 —— 所以 30s 的节拍并不等于 30s 扫一次。
   */
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") refreshIfStale();
    }, TICK_MS);
    return () => { clearInterval(id); };
  }, [enabled, refreshIfStale]);

  // ★ 口径重塑放在**出口**,不进 state:扫描/快照/广播那套逻辑完全不知道有这回事,
  //   切口径也就不会触发任何重扫(它只是换个算法看同一份数据)。`full` 时返回原引用,零开销。
  const { mode: cacheMode } = useCacheMode();
  const shaped = useMemo(() => applyCacheMode(data, cacheMode), [data, cacheMode]);

  return { data: shaped, raw: data, cacheMode, busy, err, refresh: () => void scan(true), refreshIfStale };
}
