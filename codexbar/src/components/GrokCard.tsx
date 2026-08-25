import Ring from "./Ring";
import GrokStaleMark from "./GrokStaleMark";
import type { Theme } from "../theme";
import type { GrokSnapshot, GrokAccount } from "../grok";
import { grokRemPct, grokLastGoodRemPct, grokQuotaVisible } from "../grok";
import { fmtEta, fmtAgo, maskId } from "../helpers";

const MONO = "'JetBrains Mono'";

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
export default function GrokCard({ t, color, snap, privacy, busy, err, disabled, onOpen, onRefresh }: {
  t: Theme;
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
  const numColor = (p: number | null) =>
    p == null ? t.muted : p <= 10 ? "#E0524D" : p < 50 ? "#E0901C" : t.text2;

  const shownRem = degraded ? lgRem : rem;
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
      <span style={{ position: "absolute", top: 6, left: 10, fontSize: 9, color,
                     fontFamily: MONO, letterSpacing: ".04em" }}>CLI</span>
      {onRefresh && (
        // ★ stopPropagation:点卡片是"进 Grok 详情",点 ↻ 是"重取额度",两个动作叠在同一块区域上。
        //   不拦的话点 ↻ 会顺带跳页 —— 而这个按钮存在的意义正是"不离开总览就刷新"。
        <button onClick={(e) => { e.stopPropagation(); if (!busy) onRefresh(); }} disabled={busy}
                title="重新取一次 grok 额度（不消耗额度）"
                style={{ position: "absolute", top: 4, right: 8, background: "transparent",
                         border: "none", color: t.muted, fontFamily: MONO, fontSize: 11,
                         cursor: busy ? "default" : "pointer", opacity: busy ? .4 : 1 }}>↻</button>
      )}

      <div style={{ display: "flex", gap: 11, alignItems: "center" }}>
        {/* ★★ 降级时环与条**强制琥珀**,与菜单栏行同口径。
            截图核对时发现两个 surface 曾不一致(行是琥珀、卡还是平台紫)——
            **同一个状态两种画法**正是这套闸一直在防的东西。
            琥珀在这里表示的是"这个数不是现在的",不是额度水位。 */}
        <Ring pct={shownRem ?? 0} r={21} sw={5}
              color={shownRem == null ? t.ringTrack : (degraded ? "#E0901C" : color)}
              track={t.ringTrack} size={52} glow={glow}>
          <span style={{ fontSize: 13, fontWeight: 700, color: t.text,
                         fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
            {shownRem == null ? "—" : Math.round(shownRem)}
          </span>
        </Ring>

        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontSize: 13.5, fontWeight: 700, color }}>grok</span>
            {/* 与旁边三张卡唯一需要的区别:它们能切,这张不能。 */}
            <span title="grok 不在轮换池,只显示额度,不参与切号"
                  style={{ fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 5,
                           color, border: `1px solid ${hexA(color, .45)}` }}>只读</span>
            {/* ★ 降级说明**只在这里**,一个字符 + 悬浮。理由见 GrokStaleMark 的文件头。 */}
            {degraded && a && <GrokStaleMark t={t} a={a} size={11} />}
            {/* ★ 读**本机 sidecar** 失败(IO 层)。与"额度读不到"是两回事,所以文案不同,
                但呈现方式一致 —— 都是一个感叹号,不再各弹各的横幅。 */}
            {!!err && <GrokStaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
          </div>
          <div style={{ fontSize: 10.5, color: t.text2, fontFamily: MONO, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {a?.email ? maskId(a.email, privacy) : (busy ? "正在取额度…" : "未探测")}
          </div>

          {shownRem != null && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>周</span>
              <div style={{ flex: 1, height: 4, borderRadius: 2, background: t.barTrack, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${shownRem}%`,
                              background: degraded ? "#E0901C" : color, borderRadius: 2,
                              transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
              </div>
              <span style={{ fontSize: 10, fontWeight: 600,
                             color: degraded ? "#E0901C" : numColor(shownRem),
                             fontFamily: MONO, fontVariantNumeric: "tabular-nums" }}>
                {Math.round(shownRem)}%
              </span>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>
                ↻{fmtEta((degraded ? a?.last_good?.period_end : a?.quota?.period_end) ?? undefined)}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ★ 降级披露放卡内底部。**语义色，不染紫** —— "读不到"必须与"读到了"一眼可分。 */}
      {/* ★ 底注一行,降级与否都在同一位置、同样高度 —— 卡片不会因为 token 过期就长高一截。
          ★★ **数字绝不假装是活的**:有上次读数就说明它是几时的,没有就说「暂时读不到」。
             省掉的是**解释**(挪进感叹号的悬浮),不是**披露**。 */}
      <div style={{ marginTop: 9, fontSize: 9.5, fontFamily: MONO,
                    color: degraded ? "#E0901C" : t.muted }}>
        {degraded
          ? (lgRem != null ? `${fmtAgo(a?.last_good?.fetched_at)}的读数` : "额度暂时读不到")
          : "xAI 账单 · 不在轮换池"}
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
