import { useState, useEffect, useRef } from "react";
import type { Theme } from "../theme";
import { AMBER, AMBER_TEXT } from "./CardBadge";

const IconBolt = ({ size = 12 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>
);

/**
 * 计费探针按钮 —— 唯一一个点下去会花真钱（周额度）的控件。
 *
 * 与它旁边所有按钮的区别必须在**点击处**就看得见：其余按钮要么零消耗（`刷新全池` 带「免费」角标、
 * `检查 token`），要么只动本地状态。所以这里做两件事，且两个界面共用这一份实现，防止哪天只改了一边：
 *
 *  1. **两段确认**。单击只是亮出「确认?」，再点一次才发请求。沿用本项目既有的就地确认范式
 *     （卡片删除、设置页退出），不弹系统对话框——WKWebView 里 `confirm()` 不可用（历史坑）。
 *  2. **琥珀色 + 闪电 + 「计费」角标**。语义色在本项目里已被占用（绿=活/琥珀=低/红=死），琥珀在
 *     这里表达的是「要花钱、慢点」，与额度低的语义同源：都是「停一下再动」。
 *
 * 5 秒没有第二次点击就自动退回，避免一个亮着的「确认?」被下一次无意点击引爆。
 */
export default function ProbeButton({ t, label, hint, onConfirm, loading, loadingText, variant = "toolbar" }: {
  t: Theme;
  label: string;
  hint: string;
  onConfirm: () => void;
  loading?: boolean;
  loadingText?: string;
  variant?: "toolbar" | "menubar" | "inline";
}) {
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!armed) return;
    timer.current = setTimeout(() => setArmed(false), 5000);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [armed]);
  useEffect(() => { if (loading) setArmed(false); }, [loading]);

  // 琥珀是深浅通用的语义色(设计稿「状态语义色」),但 AMBER_TEXT(#f2b45c)是给深色底调的浅琥珀,
  // 铺在浅色主题的白底上对比度不足。软底态下按主题选字色;实心(armed)态两个主题都用深色字。
  const softText = t.isDark ? AMBER_TEXT : AMBER;

  const click = () => {
    if (loading) return;
    if (!armed) { setArmed(true); return; }
    setArmed(false);
    onConfirm();
  };

  const common = {
    cursor: loading ? "default" : "pointer",
    userSelect: "none" as const,
    display: "inline-flex" as const,
    // ★ 同 GhostButton:按钮**永不断字**。「探针 全池」被劈成「探针 全 / 池」是窄窗实测缺陷
    //   (用户 2026-08-24 截图)。这个按钮尤其不能挤 —— 它是全 app 唯一花钱的控件,
    //   琥珀 + ⚡ + 「计费」角标那一整套警示语言,靠的就是它一眼可辨的完整外形。
    whiteSpace: "nowrap" as const, flexShrink: 0,
    alignItems: "center" as const,
    gap: 6,
    opacity: loading ? 0.6 : 1,
    transition: "background .2s, border-color .2s, color .2s",
  };

  if (variant === "menubar") {
    return (
      <span title={hint} onClick={click} className="mb-action-btn"
        style={{ ...common, justifyContent: "center", flex: 1, padding: "13px 0", fontSize: 12.5, fontWeight: 600,
          color: armed ? "#1c1104" : softText, background: armed ? AMBER : "rgba(224,144,28,.08)" }}>
        {loading ? <><span className="mb-spinner" />{loadingText}</>
          : <><IconBolt size={13} />{armed ? "确认? 会花额度" : label}
              {!armed && <span className="mb-action-badge" style={{ color: "#1c1104", background: AMBER }}>计费</span>}</>}
      </span>
    );
  }

  const small = variant === "inline";
  return (
    <span title={hint} onClick={click}
      style={{ ...common, padding: small ? "5px 10px" : "7px 11px", borderRadius: small ? 6 : 8,
        fontSize: small ? 11 : 11, fontWeight: armed ? 700 : 400,
        border: `1px solid ${armed ? AMBER : "rgba(224,144,28,.45)"}`,
        color: armed ? "#1c1104" : softText,
        background: armed ? AMBER : "rgba(224,144,28,.10)" }}>
      {loading ? <>{loadingText}</>
        : <><IconBolt size={small ? 11 : 12} />{armed ? "确认?" : label}
            {!armed && !small && <span style={{ fontSize: 8.5, fontWeight: 700, color: "#1c1104", background: AMBER, padding: "1px 5px", borderRadius: 4 }}>计费</span>}</>}
    </span>
  );
}
