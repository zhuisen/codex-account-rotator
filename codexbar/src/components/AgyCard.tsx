import Ring from "./Ring";
import StaleMark from "./StaleMark";
import { CardBadgeGhost } from "./CardBadge";
import { CARD_TYPE as Z, type Theme } from "../theme";
import type { AgySnapshot } from "../agy";
import {
  agyShown, agyTightest, agyWinRows, agyQuotaVisible, agyReasonNote, agyReasonTone, agyResetText,
} from "../agy";
import { fmtAgo, winNumColor } from "../helpers";
import { IconBtn, IcPen, IcTrash, IcRotate } from "./CardIcons";
import ProbeButton from "./ProbeButton";
import { useState } from "react";

const MONO = "'JetBrains Mono'";

/** 「这次是在哪些窗口上比的」—— 给 `最优`/`USE` 的 title 用。 */
const cmpBasis = (missing: string[]): string =>
  missing.length ? "各号都读得到的那些窗口" : "全部窗口";

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
export default function AgyCard({ t, color, snap, busy, err, disabled, winSlots, onOpen, onRefresh,
                                 isSelected, reserveActions, shortcut, isBest, bestPct, partialWins,
                                 onSelect, onRename, onRemove, onProbe, probing,
                                 rotates, onToggleRotate,
                                  label, email, isCurrent, onSwitch, switching }: {
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
  // ── 账号池（2026-09-13 起 agy 可轮换；没有这些 prop 时退回原来的只读形态）──
  /** 池里的显示名。缺省 `agy` —— 池还没建起来时就是这个。 */
  label?: string;
  email?: string;
  /** 这个号是不是 agy 当前的登录态。 */
  isCurrent?: boolean;
  /** 切到这个号。★ **只对下一次启动的 agy 生效** —— agy 只在启动时读凭证，
   *  已经开着的会话不受影响。这条必须写进 `title`，否则用户会以为点一下就切走了正在跑的那个。 */
  onSwitch?: () => void;
  switching?: boolean;
  // ── 与 codex 账号卡对齐（用户 2026-09-13：「gemini 的功能也没有 1:1 同步上 codex」）──
  /** 卡被选中 ⇒ 展开动作条。 */
  isSelected?: boolean;
  /** 同排有别的卡展开 ⇒ 本卡渲染**同一条动作条但整条隐形**，高度由构造保证一致。
   *  ★ 画一个"差不多高"的占位是行不通的：按钮尺寸一改就静默失准（账号卡实测差过 34px）。 */
  reserveActions?: boolean;
  /** ⌘N 角标。没有就不画 —— agy 不进 `alive`，快捷键另走一条路。 */
  shortcut?: number;
  /** 全池里余量最多的那个号 ⇒ 画 `最优` / `USE`。 */
  isBest?: boolean;
  /** 最优号的余量，用来算本卡的差值角标 `-N%`。 */
  bestPct?: number;
  /**
   * ★★★ 这次"谁最优"的比较**少看了**哪些窗口。
   *
   * 周窗口只有当值号读得到（云端按账号那条结构上没有周），所以池里各号的窗口集合
   * 常常**不齐**。比较只能落在大家都有的那些窗口上 —— 而"少看了什么"必须说出来，
   * 否则 `USE` 会被读成"这个号全面最优"，事实只是"在我们都量到的那部分上最优"。
   * 2026-09-15 用户实报的「一个 USE 一个当前」就是这个比较出的岔子。
   */
  partialWins?: string[];
  onSelect?: () => void;
  /** 改显示名。★ label 只是昵称，身份始终是 `sub`（同 codex 的 aid）。 */
  onRename?: (next: string) => void;
  /** 从池里移除。★ **不可逆** —— 这里有两段确认，CLI 侧另有一道拒绝删当值号的守卫。 */
  onRemove?: () => void;
  /** ★★★ 计费探针 —— **花的是 agy 自己的额度**（起一次 `agy -p`，实测约 15k token）。
   *  与 codex 的探针是两套机制：那边直接打 `/responses`，agy 只在启动时读凭证。 */
  onProbe?: () => void;
  probing?: boolean;
  /** 这个号参不参与自动轮换。缺省 = 参与（池里存的是反向的 `rotate_off`）。 */
  rotates?: boolean;
  onToggleRotate?: (on: boolean) => void;
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
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  /** 与最优号的差值角标。★ 与账号卡同一套口径：**只在落后时画**，
   *  领先/持平不画 —— 画一个 `+0%` 只是噪音。 */
  const gap = rem != null && bestPct != null && bestPct - rem >= 1
    ? -Math.round(bestPct - rem) : null;

  /** 这一格为什么读不到 —— 说清楚**原因**和**怎么才能看到**，不是只说"没有"。 */
  /**
   * ★★ 文案 2026-09-15 从「非当值号」改成「用过才有」（用户：「还存在什么非当值号，
   *   一次性找办法根治啊」）。「非当值号」说的是**我们的内部状态**，而用户要知道的是
   *   **他能做什么**。本仓 §5d：披露要说"做什么"，不是只说"坏了"。
   * ★ 而且它现在是**会自己消失**的：这个号下次当值时 `agy-quota` 会把周额度记进
   *   `weekly_seen`（B49），此后这一格显示的是那次的真实读数（带 `~` 标龄）。
   *   所以这句话描述的是一个**有终点**的状态，不是一条永久免责。
   */
  /** 这一格为什么读不到。★ 说清**原因**和**下一步**，不是只说"没有"。 */
  const missTitle = (label: string, _cur?: boolean) =>
    `${label} 窗口这次没读到 —— 点右上角 ↻ 重取一次。`
    + `（2026-09-15 起每个号都按账号直接读完整摘要，含周窗口；`
    + `所以这里为空**不再是"非当值号"那种结构性缺失**，就是这一次没取到。）`;

  return (
    <div onClick={onSelect ?? onOpen} style={{
      position: "relative", background: isSelected ? t.heroBg : t.cardBg,
      border: `1px solid ${isSelected ? t.accent : hexA(color, .30)}`, borderRadius: 12,
      padding: "16px 14px 12px", display: "flex", flexDirection: "column",
      cursor: (onSelect ?? onOpen) ? "pointer" : "default", userSelect: "none",
      transition: "background .2s ease, border-color .2s ease",
    }}>
      {/* ★ 有快捷键就画 `⌘N`（与账号卡同位同字号），没有就退回 `CLI` ——
          那个角标本来就是"这张卡怎么来的"，两种写法都在回答同一个问题。 */}
      <span style={{ position: "absolute", top: 6, left: 10, color,
                     fontFamily: MONO, letterSpacing: ".04em", fontSize: Z.shortcut }}>
        {shortcut ? `⌘${shortcut}` : "CLI"}</span>
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
            {editing !== null ? (
              // ★ `onKeyDown` 必须 `stopPropagation`：全局 ⌘1~⌘9 是切号快捷键，
              //   不拦的话在框里打数字会切号（与账号卡同一条教训）。
              <input autoFocus value={editing}
                     onClick={(e) => e.stopPropagation()}
                     onChange={(e) => setEditing(e.target.value)}
                     onKeyDown={(e) => {
                       e.stopPropagation();
                       if (e.key === "Enter" && editing.trim()) {
                         onRename?.(editing.trim()); setEditing(null);
                       }
                       if (e.key === "Escape") setEditing(null);
                     }}
                     // ★ `onBlur` 一律**放弃**，不静默提交 —— 与账号卡同一条。
                     onBlur={() => setEditing(null)}
                     style={{ fontSize: Z.name, fontWeight: 700, color, minWidth: 0, flex: 1,
                              background: "transparent", border: `1px solid ${hexA(color, .45)}`,
                              borderRadius: 5, padding: "0 4px", fontFamily: "inherit" }} />
            ) : (
              <span style={{ fontSize: Z.name, fontWeight: 700, color, minWidth: 0,
                             overflow: "hidden", textOverflow: "ellipsis" }}>{label ?? "agy"}</span>
            )}
            {/* ★★ 徽章三态，**别合并**：
                · 在池里且当值  → 「当前」（青底，与账号卡同一套语义）
                · 在池里不当值  → 「切换」（可点）
                · 不在池里      → 「只读」——这是 2026-09-13 之前的形态，没建池时仍然成立。
                把后两者合并成一个灰标签，就等于回到用户问的那个问题：「不是解决了吗」。 */}
            {isCurrent ? (
              <span style={{ fontSize: Z.curBadge, fontWeight: 700, padding: "1px 5px",
                             borderRadius: 5, color: t.accentText, background: t.accent }}>当前</span>
            ) : onSwitch ? (
              <span onClick={(e) => { e.stopPropagation(); if (!switching) onSwitch(); }}
                    title="切到这个号 —— ★ 只对下一次启动的 agy 生效，已经开着的会话不受影响"
                    style={{ fontSize: Z.curBadge, fontWeight: 700, padding: "1px 5px",
                             borderRadius: 5, cursor: switching ? "default" : "pointer",
                             color, border: `1px solid ${hexA(color, .45)}`,
                             opacity: switching ? .5 : 1 }}>{switching ? "切换中…" : "切换"}</span>
            ) : (
              <span title="Antigravity 还没建账号池 —— `agy-rotate login --current` 收编当前号"
                    style={{ fontSize: Z.curBadge, fontWeight: 700, padding: "1px 5px", borderRadius: 5,
                             color, border: `1px solid ${hexA(color, .45)}` }}>只读</span>
            )}
            {/* ★ 降级说明**只在这里**,一个字符 + 悬浮。理由见 StaleMark 的文件头。 */}
            {degraded && snap && <StaleMark t={t} note={agyReasonNote(snap)} tone={tone} size={11} />}
            {/* 读**本机 sidecar** 失败(IO 层),与"额度读不到"是两回事,所以文案不同。 */}
            {!!err && <StaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
            {/* ★ 与账号卡同一套语义：`最优` = 全池余量最多；`USE` = 最优**且不是当前号**
                （已经在用最优号时再喊一句"用这个"只是噪音）。 */}
            {/* ★ `title` 如实说出这次比较的**基础**。少看了窗口就直说少看了哪些 ——
                不说的话 `USE` 会被读成"全面最优"，而事实只是"在都量到的那部分上最优"。 */}
            {isBest && (() => {
              const why = partialWins?.length
                ? `在**${(partialWins.length ? cmpBasis(partialWins) : "")}**上余量最多。`
                  + `⚠️ 这次比较没算上 ${partialWins.join("、")} —— 那些窗口不是每个号都读得到`
                  + `（周窗口只有当值号有，云端按账号那条没有周）。`
                : "在所有号都读到的窗口上余量最多。";
              return isCurrent
                ? <span title={why}
                        style={{ fontSize: Z.curBadge, fontWeight: 700, padding: "1px 5px", borderRadius: 5,
                                 color: "#27B26B", border: "1px solid #27B26B55" }}>最优</span>
                : <span title={why}
                        style={{ fontSize: Z.curBadge, fontWeight: 700, padding: "1px 5px", borderRadius: 5,
                                 color: t.accent, border: `1px solid ${t.accent}55` }}>USE</span>;
            })()}
            {/* 差值角标：**只在落后时画**。领先/持平画一个 `+0%` 只是噪音。 */}
            {gap != null && !isBest && (
              <span title={`比最优的号少 ${-gap}%`}
                    style={{ marginLeft: "auto", fontSize: Z.curBadge, fontWeight: 700,
                             fontFamily: MONO, color: t.muted,
                             fontVariantNumeric: "tabular-nums" }}>{gap}%</span>
            )}
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
              // ★★ 这一行以前是 `visibility: hidden` 的纯占位 —— 用户看到的是**一整行空白**，
              //   连 `—` 都没有，于是直接问「为什么这个号少了一个窗口」。
              //   本仓 §5d 的规矩是「**读不到显 `—`，不显 `0`**」，而"什么都不显"比显 0 还糟：
              //   它把「读不到」伪装成了「没有这个窗口」，两者的下一步动作完全相反。
              //   高度仍与真行同构（跨卡对齐靠它），只是把话说出来。
              // ★★★ **原因写在行上，不只写在 `title` 里**（2026-09-14 用户实报
              //   「我的 gemini 周额度没刷新？还丢失了？」）。实测当时**并没有丢**：
              //   `.agy-quota.json` 里 `gemini-weekly = 98.78%`、`fetched_at` 就在几秒前，
              //   只是它的 `pid_email` 指向**另一个号**，所以这张卡结构上拿不到它。
              //   在那之前这一行是 `—  ↻—`，而同一个 `—` 同时表示「非当值号」和「读失败」，
              //   两者的下一步动作完全相反。解释一直写着 —— 写在 `title` 里，
              //   **而本仓的规矩是「告警放在眼睛已经在的地方」，只写进悬浮的真话等于没写**。
              <div key={label} title={missTitle(label, isCurrent)}
                   style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: Z.winLabel, color: t.muted, fontFamily: MONO }}>{label}</span>
                {/* ★ 条槽保留：跨卡对齐靠这一行的高度撑着（见 test_missing_window_says_so）。 */}
                <div style={{ flex: 1, height: Z.bar, borderRadius: 2, background: t.barTrack }} />
                <span style={{ fontSize: Z.eta, color: t.muted, fontFamily: MONO,
                               whiteSpace: "nowrap" }}>
                  "这次没读到"</span>
              </div>
            ) : (
              // ★★★ `seen_at` = 这一格是**上次当值时看到的**，不是现在读到的
              //   （2026-09-15 用户实报「两个号一个有周额度一个没有」）。
              //   周窗口只有本机 RPC 有、只看得到当值号；云端那条**结构上没有周**（当天实测）。
              //   所以这里画的是一个**真实发生过**的数字 —— 但必须标龄、走中性色，
              //   否则它会冒充现值，而那比画空更糟（§7.0b 的反面：不许把旧值伪装成新值）。
              <div key={label}
                   title={row.seen_at
                     ? `${row.group ?? "?"} · 剩 ${row.remaining.toFixed(1)}% —— 这是这个号**上次当值时**读到的（${fmtAgo(row.seen_at)}）。周窗口只有当前登录的号读得到，云端按账号那条没有周。`
                     : `${row.group ?? "?"} · 剩 ${row.remaining.toFixed(1)}%`}
                   style={{ display: "flex", alignItems: "center", gap: 6,
                            opacity: row.seen_at ? .62 : 1 }}>
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
                <span title={agyResetText(row).title || undefined}
                      style={{ fontSize: Z.eta, color: t.muted, fontFamily: MONO }}>
                  ↻{agyResetText(row).text}
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
                // ★ 「在/不在轮换池」是**事实陈述**，跟着池走。写死"不在"是 2026-09-13
                //   之前的事实，池建起来之后它就变成了一句假话。
                : shown ? (email ?? (onSwitch || isCurrent ? "Google 订阅 · 在轮换池"
                                                          : "Google 订阅 · 不在轮换池"))
                : "额度暂时读不到"}</span>
            {/* agy 没有重置卡这个概念，占位只为让页脚与账号卡等高。 */}
            <span style={{ alignSelf: "flex-end" }}><CardBadgeGhost /></span>
          </div>
        </div>
      </div>

      {/* ★★ 动作条。与账号卡**同一条构造**：同排有别的卡展开时，本卡渲染同一条动作条
          但整条隐形 —— 不是画一个"差不多高"的占位。账号卡那边手算过一次，sweep 当场
          量出还差 34px；高度必须**由构造保证**，按钮尺寸一改自动跟上。
          ★ 隐形那份必须 `pointerEvents: none` + `aria-hidden`，否则会出现看不见却点得到的按钮。
          ⚠️ **没有「探针」和「轮换开关」** —— 探针跑的是 `codex-rotate probe`，扣的是
             codex 的额度；而 agy 的自动切号发生在 `bin/agy` 拉起进程之前，不是按号的开关。
             给一个点了没用的按钮，比没有这个按钮糟。 */}
      {(isSelected || reserveActions) && (
        <div onClick={(e) => e.stopPropagation()}
             aria-hidden={!isSelected}
             style={{ display: "flex", gap: 6, marginTop: 10, paddingTop: 8,
                      borderTop: `1px solid ${isSelected ? t.divider : "transparent"}`,
                      ...(isSelected ? null : { visibility: "hidden" as const, pointerEvents: "none" as const }),
                      flexWrap: "wrap", rowGap: 6 }}>
          {isCurrent ? (
            <span style={{ flex: "1 1 auto", minWidth: 62, textAlign: "center", fontSize: 11,
                           fontWeight: 600, whiteSpace: "nowrap", color: t.accent, padding: "5px 0" }}>✓ 当前</span>
          ) : onSwitch ? (
            <span onClick={() => { if (!switching) onSwitch(); }}
                  title={`把当前号切到 ${label ?? "这个号"} —— ★ 只对**下一次启动的** agy 生效`}
                  style={{ flex: "1 1 auto", minWidth: 62, textAlign: "center", fontSize: 11,
                           fontWeight: 700, whiteSpace: "nowrap", color: t.accentText,
                           background: t.accent, padding: "5px 8px", borderRadius: 6,
                           cursor: switching ? "default" : "pointer", opacity: switching ? .5 : 1 }}>
              {switching ? "切换中…" : "切换"}</span>
          ) : null}
          {onProbe && (
            /* ★ 探针**不压成图标**：它是这一档唯一花钱的控件，必须与旁边免费的按钮
               一眼可分（琥珀 + ⚡ + 两段确认）。压成一个 34px 的灰图标正好抹掉那条区分。 */
            <ProbeButton t={t} variant="inline" label="探针"
              hint={`起一次 agy 让 ${label ?? "这个号"} 真跑一句，验它是否真能干活。⚠️ 花的是 **agy 自己**的额度（实测单次约 15k token、约 30s）`}
              loading={!!probing} onConfirm={onProbe} loadingText="探测…" />
          )}
          {onToggleRotate && (
            <IconBtn title={rotates
                       ? `${label ?? "这个号"} 正参与自动轮换。点一下移出 —— wrapper 不再挑它`
                       : `${label ?? "这个号"} 已停用自动轮换。点一下放回轮换池`}
                     onClick={() => onToggleRotate(!rotates)}
                     color={rotates ? t.muted : "#E0901C"}
                     border={rotates ? t.ghostBorder : "#E0901C55"}
                     bg={rotates ? undefined : "rgba(224,144,28,.10)"}>
              <IcRotate off={!rotates} />
            </IconBtn>
          )}
          {onRefresh && (
            <IconBtn title="重新取一次这一池的额度（云端按账号读，零消耗）"
                     onClick={() => { if (!busy) onRefresh(); }}
                     color={t.muted} border={t.ghostBorder}>
              <span style={{ fontFamily: MONO, fontSize: 12, lineHeight: 1 }}>↻</span>
            </IconBtn>
          )}
          {onRename && (
            <IconBtn title="重命名 —— 改显示名。卡片、菜单栏、`agy --as` 都会跟着变（label 只是昵称，身份始终是 sub）"
                     onClick={() => setEditing(label ?? "")} color={t.muted} border={t.ghostBorder}>
              <IcPen />
            </IconBtn>
          )}
          {onRemove && (!confirmDelete ? (
            <IconBtn title={`从池里移除 ${label ?? ""}（会先要一次确认）`}
                     onClick={() => setConfirmDelete(true)} color="#E0524D" border="#E0524D40">
              <IcTrash />
            </IconBtn>
          ) : (
            <>
              {/* ★ 确认态**保留文字**：移除不可逆，把「确认删除」也压成图标等于让人凭记忆点。 */}
              <span onClick={() => { setConfirmDelete(false); onRemove(); }}
                    style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: "#E0524D",
                             padding: "5px 10px", borderRadius: 6, cursor: "pointer",
                             whiteSpace: "nowrap", flexShrink: 0 }}>确认删除</span>
              <span onClick={() => setConfirmDelete(false)}
                    style={{ fontSize: 11, color: t.muted, padding: "5px 10px", cursor: "pointer" }}>取消</span>
            </>
          ))}
        </div>
      )}
    </div>
  );
}

/** `#rrggbb` → `rgba(...)`。边框与徽章描边要跟着平台色走，写死一套就没法响应用户改色。 */
function hexA(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
