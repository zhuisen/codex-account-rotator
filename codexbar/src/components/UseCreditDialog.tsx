import { useEffect, useRef } from "react";
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
 *  · 正文**明说**要用掉哪一张（到期日 + 剩几天）、用完还剩几张、不可逆。
 */
export default function UseCreditDialog({ a, t, onCancel, onConfirm }: {
  a: Account; t: Theme; onCancel: () => void; onConfirm: () => void;
}) {
  const cancelRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    cancelRef.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onCancel]);

  const days = a.cardDays == null ? null : Math.max(0, Math.floor(a.cardDays));
  return (
    <div data-use-credit-dialog onClick={onCancel}
         style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center",
                  justifyContent: "center", zIndex: 110, backdropFilter: "blur(4px)" }}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
           style={{ background: t.cardBg, border: `1px solid ${AMBER}`, borderRadius: 14, padding: "20px 24px", width: 400,
                    boxShadow: "0 20px 60px rgba(0,0,0,.5)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>使用重置卡 · {a.node}</span>
          <span onClick={onCancel} style={{ fontSize: 18, color: t.muted, cursor: "pointer", padding: "0 4px" }}>✕</span>
        </div>
        <div style={{ fontSize: 12.5, lineHeight: 1.7, color: t.text }}>
          将用掉<b style={{ color: t.isDark ? AMBER_TEXT : AMBER }}> 最近到期 </b>的那一张：
          <div data-use-credit-target style={{ fontFamily: "'JetBrains Mono'", margin: "6px 0 8px", padding: "8px 10px",
                                                borderRadius: 8, background: t.ghostBg, border: `1px solid ${t.cardBorder}` }}>
            <div>{a.cardExp ?? "?"} 到期{days != null ? `（还剩 ${days} 天）` : ""}</div>
            <div style={{ color: t.text2 }}>共 {a.cards} 张，用后剩 {Math.max(0, a.cards - 1)} 张</div>
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
          <span data-use-credit-confirm onClick={onConfirm}
                style={{ fontSize: 12.5, fontWeight: 700, padding: "7px 22px", borderRadius: 8, cursor: "pointer",
                         border: `1px solid ${AMBER}`, color: "#1c1104", background: AMBER }}>确认用卡</span>
        </div>
      </div>
    </div>
  );
}
