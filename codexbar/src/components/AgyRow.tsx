import Ring from "./Ring";
import StaleMark from "./StaleMark";
import type { Theme } from "../theme";
import type { AgySnapshot } from "../agy";
import {
  agyShown, agyTightest, agyQuotaVisible, agyReasonNote, agyReasonTone, agyResetText, agyWinRows,
} from "../agy";
import { winNumColor } from "../helpers";

const MONO = "'JetBrains Mono'";

/**
 * 行上固定画这两格。★★ **写成固定槽位而不是"有什么画什么"** ——
 * 非当值号读不到周窗口（云端按账号那条只给 5h），"有什么画什么"会让那些行少一格、
 * 比旁边的行矮一截，而那个矮**没有任何地方解释**。固定槽位下缺的那格显式画 `—`。
 */
const MB_WIN_SLOTS = ["5h", "周"] as const;

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
export default function AgyRow({ t, color, snap, busy, disabled, onOpen,
                                 label, isCurrent, onSwitch, switching }: {
  t: Theme;
  /** agy 平台识别色，来自 `colorOf(data, "agy")`（已折进用户偏好）。 */
  color: string;
  snap: AgySnapshot | null;
  busy?: boolean;
  /** 用户在设置页停用了 agy。停用 = 一个像素都不画。 */
  disabled?: boolean;
  /** 点行 = 弹出主界面的 Antigravity 详情页。 */
  onOpen?: () => void;
  // ── 账号池（2026-09-13，菜单栏 v4）──────────────────────────────────
  /** 池里的显示名。缺省 `agy` —— 池还没建起来时就是这个。 */
  label?: string;
  /** 这个号是不是 agy **当前**的登录态（现读钥匙串，不是我们写进去的值）。 */
  isCurrent?: boolean;
  /** 切到这个号。★★ **只对下一次启动的 agy 生效** —— agy 只在启动时读凭证。
   *  ⚠️ v4 稿里这一档写的是「只读·点卡不切号」，用户 2026-09-13 明确**淘汰**了那个方式：
   *     「可以切号的，按照目前 codex 的方式」。所以这里与账号卡同构，不是只读。 */
  onSwitch?: () => void;
  switching?: boolean;
}) {
  // ★ 与总览卡**共用同一个判据** —— 两边各写一份迟早出现「主窗有、菜单栏没有」。
  if (!agyQuotaVisible(snap, { disabled })) return null;

  const shown = agyShown(snap);
  const tight = agyTightest(shown?.quota);
  const rows = agyWinRows(shown?.quota);
  const degraded = !!snap && !snap.available;
  const tone = snap ? agyReasonTone(snap) : "muted";
  const alarmed = degraded && tone !== "muted";

  // 还没取过 / 一个数都没有 ——— ★ 绝不画 0%：`0` 在环里和"额度用光了"长得一模一样，
  // 而这里的真相是"读不到"。同理也绝不画 100%（上游缺省值就是满格）。
  if (!tight) {
    return (
      <Shell t={t} color={color} onOpen={onOpen} switching={switching} isCurrent={isCurrent}>
        <Ring pct={0} r={18} sw={4.5} color={t.ringTrack} track={t.ringTrack} size={46}>
          <span style={{ fontSize: 12, fontWeight: 700, color: t.muted, lineHeight: 1 }}>—</span>
        </Ring>
        <div className="mb-row-info">
          <NameLine t={t} color={color} label={label} isCurrent={isCurrent} inPool={!!onSwitch}
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
  // ★ 阈值走 `winNumColor`（helpers 的**唯一真源**），不在这里再抄一份：
  //   本仓记过「同一判据三处副本，漏改任一份都不报错」那一族。
  const glow = rem <= 20 ? (rem <= 10 ? "#E0524D" : "#E0901C") : undefined;

  return (
    <Shell t={t} color={color} onOpen={onOpen} switching={switching} isCurrent={isCurrent}>
      <Ring pct={rem} r={18} sw={4.5} color={ringColor} track={t.ringTrack} size={46} glow={glow}>
        <span style={{ fontSize: 12, fontWeight: 700, color: t.text,
                       fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{Math.round(rem)}</span>
      </Ring>
      <div className="mb-row-info">
        <NameLine t={t} color={color} sub={tight.group ?? undefined}
                  label={label} isCurrent={isCurrent} inPool={!!onSwitch}
                  mark={degraded && snap
                    ? <StaleMark t={t} note={agyReasonNote(snap)} tone={tone} size={10} />
                    : undefined} />
        {/* ★★ **每个窗口一行，不是只画最紧的那个**（v4 稿 §6 行 3/4 = `5h` / `周`）。
            2026-09-13 用户实报「gemini 缺少 5h 额度」—— 此前这里只渲染 `tight`，
            于是当值号明明有 5h + 周两格，行上只看得到其中一格，而旁边 codex 的行有两格。
            ★ 缺的那一格**补 `—` 不留空**：非当值号读不到周窗口（云端只给 5h），
              空着会把「读不到」伪装成「没有这个窗口」，两者的下一步动作完全相反。 */}
        {MB_WIN_SLOTS.map((label) => {
          const row = rows.find(r => r.label === label);
          if (!row) {
            return (
              <div key={label} className="mb-row-meta"
                   title={isCurrent ? `${label} 窗口这次没读到`
                     : `${label} 窗口只有**当前登录**的号读得到（本机 RPC）—— 云端按账号那条只给 5h`}>
                <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>{label}</span>
                <div className="mb-row-bar" style={{ background: t.barTrack }} />
                <span style={{ fontSize: 9.5, fontWeight: 600, color: t.muted,
                               fontVariantNumeric: "tabular-nums" }}>—</span>
                <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>↻—</span>
              </div>
            );
          }
          const rr = row.remaining;
          return (
            <div key={label} className="mb-row-meta">
              <span style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>{row.label}</span>
              <div className="mb-row-bar" style={{ background: t.barTrack }}>
                <div style={{ height: "100%", width: `${rr}%`, background: ringColor, borderRadius: 2,
                              transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
              </div>
              <span style={{ fontSize: 9.5, fontWeight: 600, color: alarmed ? "#E0901C" : winNumColor(rr, t),
                             fontVariantNumeric: "tabular-nums" }}>{rr.toFixed(0)}%</span>
              <span title={agyResetText(row).title || undefined}
                    style={{ fontSize: 9, color: t.muted, fontFamily: MONO }}>
                ↻{agyResetText(row).text}
              </span>
            </div>
          );
        })}
      </div>
    </Shell>
  );
}

/** 卡片外壳。左轨用 agy 识别色 —— 账号卡那条轨编码的是「临期 > 当前 > 额度」,
 *  这里编码的是「不是池成员」,所以刻意不参与那套优先级。 */
function Shell({ t, color, onOpen, switching, isCurrent, children }: {
  t: Theme; color: string; onOpen?: () => void;
  switching?: boolean; isCurrent?: boolean; children: React.ReactNode;
}) {
  return (
    // ★★ 点行 = **开主界面**（换号走名字旁边那个「切换」徽章）。
    //   这与账号行是同一条语义 —— 用户 2026-08-11 从三个 demo 里选的方案 A。
    //   ⚠️ 这里曾写成"点行即切号"（照 v4 稿 §7），结果三档的点击行为各不相同，
    //      而当值号没有 `onSwitch` 就退回 `onOpen` ⇒ 跳到 AI 用量的平台详情页，
    //      用户 2026-09-14 直接问「怎么跳到 ai 用量那里了」。
    <div className="mb-row" onClick={switching ? undefined : onOpen} style={{
      background: t.cardBg,
      border: `1px solid ${t.cardBorder}`,
      borderLeft: `3px solid ${isCurrent ? t.accent : color}`,
      cursor: onOpen && !switching ? "pointer" : "default",
      opacity: switching ? .55 : 1,
    }}>
      {children}
    </div>
  );
}

function NameLine({ t, color, sub, mark, label, isCurrent, inPool }: {
  t: Theme; color: string; sub?: string; mark?: React.ReactNode;
  label?: string; isCurrent?: boolean; inPool?: boolean;
}) {
  return (
    <>
      <div className="mb-row-name-line">
        <span className="mb-row-name" style={{ color }}>{label ?? "agy"}</span>
        {/* ★★ 徽章三态，**别合并**（与总览的 AgyCard 同一套语义）：
            · 在池里且当值 → 「当前」  · 在池里不当值 → 「切换」  · 不在池里 → 「只读」
            合并成一个灰标签就等于回到用户问过的那句「不是解决了吗」。 */}
        {isCurrent ? (
          <span className="mb-row-badge-cur"
                title="agy 当前就登录着这个号（现读钥匙串）"
                style={{ color: t.accentText, background: t.accent, border: "1px solid transparent" }}>当前</span>
        ) : inPool ? (
          <span className="mb-row-badge-cur"
                title="切到这个号 —— ★ 只对下一次启动的 agy 生效，已经开着的会话不受影响"
                style={{ color, border: `1px solid ${hexA(color, .45)}` }}>切换</span>
        ) : (
          <span className="mb-row-badge-cur"
                title="这个号不在轮换池里，只显示额度（`agy-rotate login --current` 可收编）"
                style={{ color, border: `1px solid ${hexA(color, .45)}` }}>只读</span>
        )}
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
