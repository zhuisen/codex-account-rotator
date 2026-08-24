import { useState, useEffect } from "react";
import { STATUS_COLORS, STATUS_TEXT, type Theme } from "../theme";
import { type Account, fmtCd, quotaColor, maskId } from "../helpers";
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
      fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
      fontVariantNumeric: "tabular-nums",
      color: best ? t.accent : far ? "#E0901C" : t.text2,
      background: best ? t.accentSoft : far ? "rgba(224,144,28,.12)" : t.ghostBg,
    }}>{best ? "最优" : `${delta}%`}</span>
  );
}

export default function AccountCard({ a, isCurrent, isBest, isSelected, shortcut, bestPct, probing, privacy, t, onSelect, onSwitch, onShowDetail, onRemove, onProbe, onRename }: {
  a: Account; isCurrent: boolean; isBest: boolean; isSelected: boolean; shortcut?: number;
  /** Highest remaining quota in the pool — the baseline the delta chip compares against. */
  bestPct: number; /** 该号正在探测中 */ probing: boolean; /** 打码模式 */ privacy: boolean; t: Theme;
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
  const pct = a.windows[0]?.pct ?? -1;
  const known = pct >= 0 && !isDead;
  // Quota-driven colour for live/low (handoff rule), status colour for cool/dead where the state
  // matters more than the number.
  const qc = isDead || isCool ? sc : quotaColor(pct);
  const glow = known && pct <= 20 ? (pct <= 10 ? "#E0524D" : "#E0901C") : undefined;
  const expiring = isCardExpiring(a);

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

      {shortcut && <span style={{ position: "absolute", top: 6, left: 10, fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>⌘{shortcut}</span>}

      <div style={{ display: "flex", gap: 11, alignItems: "center" }}>
        <Ring pct={known ? pct : 0} r={21} sw={5} color={qc} track={t.ringTrack} size={52} glow={glow}>
          <span style={{ fontSize: 13, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{known ? pct : "—"}</span>
        </Ring>

        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
          {/* ★ 三列九宫格下这一行**零余量**:`plus4 活 USE 最优` 实测自然宽 126、可用 117。
              零余量意味着任何扰动都会破 —— 分数缩放下的字形量化就够了(每个内联元素舍入
              半像素,十几个累积出 9px)。所以指定**唯一让位者**:名字截省略号,徽章一个不压。
              名字截一点还认得出,徽章少一半就读不出是 USE 还是 PRO。 */}
          <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
            {editing === null ? (
              <span style={{ fontSize: 13.5, fontWeight: 700, color: t.text, minWidth: 0,
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
                style={{ fontSize: 13.5, fontWeight: 700, color: t.text, width: 96,
                         background: "transparent", border: `1px solid ${t.accentBorder}`,
                         borderRadius: 5, padding: "1px 5px", outline: "none",
                         fontFamily: "'JetBrains Mono'" }} />
            )}
            <PlanBadge plan={a.plan} t={t} />
            <span style={{ fontSize: 10, fontWeight: 600, color: sc }}>{STATUS_TEXT[a.status]}</span>
            {isBest && <span style={{ fontSize: 8, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 5px", borderRadius: 4, flexShrink: 0 }}>USE</span>}
            {isCurrent
              ? <span style={{ marginLeft: "auto", flexShrink: 0, fontSize: 8.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, padding: "1px 7px", borderRadius: 999 }}>当前</span>
              : known && bestPct >= 0 && <DeltaChip delta={pct - bestPct} t={t} />}
          </div>

          <div style={{ fontSize: 10.5, color: t.text2, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{maskId(a.email, privacy)}</div>

          {known && a.windows.map(w => (
            <div key={w.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{w.label}</span>
              <div style={{ flex: 1, height: 4, borderRadius: 2, background: t.barTrack, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${w.pct}%`, background: quotaColor(w.pct), borderRadius: 2, transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
              </div>
              <span style={{ fontSize: 10, fontWeight: 600, color: w.pct < 50 ? "#E0901C" : t.text2, fontFamily: "'JetBrains Mono'", fontVariantNumeric: "tabular-nums" }}>{w.pct}%</span>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>↻{w.reset}</span>
            </div>
          ))}
          {!isDead && a.windows.length === 0 && <span style={{ fontSize: 9, color: t.muted }}>未探测 · 刷新一次</span>}
          {isDead && <span style={{ fontSize: 9.5, color: "#E0524D", fontWeight: 600 }}>token 失效 · 需重登</span>}
          {isCool && <span style={{ fontSize: 9, color: "#2BA0C0", fontWeight: 600 }}>❄ 冷却 {fmtCd(a.cooldownSec)}</span>}

          {/* wrap + nowrap date: a long amber badge must push itself onto a second line rather than
              break "到期 2026-08-10" mid-date (observed with 重置卡 ×2 · 1张剩1天 on a 3-col grid). */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6, marginTop: 5, paddingTop: 7, borderTop: `1px solid ${t.divider}` }}>
            <span title={a.expStale ? "OpenAI 上次复核订阅早于这个日期,所以「已过期」是拿陈旧快照下的结论 —— 续费不在它视野里。刷新 token 也拉不到新状态,要等 OpenAI 自己复核。" : undefined} style={{ fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap" }}>到期 {a.exp}{a.expStale && <span style={{ color: "#E0901C" }}>*</span>}</span>
            <span style={{ marginLeft: "auto" }}><CardBadge a={a} t={t} /></span>
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
