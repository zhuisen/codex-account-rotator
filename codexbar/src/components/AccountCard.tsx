import { useState, useEffect } from "react";
import { STATUS_COLORS, STATUS_TEXT, CARD_TYPE as Z, type Theme } from "../theme";
import StaleMark from "./StaleMark";
import { type Account, fmtCd, fmtAgeSec, maskId, winBarColor, winNumColor,
         QUOTA_STALE_SEC } from "../helpers";
import Ring from "./Ring";
import PlanBadge from "./PlanBadge";
import CardBadge, { isCardExpiring } from "./CardBadge";
import ProbeButton from "./ProbeButton";

/** Delta vs the best account in the pool — "最优" / "-19%". ≤-50 is amber (handoff §5.0). */
function DeltaChip({ delta, t }: { delta: number; t: Theme }) {
  const best = delta === 0;
  const far = delta <= -50;
  return (
    <span style={{
      marginLeft: "auto", flexShrink: 0,
      fontSize: Z.delta, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
      fontVariantNumeric: "tabular-nums",
      color: best ? t.accent : far ? "#E0901C" : t.text2,
      background: best ? t.accentSoft : far ? "rgba(224,144,28,.12)" : t.ghostBg,
    }}>{best ? "最优" : `${delta}%`}</span>
  );
}

export default function AccountCard({ a, isCurrent, isBest, isSelected, shortcut, bestPct, probing, privacy, t, onSelect, onSwitch, onShowDetail, onRemove, onProbe, onRename, winSlots }: {
  a: Account; isCurrent: boolean; isBest: boolean; isSelected: boolean; shortcut?: number;
  /** Highest remaining quota in the pool — the baseline the delta chip compares against. */
  bestPct: number;
  /**
   * 这一格网格里出现过的窗口**槽位**，按时长升序（由调用方跨所有卡算出，如 `["5h","周"]`）。
   * 卡片按槽位逐行渲染，自己没有的槽位画一行同构的隐藏行 —— 让「到期」及其下方
   * 在所有卡之间对齐到同一条水平线（用户 2026-08-26）。
   *
   * ★ 传**标签而不是行数**：只补行数的话 Pro 的「周」会顶到第一行、和 Plus 的「5h」
   *   画在同一条线上 —— 对齐了，但对齐的是两种不同的窗口，**比错开更糟**。
   * ★ 不写死 `["5h","周"]`：Plus 现在 2 个窗口、Pro 1 个，但那是**上游此刻的形状**不是不变量 ——
   *   2026-07 它还只有周，2026-08-25 5h 才回来。写死等于把一个会变的观测钉进布局。
   * ★ 不用「把 Pro 的条加粗填满」：同一个指标出现两种粗细，会让粗细看起来有含义而实际没有；
   *   且设计语言明写「进度=细胶囊条 3–8px，反对粗色块」。
   */
  winSlots: string[]; /** 该号正在探测中 */ probing: boolean; /** 打码模式 */ privacy: boolean; t: Theme;
  onSelect: () => void; onSwitch: () => void; onShowDetail: (aid: string) => void; onRemove: (label: string) => void; onProbe: (label: string) => void;
  /** 改名。空名/含空格/重名的校验在 `codex-rotate rename`(唯一真源)——那三种都会让按 label
   *  查找的 switch/probe 静默操作到错的号上。这里只挡「没改」。 */
  onRename: (next: string) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);   // null = 不在改名
  // 卡片一取消选中就退出改名:否则输入框会留在收起的卡片上,看不见却仍持有焦点
  useEffect(() => { if (!isSelected) { setConfirmDelete(false); setEditing(null); } }, [isSelected]);

  const isDead = a.status === "dead";
  const isCool = a.status === "cool";
  const sc = STATUS_COLORS[a.status] ?? STATUS_COLORS.live;
  // ★ 环取**最紧**的窗口,不是第一个 —— 下方细条会把所有窗口列全,环是那份清单的"最坏值"。
  //   用 windows[0] 会让环显示 5h、而真正卡住你的是周,**把约束藏起来**。
  const pct = a.tightest;
  const known = pct >= 0 && !isDead;
  // Quota-driven colour for live/low (handoff rule), status colour for cool/dead where the state
  // matters more than the number.
  // ★★ 与菜单栏行**同一条规则**(`winBarColor`):平时按窗口取色,低额度时警告色夺回。
  //    用户 2026-08-26 的两条要求 ——「5h 与周颜色不一样」+「低额度靠条色报警」——
  //    在这条规则里和解:**识别是常态,报警是例外,而例外优先**。
  //    两个 surface 各写一份迟早分叉(grok 那边栽过一次,靠截图才发现)。
  const qc = isDead || isCool ? sc : winBarColor(a.tightestWin, pct, t);
  const glow = known && pct <= 20 ? (pct <= 10 ? "#E0524D" : "#E0901C") : undefined;
  const expiring = isCardExpiring(a);
  // 槽位化窗口行：先按调用方给的槽位顺序排，再兜上任何不在槽位表里的窗口（见渲染处注释）。
  const slotRows: { label: string; w?: typeof a.windows[number] }[] = [
    ...winSlots.map(label => ({ label, w: a.windows.find(x => x.label === label) })),
    ...a.windows.filter(w => !winSlots.includes(w.label)).map(w => ({ label: w.label, w })),
  ];

  const border = isSelected ? t.accent
    : expiring ? "rgba(224,144,28,.4)"
    : isCurrent ? t.accentBorder
    : t.cardBorder;

  return (
    <div
      onClick={onSelect}
      style={{
        position: "relative", background: isCurrent ? t.curCardBg : t.cardBg,
        border: `1px solid ${border}`, borderRadius: 12,
        padding: "16px 14px 12px", display: "flex", flexDirection: "column",
        cursor: "pointer", userSelect: "none", opacity: isDead ? 0.55 : 1,
        transition: "background .2s ease, border-color .2s ease",
      }}>

      {shortcut && <span style={{ position: "absolute", top: 6, left: 10, fontSize: Z.shortcut, color: t.muted, fontFamily: "'JetBrains Mono'" }}>⌘{shortcut}</span>}

      {/* ★★ `flex:1` + 内容列 `alignSelf:stretch`：卡片在网格里本来就等高（`stretch`），
          这里把多出来的高度交给内容列，好让下方区块**吊在卡片底边**（见下方 spacer）。

          ★ 环保持**垂直居中**（用户 2026-08-26 指出顶对齐难看）。这与"环要跨卡对齐"不冲突：
            内容列一旦拉满卡片高度，这一行的交叉轴尺寸就等于**卡片高度**，而同排卡片等高，
            所以居中的环自然落在同一条线上。
            ⚠️ 我先前把环改成顶对齐、并注了「居中会上下浮动」—— 那是**拉满之前**的观测，
            现在不成立了。别再照那句话改回顶对齐。闸在 sweep.py 的 `rings` 那一项。 */}
      <div style={{ display: "flex", gap: 11, alignItems: "center", flex: 1, minHeight: 0 }}>
        <Ring pct={known ? pct : 0} r={Z.ringR} sw={Z.ringSw} color={qc} track={t.ringTrack} size={Z.ring} glow={glow}>
          <span style={{ fontSize: Z.ringNum, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{known ? pct : "—"}</span>
        </Ring>

        <div style={{ flex: 1, minWidth: 0, alignSelf: "stretch", display: "flex", flexDirection: "column", gap: 4 }}>
          {/* ★ 三列九宫格下这一行**零余量**:`plus4 活 USE 最优` 实测自然宽 126、可用 117。
              零余量意味着任何扰动都会破 —— 分数缩放下的字形量化就够了(每个内联元素舍入
              半像素,十几个累积出 9px)。所以指定**唯一让位者**:名字截省略号,徽章一个不压。
              名字截一点还认得出,徽章少一半就读不出是 USE 还是 PRO。 */}
          {/* ★★ `minWidth: 0` 单独用会把名字压到 **0px 直接消失**(2026-08-25 实测:
              Pro1 那行徽章最多 —— PRO+活+USE+当前 —— 860px 下自然宽 122 / 可用 114,
              flex 就把唯一可缩的名字压没了)。**认不出是哪个号,比裁掉半个日期更糟。**
              所以两条一起:名字给一个**下限**(4 个字符宽,截成 `Pro…` 也还认得出),
              整行允许换行 —— 宽屏永不触发,只在下限宽度让徽章掉到第二行。 */}
          <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0,
                        flexWrap: "wrap", rowGap: 4 }}>
            {editing === null ? (
              <span style={{ fontSize: Z.name, fontWeight: 700, color: t.text, minWidth: 40,
                             overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.node}</span>
            ) : (
              <input
                autoFocus value={editing}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => setEditing(e.target.value)}
                onKeyDown={(e) => {
                  // ★ 必须拦:全局 ⌘1~⌘9 是切号快捷键,不拦的话在输入框里打数字会切号
                  e.stopPropagation();
                  if (e.key === "Enter") {
                    const v = editing.trim();
                    if (v && v !== a.node) onRename(v);
                    setEditing(null);
                  } else if (e.key === "Escape") setEditing(null);
                }}
                onBlur={() => setEditing(null)}
                style={{ fontSize: Z.name, fontWeight: 700, color: t.text, width: 96,
                         background: "transparent", border: `1px solid ${t.accentBorder}`,
                         borderRadius: 5, padding: "1px 5px", outline: "none",
                         fontFamily: "'JetBrains Mono'" }} />
            )}
            <PlanBadge plan={a.plan} t={t} size={Z.planBadge} />
            {/* ★★ 冷却倒计时**并进状态字,不另起一行**(2026-09-05 修)。
                原来它在窗口行之后单独占一行,于是冷却中的卡比兄弟卡高一行,
                页脚被推下、细条被推上 —— 实测跨卡错开 **21px**,所有总览宽度全中。
                ★ 这个缺陷 memory.md 里**预测过**:「冷却态多一行 ⇒ 理论上破对齐,
                但这是推理不是实测,没有夹具能造出冷却态」。今天真实数据造出了冷却号,
                对齐闸如期抓到 —— 预测、判据、修法三样当初就都写对了,只差一个触发条件。
                ★ 名字行本来就有「冷却」两个字,那一行**只多了个倒计时**,所以合并零信息损失。 */}
            <span style={{ fontSize: Z.status, fontWeight: 600, color: sc }}>
              {STATUS_TEXT[a.status]}{isCool && a.cooldownSec ? ` ${fmtCd(a.cooldownSec)}` : ""}
            </span>
            {/* ★★ 额度快照陈旧的标记（2026-09-05 加）。此前 `StaleMark` **只接了 grok/agy，
                codex 账号卡一个都没接** —— 于是一个 token 已失效、快照陈旧 3.8 天的号，
                卡片上没有任何提示，而池级「上次刷新」取的是全池最大值、被每 300s 刷新的
                活号盖成「刚刚」，**主动把这件事藏了起来**。
                ★ 刻意用 muted 不用红：合盖休眠唤醒的那一瞬间全池都会陈旧，那是事实不是故障；
                  把它染成告警色只会训练用户忽略所有告警。它只是一句可悬浮的事实陈述。 */}
            {a.quotaStale && a.quotaAgeSec != null && (
              <StaleMark t={t} tone="muted" size={10}
                         note={`这个号的额度快照是 ${fmtAgeSec(a.quotaAgeSec)}前读到的（超过 ${Math.round(QUOTA_STALE_SEC / 60)} 分钟）。`
                               + `条和百分比画的是那一刻的值，不是现在的值。`
                               + `这不代表额度有问题——只代表我们有一阵子没读到它了。`} />
            )}
            {isBest && <span style={{ fontSize: Z.useBadge, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 5px", borderRadius: 4, flexShrink: 0 }}>USE</span>}
            {isCurrent
              ? <span style={{ marginLeft: "auto", flexShrink: 0, fontSize: Z.curBadge, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, padding: "1px 7px", borderRadius: 999 }}>当前</span>
              : known && bestPct >= 0 && <DeltaChip delta={pct - bestPct} t={t} />}
          </div>

          <div style={{ fontSize: Z.email, color: t.text2, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{maskId(a.email, privacy)}</div>

          {/* ★★ 弹性留白：把条形区与其下方压到卡片底边，于是这些水平线**与上方高度无关** ——
              徽章行折不折行随窗宽而变（240px 卡里 `plus5 活 -4%` 就要折行、253px 不折），
              **给上方补固定高度永远追不上这种随宽度变化的差异**。
              ★ 必须放在条形区**之前**：放在它之后只能对齐「到期」，条形区自己仍是顶对齐的 ——
                而用户 2026-08-26 的红线正是画在条上。

              ★ **不封顶**（曾经封在 28px）。封顶是为了避免"邻卡展开时兄弟卡中间裂一道大洞"，
                但要吸的量 = 徽章折行差 **+ 动作条高度**，28px 吸不完，兄弟卡之间就差了 24px
                （实测 960px 展开态：plus5 名字行 45、grok 21，两边留白都顶到 28 就卡住了）。
                而那道"洞"出现的**唯一场合**正是邻卡展开 —— 洞里对应的就是邻卡的按钮区，
                读起来是合理的。**用一个会错位的上限换一个不难看的空白，是划不来的交易。** */}
          <div aria-hidden style={{ flex: 1, minHeight: 0 }} />

          {/* ★★ 逐**槽位**画，不是逐窗口画：自己没有的槽位画一行 `visibility:hidden` 的同构行。
              占位行**复用同一份行结构**，高度由构造保证一致 —— 写一个固定像素的空 div
              是在复制"行有多高"这个知识，字号一改就错位。
              ★ 末尾兜上不在槽位表里的窗口：宁可多一行，也不能把一个真窗口悄悄画没 ——
                「合法窗口被静默丢掉」正是 2026-08-25 那个 bug 的形态，它不报错，只是看不见。 */}
          {/* ★★ 「从没探测过」的号（`windows: []`）**也走槽位**，提示文字占**第一条槽位行**，
              而不是在槽位之外另起一行 —— 另起一行就意味着这张卡比兄弟卡多/少一行，
              而条形区与页脚是从卡片底边往上推的，于是它的「到期」整体错位（实测 9px：
              少两条细条 34px、多一行提示 17px，差 37px 超过留白 28px 的上限，吸不完）。
              ★ 提示行**沿用同一份 4 段结构**（后三段隐形），高度由构造与真行一致。 */}
          {!isDead && (slotRows.length ? slotRows : [{ label: "—", w: undefined }])
            .map(({ label, w }, i) => {
            const real = known && !!w;
            const notice = !known && i === 0;
            return (
              <div key={label} aria-hidden={real || notice ? undefined : true}
                   style={{ display: "flex", alignItems: "center", gap: 6, visibility: real || notice ? undefined : "hidden" }}>
                <span style={{ fontSize: Z.winLabel, color: t.muted, fontFamily: notice ? undefined : "'JetBrains Mono'", whiteSpace: "nowrap" }}>{notice ? "未探测 · 刷新一次" : label}</span>
                <div style={{ flex: 1, height: Z.bar, borderRadius: 2, background: real ? t.barTrack : "transparent", overflow: "hidden" }}>
                  {real && w && <div style={{ height: "100%", width: `${w.pct}%`, background: winBarColor(w, w.pct, t), borderRadius: 2, transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />}
                </div>
                <span style={{ fontSize: Z.pct, fontWeight: 600, color: real && w ? winNumColor(w.pct, t) : t.text2, fontFamily: "'JetBrains Mono'", fontVariantNumeric: "tabular-nums",
                              // ★ 提示行里这两段只借**高度**：`visibility:hidden` 仍占宽度，
                              //   在 168px 的窄卡里把整行撑到 177 溢出。加 `width:0` 只留行盒。
                              ...(notice ? { visibility: "hidden" as const, width: 0, overflow: "hidden" as const } : null) }}>{real && w ? `${w.pct}%` : "00%"}</span>
                <span style={{ fontSize: Z.eta, color: t.muted, fontFamily: "'JetBrains Mono'",
                              ...(notice ? { visibility: "hidden" as const, width: 0, overflow: "hidden" as const } : null) }}>↻{real && w ? w.reset : "0d00h"}</span>
              </div>
            );
          })}
          {isDead && <span style={{ fontSize: Z.note, color: "#E0524D", fontWeight: 600 }}>token 失效 · 需重登</span>}
          {/* ★ 冷却那一行已并进名字行的状态字(见上面 STATUS_TEXT 处的说明)。
              **别再在这里加任何独立行** —— 窗口行与页脚之间每多一行,这张卡就比兄弟卡高一行,
              而细条是从页脚往上推的,整排就会错开。死号不受影响:它只在折叠区渲染,不进网格。 */}

          {/* ★★ 页脚**固定两行**（日期一行、徽章一行右对齐），不再靠 `flex-wrap` 自己决定。
              原来是 wrap：徽章长了就自己掉到第二行，避免把 "到期 2026-08-10" 从中间折断。
              问题是**折不折行取决于文案长短**，于是「有一张卡的重置卡快到期、另一张不快」时，
              两张卡的页脚一个 48px 一个 29px —— 而条形区是从页脚往上推的，
              **上面那些细条就整体错开 19px**（实测 1040~1120px 这一段，用 `?cardexp=1` 夹具复现）。

              固定两行 = 页脚高度与文案无关 ⇒ 那条水平线在任何宽度、任何徽章文案下都成立。
              代价是宽屏下比单行高约 19px；换来的是这条对齐**不再有会破的宽度区间**。
              ★ 别改回 wrap 去省这 19px：那正是上面那个 bug。 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 5, paddingTop: 7, borderTop: `1px solid ${t.divider}` }}>
            <span title={a.expStale ? "OpenAI 上次复核订阅早于这个日期,所以「已过期」是拿陈旧快照下的结论 —— 续费不在它视野里。刷新 token 也拉不到新状态,要等 OpenAI 自己复核。" : undefined} style={{ fontSize: Z.exp, color: t.muted, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap" }}>到期 {a.exp}{a.expStale && <span style={{ color: "#E0901C" }}>*</span>}</span>
            <span style={{ alignSelf: "flex-end" }}><CardBadge a={a} t={t} /></span>
          </div>
        </div>
      </div>

      {isSelected && (
        <div onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 6, marginTop: 10, paddingTop: 8, borderTop: `1px solid ${t.divider}`,
                     // ★ 6 个按钮塞在三列网格的一张 ~300px 卡里放不下。不换行时 flex 会把每个
                     //   压到 ~20px ⇒「切换到此号」变成一列竖排的单字(用户 2026-08-24 截图)。
                     //   探针实测:内容高 80px / 行高 13px = 六行。
                     flexWrap: "wrap", rowGap: 6 }}>
          {!isCurrent && !isDead && (
            <span onClick={onSwitch} style={{ flex: "1 1 auto", minWidth: 84, textAlign: "center", fontSize: 11, fontWeight: 700, whiteSpace: "nowrap", color: t.accentText, background: t.accent, padding: "5px 8px", borderRadius: 6, cursor: "pointer" }}>切换到此号</span>
          )}
          {isCurrent && (
            <span style={{ flex: "1 1 auto", minWidth: 84, textAlign: "center", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap", color: t.accent, padding: "5px 0" }}>✓ 当前使用中</span>
          )}
          {!isDead && (
            <ProbeButton t={t} variant="inline" label="探针"
              hint={`对 ${a.node} 发一次真实补全,验它是否真能干活。⚠️ 消耗周额度(实测单次 <1%)`}
              loading={probing} onConfirm={() => onProbe(a.node)} loadingText="探测…" />
          )}
          <span onClick={() => setEditing(a.node)}
                title="改这个号的显示名。菜单栏标题、弹窗、卡片会一起变（label 只是昵称，不影响套餐判定）"
                style={{ fontSize: 11, color: t.muted, padding: "5px 10px", borderRadius: 6, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0, border: `1px solid ${t.ghostBorder}` }}>重命名</span>
          <span onClick={() => onShowDetail(a.aid)} style={{ fontSize: 11, color: t.muted, padding: "5px 10px", borderRadius: 6, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0, border: `1px solid ${t.ghostBorder}` }}>详情</span>
          {!confirmDelete ? (
            <span onClick={() => setConfirmDelete(true)} style={{ fontSize: 11, color: "#E0524D", padding: "5px 10px", borderRadius: 6, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0, border: "1px solid #E0524D40" }}>删除</span>
          ) : (
            <>
              <span onClick={() => { setConfirmDelete(false); onRemove(a.node); }} style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: "#E0524D", padding: "5px 10px", borderRadius: 6, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0 }}>确认删除</span>
              <span onClick={() => setConfirmDelete(false)} style={{ fontSize: 11, color: t.muted, padding: "5px 10px", cursor: "pointer" }}>取消</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
