import Ring from "./Ring";
import StaleMark from "./StaleMark";
import type { Theme } from "../theme";
import type { AgySnapshot } from "../agy";
import {
  agyShown, agyTightest, agyWinLabel, agyQuotaVisible, agyReasonNote, agyReasonTone,
} from "../agy";
import { fmtEta } from "../helpers";

const MONO = "'JetBrains Mono'";

/**
 * 菜单栏里的 agy 额度行。与 `GrokRow` 同款外形，同一套 `mb-row` class。
 *
 * ★★ **复用账号卡的样式，但走完全独立的数据通路** —— 与 grok 同理，两件事必须同时成立：
 * - 视觉复用：环形和细条是这个 app 表达额度的固有语言，agy 的额度就是额度。
 * - 数据**绝不**混进 `accounts` / `alive` / `aliveByLabel`：那几个数组同时驱动
 *   **⌘1~⌘9 切号**、计数徽章、探针全池的号数、自动切号。混进去 ⌘3 就可能"切"到一个
 *   根本切不了的东西上，**而且不报错**。闸在 `tests/test_agy_not_in_pool_ui.py`。
 *
 * ★ 与 GrokRow 的三处差别（都不是随意的）：
 * ① **不显示邮箱**：agy 的额度接口无鉴权、响应里没有任何身份信息。副标题改放
 *    「哪一组最紧」—— 4 个桶压成 1 个环上数字后，这是用户唯一能知道来源的地方。
 *    因此这个组件**没有 `privacy` prop**：没有可遮的东西，接一个空转的开关只会误导。
 * ② **只画最紧的那个窗口**：agy 有 5h 和周两个窗口，菜单栏行的高度只够一条。
 *    最紧的那个才是约束，另一个在主窗卡片上看。
 * ③ **「没在跑」不染警告色**：agy 不常驻，那是常态。染了就是又造一盏长亮的灯。
 */
export default function AgyRow({ t, color, snap, busy, disabled, onOpen }: {
  t: Theme;
  /** agy 平台识别色，来自 `colorOf(data, "agy")`（已折进用户偏好）。 */
  color: string;
  snap: AgySnapshot | null;
  busy?: boolean;
  /** 用户在设置页停用了 agy。停用 = 一个像素都不画。 */
  disabled?: boolean;
  /** 点行 = 弹出主界面的 Antigravity 详情页。 */
  onOpen?: () => void;
}) {
  // ★ 与总览卡**共用同一个判据** —— 两边各写一份迟早出现「主窗有、菜单栏没有」。
  if (!agyQuotaVisible(snap, { disabled })) return null;

  const shown = agyShown(snap);
  const tight = agyTightest(shown?.quota);
  const degraded = !!snap && !snap.available;
  const tone = snap ? agyReasonTone(snap) : "muted";
  const alarmed = degraded && tone !== "muted";

  // 还没取过 / 一个数都没有 ——— ★ 绝不画 0%：`0` 在环里和"额度用光了"长得一模一样，
  // 而这里的真相是"读不到"。同理也绝不画 100%（上游缺省值就是满格）。
  if (!tight) {
    return (
      <Shell t={t} color={color} onOpen={onOpen}>
        <Ring pct={0} r={18} sw={4.5} color={t.ringTrack} track={t.ringTrack} size={46}>
          <span style={{ fontSize: 12, fontWeight: 700, color: t.muted, lineHeight: 1 }}>—</span>
        </Ring>
        <div className="mb-row-info">
          <NameLine t={t} color={color}
                    mark={degraded && snap
                      ? <StaleMark t={t} note={agyReasonNote(snap)} tone={tone} size={10} />
                      : undefined} />
          <div className="mb-row-sub">
            <span className="mb-row-email" style={{ color: t.muted }}>
              {busy ? "正在取额度…" : snap?.reason === "no_process" ? "agy 没在运行" : "未探测"}
            </span>
          </div>
        </div>
      </Shell>
    );
  }

  const rem = tight.b.remaining_percent;
  const ringColor = alarmed ? "#E0901C" : color;
  // 环与条走平台色（同 grok 的定稿）；数字仍按阈值变色 —— 那是这行唯一还能报警的地方。
  const numColor = rem <= 10 ? "#E0524D" : rem < 50 ? "#E0901C" : t.text2;
  const glow = rem <= 20 ? (rem <= 10 ? "#E0524D" : "#E0901C") : undefined;

  return (
    <Shell t={t} color={color} onOpen={onOpen}>
      <Ring pct={rem} r={18} sw={4.5} color={ringColor} track={t.ringTrack} size={46} glow={glow}>
        <span style={{ fontSize: 12, fontWeight: 700, color: t.text,
                       fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{Math.round(rem)}</span>
      </Ring>
      <div className="mb-row-info">
        <NameLine t={t} color={color} sub={tight.group ?? undefined}
                  mark={degraded && snap
                    ? <StaleMark t={t} note={agyReasonNote(snap)} tone={tone} size={10} />
                    : undefined} />
        <div className="mb-row-meta">
          <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>{agyWinLabel(tight.b.window)}</span>
          <div className="mb-row-bar" style={{ background: t.barTrack }}>
            <div style={{ height: "100%", width: `${rem}%`, background: ringColor, borderRadius: 2,
                          transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
          </div>
          <span style={{ fontSize: 9.5, fontWeight: 600, color: alarmed ? "#E0901C" : numColor,
                         fontVariantNumeric: "tabular-nums" }}>{rem.toFixed(0)}%</span>
          <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>
            ↻{fmtEta(tight.b.reset_at ?? undefined)}
          </span>
        </div>
      </div>
    </Shell>
  );
}

/** 卡片外壳。左轨用 agy 识别色 —— 账号卡那条轨编码的是「临期 > 当前 > 额度」,
 *  这里编码的是「不是池成员」,所以刻意不参与那套优先级。 */
function Shell({ t, color, onOpen, children }: { t: Theme; color: string; onOpen?: () => void; children: React.ReactNode }) {
  return (
    <div className="mb-row" onClick={onOpen} style={{
      background: t.cardBg,
      border: `1px solid ${t.cardBorder}`,
      borderLeft: `3px solid ${color}`,
      cursor: onOpen ? "pointer" : "default",
    }}>
      {children}
    </div>
  );
}

function NameLine({ t, color, sub, mark }: { t: Theme; color: string; sub?: string; mark?: React.ReactNode }) {
  return (
    <>
      <div className="mb-row-name-line">
        <span className="mb-row-name" style={{ color }}>agy</span>
        {/* 「只读」是这张卡与旁边几张唯一需要的区别 —— 那几张 hover 出「切换」,这张永远不会。 */}
        <span className="mb-row-badge-cur"
              title="Antigravity 不在轮换池,只显示额度,不参与切号"
              style={{ color, border: `1px solid ${hexA(color, .45)}` }}>只读</span>
        {mark}
      </div>
      {sub !== undefined && (
        <div className="mb-row-sub">
          {/* ★ 这里放的是"哪一组最紧",不是账号 —— agy 的响应里没有身份信息。 */}
          <span className="mb-row-email" style={{ color: t.text2 }}>{sub} 最紧</span>
        </div>
      )}
    </>
  );
}

/** `#rrggbb` → `rgba(...)`。徽章描边要跟着平台色走，写死就无法响应用户改色。 */
function hexA(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
