import Ring from "./Ring";
import GrokStaleMark from "./GrokStaleMark";
import type { Theme } from "../theme";
import type { GrokSnapshot, GrokAccount } from "../grok";
import { grokRemPct, grokLastGoodRemPct, grokQuotaVisible } from "../grok";
import { fmtEta, maskId } from "../helpers";

const MONO = "'JetBrains Mono'";

/**
 * 菜单栏里的 grok 额度行（用户 2026-08-24 从三版 demo 之外自己定的：
 * 「我还是喜欢目前的菜单栏样式，不如直接保留现在的新增紫色的 grok」）。
 *
 * ★★ **复用账号卡的样式，但走完全独立的数据通路** —— 这两件事必须同时成立：
 * - 视觉复用（`mb-row` 那套 class + `Ring`）：环形和细条是这个 app 表达额度的固有语言，
 *   grok 的额度就是额度，没理由换一种画法。
 * - 数据**绝不**混进 `accounts` / `alive` / `aliveByLabel`：那几个数组同时驱动
 *   **⌘1~⌘9 切号**（`aliveByLabel[idx]` 直接 `run("switch", …)`）、计数徽章、探针全池的号数、
 *   自动切号。grok 混进去，⌘3 就可能"切"到一个根本切不了的东西上，**而且不报错**。
 *   闸在 `tests/test_grok_not_in_pool_ui.py`。
 *
 * ★★ **环、条、左轨、名字全部走 grok 识别色**（用户 2026-08-24 定稿：「grok 的所有颜色
 * 包括条形图和圆形图都是紫色的」）。我先前主张"紫色只给身份、环按额度染绿/琥珀"，被否掉了。
 * 代价与补偿见 `GrokCard.tsx` 的头注释（同一套决定，那里写全了）：数字仍按阈值变色、
 * `glow` 在低额度时点亮、**失败态仍走语义色**（琥珀=旧读数，红=需处理）。
 * ★ 颜色**由调用方传入**（`colorOf(traffic, "grok")`），不写死 —— 用户能在设置页改平台色。
 *
 * ★ **不给「切换」按钮**：卡片这个形状本身在说"这是能切的号"，而 grok 不在池里。
 * 少一个按钮 + 一枚「只读」徽章，是它与旁边三张卡唯一需要的区别。
 */
export default function GrokRow({ t, color, snap, privacy, busy, disabled, onOpen }: {
  t: Theme;
  /** grok 平台识别色，来自 `colorOf(data, "grok")`（已折进用户偏好）。 */
  color: string;
  snap: GrokSnapshot | null;
  privacy: boolean;
  busy?: boolean;
  /** 用户在设置页停用了 grok。停用 = 一个像素都不画。 */
  disabled?: boolean;
  /** 点行 = 弹出主界面的 Grok 详情页（与账号行「点行弹主窗」同一手势）。 */
  onOpen?: () => void;
}) {
  // ★ 与总览卡**共用同一个判据** —— 两边各写一份迟早出现「主窗有、菜单栏没有」。
  if (!grokQuotaVisible(snap, { disabled })) return null;
  if (!snap || snap.accounts.length === 0) {
    return (
      <Shell t={t} color={color} onOpen={onOpen}>
        <Ring pct={0} r={18} sw={4.5} color={t.ringTrack} track={t.ringTrack} size={46}>
          <span style={{ fontSize: 12, fontWeight: 700, color: t.muted, lineHeight: 1 }}>—</span>
        </Ring>
        <div className="mb-row-info">
          <NameLine t={t} color={color} />
          <div className="mb-row-sub">
            <span className="mb-row-email" style={{ color: t.muted }}>
              {busy ? "正在取额度…" : "未探测"}
            </span>
          </div>
        </div>
      </Shell>
    );
  }

  const a: GrokAccount = snap.accounts[0];
  const rem = grokRemPct(a);
  const lgRem = grokLastGoodRemPct(a);

  // ---- 降级态 --------------------------------------------------------------
  // ★ 绝不画 0%。`0` 在环里和"这周一点没用"长得一模一样,而这里的真相是"读不到"。
  // ---- 降级态 --------------------------------------------------------------
  // ★ 与总览卡同一套:一个感叹号 + 悬浮说明,读数如实标「旧」。**不弹横幅** ——
  //   token 6 小时一过期,横幅按设计每天要弹几次,那是噪音不是警报(见 GrokStaleMark 文件头)。
  // ★ 绝不画 0%:`0` 在环里和"这周一点没用"长得一模一样,而这里的真相是"读不到"。
  if (!a.available) {
    const stale = lgRem != null;
    return (
      <Shell t={t} color={color} onOpen={onOpen}>
        <Ring pct={stale ? lgRem : 0} r={18} sw={4.5}
              color={stale ? "#E0901C" : t.ringTrack} track={t.ringTrack} size={46}>
          <span style={{ fontSize: 12, fontWeight: 700, color: stale ? t.text : t.muted,
                         fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
            {stale ? Math.round(lgRem) : "—"}
          </span>
        </Ring>
        <div className="mb-row-info">
          <NameLine t={t} color={color} email={a.email} privacy={privacy} mark={<GrokStaleMark t={t} a={a} size={10} />} />
          <div className="mb-row-meta">
            <span style={{ fontSize: 9, color: "#E0901C", fontFamily: MONO }}>
              {stale ? "上次读数" : "额度暂时读不到"}
            </span>
          </div>
        </div>
      </Shell>
    );
  }

  const q = a.quota!;
  const remPct = rem ?? 0;   // ★ 名字带方向:裸 `remPct` 正是这类反相 bug 的温床
  // 与账号卡同一把尺:`quotaColor` 吃的是**剩余**,环、条、数字三处同向。
  // 环与条恒紫(用户定稿);数字仍按阈值变色 —— 那是这张卡唯一还能报警的地方。
  const numColor = remPct <= 10 ? "#E0524D" : remPct < 50 ? "#E0901C" : t.text2;
  const glow = remPct <= 20 ? (remPct <= 10 ? "#E0524D" : "#E0901C") : undefined;
  return (
    <Shell t={t} color={color} onOpen={onOpen}>
      <Ring pct={remPct} r={18} sw={4.5} color={color} track={t.ringTrack} size={46} glow={glow}>
        <span style={{ fontSize: 12, fontWeight: 700, color: t.text,
                       fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{Math.round(remPct)}</span>
      </Ring>
      <div className="mb-row-info">
        <NameLine t={t} color={color} email={a.email} privacy={privacy} />
        <div className="mb-row-meta">
          <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>周</span>
          <div className="mb-row-bar" style={{ background: t.barTrack }}>
            <div style={{ height: "100%", width: `${remPct}%`, background: color, borderRadius: 2,
                          transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
          </div>
          <span style={{ fontSize: 9.5, fontWeight: 600, color: numColor,
                         fontVariantNumeric: "tabular-nums" }}>{remPct.toFixed(0)}%</span>
          <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>
            ↻{fmtEta(q.period_end ?? undefined)}
          </span>
        </div>
      </div>
    </Shell>
  );
}

/** 卡片外壳。左轨用 grok 紫 —— 账号卡那条轨编码的是「临期 > 当前 > 额度」,
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

function NameLine({ t, color, email, privacy, mark }: { t: Theme; color: string; email?: string | null; privacy?: boolean; mark?: React.ReactNode }) {
  return (
    <>
      <div className="mb-row-name-line">
        <span className="mb-row-name" style={{ color }}>grok</span>
        {/* 「只读」是这张卡与旁边三张唯一需要的区别 —— 那三张 hover 出「切换」,这张永远不会。 */}
        <span className="mb-row-badge-cur"
              title="grok 不在轮换池,只显示额度,不参与切号"
              style={{ color, border: `1px solid ${hexA(color, .45)}` }}>只读</span>
        {mark}
      </div>
      {email !== undefined && (
        <div className="mb-row-sub">
          <span className="mb-row-email" style={{ color: t.text2 }}>{maskId(email ?? "", !!privacy)}</span>
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
