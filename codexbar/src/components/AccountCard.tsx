import { useState, useEffect } from "react";
import { STATUS_COLORS, STATUS_TEXT, type Theme } from "../theme";
import { type Account, fmtCd } from "../helpers";
import Ring from "./Ring";

export default function AccountCard({ a, isCurrent, isBest, isSelected, shortcut, t, onSelect, onSwitch, onShowDetail, onRemove }: {
  a: Account; isCurrent: boolean; isBest: boolean; isSelected: boolean; shortcut?: number; t: Theme;
  onSelect: () => void; onSwitch: () => void; onShowDetail: (aid: string) => void; onRemove: (label: string) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  useEffect(() => { if (!isSelected) setConfirmDelete(false); }, [isSelected]);
  const sc = STATUS_COLORS[a.status] ?? STATUS_COLORS.live;
  const isDead = a.status === "dead";
  const isCool = a.status === "cool";
  const mainPct = a.windows[0]?.pct ?? -1;
  const glowColor = mainPct >= 0 && mainPct <= 10 && !isDead ? "#E0524D" : mainPct >= 0 && mainPct <= 20 && !isDead ? "#E0901C" : undefined;

  return (
    <div
      onClick={onSelect}
      style={{
        background: `linear-gradient(135deg, ${isDead ? "rgba(224,82,77,.06)" : `${sc}0a`} 0%, transparent 60%)`,
        border: isSelected ? `1px solid ${t.accent}` : `1px solid ${t.cardBorder}`,
        borderLeftWidth: 2, borderLeftColor: isSelected ? t.accent : sc,
        borderRadius: 12, padding: 12, display: "flex", flexDirection: "column", gap: 10,
        overflow: "hidden", position: "relative",
        cursor: "pointer", userSelect: "none",
        opacity: isDead ? 0.55 : 1,
        transition: "background .2s ease, border-color .2s ease",
      }}>

      {shortcut && <span style={{ position: "absolute", top: 4, left: 8, fontSize: 9, color: t.faint, fontFamily: "'JetBrains Mono'" }}>⌘{shortcut}</span>}

      <div style={{ display: "flex", gap: 11, alignItems: "center" }}>
        <Ring pct={mainPct < 0 || isDead ? 0 : mainPct} r={21} sw={5} color={sc} track={t.ringTrack} size={52} glow={glowColor}>
          <span style={{ fontSize: 13, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{isDead || mainPct < 0 ? "—" : mainPct}</span>
        </Ring>

        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 3, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{a.node}</span>
            <span style={{ fontSize: 9.5, fontWeight: 600, color: sc }}>{STATUS_TEXT[a.status]}</span>
            {isBest && <span style={{ fontSize: 8, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 5px", borderRadius: 4, flexShrink: 0 }}>USE</span>}
            {isCurrent && <span style={{ marginLeft: "auto", fontSize: 8.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, padding: "1px 6px", borderRadius: 999, flexShrink: 0 }}>当前</span>}
          </div>
          <div style={{ fontSize: 10.5, color: t.email, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{a.email}</div>

          {!isDead && a.windows.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 3 }}>
              {a.windows.map(w => {
                const barColor = w.pct <= 10 ? "#E0524D" : w.pct <= 30 ? "#E0901C" : sc;
                return (
                  <div key={w.label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <span style={{ fontSize: 8, color: w.pct <= 30 ? barColor : t.muted, fontFamily: "'JetBrains Mono'", width: 14, textAlign: "right", fontWeight: w.pct <= 30 ? 600 : 400 }}>{w.label}</span>
                    <div style={{ flex: 1, height: 4, borderRadius: 2, background: t.barTrack, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${w.pct}%`, background: barColor, borderRadius: 2, transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
                    </div>
                    <span style={{ fontSize: 9, color: w.pct <= 30 ? barColor : t.text2, fontFamily: "'JetBrains Mono'", fontWeight: w.pct <= 30 ? 700 : 600, width: 30 }}>{w.pct}%</span>
                    <span style={{ fontSize: 8, color: t.muted, fontFamily: "'JetBrains Mono'" }}>↻{w.reset}</span>
                  </div>
                );
              })}
              {isCool && <span style={{ fontSize: 9, color: "#2BA0C0", fontWeight: 600 }}>❄ 冷却 {fmtCd(a.cooldownSec)}</span>}
              <div style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>到期 {a.exp}</div>
            </div>
          )}

          {!isDead && a.windows.length === 0 && (
            <span style={{ fontSize: 9, color: t.muted, marginTop: 2 }}>未探测 · 刷新一次</span>
          )}

          {isDead && (
            <span style={{ fontSize: 9.5, color: "#E0524D", fontWeight: 600, marginTop: 2 }}>token 失效 · 已到期</span>
          )}
        </div>
      </div>

      {isSelected && (
        <div onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 6, paddingTop: 6, borderTop: `1px solid ${t.divider}` }}>
          {!isCurrent && !isDead && (
            <span onClick={onSwitch} style={{ flex: 1, textAlign: "center", fontSize: 11, fontWeight: 700, color: t.accentText, background: t.accent, padding: "5px 0", borderRadius: 6, cursor: "pointer" }}>切换到此号</span>
          )}
          {isCurrent && (
            <span style={{ flex: 1, textAlign: "center", fontSize: 11, fontWeight: 600, color: t.accent, padding: "5px 0" }}>✓ 当前使用中</span>
          )}
          <span onClick={() => onShowDetail(a.aid)} style={{ fontSize: 11, color: t.muted, padding: "5px 10px", borderRadius: 6, cursor: "pointer", border: `1px solid ${t.ghostBorder}` }}>详情</span>
          {!confirmDelete ? (
            <span onClick={() => setConfirmDelete(true)} style={{ fontSize: 11, color: "#E0524D", padding: "5px 10px", borderRadius: 6, cursor: "pointer", border: "1px solid #E0524D40" }}>删除</span>
          ) : (
            <>
              <span onClick={() => { setConfirmDelete(false); onRemove(a.node); }} style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: "#E0524D", padding: "5px 10px", borderRadius: 6, cursor: "pointer" }}>确认删除</span>
              <span onClick={() => setConfirmDelete(false)} style={{ fontSize: 11, color: t.muted, padding: "5px 10px", cursor: "pointer" }}>取消</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
