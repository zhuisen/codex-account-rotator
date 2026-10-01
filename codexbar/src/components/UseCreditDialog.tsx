import { useEffect, useRef, useState } from "react";
import type { Theme } from "../theme";
import { AMBER, AMBER_TEXT } from "./CardBadge";
import type { Account } from "../helpers";

/**
 * 「使用重置卡」的确认弹窗。
 *
 * 为什么是弹窗而不是就地「再点一次」：用户 2026-10-01 实测**很容易误触**（角标就在卡片页脚里，
 * 旁边全是可点的东西）。用卡**不可逆**，所以要一个必须读完、必须点另一个位置才能通过的确认。
 * 不用系统 `confirm()`：WKWebView 里它不可用（本仓的老坑，见 ProbeButton 的注释），所以自绘。
 *
 * 防误触的几处细节，都是有意的：
 *  · **默认焦点在「取消」**，Enter 不会确认 —— 确认只能用鼠标点（连按两下回车不会花掉一张卡）；
 *  · 点遮罩 / Esc / ✕ 都是取消；
 *  · 「确认」按钮在右、琥珀色，「取消」在左，两者**间隔**开，不挨着；
 *  · 正文**列出这个号的每一张卡**（到期各不相同），默认选最近到期的那张，可以改选；
 *    确认时把**选中的那张的 id** 传给 CLI（`--card`）—— 用户看到的就是将被用掉的，不靠两边各自再算一遍「最近」；
 *  · 写明用后还剩几张、不可逆。
 */
export default function UseCreditDialog({ a, t, onCancel, onConfirm }: {
  a: Account; t: Theme; onCancel: () => void; onConfirm: (cardId: string) => void;
}) {
  const cancelRef = useRef<HTMLSpanElement>(null);
  // 默认选**最近到期**的那张（`cardList` 已按到期升序）。
  const [sel, setSel] = useState<string>(a.cardList[0]?.id ?? "");
  const selRef = useRef(sel);
  selRef.current = sel;
  useEffect(() => {
    cancelRef.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onCancel(); return; }
      // 上下键换选中的卡；**Enter 不确认**（连按回车不能花掉一张卡）。
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const ids = a.cardList.map((c) => c.id);
        const k = ids.indexOf(selRef.current);
        const n = e.key === "ArrowDown" ? Math.min(ids.length - 1, k + 1) : Math.max(0, k - 1);
        if (ids[n]) setSel(ids[n]);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onCancel, a.cardList]);

  const chosen = a.cardList.find((c) => c.id === sel) ?? a.cardList[0];
  const unknown = Math.max(0, a.cards - a.cardList.length);
  const left = (d: number) => (d >= 1 ? `还剩 ${Math.floor(d)} 天` : `还剩 ${Math.max(1, Math.floor(d * 24))} 小时`);
  return (
    <div data-use-credit-dialog onClick={onCancel}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 110, backdropFilter: "blur(4px)" }}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
           style={{ background: t.cardBg, border: `1px solid ${AMBER}`, borderRadius: 14, padding: "20px 24px", width: 420,
                    boxShadow: "0 20px 60px rgba(0,0,0,.5)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>使用重置卡 · {a.node}</span>
          <span onClick={onCancel} style={{ fontSize: 18, color: t.muted, cursor: "pointer", padding: "0 4px" }}>✕</span>
        </div>
        <div style={{ fontSize: 12.5, lineHeight: 1.7, color: t.text }}>
          选一张要用掉的卡（默认<b style={{ color: t.isDark ? AMBER_TEXT : AMBER }}> 最近到期 </b>的那张）：
          <div role="radiogroup" data-use-credit-list style={{ margin: "6px 0 8px", display: "flex", flexDirection: "column", gap: 6 }}>
            {a.cardList.map((c, i) => {
              const on = c.id === sel;
              return (
                <div key={c.id} role="radio" aria-checked={on} data-use-credit-row={c.id} data-selected={on ? "" : undefined}
                     onClick={() => setSel(c.id)}
                     style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 8, cursor: "pointer",
                              fontFamily: "'JetBrains Mono'", fontSize: 12,
                              background: on ? "rgba(224,144,28,.12)" : t.ghostBg,
                              border: `1px solid ${on ? AMBER : t.cardBorder}` }}>
                  <span style={{ width: 12, height: 12, borderRadius: "50%", flexShrink: 0,
                                 border: `2px solid ${on ? AMBER : t.muted}`, background: on ? AMBER : "transparent",
                                 boxSizing: "border-box" }} />
                  <span style={{ fontWeight: on ? 700 : 400 }}>{c.expiresAt.slice(0, 10)} 到期</span>
                  <span style={{ color: t.text2 }}>{left(c.days)}</span>
                  {i === 0 && <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 700, color: "#1c1104", background: AMBER, padding: "1px 6px", borderRadius: 4 }}>最近</span>}
                </div>
              );
            })}
            {unknown > 0 && (
              <div data-use-credit-unknown style={{ fontSize: 11, color: t.muted, padding: "2px 2px" }}>
                另有 {unknown} 张还没取到到期日，暂不能选（点「刷新全池」后再看）
              </div>
            )}
          </div>
          <div data-use-credit-target style={{ color: t.text2 }}>
            共 {a.cards} 张，用掉所选的这一张后剩 {Math.max(0, a.cards - 1)} 张
          </div>
          <span style={{ color: "#E0524D", fontWeight: 600 }}>不可逆：</span>用掉就没了，不能撤回。
          {a.cardsUsable > 0 ? null : (
            <div style={{ marginTop: 6, fontSize: 11, color: t.muted }}>
              服务端此刻报告「没有需要重置的窗口」；额度没见底也能用（实测），结果以弹出的提示为准。
            </div>
          )}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18 }}>
          <span ref={cancelRef} tabIndex={0} data-use-credit-cancel onClick={onCancel}
                style={{ fontSize: 12.5, fontWeight: 600, padding: "7px 22px", borderRadius: 8, cursor: "pointer",
                         border: `1px solid ${t.ghostBorder}`, color: t.text, outline: "none" }}>取消</span>
          <span data-use-credit-confirm onClick={() => chosen && onConfirm(chosen.id)}
                style={{ fontSize: 12.5, fontWeight: 700, padding: "7px 22px", borderRadius: 8, cursor: "pointer",
                         border: `1px solid ${AMBER}`, color: "#1c1104", background: AMBER }}>
            确认用卡{chosen ? ` ${chosen.expiresAt.slice(5, 10)}` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}
