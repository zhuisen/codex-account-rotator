import { useEffect, useState, useCallback, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { Theme } from "../theme";
import Seg from "../components/Seg";

/**
 * 代理轮换（泳道时间轴）· 1:1 复刻用户 2026-09-07 的交接稿
 * `~/Downloads/design_handoff_codexbar 5/代理轮换-交接说明.md` + 同目录原型。
 *
 * 回答四个问题：**什么时间 · 哪个号在岗 · 烧了多少 token（哪些模型）· 为什么切换**。
 *
 * ## 与稿子的三处刻意偏离（都不是照抄不动，是稿子的前提在真机上不成立）
 *
 * 1. **账号配色不按稿子的具体映射**（稿子写死 plus5=#2dd4bf 等六条）。label 用户可改名，
 *    把一次快照写成规则迟早对不上。复刻的是**调色板 + 每号专属色**这条不变量，
 *    分配在 `traffic/rotation.py::assign_colors`（散列偏好 + 线性探测，保证互不相同 ——
 *    纯散列实测当场让 Pro1 与 plus6 撞成同一个紫）。
 * 2. **多一行覆盖率脚注**。稿子把「612M token」当完整总量写，而真机上 token 只能归属到
 *    **走过代理**的响应（实测 93%）；直连 `codex` 的请求根本不经过代理，永远不在里面。
 *    把下界当总量画出来和编造没有区别，所以合计旁边必须写明它是下界。
 * 3. **段会比稿子碎得多**。稿图是 13 段 / 平均驻留 1h51m；真机 24h 是 28 段 / 5m ——
 *    因为代理是**逐请求**挑号的，本来就不存在长时间"驻留"。这是数据的真相不是渲染问题。
 */

const WINDOWS = [1, 6, 24, 168] as const;
type WinH = (typeof WINDOWS)[number];
const winLabel = (h: WinH): string => (h === 168 ? "7d" : `${h}h`);

/** 时间窗选择要**记住**（用户 2026-09-07：「我选 6h，下次打开也是 6h」）。
 *  ★ 用 localStorage 而不是 `state.json`：这是**纯展示偏好**，代理与后台任务都不读它，
 *    与「参与轮换」那种必须让 app 关着的代理也能读到的开关不是一回事。
 *  ★ 读回来要**校验在合法集合里**：localStorage 里是字符串，手改过或旧版本留下的值
 *    会变成一个谁都不匹配的窗口，页面就永远空着且没有任何报错。 */
const WIN_KEY = "codexbar_rot_win";
function loadWin(): WinH {
  try {
    const n = Number(localStorage.getItem(WIN_KEY));
    if ((WINDOWS as readonly number[]).includes(n)) return n as WinH;
  } catch { /* 无痕模式：本次用默认值 */ }
  return 24;
}

interface Seg0 {
  acc: string;
  start: number;
  end: number;
  requests: number;
  tokens: number;
  by_model: { model: string; tokens: number }[];
  enter_reason: string;
  current?: boolean;
}
interface Acct {
  acc: string;
  /** 套餐。★ 看 `plan` 不看 label —— 老号从 Plus 升 Pro 时 label 一个字都不变。 */
  plan: string;
  color: string;
  tokens: number;
  requests: number;
  top_model: { model: string; share: number } | null;
  quota_pct: number | null;
}
interface Marker { acc: string; t: number; kind: string }
interface Ev { t: number; type: string; from: string | null; to: string | null; reason: string; text: string; accs: string[] }
interface Rotation {
  ok: boolean;
  reason?: string;
  detail?: string;
  generated_at: number;
  window: { start: number; end: number; hours: number };
  accounts: Acct[];
  segments: Seg0[];
  markers: Marker[];
  events: Ev[];
  log: { t: number; text: string }[];
  kpi: {
    tokens: number; requests: number; avg_tokens: number;
    rotations: number; avg_dwell: number; cool_429: number; stream_err: number;
    pro_segs: number; pro_secs: number;
  };
  coverage: {
    responses_seen: number; responses_with_tokens: number; responses_unplaced: number;
    attributed_pct: number | null; undated_lines: number; in_window_lines: number; tail_truncated: boolean;
  };
}

// 稿子 §2 的模型色：主 → 次 → 第三（同族三档青），之后接其它色相。
const MODEL_SHADES = ["#2dd4bf", "#7fe8da", "#158f80", "#4d9fff", "#8b7cf6", "#E0A21C"];
const COOL = "#2BA0C0";
const WARN = "#E0901C";
const GOOD = "#27B26B";
const BAD = "#E0524D";
const MONO = "'JetBrains Mono'";

const fmtTok = (n: number): string =>
  n >= 1e9 ? `${(n / 1e9).toFixed(2)}B`
    : n >= 1e8 ? `${Math.round(n / 1e6)}M`
      : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M`
        : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(Math.round(n));

const clock = (ts: number): string => {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
const dur = (secs: number): string => {
  const m = Math.round(secs / 60), h = Math.floor(m / 60), mm = m % 60;
  return (h ? `${h}h` : "") + (mm || !h ? `${mm}m` : "");
};

/** 稿子 §1：额度 100% 绿 / <50% 琥珀 / 0% 红。★ 读不到是 `null`，走中性灰**不画成满额**。 */
const quotaColor = (p: number | null, t: Theme): string =>
  p === null ? t.muted : p === 0 ? BAD : p < 50 ? WARN : GOOD;

const REASON_CN: Record<string, string> = {
  cool_429: "429 冷却 → 故障转移",
  stream_err: "断流 → 轮换",
  quota_rotate: "额度轮换",
  window_start: "窗口起点",
  pro_fallback: "Plus 全部不可用 → Pro 保底接管",
};
const EV_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  switch: { label: "切换", color: "#2dd4bf", bg: "rgba(45,212,191,.12)" },
  failover: { label: "故障转移", color: COOL, bg: "rgba(43,160,192,.14)" },
  cool_429: { label: "429 冷却", color: COOL, bg: "rgba(43,160,192,.14)" },
  stream_err: { label: "断流", color: WARN, bg: "rgba(224,144,28,.14)" },
  // ★★ 三类失败的计费含义完全不同,颜色必须一眼分得开(`CLAUDE.md` §8「计费相位分界」):
  //   断流=已计费(琥珀) · **计费未知=可能已计费(红,唯一的危险级)** · 安全换号=没计费(中性)。
  //   合并成一个"错误"色,用户就再也分不出「白花了钱」和「安全换了个号」。
  billed_unknown: { label: "计费未知", color: BAD, bg: "rgba(224,82,77,.14)" },
  safe_switch: { label: "安全换号", color: "#8a93a0", bg: "rgba(255,255,255,.06)" },
  probe: { label: "探活", color: "#8a93a0", bg: "rgba(255,255,255,.06)" },
  // ★ 「Pro 保底接管」用紫色(与卡片上的 PRO 徽章同色系),不用红 ——
  //   它是**按设计工作**,不是故障;染红会训练用户忽略真正的告警。
  pro_fallback: { label: "Pro 保底", color: "#8b7cf6", bg: "rgba(139,124,246,.16)" },
};

interface Tip {
  xPct: number; laneIdx: number; flip: boolean;
  range: string; dur: string; acc: string; tokens: number; requests: number;
  models: { model: string; tokens: number; pct: number; color: string }[];
  errs: number; why: string;
}

const LANE_H = 40;
/** 下半区两栏的统一高度。两边共用**一个**常量 —— 各写一个数迟早只改一边。 */
const PANEL_H = 320;
/** 泳道左列宽。★ 字号从 13 提到 14.5 后 96px 会把 `plus4` 截成 `plu…`（截图实证）——
 *  **字号与列宽是同一件事的两半**，只改一边就是在制造截断。名字后面还要放「当前」徽章。 */
/** 泳道左列宽。★ 三次被字号/徽章追着改，这次按**最坏情况**定死：
 *  圆点 8 + 名字 ~44（`plus4` 5 字符 @14.5px 等宽）+ `PRO` 徽章 ~34 + `当前` 徽章 ~40 + 3 个 gap 21
 *  = 147。取 152 留一点余量。
 *  ⚠️ 之前是 118：Pro 号同时挂 `PRO` 和 `当前` 两个徽章时，名字只剩 ~20px，被截成 `Pr…`
 *  （用户截图实证）。**认不出是哪个号，比时间轴窄 34px 严重得多** —— 让位者绝不能是名字。 */
const NAME_W = 152;
const STAT_W = 300;

export default function LogsPage({ t }: { t: Theme }): React.ReactElement {
  const [rot, setRot] = useState<Rotation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [win, setWinState] = useState<WinH>(loadWin);
  const setWin = useCallback((h: WinH) => {
    setWinState(h);
    try { localStorage.setItem(WIN_KEY, String(h)); } catch { /* 无痕模式：本次不记住 */ }
  }, []);
  /** 后台正在重扫（快照已经画出来了，这只是个不打断阅读的小标记）。 */
  const [busy, setBusy] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [filter, setFilter] = useState<string>("all");

  const load = useCallback(async (hours: WinH) => {
    // ★★ 两段式:先把**成品快照**画出来(读盘 ~1ms),再后台重扫。
    //    用户报的「太卡」就是缺这一段 —— 原来每次进页面/切窗口都同步等一次全扫
    //    (实测 1h 0.9s / 24h 1.7s / 7d 3.3s,冷缓存下更久)。
    // ★ 快照可能是**旧的**,所以重扫照跑;但先画出来的那一刻页面已经可读了。
    try {
      const snap = await invoke<Rotation | null>("read_rotation_snapshot", { hours });
      if (snap && snap.ok) { setRot(snap); setErr(null); }
    } catch { /* 没有快照是首次运行的正常状态，不是故障 */ }

    setBusy(true);
    try {
      const r = await invoke<Rotation>("read_proxy_rotation", { hours });
      setRot(r.ok ? r : null);
      setErr(r.ok ? null : (r.detail ?? "读不到 proxy/proxy.log"));
    } catch (e: unknown) {
      // ★ 失败必须清空,**不能留着上一窗口的数** —— 换窗口失败后旧数字还挂在新标签下面,
      //   看上去完全正常。同本仓「降级态恒 None,绝不写 0」。
      setRot(null);
      setErr(String(e));
    } finally {
      // ★ 必须在 `finally`:失败时不熄灯的话,那盏「刷新中」会一直亮着 ——
      //   长亮又灭不掉的灯是本仓判过死刑的形态。
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    load(win);
    const id = setInterval(() => load(win), 30_000);
    return () => clearInterval(id);
  }, [load, win]);

  // 切窗口/切聚焦时浮层必须消失 —— 它存的是「某个数据集里的位置」,数据换了它就过期了,
  // 而过期的浮层会理直气壮地描述另一段时间(本仓 StackedArea 那条同族教训)。
  useEffect(() => { setTip(null); }, [win, rot?.generated_at]);

  const W = rot?.window;
  const span = W ? Math.max(1, W.end - W.start) : 1;
  const pct = (ts: number): number => ((ts - (W?.start ?? 0)) / span) * 100;

  const lanes = useMemo(() => {
    if (!rot) return [];
    const maxDensity = Math.max(
      1e-9,
      ...rot.segments.map(s => s.tokens / Math.max(60, s.end - s.start)));
    return rot.accounts.map(a => {
      const segs = rot.segments.filter(s => s.acc === a.acc);
      return {
        ...a,
        current: segs.some(s => s.current),
        segs: segs.map(s => ({
          ...s,
          left: pct(s.start),
          width: Math.max(0, pct(s.end) - pct(s.start)),
          // 稿子 §1：色块透明度 = token 密度（.45–1）
          op: 0.45 + (s.tokens / Math.max(60, s.end - s.start) / maxDensity) * 0.55,
        })),
        errs: rot.markers.filter(m => m.acc === a.acc && m.kind === "stream_err").map(m => pct(m.t)),
        cools: rot.markers.filter(m => m.acc === a.acc && m.kind === "cool_429").map(m => pct(m.t)),
      };
    });
  }, [rot]);

  // 轴刻度：1h 每 10 分 / 6h 每小时 / 24h 每 6 小时 / 7d 每天（稿子 §6）
  const axis = useMemo(() => {
    if (!W) return [];
    const stepSec = win === 1 ? 600 : win === 6 ? 3600 : win === 24 ? 6 * 3600 : 86400;
    const out: { left: number; label: string }[] = [];
    // 从窗口末端往回对齐,保证最后一格落在节拍上(全局 ui-design：刻度从末端起稀释)
    for (let ts = W.end; ts >= W.start; ts -= stepSec) {
      const d = new Date(ts * 1000);
      out.unshift({
        left: pct(ts),
        label: win === 168
          ? `${d.getMonth() + 1}/${d.getDate()}`
          : `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
      });
    }
    // 首尾两格让位给「账号」表头与右端的「现在」——它们会重叠。中间的全留。
    return out.filter(x => x.left > 3 && x.left < 88);
  }, [W, win]);

  const evs = useMemo(
    () => (rot?.events ?? []).filter(e => !focus || e.accs.includes(focus)),
    [rot, focus]);

  const logs = useMemo(() => {
    const all = rot?.log ?? [];
    if (filter === "all") return all;
    return all.filter(l => l.text.toLowerCase().includes(filter));
  }, [rot, filter]);

  const cov = rot?.coverage;
  // 覆盖率说明。★ 去掉的是那**一行字**,不是那个**事实** —— 它改挂到 KPI 标签与 title 上。
  const covNote = cov
    ? `只统计走过代理的响应：${cov.responses_with_tokens}/${cov.responses_seen} 次`
      + `（${cov.attributed_pct === null ? "—" : Math.round(cov.attributed_pct * 100) + "%"}）。`
      + `直连 codex 的请求不经过代理，永远不会被算进来，所以这是**下界**不是总量。`
      + (cov.undated_lines > 0 ? ` 另有 ${cov.undated_lines} 行旧格式日志无时间戳、未计入。` : "")
      + (cov.tail_truncated ? " 仅统计日志尾部。" : "")
    : undefined;
  const card: React.CSSProperties = {
    background: t.cardBg, border: `1px solid ${t.cardBorder}`, borderRadius: 13,
  };

  const openTip = (laneIdx: number, s: Seg0, errs: number): void => {
    const mid = (pct(s.start) + pct(s.end)) / 2;
    const total = s.by_model.reduce((x, m) => x + m.tokens, 0) || 1;
    setTip({
      xPct: mid, laneIdx, flip: mid > 55,
      range: `${clock(s.start)} – ${clock(s.end)}`, dur: dur(s.end - s.start),
      acc: s.acc, tokens: s.tokens, requests: s.requests,
      models: s.by_model.slice(0, 4).map((m, i) => ({
        ...m, pct: Math.round((m.tokens / total) * 100), color: MODEL_SHADES[i % MODEL_SHADES.length],
      })),
      errs, why: REASON_CN[s.enter_reason] ?? s.enter_reason,
    });
  };

  return (
    // 页面自带滚动容器：App 内容区是 overflow:hidden,不加这层超出部分会被静默裁掉。
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, overflowY: "auto" }}>
      {/* ── 顶栏：标题 + 汇总条（左）｜图例 + 时间（右）─────────────────────
          用户 2026-09-07 定：方案 B 的单行汇总**并进标题行**，右侧「在岗/断流/429」图例不动。
          ★ 原来标题后面那句副标（`682M token · 371 次请求 · 6 个号`）**已删** ——
            它和汇总条逐字重复。留着就是同一组数字在同一行说两遍。
          ★ 整行允许 `flexWrap`：窄窗口下汇总条掉到第二行，而不是把标题挤没或横向溢出。
            实测 960px 会折，1200 以上单行 —— 折了仍然可读，挤没了就不可读。 */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12,
                    flexShrink: 0, flexWrap: "wrap", rowGap: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.01em", flexShrink: 0 }}>代理轮换</span>

        {/* ★ `flex: 1 1 auto` + `minWidth: 0` 是必需的：不给它，这条汇总是**不可收缩**的，
            于是空间不够时被挤到第二行的会是右边的窗口分段控件（`1h 6h 24h 7d`），
            那玩意独占一整行看着像画错了。给了之后让位者变成汇总条自己 ——
            它内部会折成两行，而折行的数字仍然可读。**指定唯一让位者**，同卡片名字那条。 */}
        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap",
                      // ★ `flex: 1 1 **0**` 不是 `auto`：basis=auto 时浏览器优先把**整项换行**
                      //   （实测 Seg 独占第二行），basis=0 才会让它吃剩余空间、在内部折。
                      flex: "1 1 0", minWidth: 0, rowGap: 4,
                      fontFamily: MONO, fontSize: 11.5, color: t.text2 }}>
          <Stat t={t} v={rot ? fmtTok(rot.kpi.tokens) : "—"} k="token" title={covNote} />
          <Stat t={t} v={rot ? String(rot.kpi.requests) : "—"} k="请求" />
          <Stat t={t} v={rot ? fmtTok(rot.kpi.avg_tokens) : "—"} k="均/次" />
          <Stat t={t} v={rot ? String(rot.kpi.rotations) : "—"} k="轮换" />
          <Stat t={t} v={rot ? dur(rot.kpi.avg_dwell) : "—"} k="驻留" />
          <Stat t={t} v={rot ? String(rot.kpi.cool_429) : "—"} k="429" c={COOL} />
          <Stat t={t} v={rot ? String(rot.kpi.stream_err) : "—"} k="断流" c={WARN} />
          {/* ★ 汇总条上原有一格「Pro 保底 Nm」,用户 2026-09-07 要求去掉。
              ⚠️ **信号本身没有删** —— 它仍在两个更合适的位置:
                · 泳道上 Pro 号的紫色 `PRO` 徽章(哪个号是保底档,一眼可见);
                · 轮换事件里独立的「Pro 保底」类型 + 「Plus 全部不可用 → Pro 保底接管」文案。
              删的是顶栏那一格常驻数字,不是「Plus 池干了」这件事的可见性。
              引擎侧 `kpi.pro_segs/pro_secs` 保留 —— 拿掉它等于把一个已经算好的事实丢掉,
              而下次想在别处显示时又要重算。 */}
        </div>

        {busy && (
          <span title="正在重扫（页面上现在显示的是上次的快照）"
                style={{ fontSize: 10.5, color: t.accent, fontFamily: MONO, flexShrink: 0 }}>刷新中…</span>
        )}

        {/* 右侧三样打成**一个原子组**（用户点名图例要留在右边）。
            ★ 不打成一组的话，flex 会把它们逐个往下换行 —— 实测「1h 6h 24h 7d」独占第二行，
              看着像画错了。整组 `flexShrink: 0` ⇒ 让位者只可能是左边那条汇总。 */}
        <div style={{ marginLeft: "auto", flexShrink: 0, display: "flex",
                      alignItems: "center", gap: 12 }}>
          <span style={{ display: "flex", gap: 12, fontSize: 10, color: t.text2 }}>
            <Legend t={t}><span style={{ width: 13, height: 7, borderRadius: 2, background: t.accent, opacity: .85 }} />在岗</Legend>
            <Legend t={t}><span style={{ width: 6, height: 6, borderRadius: "50%", background: WARN }} />断流</Legend>
            <Legend t={t}><span style={{ width: 8, height: 8, borderRadius: "50%", border: `2px solid ${COOL}` }} />429</Legend>
          </span>
          {/* ★ 「现在 xx:xx · 当前号 X」已删（用户 2026-09-07）：两条信息在这一页都是**重复的** ——
              时间轴右端本来就标着「现在」那条青竖线，而「当前号」在泳道上已经有「当前」徽章。
              删掉它同时把这一行的宽度压力去掉了一大截（它是右侧最长的一项）。 */}
          <Seg opts={WINDOWS} cur={win} on={setWin} label={winLabel} t={t} />
        </div>
      </div>

      {/* ── 泳道时间轴（稿子 §1/§2/§3）───────────────── */}
      <div style={{ ...card, padding: "12px 16px 10px", flexShrink: 0 }}>
        <div style={{
          display: "grid", gridTemplateColumns: `${NAME_W}px 1fr ${STAT_W}px`, gap: 14,
          alignItems: "center", paddingBottom: 8, fontFamily: MONO, fontSize: 11,
          letterSpacing: ".06em",
          // ★★ 用 `text2` 不是 `muted`（用户 2026-09-07：「有些字体太灰了」）。
          //   实算（深色，cardBg 底）：muted **4.55** / text2 **8.26**。muted 过得了 AA 4.5，
          //   但 9.5px + 大写 + 字距下就是读不动 —— 而表头是**要读的内容**，不是装饰。
          //   ★ 稿子写的 `#5b6470` 只有 **2.92**，连图形线的 3.0 都够不着，照抄就是把
          //   本仓已经判过死刑的 `faint` 换个写法请回来。
          //   ★ 修法是**改用三级里对的那一级**，不是新造一个色 —— 这个问题此前被
          //   「就地留一句注释换个色」绕过两次（`.claude/rules/ui.md`），第三次才做成闸。
          color: t.text2, textTransform: "uppercase",
        }}>
          <span>账号</span>
          <div style={{ position: "relative", height: 14 }}>
            {axis.map((a, i) => (
              <span key={i} style={{ position: "absolute", left: `${a.left}%`, transform: "translateX(-50%)", letterSpacing: 0 }}>{a.label}</span>
            ))}
            {/* ★ 稿子写的是 `translateX(40%)`,但那是让它**探出容器右缘**;在真实布局里
                量出来横向溢出 8px(harness overflow 探针报 608/600)。稿子的画布比这里宽,
                所以那 40% 在它那儿不越界 —— 这是照抄稿子会带进来的缺陷,不是复刻不到位。 */}
            <span style={{ position: "absolute", right: 0, color: t.accent, letterSpacing: 0 }}>现在</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "58px 44px 1fr 74px", gap: 8, textAlign: "right" }}>
            <span>TOKEN</span><span>请求</span><span>主模型</span><span>额度</span>
          </div>
        </div>

        <div style={{ position: "relative" }}>
          {lanes.length === 0 && (
            <div style={{ padding: "26px 0", textAlign: "center", color: t.muted, fontSize: 11 }}>
              {/* ★ 三种「没数字」必须说三句不同的话 —— 合成「暂无数据」就是把「我们没看到」
                  伪装成「确实没有」。 */}
              {err ? `读不到 proxy/proxy.log（${err}）`
                : !rot ? "读取中"
                  : (cov?.in_window_lines ?? 0) === 0 ? `最近 ${winLabel(win)} 代理没有处理过请求`
                    : "窗口内有日志，但没有可归属到账号的计费请求"}
            </div>
          )}
          {lanes.map((l, li) => (
            <div key={l.acc} style={{
              display: "grid", gridTemplateColumns: `${NAME_W}px 1fr ${STAT_W}px`, gap: 14,
              alignItems: "center", height: LANE_H, borderTop: `1px solid ${t.divider}`,
              opacity: focus && focus !== l.acc ? .28 : 1, transition: "opacity .15s",
            }}>
              <div data-lane={l.acc}
                   onClick={() => setFocus(focus === l.acc ? null : l.acc)}
                   style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", minWidth: 0 }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: l.color, flex: "none" }} />
                {/* ★ `flexShrink: 0`：名字是这一行的**身份**，宁可徽章挤也不能把号名截掉。
                    列宽已按最坏情况（名字+PRO+当前）算过，正常不会触发收缩。 */}
                <span style={{ fontSize: 14.5, fontWeight: 700, fontFamily: MONO,
                               flexShrink: 0, whiteSpace: "nowrap" }}>{l.acc}</span>
                {/* ★ PRO 徽章:一眼看出这条泳道是**保底档**,它有流量就意味着 Plus 池当时不可用。
                    不显示 PLUS —— 绝大多数号都是 Plus,画出来只是噪音(同卡片上 `PlanBadge` 的口径)。 */}
                {l.plan === "pro" && (
                  <span title="Pro 是保底档：只有 Plus 全部不可用时代理才会挑它"
                        style={{ fontSize: 9, fontWeight: 700, color: "#8b7cf6", border: "1px solid #8b7cf655",
                                 background: "rgba(139,124,246,.14)", padding: "1px 5px", borderRadius: 4, flexShrink: 0 }}>PRO</span>
                )}
                {l.current && (
                  <span style={{ fontSize: 9.5, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 6px", borderRadius: 4, flexShrink: 0 }}>当前</span>
                )}
              </div>

              <div style={{ position: "relative", height: LANE_H }}>
                <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: t.divider }} />
                {l.segs.map((s, si) => (
                  <div key={si}
                       // ★ `data-seg` 是给 harness 的 `?tipseg=<n>` 用的选择器锚点。
                       //   headless 里鼠标事件不会自己发生,而"悬浮才出现的读数"只能这样验。
                       data-seg={`${l.acc}:${si}`}
                       onMouseEnter={() => openTip(li, s, l.errs.filter(e => e >= s.left && e <= s.left + s.width).length)}
                       onMouseLeave={() => setTip(null)}
                       style={{
                         position: "absolute", left: `${s.left}%`, width: `${s.width}%`,
                         top: 10, height: 20, borderRadius: 4, background: l.color,
                         opacity: s.op, cursor: "pointer", minWidth: 3,
                       }} />
                ))}
                {l.errs.map((x, i) => (
                  <div key={`e${i}`} style={{
                    position: "absolute", left: `${x}%`, bottom: 2, width: 6, height: 6,
                    borderRadius: "50%", background: WARN, transform: "translateX(-50%)", pointerEvents: "none",
                  }} />
                ))}
                {l.cools.map((x, i) => (
                  <div key={`c${i}`} style={{
                    position: "absolute", left: `${x}%`, top: 2, width: 9, height: 9, borderRadius: "50%",
                    border: `2px solid ${COOL}`, background: t.cardBg, transform: "translateX(-50%)", pointerEvents: "none",
                  }} />
                ))}
              </div>

              <div style={{
                display: "grid", gridTemplateColumns: "58px 44px 1fr 74px", gap: 8,
                alignItems: "center", textAlign: "right", fontFamily: MONO,
              }}>
                <span style={{ fontSize: 15, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtTok(l.tokens)}</span>
                <span style={{ fontSize: 12.5, color: t.text2, fontVariantNumeric: "tabular-nums" }}>{l.requests}</span>
                {/* ★ 模型名放不下时截省略号，全名走 title —— 模型名长度不可控
                    （`gpt-5.3-codex-mini` 之类），为它加宽会挤掉右边的额度条。 */}
                <span title={l.top_model ? `${l.top_model.model}（占该号已归属 token 的 ${Math.round(l.top_model.share * 100)}%）` : "该号没有归属到 token"}
                      style={{ fontSize: 11.5, color: t.text2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {l.top_model ? `${l.top_model.model} ${Math.round(l.top_model.share * 100)}%` : "—"}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
                  <div style={{ width: 34, height: 3, borderRadius: 2, background: t.divider, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${l.quota_pct ?? 0}%`, background: quotaColor(l.quota_pct, t) }} />
                  </div>
                  <span style={{ width: 36, fontSize: 12.5, fontWeight: 700, color: quotaColor(l.quota_pct, t), fontVariantNumeric: "tabular-nums" }}>
                    {/* ★ 读不到额度画 `—`,**绝不画成 100%** —— 那是本仓的「不许编造满额」铁律。 */}
                    {l.quota_pct === null ? "—" : `${Math.round(l.quota_pct)}%`}
                  </span>
                </div>
              </div>
            </div>
          ))}

          {/* 右缘 1px 青竖线 = 现在（稿子 §1） */}
          {lanes.length > 0 && (
            <div style={{
              position: "absolute", top: 0, bottom: 0, right: STAT_W + 14, width: 1,
              background: t.accent, opacity: .7, pointerEvents: "none",
            }} />
          )}

          {/* 悬浮明细（稿子 §2） */}
          {tip && (
            <div style={{
              position: "absolute",
              left: `calc(${NAME_W + 14}px + (100% - ${NAME_W + STAT_W + 28}px) * ${tip.xPct / 100})`,
              top: tip.laneIdx * LANE_H + 34,
              transform: tip.flip ? "translateX(calc(-100% - 8px))" : "translateX(8px)",
              width: 170, background: "rgba(10,13,16,.6)", backdropFilter: "blur(6px)",
              border: `1px solid ${t.ghostBorder}`, borderRadius: 8, padding: "7px 9px",
              pointerEvents: "none", zIndex: 5, fontFamily: MONO,
            }}>
              <div style={{ fontSize: 9.5, color: "#8a93a0", marginBottom: 4 }}>{tip.range} · {tip.dur}</div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                <span style={{ color: "#c3cad3", fontWeight: 700 }}>{tip.acc}</span>
                <span style={{ fontWeight: 700, color: t.accent }}>{fmtTok(tip.tokens)}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, marginTop: 2 }}>
                <span style={{ color: "#8a93a0" }}>请求</span><span style={{ color: "#c3cad3" }}>{tip.requests} 次</span>
              </div>
              <div style={{ marginTop: 5, paddingTop: 4, borderTop: "1px solid rgba(255,255,255,.1)" }}>
                {tip.models.length === 0 && (
                  // ★ 「这段没有归属到 token」不是 0 —— 请求可能失败(没有响应就没有 token 记录),
                  //   或者那些响应没走代理。写 0 会被读成"这段白跑了"。
                  <div style={{ fontSize: 9.5, color: "#8a93a0" }}>该时段无归属到的 token</div>
                )}
                {tip.models.map((m, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 9.5, marginTop: 2 }}>
                    <span style={{ width: 6, height: 6, borderRadius: 2, background: m.color, flexShrink: 0 }} />
                    <span style={{ color: "#c3cad3", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.model}</span>
                    <span style={{ marginLeft: "auto", fontWeight: 700 }}>{fmtTok(m.tokens)}</span>
                    <span style={{ width: 34, textAlign: "right", color: "#6b7480" }}>{m.pct}%</span>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, marginTop: 5, paddingTop: 4, borderTop: "1px solid rgba(255,255,255,.1)" }}>
                <span style={{ color: "#8a93a0" }}>断流</span><span style={{ color: WARN }}>{tip.errs} 次</span>
              </div>
              <div style={{ marginTop: 3, fontSize: 9.5, color: t.accent }}>切入 · {tip.why}</div>
            </div>
          )}
        </div>

        {/* ★ 两行说明按用户 2026-09-07 要求去掉（操作提示自解释，脚注太吵）。
            ⚠️ 但**覆盖率这个事实不能跟着消失** —— 合计 token 只涵盖走过代理的响应，
            直连 `codex` 的请求永远进不来。去掉的是那一行字，不是那个真相：
            它改挂到 KPI 的「合计 token（已归属）」标签上（见下方 `covNote`），
            **不占一行、也不用把下界说成总量**。 */}
      </div>

      {/* ── 下半区双栏（稿子 §4）─────────────────────── */}
      {/* ★★ 两栏**等高 + 各自滚动**（用户 2026-09-07：「等长…信息过多就改成滚动滑块」）。
          ★ 高度写在**外层网格**上而不是各写一个 minHeight：两边各写一个数迟早只改一边，
            而"两栏不等高"是肉眼一看就出戏、却没有任何检查会报错的那类。
          ★ 列表用 `flex:1 + minHeight:0 + overflowY:auto`，标题行 `flexShrink:0` 钉住 ——
            少了 `minHeight:0`，flex 子项的默认 `min-height:auto` 会让它撑破容器而**不滚动**
            （本仓菜单栏那次「裁切比溢出更糟」同一个坑）。 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12,
                    flexShrink: 0, height: PANEL_H }}>
        <div style={{ ...card, padding: "12px 16px", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 9, marginBottom: 8, flexShrink: 0 }}>
            <span style={{ fontSize: 14.5, fontWeight: 700 }}>轮换事件</span>
            <span style={{ fontSize: 11, color: t.text2, fontFamily: MONO }}>
              {evs.length} 条 · 新→旧{focus && ` · 仅 ${focus}`}
            </span>
          </div>
          <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
          {evs.length === 0 && <div style={{ fontSize: 12, color: t.text2, padding: "12px 0" }}>无轮换事件</div>}
          {/* ★ 不再 `slice(0, 9)`：有了滚动条就没有理由把其余的**丢掉不给看** ——
              截断会让「37 条」这个计数和实际能看到的对不上。 */}
          {evs.map((e, i) => {
            const st = EV_STYLE[e.type] ?? EV_STYLE.probe;
            return (
              <div key={i} style={{
                display: "grid", gridTemplateColumns: "44px 64px 1fr", gap: 10, alignItems: "center",
                padding: "7px 0", borderTop: `1px solid ${t.divider}`, fontFamily: MONO, fontSize: 12,
              }}>
                <span style={{ color: t.muted, fontVariantNumeric: "tabular-nums" }}>{clock(e.t)}</span>
                <span style={{ fontSize: 10, fontWeight: 700, textAlign: "center", padding: "3px 0", borderRadius: 999, color: st.color, background: st.bg }}>{st.label}</span>
                <span title={e.text} style={{ color: t.text2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.text}</span>
              </div>
            );
          })}
          </div>
        </div>

        <div style={{ ...card, padding: "12px 16px", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 9, marginBottom: 8, flexShrink: 0 }}>
            <span style={{ fontSize: 14.5, fontWeight: 700 }}>运行日志</span>
            <span style={{ fontSize: 11, color: t.text2, fontFamily: MONO }}>{logs.length} 条</span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 4, fontFamily: MONO, fontSize: 10.5 }}>
              {["all", "refresh", "switch", "cool"].map(f => (
                <span key={f} onClick={() => setFilter(f)} style={{
                  padding: "2px 8px", borderRadius: 999, cursor: "pointer",
                  color: filter === f ? t.accentText : t.text2,
                  background: filter === f ? t.accent : "transparent",
                  border: filter === f ? `1px solid ${t.accent}` : `1px solid ${t.ghostBorder}`,
                  fontWeight: filter === f ? 700 : 400,
                }}>{f === "all" ? "全部" : f}</span>
              ))}
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
          {logs.length === 0 && <div style={{ fontSize: 12, color: t.text2, padding: "12px 0" }}>无匹配日志</div>}
          {logs.map((l, i) => (
            <div key={i} style={{
              display: "grid", gridTemplateColumns: "44px 1fr", gap: 10, padding: "6px 0",
              borderTop: `1px solid ${t.divider}`, fontFamily: MONO, fontSize: 11.5,
            }}>
              <span style={{ color: t.muted, fontVariantNumeric: "tabular-nums" }}>{clock(l.t)}</span>
              <span title={l.text} style={{
                color: l.text.includes("cooled") ? COOL
                  : l.text.includes("stream err") ? WARN
                    : l.text.includes("switch") ? t.accent : t.text2,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>{l.text}</span>
            </div>
          ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 汇总条上的一格：`值 + 标签`，右侧一条发丝竖线。★ 定义在**模块作用域** ——
 *  写在页面 render 里每次渲染都是新组件类型，React 会整组卸载重建（本仓 `Seg` 那条）。 */
function Stat({ v, k, c, title, last, t }: {
  v: string; k: string; c?: string; title?: string; last?: boolean; t: Theme;
}): React.ReactElement {
  return (
    <span title={title} style={{
      padding: "0 11px", whiteSpace: "nowrap",
      borderRight: last ? "none" : `1px solid ${t.divider}`,
    }}>
      <b style={{ color: c ?? t.text, fontWeight: 700, fontSize: 13,
                  fontVariantNumeric: "tabular-nums" }}>{v}</b>
      <span style={{ color: c ?? t.text2, marginLeft: 5 }}>{k}</span>
    </span>
  );
}

function Legend({ children, t }: { children: React.ReactNode; t: Theme }): React.ReactElement {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: t.text2 }}>{children}</span>;
}
