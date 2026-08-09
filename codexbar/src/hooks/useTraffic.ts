import { useState, useEffect, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { TrafficData } from "../traffic";

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
 * 文件读,无 python、无解析目录),立刻有图;再按 `revalidate` 决定要不要在后台补扫描。
 *
 * - 主窗口 `revalidate: true` —— 进页面顺手刷新,用户在这里就是来看准数的。
 * - 菜单栏 `revalidate: false` —— 只在快照已过期时才后台补一次,平时零成本。
 *   (不能完全不扫:如果用户从不打开主窗口,快照永远不存在,今日 Tab 就永远是空的。)
 */
export function useTraffic(opts: { enabled?: boolean; revalidate: boolean }): {
  data: TrafficData | null;
  /** 正在后台扫描。**有快照时不该拿它挡 UI** —— 那样就白做快照了。 */
  busy: boolean;
  err: string | null;
  /** 手动重扫(两处 `↻ 上次刷新 HH:MM` 按钮) */
  refresh: () => void;
  /** 只在数据比 `maxAgeMs` 还旧时才重扫。给"界面刚被看到"这类时刻用。 */
  refreshIfStale: (maxAgeMs?: number) => void;
} {
  const { revalidate, enabled = true } = opts;
  const [data, setData] = useState<TrafficData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const running = useRef(false);

  const scan = useCallback(() => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setErr(null);
    invoke<string>("run_traffic", { args: ["--days", "90", "--json"] })
      .then((raw) => { setData(JSON.parse(raw) as TrafficData); })
      .catch((e: unknown) => { setErr(String(e).slice(0, 200)); })
      .finally(() => { running.current = false; setBusy(false); });
  }, []);

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
        if (snap) setData(snap);
        const age = snap ? Date.now() - snap.generated_at * 1000 : Infinity;
        if (revalidate || age > FRESH_MS) scan();
      })
      .catch(() => { if (alive) scan(); });
    return () => { alive = false; };
  }, [enabled, revalidate, scan]);

  // 岁数判断要读**最新**的 data,但不该让 `refreshIfStale` 每次 data 变就换引用(它挂在
  // 事件监听和定时器上,换引用 = 反复解绑重绑)。所以走 ref。
  const dataRef = useRef<TrafficData | null>(null);
  dataRef.current = data;

  const refreshIfStale = useCallback((maxAgeMs: number = FRESH_MS) => {
    const g = dataRef.current?.generated_at;
    if (g == null || Date.now() - g * 1000 > maxAgeMs) scan();
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

  return { data, busy, err, refresh: scan, refreshIfStale };
}
