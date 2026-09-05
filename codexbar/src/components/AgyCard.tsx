import Ring from "./Ring";
import StaleMark from "./StaleMark";
import { CardBadgeGhost } from "./CardBadge";
import { CARD_TYPE as Z, type Theme } from "../theme";
import type { AgySnapshot } from "../agy";
import {
  agyShown, agyTightest, agyWinRows, agyQuotaVisible, agyReasonNote, agyReasonTone,
} from "../agy";
import { fmtEta, fmtAgo, winNumColor } from "../helpers";

const MONO = "'JetBrains Mono'";

/**
 * 总览九宫格里的 agy(Antigravity)额度卡。与 `GrokCard` 同款外形 —— 同样的圆环、
 * 细条、卡片外框，理由见那份文件（细长条用户读不出来）。
 *
 * ★★ 与 grok 卡的**三处本质差别**，改这个文件前先读：
 *
 * ① **方向相反。** grok 接口给「已用」，agy 给「剩余」。这里全程直接用剩余，
 *    不做任何 `100 - x` —— 换向知识只存在于 `agy.ts` 的函数名里（`remaining_percent`）。
 *    在这个文件里写一次减法，就等于把方向复制了一份出来。
 *
 * ② **4 个桶挤进 2 行。** agy 是 2 组（Gemini / Claude+GPT）× 2 窗口（5h / 周）。
 *    环取**最紧的那个桶**（任何一个见底 agy 就用不了，所以"还剩多少"只能取最小值，
 *    不是平均）；每个窗口一行，取该窗口下最紧的那组，具体是哪组放进 `title`。
 *    全 4 行铺开会撑高卡片，破坏与账号卡的像素级对齐。
 *
 * ③ **「没在跑」是常态，不是故障。** agy 不常驻。所以 `no_process` 走 muted 而非警告色，
 *    并且**照常显示上次读数** —— 那是关于一份真实额度的真实数字。
 *    只有 `not_installed`（本机根本没有 agy）才整卡隐藏，那是**确定的否定**。
 *
 * ★ 颜色由调用方传入（`colorOf(traffic, "agy")`），不写死：用户在设置页能改平台色。
 */
export default function AgyCard({ t, color, snap, busy, err, disabled, winSlots, onOpen, onRefresh }: {
  t: Theme;
  /** 与账号卡**同一份**窗口槽位表。agy 没有的窗口画一行隐藏等高行 —— 不占槽的话
   *  它的「5h」会和别人的「周」画在同一条线上。 */
  winSlots: string[];
  color: string;
  snap: AgySnapshot | null;
  busy?: boolean;
  /** 读**本机 sidecar** 失败（IO 层）。★ 与"额度读不到"是两回事：后者在 `snap.reason` 里，
   *  是正常返回的降级数据。两者文案必须不同。 */
  err?: string | null;
  disabled?: boolean;
  onOpen?: () => void;
  onRefresh?: () => void;
}) {
  // 本机没有 agy / 已停用 ⇒ **零像素**。见 `agyQuotaVisible` 的注释。
  if (!agyQuotaVisible(snap, { disabled })) return null;

  const shown = agyShown(snap);
  const degraded = !!snap && !snap.available;
  const tight = agyTightest(shown?.quota);
  const rem = tight ? tight.b.remaining_percent : null;
  const rows = agyWinRows(shown?.quota);
  const tone = snap ? agyReasonTone(snap) : "muted";
  // ★ 「没在跑」是常态,不该染成警告色。只有真正异常的降级才上琥珀。
  const alarmed = degraded && tone !== "muted";
  const stateColor = alarmed ? "#E0901C" : color;

  // 槽位表里必须有 agy 自己那几格：池里一个账号都没有时 winSlots 是空的，
  // 不兜的话 agy 的条会**一整条消失**——「读不到 ≠ 确实没有」的另一种形态。
  const mine = rows.map(r => r.label);
  const slotRows = [...winSlots, ...mine.filter(l => !winSlots.includes(l))];
  const glow = rem != null && rem <= 20 ? (rem <= 10 ? "#E0524D" : "#E0901C") : undefined;

  return (
    <div onClick={onOpen} style={{
      position: "relative", background: t.cardBg,
      border: `1px solid ${hexA(color, .30)}`, borderRadius: 12,
      padding: "16px 14px 12px", display: "flex", flexDirection: "column",
      cursor: onOpen ? "pointer" : "default", userSelect: "none",
      transition: "background .2s ease, border-color .2s ease",
    }}>
      <span style={{ position: "absolute", top: 6, left: 10, color,
                     fontFamily: MONO, letterSpacing: ".04em", fontSize: Z.shortcut }}>CLI</span>
      {onRefresh && (
        // stopPropagation：点卡片是"进详情"，点 ↻ 是"重取额度"，两个动作叠在同一块区域上。
        <button onClick={(e) => { e.stopPropagation(); if (!busy) onRefresh(); }} disabled={busy}
                title="重新取一次 agy 额度（本机 loopback，不联网、不消耗额度）"
                style={{ position: "absolute", top: 4, right: 8, background: "transparent",
                         border: "none", color: t.muted, fontFamily: MONO, fontSize: 11,
                         cursor: busy ? "default" : "pointer", opacity: busy ? .4 : 1 }}>↻</button>
      )}

      <div style={{ display: "flex", gap: 11, alignItems: "center", flex: 1, minHeight: 0 }}>
        {/* ★ 降级时环与条走状态色,与菜单栏行同口径 —— 同一个状态两种画法正是这套闸在防的。
            ★ 但 `no_process` 不算异常(常态),所以它仍用平台色,只是数字旁边挂一个 `!`。 */}
        <Ring pct={rem ?? 0} r={Z.ringR} sw={Z.ringSw}
              color={rem == null ? t.ringTrack : stateColor}
              track={t.ringTrack} size={Z.ring} glow={glow}>
          <span style={{ fontSize: Z.ringNum, fontWeight: 700, color: t.text,
                         fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
            {rem == null ? "—" : Math.round(rem)}
          </span>
        </Ring>

        <div style={{ flex: 1, minWidth: 0, alignSelf: "stretch", display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontSize: Z.name, fontWeight: 700, color }}>agy</span>
            <span title="Antigravity 不在轮换池,只显示额度,不参与切号"
                  style={{ fontSize: Z.curBadge, fontWeight: 700, padding: "1px 5px", borderRadius: 5,
                           color, border: `1px solid ${hexA(color, .45)}` }}>只读</span>
            {/* ★ 降级说明**只在这里**,一个字符 + 悬浮。理由见 StaleMark 的文件头。 */}
            {degraded && snap && <StaleMark t={t} note={agyReasonNote(snap)} tone={tone} size={11} />}
            {/* 读**本机 sidecar** 失败(IO 层),与"额度读不到"是两回事,所以文案不同。 */}
            {!!err && <StaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
          </div>
          {/* grok 那行放的是账号邮箱;agy 的响应里**没有任何身份信息**(接口无鉴权),
              所以这里放"哪一组最紧"—— 环上那个数字来自哪个池子,否则 4 个桶压成 1 个数后
              用户无从知道是 Gemini 还是 Claude/GPT 见底。 */}
          <div style={{ fontSize: Z.email, color: t.text2, fontFamily: MONO, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {tight?.group ? `${tight.group} 最紧` : (busy ? "正在取额度…" : "未探测")}
          </div>

          {/* 弹性留白：把条形区压到卡片底边，与账号卡同款。 */}
          <div aria-hidden style={{ flex: 1, minHeight: 0 }} />

          {rem != null && slotRows.map(label => {
            const row = rows.find(r => r.label === label);
            return !row ? (
              // 没有这个窗口 ⇒ 同构隐藏行占位，高度由构造保证与真行一致。
              <div key={label} aria-hidden style={{ display: "flex", alignItems: "center", gap: 6, visibility: "hidden" }}>
                <span style={{ fontSize: Z.winLabel, fontFamily: MONO }}>{label}</span>
                <div style={{ flex: 1, height: Z.bar }} />
                <span style={{ fontSize: Z.pct, fontWeight: 600, fontFamily: MONO }}>00%</span>
                <span style={{ fontSize: Z.eta, fontFamily: MONO }}>↻0d00h</span>
              </div>
            ) : (
              <div key={label} title={`${row.group ?? "?"} · 剩 ${row.remaining.toFixed(1)}%`}
                   style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: Z.winLabel, color: t.muted, fontFamily: MONO }}>{row.label}</span>
                <div style={{ flex: 1, height: Z.bar, borderRadius: 2, background: t.barTrack, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${row.remaining}%`,
                                background: stateColor, borderRadius: 2,
                                transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
                </div>
                {/* 数字仍按阈值变色 —— 环恒平台色,这是卡上唯一还能报警的地方(同 GrokCard)。 */}
                <span style={{ fontSize: Z.pct, fontWeight: 600,
                               color: alarmed ? "#E0901C" : winNumColor(row.remaining, t),
                               fontFamily: MONO, fontVariantNumeric: "tabular-nums" }}>
                  {Math.round(row.remaining)}%
                </span>
                <span style={{ fontSize: Z.eta, color: t.muted, fontFamily: MONO }}>
                  ↻{fmtEta(row.reset_at ?? undefined)}
                </span>
              </div>
            );
          })}

          {/* ★ 底注一行,降级与否都在同一位置、同样高度 —— 卡片不会因为 agy 关掉就长高一截。
              ★★ **数字绝不假装是活的**:有上次读数就说明它是几时的,没有就说读不到。
              位置与外框刻意与账号卡的「到期」行同构(对齐的一部分,不是装饰线)。 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
                        marginTop: 5, paddingTop: 7, borderTop: `1px solid ${t.divider}`,
                        color: alarmed ? "#E0901C" : t.muted }}>
            <span style={{ fontSize: Z.exp, fontFamily: MONO, whiteSpace: "nowrap",
                         overflow: "hidden", textOverflow: "ellipsis" }}>{
              shown?.stale ? `${fmtAgo(shown.at ?? undefined)}的读数`
                : shown ? "Google 订阅 · 不在轮换池"
                : "额度暂时读不到"}</span>
            {/* agy 没有重置卡这个概念，占位只为让页脚与账号卡等高。 */}
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
