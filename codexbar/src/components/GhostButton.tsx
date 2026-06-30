import { useState } from "react";
import type { Theme } from "../theme";

interface GhostButtonProps {
  t: Theme;
  onClick: () => void;
  children: React.ReactNode;
  accent?: boolean;
  disabled?: boolean;
}

export default function GhostButton({ t, onClick, children, accent, disabled }: GhostButtonProps) {
  const [hover, setHover] = useState(false);
  return (
    <span
      onClick={disabled ? undefined : onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 11px",
        border: `1px solid ${accent ? t.accentBorder : (hover && !disabled ? t.accentBorder : t.ghostBorder)}`,
        borderRadius: 8, fontSize: 11,
        color: accent ? t.accentTextSoft : t.ghostText,
        background: accent ? t.accentSoft : t.ghostBg,
        cursor: disabled ? "default" : "pointer", userSelect: "none",
        opacity: disabled ? 0.4 : 1,
        filter: hover && accent && !disabled ? "brightness(1.12)" : undefined,
        transition: "border-color .2s, filter .15s, opacity .2s",
      }}
    >
      {children}
    </span>
  );
}
