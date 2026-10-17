import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useNotchData } from "./hooks/useNotchData";
import { useAgyPool } from "./hooks/useAgyPool";
import { usePlatformPrefs } from "./hooks/usePlatformPrefs";
import { usePrivacy } from "./hooks/usePrivacy";
import { agyShown, agyWinRows } from "./agy";
import { maskId, slotToAccount, inUseAid } from "./helpers";
import { agySegs, codexSegs, ringNum, segColor, type NotchSeg } from "./notchSegs";
import { platformColor } from "./theme";
import "./notch.css";

/** 面板开着时倒计时文字的刷新间隔。收起时细线只画百分比，不需要它。 */
const OPEN_TICK_MS = 30_000;
/** 「下一个时间点」闹钟的上限：睡眠唤醒后计时器会晚到，最多晚这么久自己纠正。 */
const MAX_WAKE_MS = 60 * 60 * 1000;

/** 与 `notch.rs` 的 `PANEL_W`、`notch.css` 的 `--pw` 同值。闸在 `tests/test_notch_hud.py`。 */
const PANEL_W = 312;
/** 读不到的额度窗口在光晕里的颜色（theme 的 muted）。读不到 ≠ 0，不能画红。 */
const UNKNOWN = "#798390";

/**
 * 刘海额度条（用户 2026-10-17 从 demo 里选定：收起 = 刘海周围的光晕〔起初是下沿细线，用户嫌不明显改成光晕〕，悬停 = 额度环面板；
 * 只显示 Codex 与 Antigravity；默认关）。窗口、层级、悬停判定全在 `notch.rs`，这里只画；
 * 画什么在 `notchSegs.ts`（纯函数，有行为闸）。
 *
 * ★ 颜色走**托盘那一条**规则（`quotaColor`：<50 琥珀、否则绿；显示成 0 额外标红）——
 *   刘海条和托盘标题是同一类"瞄一眼"的指示，两处说法必须一致（ui.md「额度色阈值只有一条规则」）。
 * ★ 取数**一个子进程都不起、也不轮询**：Codex 状态与本机 agy 快照走 `useNotchData`（只听推送）；
 *   `useAgyPool(false)` 只读池文件、收别的 webview 广播的现读结果。保鲜由菜单栏 webview 负责（它是唯一的 `background`）。
 */
type Seg = NotchSeg;

function Ring({ s }: { s: Seg }) {
  const r = 18, c = 2 * Math.PI * r;
  const col = s.pct == null ? "#8a929c" : segColor(s.pct);
  const d = s.pct == null ? 0 : (ringNum(s.pct) / 100) * c;
  return (
    <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
      <circle cx="23" cy="23" r={r} fill="none" stroke="rgba(255,255,255,.14)" strokeWidth="4" />
      {s.pct != null && (
        <circle cx="23" cy="23" r={r} fill="none" stroke={col} strokeWidth="4" strokeLinecap="round"
                strokeDasharray={`${d.toFixed(2)} ${c.toFixed(2)}`} transform="rotate(-90 23 23)" />
      )}
      <text x="23" y="27" textAnchor="middle" fontFamily="'JetBrains Mono', ui-monospace, Menlo, monospace"
            fontSize="11" fontWeight="600" fill={col}>{s.pct == null ? "—" : ringNum(s.pct)}</text>
    </svg>
  );
}

export default function NotchHud() {
  const { state, agy: agySnap } = useNotchData();
  // ★ agy 走池（四方评审 2026-10-17）：`useAgyPool(false)` 只读池文件、只收 `agy-pool-updated` /
  //   `agy-live-changed` 两个推送，不起子进程、不轮询。本机 RPC 那份（`agySnap`）只在 `snapshotOf`
  //   能证明归属时才用 —— 自 agy 1.2 起它恒 `csrf_required`，单用它就是画几周前的 `last_good`。
  const agyPool = useAgyPool(false);
  const { prefs } = usePlatformPrefs();
  const { privacy } = usePrivacy();
  const [open, setOpen] = useState(false);
  /** 只为让「随时间变」的部分重算：窗口过重置点、冷却结束、倒计时文字。 */
  const [tick, setTick] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const geom = (g: { width: number; height: number } | null | undefined) => {
      if (!g) return;
      document.documentElement.style.setProperty("--nw", `${g.width}px`);
      document.documentElement.style.setProperty("--nh", `${g.height}px`);
    };
    let dead = false;
    const uns = [
      listen<boolean>("notch-open", (e) => setOpen(!!e.payload)),
      // 改分辨率 / 换屏后刘海尺寸变了，Rust 摆完窗口再告诉这里
      listen<{ width: number; height: number }>("notch-geom", (e) => geom(e.payload)),
    ];
    // ★ 两个监听都注册好之后再问一次当前状态：窗口刚建好时光标已经停在刘海上，
    //   `notch-open` 可能早于 listen 生效 —— 不补这一句，Rust 认为展开了、这里还收着。
    void Promise.all(uns).then(() => invoke<{ width: number; height: number; open?: boolean } | null>("notch_geometry"))
      .then((g) => { if (dead || !g) return; geom(g); setOpen(!!g.open); })
      .catch(() => {});
    return () => { dead = true; for (const u of uns) void u.then((f) => f()); };
  }, []);

  const { inUse, live } = useMemo(() => {
    const slots = state.slots ?? {};
    // `slotToAccount` 第三参是 token 表，只影响 token 过期提示，额度窗口与状态用不到 ——
    // 刘海条因此不读 `read_auth_tokens`（useStore 每 30s 读一次全部 token）。
    const accts = Object.entries(slots).map(([aid, sl]) => slotToAccount(aid, sl, {}, state.pinned));
    const aid = inUseAid(state);
    return {
      inUse: accts.find((a) => a.aid === aid),
      live: accts.filter((a) => a.status === "live" || a.status === "low").length,
    };
  }, [state, tick]);   // tick：数据没变时让 now 前进（窗口过重置点、冷却结束）

  // agy 画哪一份：池里当前号的（与菜单栏同一条）；池还没建起来就退回本机那份
  const agyCur = agyPool.accounts.find((a) => a.sub === agyPool.liveSub);
  const agyShownSnap = useMemo(
    () => (agyCur ? agyPool.snapshotOf(agyCur, agySnap) : agyPool.accounts.length === 0 ? agySnap : null),
    [agyCur, agyPool.snapshotOf, agyPool.accounts.length, agySnap]);

  // ★ 下一个「数据没变、但该重画」的时间点：在用号各窗口的重置点、agy 各窗口的重置点、
  //   任一号冷却结束。只定这一个闹钟，到点重算；空闲时没有任何周期性工作。
  useEffect(() => {
    const now = Date.now() / 1000;
    const times: number[] = [];
    const q = (state.slots ?? {})[inUseAid(state) ?? ""]?.quota;
    for (const w of [q?.primary, q?.secondary]) if (w?.resets_at) times.push(w.resets_at);
    for (const sl of Object.values(state.slots ?? {})) if (sl.cooling_until) times.push(sl.cooling_until);
    for (const r of agyWinRows(agyShown(agyShownSnap)?.quota)) if (r.reset_at) times.push(r.reset_at);
    const next = Math.min(...times.filter((t) => t > now));
    const ms = Number.isFinite(next) ? Math.min((next - now) * 1000 + 1000, MAX_WAKE_MS) : MAX_WAKE_MS;
    const id = setTimeout(() => setTick((n) => n + 1), ms);
    return () => clearTimeout(id);
  }, [state, agyShownSnap, tick]);

  // 面板开着才走倒计时文字
  useEffect(() => {
    if (!open) return;
    setTick((n) => n + 1);
    const id = setInterval(() => setTick((n) => n + 1), OPEN_TICK_MS);
    return () => clearInterval(id);
  }, [open]);

  const segs = useMemo<Seg[]>(() => [
    ...codexSegs(inUse, !!prefs.by?.codex?.off),
    ...agySegs(agyShownSnap, !!prefs.by?.agy?.off, agyPool.accounts.length > 0 && !agyCur),
  ], [inUse, agyShownSnap, agyCur, agyPool.accounts.length, prefs, tick]);   // tick：让 agy 倒计时文字前进

  // 面板自然高度随窗口个数变 → 报给 Rust，展开时按它定窗口高
  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const report = () => { invoke("notch_panel_height", { h: el.scrollHeight }).catch(() => {}); };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const node = inUse ? maskId(inUse.node, privacy) : null;

  // 谁正在跑 —— Rust 看 Codex rollout / agy 对话库的写入时间，**变了才推**（`notch.rs::watch_activity`）。
  // 用户 2026-10-17：Codex 跑亮 Codex 色、agy 跑亮 agy 色、同时跑两个都亮；空闲只剩细线慢呼吸。
  const [act, setAct] = useState<{ codex: boolean; agy: boolean }>({ codex: false, agy: false });
  useEffect(() => {
    invoke<{ codex: boolean; agy: boolean } | null>("notch_activity").then((a) => { if (a) setAct(a); }).catch(() => {});
    const un = listen<{ codex: boolean; agy: boolean }>("notch-activity", (e) => setAct(e.payload));
    return () => { void un.then((f) => f()); };
  }, []);
  // 平台色：用户在设置里改过就用改过的，否则静态表（同 colorOf 的优先级，刘海条没有扫描结果那一层）
  const colorOfK = (k: string) => prefs.by?.[k]?.color ?? platformColor(k);
  const lit = [act.codex && !prefs.by?.codex?.off && colorOfK("codex"),
               act.agy && !prefs.by?.agy?.off && colorOfK("agy")].filter(Boolean) as string[];
  // ★ 光晕两种含义（用户 2026-10-17 选定）：平时 = 额度（每个窗口一段，按剩余着色，段间渐变，
  //   第 i 段的色标在 (i+.5)/n，与 Agent HUD 同法）；有平台在跑 = 整圈换成平台色，停下恢复额度色。
  const quotaGlow = segs.length === 0 ? "transparent"
    : segs.length === 1 ? (segs[0].pct == null ? UNKNOWN : segColor(segs[0].pct))
    : `linear-gradient(90deg, ${segs.map((s, i) =>
        `${s.pct == null ? UNKNOWN : segColor(s.pct)} ${(((i + 0.5) / segs.length) * 100).toFixed(1)}%`).join(", ")})`;
  const platformGlow = lit.length === 2 ? `linear-gradient(90deg, ${lit[0]} 0%, ${lit[0]} 30%, ${lit[1]} 70%, ${lit[1]} 100%)`
                     : lit[0];
  const glow = lit.length > 0 ? platformGlow : quotaGlow;
  return (
    <div className={[open && "nh-open", lit.length > 0 && "nh-active",
                     lit.length === 0 && segs.length === 0 && "nh-quiet"].filter(Boolean).join(" ") || undefined}
         style={{ ["--pw" as string]: `${PANEL_W}px`, ["--glow" as string]: glow }}>
      <div className="nh-glow" aria-hidden="true"><i className="g2" /><i className="g1" /></div>
      <div className="nh-panel" ref={panelRef}
           onClick={() => { invoke("set_main_visible", { show: true }).catch(() => {}); }}>
        <div className="nh-head"><b>额度剩余 %</b><span>{node ? `Codex 在用 ${node}` : ""}</span></div>
        {segs.length === 0 && <div className="nh-empty">暂无可显示的额度（Codex / agy 都没开或都没读到）</div>}
        <div className="nh-rings" style={{ gridTemplateColumns: `repeat(${Math.max(1, segs.length)}, 1fr)` }}>
          {segs.map((s) => (
            <div key={s.key} className={`nh-ring${s.stale ? " stale" : ""}`} title={s.title}>
              <Ring s={s} />
              <span className="nm">{s.name}</span>
              <span className="rs">{s.reset}</span>
            </div>
          ))}
        </div>
        <div className="nh-foot">账号池 <b>{live}</b> 个号可用 · 点这里打开 CodexBar</div>
      </div>
      <div className="nh-island" />
    </div>
  );
}
