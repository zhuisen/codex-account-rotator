import { useState } from "react";
import type { Theme } from "../theme";

interface GhostButtonProps {
  t: Theme;
  onClick: () => void | Promise<void>;
  children: React.ReactNode;
  accent?: boolean;
  disabled?: boolean;
  loading?: boolean;
  loadingText?: string;
}

function Spinner({ size = 12 }: { size?: number }) {
  return <span style={{
    width: size, height: size, border: "2px solid currentColor", borderTopColor: "transparent",
    borderRadius: "50%", animation: "cbSpin .65s linear infinite", display: "inline-block", flexShrink: 0,
  }} />;
}

export default function GhostButton({ t, onClick, children, accent, disabled, loading, loadingText }: GhostButtonProps) {
  const [hover, setHover] = useState(false);
  const isDisabled = disabled || loading;
  return (
    <span
      onClick={isDisabled ? undefined : onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 11px",
        // ★ 按钮**永不断字**。缺这两条时 flex 会在空间不够时压缩按钮宽度,文字只能在按钮内部
        //   折行 ——「刷新全池」变成「刷新全 / 池」,「检查 token」变成「检查 / token」。
        //   窄窗实测(用户 2026-08-24 截图)。断字是 bug,不是排版取舍:按钮该整体换行,不该被劈开。
        whiteSpace: "nowrap", flexShrink: 0,
        border: `1px solid ${accent ? t.accentBorder : (hover && !isDisabled ? t.accentBorder : t.ghostBorder)}`,
        borderRadius: 8, fontSize: 11,
        color: accent ? t.accentTextSoft : t.ghostText,
        background: accent ? t.accentSoft : t.ghostBg,
        cursor: isDisabled ? "default" : "pointer", userSelect: "none",
        opacity: isDisabled ? 0.6 : 1,
        filter: hover && accent && !isDisabled ? "brightness(1.12)" : undefined,
        transition: "border-color .2s, filter .15s, opacity .2s",
      }}
    >
      {loading ? <><Spinner />{loadingText || "处理中…"}</> : children}
    </span>
  );
}
