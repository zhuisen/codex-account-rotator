import Ring from "./Ring";
import GrokStaleMark from "./GrokStaleMark";
import { CardBadgeGhost } from "./CardBadge";
import { CARD_TYPE as Z, type Theme } from "../theme";
import type { GrokSnapshot, GrokAccount } from "../grok";
import { grokRemPct, grokLastGoodRemPct, grokQuotaVisible } from "../grok";
import { fmtEta, fmtAgo, maskId, winNumColor } from "../helpers";

const MONO = "'JetBrains Mono'";

/** grok 只有一个计费周期窗口（xAI 账单周），标签与账号卡的周窗口同名 —— 靠它对上同一条槽位。 */
const GROK_WIN = "周";

/**
 * 总览九宫格里的 grok 额度卡（用户 2026-08-24：「工作台也要显示 grok」）。
 *
 * 前一版是一条细长条，用户**没注意到** —— 在一屏三张大卡之间，一行 4px 的细条读不出来。
 * 现在与账号卡同款：同样的圆环、同样的细条、同样的卡片外框。
 *
 * ★★ **配色：环、条、名字、边框全部走 grok 识别色**（用户 2026-08-24 指定：
 * 「grok 的所有颜色包括条形图和圆形图都是紫色的」）。我先前主张环按额度染绿/琥珀、
 * 紫色只给身份，用户明确否掉了 —— 这是**已定稿的决定**，别再改回去。
 *
 * 由此**主动放弃**的东西，以及补偿（改这个文件前先读）：
 * - 放弃：环与条不再用颜色表达水位。grok 剩 8% 和剩 90% 的**环色一样**。
 * - 补偿①：百分数**仍按阈值变色**（<50% 琥珀 / ≤10% 红）—— 数字不是"条形图或圆形图"，
 *   不在用户指定的范围内，而它是这一卡里唯一还能报警的地方。
 * - 补偿②：`glow` 在 ≤20% 时点亮（≤10% 红）。它是环外的光晕，不改环的描边色。
 * - 保留：**失败态仍走语义色**（琥珀=旧读数/可自愈，红=需要人处理）。那是"数据出问题了"，
 *   与"额度水位"是两个轴；把它也染紫会让"读不到"和"读到了"长得一模一样，
 *   直接违反项目铁律「读不到 ≠ 确实没有」。
 *
 * ★ 颜色**由调用方传入**（`colorOf(traffic, "grok")`），不在这里写死 `#8b7cf6`：
 * 用户在设置页能给平台改色，写死就跟不上（CLAUDE.md §5 的既有铁律）。
 */
export default function GrokCard({ t, color, snap, privacy, busy, err, disabled, winSlots, onOpen, onRefresh }: {
  t: Theme;
  /**
   * 与账号卡**同一份**窗口槽位表（见 `AccountCard` 的同名 prop）。grok 没有 5h 窗口，
   * 那个槽位画一行隐藏的等高行 —— 它和账号卡并排在同一行网格里，
   * 不占槽的话它的「周」会和别人的「5h」画在同一条线上。
   */
  winSlots: string[];
  /** grok 的平台识别色，来自 `colorOf(data, "grok")`（已折进用户偏好）。 */
  color: string;
  snap: GrokSnapshot | null;
  privacy: boolean;
  busy?: boolean;
  /** 读**本机 sidecar** 失败（IO 层）。★ 与"额度读不到"是两回事：后者在
   *  `snap.accounts[].reason` 里，是正常返回的降级数据。两者文案必须不同，
   *  否则"我们自己读不到文件"会被说成"xAI 那边有问题"。 */
  err?: string | null;
  /** 用户在设置页停用了 grok。停用 = 一个像素都不画。 */
  disabled?: boolean;
  onOpen?: () => void;
  onRefresh?: () => void;
}) {
  // ★ 没装 grok / 已停用 ⇒ **零像素**。见 `grokQuotaVisible` 的注释。
  //   `err` 也在这之后判:取不到快照时我们分不清"这机器有没有 grok",
  //   对没装的人保持安静比报一个他看不懂的错更有价值。
  if (!grokQuotaVisible(snap, { disabled })) return null;

  const a: GrokAccount | null = snap?.accounts?.[0] ?? null;
  const rem = grokRemPct(a);
  const lgRem = grokLastGoodRemPct(a);
  const degraded = !!a && !a.available;

  // 数字的阈值色。**唯一还在报警的地方** —— 环和条已按用户要求恒紫。
  // ★ 阈值走 `winNumColor`(与账号卡、菜单栏行同一处判据)。这里本来就是三档、
  //   与它们不一致的是那两处;改成调同一个函数是**防止将来单独漂移**,不是修 bug。
  const numColor = (p: number | null) => p == null ? t.muted : winNumColor(p, t);

  const shownRem = degraded ? lgRem : rem;
  // 槽位表里必须有 grok 自己那格：池里一个账号都没有（或都探测失败）时 winSlots 是空的，
  // 不兜的话 grok 的条会**一整条消失**——「读不到 ≠ 确实没有」的另一种形态。
  const slotRows = winSlots.includes(GROK_WIN) ? winSlots : [...winSlots, GROK_WIN];
  const glow = shownRem != null && shownRem <= 20 ? (shownRem <= 10 ? "#E0524D" : "#E0901C") : undefined;

  return (
    <div onClick={onOpen} style={{
      position: "relative", background: t.cardBg,
      border: `1px solid ${hexA(color, .30)}`, borderRadius: 12,
      padding: "16px 14px 12px", display: "flex", flexDirection: "column",
      cursor: onOpen ? "pointer" : "default", userSelect: "none",
      transition: "background .2s ease, border-color .2s ease",
    }}>
      {/* 账号卡左上角是 ⌘N 快捷键提示。grok **没有**快捷键(它不在 aliveByLabel 里,
          见 tests/test_grok_not_in_pool_ui.py),所以这里放的是"它是什么"而不是"怎么切它"。 */}
      <span style={{ position: "absolute", top: 6, left: 10, color,
                     fontFamily: MONO, letterSpacing: ".04em", fontSize: Z.shortcut }}>CLI</span>
      {onRefresh && (
        // ★ stopPropagation:点卡片是"进 Grok 详情",点 ↻ 是"重取额度",两个动作叠在同一块区域上。
        //   不拦的话点 ↻ 会顺带跳页 —— 而这个按钮存在的意义正是"不离开总览就刷新"。
        <button onClick={(e) => { e.stopPropagation(); if (!busy) onRefresh(); }} disabled={busy}
                title="重新取一次 grok 额度（不消耗额度）"
                style={{ position: "absolute", top: 4, right: 8, background: "transparent",
                         border: "none", color: t.muted, fontFamily: MONO, fontSize: 11,
                         cursor: busy ? "default" : "pointer", opacity: busy ? .4 : 1 }}>↻</button>
      )}

      {/* `flex:1` + 内容列 `alignSelf:stretch`：与账号卡同款底吊布局，环仍垂直居中。
          理由与那条「别改回顶对齐」的警告见 AccountCard 同处注释。 */}
      <div style={{ display: "flex", gap: 11, alignItems: "center", flex: 1, minHeight: 0 }}>
        {/* ★★ 降级时环与条**强制琥珀**,与菜单栏行同口径。
            截图核对时发现两个 surface 曾不一致(行是琥珀、卡还是平台紫)——
            **同一个状态两种画法**正是这套闸一直在防的东西。
            琥珀在这里表示的是"这个数不是现在的",不是额度水位。 */}
        <Ring pct={shownRem ?? 0} r={Z.ringR} sw={Z.ringSw}
              color={shownRem == null ? t.ringTrack : (degraded ? "#E0901C" : color)}
              track={t.ringTrack} size={Z.ring} glow={glow}>
          <span style={{ fontSize: Z.ringNum, fontWeight: 700, color: t.text,
                         fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
            {shownRem == null ? "—" : Math.round(shownRem)}
          </span>
        </Ring>

        <div style={{ flex: 1, minWidth: 0, alignSelf: "stretch", display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontSize: Z.name, fontWeight: 700, color }}>grok</span>
            {/* 与旁边三张卡唯一需要的区别:它们能切,这张不能。 */}
            <span title="grok 不在轮换池,只显示额度,不参与切号"
                  style={{ fontSize: Z.curBadge, fontWeight: 700, padding: "1px 5px", borderRadius: 5,
                           color, border: `1px solid ${hexA(color, .45)}` }}>只读</span>
            {/* ★ 降级说明**只在这里**,一个字符 + 悬浮。理由见 GrokStaleMark 的文件头。 */}
            {degraded && a && <GrokStaleMark t={t} a={a} size={11} />}
            {/* ★ 读**本机 sidecar** 失败(IO 层)。与"额度读不到"是两回事,所以文案不同,
                但呈现方式一致 —— 都是一个感叹号,不再各弹各的横幅。 */}
            {!!err && <GrokStaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
          </div>
          <div style={{ fontSize: Z.email, color: t.text2, fontFamily: MONO, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {a?.email ? maskId(a.email, privacy) : (busy ? "正在取额度…" : "未探测")}
          </div>

          {/* 弹性留白：把条形区压到卡片底边，与账号卡同款（理由见 AccountCard 同处注释）。 */}
          <div aria-hidden style={{ flex: 1, minHeight: 0 }} />

          {shownRem != null && slotRows.map(label => label !== GROK_WIN ? (
            // 没有这个窗口 ⇒ 同构隐藏行占位，高度由构造保证与真行一致。
            <div key={label} aria-hidden style={{ display: "flex", alignItems: "center", gap: 6, visibility: "hidden" }}>
              <span style={{ fontSize: Z.winLabel, fontFamily: MONO }}>{label}</span>
              <div style={{ flex: 1, height: Z.bar }} />
              <span style={{ fontSize: Z.pct, fontWeight: 600, fontFamily: MONO }}>00%</span>
              <span style={{ fontSize: Z.eta, fontFamily: MONO }}>↻0d00h</span>
            </div>
          ) : (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: Z.winLabel, color: t.muted, fontFamily: MONO }}>{GROK_WIN}</span>
              <div style={{ flex: 1, height: Z.bar, borderRadius: 2, background: t.barTrack, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${shownRem}%`,
                              background: degraded ? "#E0901C" : color, borderRadius: 2,
                              transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
              </div>
              <span style={{ fontSize: Z.pct, fontWeight: 600,
                             color: degraded ? "#E0901C" : numColor(shownRem),
                             fontFamily: MONO, fontVariantNumeric: "tabular-nums" }}>
                {Math.round(shownRem)}%
              </span>
              <span style={{ fontSize: Z.eta, color: t.muted, fontFamily: MONO }}>
                ↻{fmtEta((degraded ? a?.last_good?.period_end : a?.quota?.period_end) ?? undefined)}
              </span>
            </div>
          ))}

          {/* ★ 降级披露放卡内底部。**语义色，不染紫** —— "读不到"必须与"读到了"一眼可分。 */}
          {/* ★ 底注一行,降级与否都在同一位置、同样高度 —— 卡片不会因为 token 过期就长高一截。
              ★★ **数字绝不假装是活的**:有上次读数就说明它是几时的,没有就说「暂时读不到」。
                 省掉的是**解释**(挪进感叹号的悬浮),不是**披露**。
              ★★ 位置与外框刻意与账号卡的「到期」行**同构**（同在内容列内、同样的
                 `marginTop/paddingTop/borderTop`）：条形行的位置是从列底往上推的，
                 页脚高度不一样，上面的条就落不到同一条线上（实测差 8~16px）。
                 所以这不是装饰性的分隔线，**它是对齐的一部分**。 */}
          {/* ★ 字号写在**文字自己**身上，不写在容器上：容器一改字号，里面那个行内占位盒的
              strut 就跟着变矮（实测差 2px），而账号卡的同位置容器没设字号 ——
              同一个占位盒在两张卡里会量出两个高度，对齐就差这 2px。 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
                        marginTop: 5, paddingTop: 7, borderTop: `1px solid ${t.divider}`,
                        color: degraded ? "#E0901C" : t.muted }}>
            <span style={{ fontSize: Z.exp, fontFamily: MONO, whiteSpace: "nowrap",
                         overflow: "hidden", textOverflow: "ellipsis" }}>{degraded
              ? (lgRem != null ? `${fmtAgo(a?.last_good?.fetched_at)}的读数` : "额度暂时读不到")
              : "xAI 账单 · 不在轮换池"}</span>
            {/* grok 没有重置卡这个概念，占位只为让页脚与账号卡等高（见 CardBadgeGhost 说明）。 */}
            <span style={{ alignSelf: "flex-end" }}><CardBadgeGhost /></span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** `#rrggbb` → `rgba(...)`。边框与徽章描边要跟着平台色走，写死一套就没法响应用户改色。 */
function hexA(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
