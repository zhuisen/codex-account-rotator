import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import type { TrafficData, CacheMode, PlatformPrefs } from "../traffic";
import { applyCacheMode, applyPlatformPrefs } from "../traffic";
import { useCacheMode } from "./useCacheMode";
import { usePlatformPrefs } from "./usePlatformPrefs";
import { useBusyMirror } from "./useBusyMirror";
import { getSettings } from "../pages/SettingsPage";

/**
 * 数据在这个岁数内算新鲜。**挂载、心跳、托盘弹出共用同一个概念**,只是托盘弹出用更紧的阈值
 * (用户主动点开就是想看现在的数)。
 *
 * ⚠️ 别再给挂载单独设一个更宽松的阈值:那样会出现「挂载时容忍 10 分钟旧、30 秒后心跳又按 2 分钟
 * 判定要重扫」—— 同一个"新鲜"两套标准,实测就是这么多扫了一次(2026-08-09)。
 */
const FRESH_MS = 2 * 60 * 1000;

/**
 * 后台自动保鲜的总开关（设置页「后台自动刷新」，用户 2026-08-19）。
 *
 * ★ **每次 tick 现读,不在 effect 建立时读一次**。两个 webview 的 localStorage 不互通,
 *   在 effect 里读就得再搭一套 Tauri 广播(同 `usePrivacy` 那套);现读则改完最多 30 秒生效,
 *   零plumbing。这是本项目少数「轮询比广播更简单」的地方 —— 因为这里本来就有一个 30s 的节拍。
 * ★ 它**只管心跳**。"进用量页"和"托盘弹出"两条触发点不受影响,否则关掉之后页面就再也不更新了。
 */
function autoRefreshEnabled(): boolean {
  try { return getSettings().autoRefresh !== false; } catch { return true; }
}
/** 新鲜度检查的节拍。只是"到点看一眼岁数",不到期不扫,所以 30s 并不等于 30s 扫一次。 */
const TICK_MS = 30 * 1000;

/**
 * 默认取数窗口。**热路径恒用它**（心跳 / 菜单栏弹出 / 进页面）。
 *
 * ★★ 实测 2026-09-12：热路径 `--days 90` **1.06s**，`--days 365` **7.65s**。
 *   所以「年度」「自定义」不能靠把默认窗口调大来实现 —— 那会让每 2 分钟的心跳和
 *   每次弹出托盘都慢 7 倍，代价压在**完全没用到年度视图**的那些时刻上。
 *   非默认窗口走各自的快照文件（`lib.rs::snapshot_name`），**且不跑心跳、不广播**。
 */
export const DEFAULT_DAYS = 90;

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
export function useTraffic(opts: {
  enabled?: boolean;
  /** 取数窗口（天）。缺省 = `DEFAULT_DAYS`(90) 的热路径行为，一个字都没变。
   *  非默认值走自己的快照文件、**不跑心跳、不广播** —— 见 `DEFAULT_DAYS` 上的说明。 */
  days?: number;
} = {}): {
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
  /** 平台呈现偏好(改名/改色/停用/顺序)。`data` 与 `raw` 都**已经**套过它,这里返回它只是给
   *  设置页和"按用户顺序排列表"用 —— 别拿它再过滤一次数据。 */
  prefs: PlatformPrefs;
  /** 正在后台扫描。**有快照时不该拿它挡 UI** —— 那样就白做快照了。
   *  ★ 包含**另一个 webview** 正在扫的情况：两个窗口读的是同一份快照，
   *  只有一边转圈就等于在说"这边没事发生"，而事实是数据马上要变。 */
  busy: boolean;
  err: string | null;
  /** 手动重扫(两处 `↻ 上次刷新 HH:MM` 按钮) */
  refresh: () => void;
  /**
   * ★★★ 给**窗口外**的某一天现补逐小时桶（用户 2026-09-15 选的「更早按需重扫」）。
   *
   * `scan.py` 只对最近 `HOURLY_DAYS`(30) 天留小时桶 —— 全部 1095 天都留会把快照从
   * 1.1 MB 撑到约 37 MB，而它每次扫描都要重写。更早的某一天要现扫一次。
   * ★ 重复调同一天是**空操作**（记在 `askedHours` 里）：图表每次渲染都会发现"没有小时桶"，
   *   不记的话就是每帧起一次 python。
   */
  requestHoursFor: (day: string) => void;
  /** 只在数据比 `maxAgeMs` 还旧时才重扫。给"界面刚被看到"这类时刻用。 */
  refreshIfStale: (maxAgeMs?: number) => void;
} {
  const { enabled = true, days = DEFAULT_DAYS } = opts;
  const isDefault = days === DEFAULT_DAYS;
  const [data, setData] = useState<TrafficData | null>(null);

  /** 读**本窗口**那一份快照。两个命令而不是一个带可选参数的命令 —— 见 lib.rs 里的说明。 */
  const readSnap = useCallback(
    (): Promise<string | null> => (isDefault
      ? invoke<string | null>("read_traffic_snapshot")
      : invoke<string | null>("read_traffic_snapshot_days", { days })),
    [isDefault, days]);
  const [busy, setBusy] = useState(false);
  const { remote: remoteBusy, announce } = useBusyMirror();
  const [err, setErr] = useState<string | null>(null);
  const running = useRef(false);
  // ★ 声明提到这里:下面「换窗口清空」那个 effect 要复位它,而它原本声明在更靠后的位置。
  const primed = useRef(false);

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
   * 每个窗口一份**内存缓存**。→ 来回切档不再重新加载。
   *
   * ★★ 用户 2026-09-12：「不要每次选择都是要重新刷新加载，这样会影响使用」。
   *   扫描侧的真因已经修掉了（`scan.py::_merge_cache`，交替窗口 5.2~8.3s → 1.1s），
   *   但只修那一半还不够：换窗口时这里会把 `data` 清空，于是**每次**切档都要看一次骨架屏。
   *   有了这张表，切回去是**零等待**（内存命中，连读盘都省）。
   *
   * ★ 放 `useRef` 不放 state：它不该触发渲染，且两次渲染之间必须是同一张表。
   */
  const byWindow = useRef(new Map<number, TrafficData>());
  useEffect(() => {
    if (data) byWindow.current.set(lastDays.current, data);
  }, [data]);

  /**
   * ★★★ **换窗口时，要么换上这个窗口的数据，要么清空 —— 绝不能留着上一个窗口的。**
   *
   * `adopt` 只在 `generated_at` 更新时才换数据（那是为"广播/快照谁更新"设计的）。
   * 换窗口时新那份**可能更旧**（年度快照是几小时前扫的，90 天那份刚扫过），
   * 于是 `adopt` 会拒绝它，页面继续画 90 天的数、而横轴和标题已经写着「年度」——
   * 图照画、数字照变，**一个字都不报错**。
   *
   * 所以命中缓存就直接换上（无骨架屏），没命中才清空。**清空这一步不能省** ——
   * 省掉它就是上面那种"拿 A 的数配 B 的轴"。
   */
  const lastDays = useRef(days);
  useEffect(() => {
    if (lastDays.current === days) return;
    lastDays.current = days;
    const hit = byWindow.current.get(days);
    setData(hit ?? null);
    primed.current = false;      // 仍要后台校验新鲜度，只是不再让用户等
  }, [days]);

  /**
   * `force = true` 只给手动的 ↻ 用:用户明确要"现在重取",不看新鲜度。
   * 其余路径都先读一次盘 —— **另一个 webview 可能刚扫完**,那就省掉一次 1.4s 的重复扫描。
   */
  const scan = useCallback(async (force = false) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    // ★ 与账号池动作同一条纪律:进行态也要广播,否则另一个窗口在整个扫描期间
    //   (冷路径 ~23s)看起来什么都没发生。用户 2026-09-06 在「刷新全池」上报过同款。
    announce("traffic-scan");
    setErr(null);
    try {
      if (!force) {
        const snap = parse(await readSnap());
        if (snap && Date.now() - snap.generated_at * 1000 <= FRESH_MS) { adopt(snap); return; }
      }
      const raw = await invoke<string>("run_traffic", { args: ["--days", String(days), "--json"] });
      adopt(parse(raw));
      // ★ 告诉另一个 webview:数据更新了,**去读盘,别自己再扫一遍**。
      //   两个窗口是独立 JS 上下文,localStorage 都不互通,只能走 Tauri 事件(同 usePrivacy 的范式)。
      // ★ 只有默认窗口才广播。非默认窗口写的是另一份快照文件,广播出去只会让对方
      //   白读一次默认快照(且因为更旧会被 `adopt` 丢掉)—— 一次无意义的往返。
      if (isDefault) void emit("traffic-updated");
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    } finally {
      running.current = false;
      setBusy(false);
      announce(null);
    }
    // ★★ `days` / `readSnap` / `isDefault` 都必须在依赖里。漏掉的后果**不是不刷新**，
    //    是**刷了错的那个窗口**:这个闭包会一直拿着切换之前的 `days` 去调 `run_traffic`，
    //    然后把结果写进那个窗口的快照 —— 年度视图永远等不到自己的数据，
    //    而页面只是安静地显示 0。
  }, [adopt, announce, days, readSnap, isDefault]);

  // 对方扫完 → 读盘采纳。一次 ~1ms 的文件读,不起 python。
  useEffect(() => {
    if (!enabled) return;
    if (!isDefault) return;          // 别拿默认窗口的数据去填年度视图
    const un = listen("traffic-updated", () => {
      void invoke<string | null>("read_traffic_snapshot").then((raw) => { adopt(parse(raw)); });
    });
    return () => { void un.then((f) => f()); };
  }, [enabled, adopt, isDefault]);

  // ★ 只跑一次:`data` 一旦有值就不再重入。主窗口钻进平台详情页再返回、菜单栏来回切 Tab,
  //   都不该触发新的扫描。
  useEffect(() => {
    if (!enabled || primed.current) return;
    primed.current = true;
    let alive = true;
    readSnap()
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
    // ★★★ `readSnap` 必须在依赖里。它随 `days` 变 —— 没有它，换窗口时上面那个
    //    「清空 + primed 复位」的 effect 跑完之后**没有任何东西会再触发取数**：
    //    effect 只在依赖变化时重跑，复位一个 ref 不会让 React 重跑它。
    //    症状是切到年度档后页面恒为 0，而且零报错（实测 2026-09-12，harness 截图抓到的）。
  }, [enabled, adopt, scan, readSnap]);

  // 岁数判断要读**最新**的 data,但不该让 `refreshIfStale` 每次 data 变就换引用(它挂在
  // 事件监听和定时器上,换引用 = 反复解绑重绑)。所以走 ref。
  const dataRef = useRef<TrafficData | null>(null);
  dataRef.current = data;

  /** 已经为哪些日期补过小时桶。★ 见 `requestHoursFor` 的注释：不记就是每帧起一次 python。 */
  const askedHours = useRef<Set<string>>(new Set());
  const requestHoursFor = useCallback((day: string) => {
    if (!day || askedHours.current.has(day)) return;
    askedHours.current.add(day);
    announce("traffic-scan");
    setBusy(true);
    void invoke<string>("run_traffic",
                        { args: ["--days", String(days), "--hours-day", day, "--json"] })
      .then((raw) => { adopt(parse(raw)); if (isDefault) void emit("traffic-updated"); })
      .catch((e: unknown) => {
        // ★ 失败就把这一天从"问过了"里拿掉 —— 否则用户再点也不会重试，
        //   而界面上"补过但没有数据"和"补失败了"长得一模一样。
        askedHours.current.delete(day);
        setErr(String(e).slice(0, 200));
      })
      .finally(() => { setBusy(false); announce(null); });
  }, [days, adopt, isDefault, announce]);

  const refreshIfStale = useCallback((maxAgeMs: number = FRESH_MS) => {
    const g = dataRef.current?.generated_at;
    if (g == null || Date.now() - g * 1000 > maxAgeMs) void scan();
  }, [scan]);

  /**
   * ★ **重新进入用量页时补一次保鲜检查。**
   *
   * 不是冗余 —— 上面那个初始化 effect 被 `primed` **永久**锁住，而 `App.tsx` 用的是
   * `useTraffic({ enabled: page === "traffic" })`：离开再回来时 `enabled` 重新为真，
   * 但 `primed.current` 已经是 true，effect 直接 return。**所以第二次以后进这个页面根本不刷新。**
   *
   * 在"心跳永远开着"的年代这个洞被心跳兜住了，看不出来。一旦允许关掉心跳（用户 2026-08-19 的开关），
   * 它就会变成「打开页面也不更新」——而那恰恰是用户明确要保留的行为。所以开关和这个补丁必须同批上。
   *
   * 只在**再次进入**时跑（`primed.current` 已为真）：首次进入由初始化 effect 负责，
   * 两个都跑会在冷启动时多一次判断。`refreshIfStale` 本身只看岁数，不到期不扫。
   */
  const wasEnabled = useRef(false);
  useEffect(() => {
    const entering = enabled && !wasEnabled.current;
    wasEnabled.current = enabled;
    if (entering && primed.current) refreshIfStale();
  }, [enabled, refreshIfStale]);

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
    // ★ 心跳**只给默认窗口**。年度那档一次扫描 7.6s,每 2 分钟自动跑一遍是纯浪费 ——
    //   而且用户停在年度视图上时,数据本来就是按月看的,分钟级新鲜度没有意义。
    if (!enabled || !isDefault) return;
    const id = setInterval(() => {
      if (!autoRefreshEnabled()) return;
      if (document.visibilityState === "visible") refreshIfStale();
    }, TICK_MS);
    return () => { clearInterval(id); };
  }, [enabled, refreshIfStale, isDefault]);

  // ★ 口径重塑放在**出口**,不进 state:扫描/快照/广播那套逻辑完全不知道有这回事,
  //   切口径也就不会触发任何重扫(它只是换个算法看同一份数据)。`full` 时返回原引用,零开销。
  const { mode: cacheMode } = useCacheMode();
  const { prefs } = usePlatformPrefs();
  // ★ 顺序:先按缓存口径重塑,再套平台偏好。两者独立,但**都必须在这一个出口做**——
  //   停用一家要让总计跟着扣(用户 2026-08-12 定稿),逐处过滤必漏,漏的那处会把它算回总数。
  //   `raw` 同样要过滤(它给缓存占比/构成行用),否则"已停用"的平台仍会混进缓存占比的分母。
  const shaped = useMemo(
    () => applyPlatformPrefs(applyCacheMode(data, cacheMode), prefs), [data, cacheMode, prefs]);
  const shapedRaw = useMemo(() => applyPlatformPrefs(data, prefs), [data, prefs]);

    // ★ 对方在扫也算 busy —— 见 `busy` 字段上的说明。
  return { data: shaped, raw: shapedRaw, cacheMode, prefs,
           busy: busy || remoteBusy === "traffic-scan", err,
           refresh: () => void scan(true), refreshIfStale, requestHoursFor };
}
