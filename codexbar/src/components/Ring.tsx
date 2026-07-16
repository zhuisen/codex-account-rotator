import { clamp, ringDash } from "../helpers";

interface RingProps {
  pct: number;
  r: number;
  sw: number;
  color: string;
  track: string;
  size: number;
  glow?: string;
  children?: React.ReactNode;
}

export default function Ring({ pct, r, sw, color, track, size, glow, children }: RingProps) {
  const cx = size / 2;
  return (
    <div className={glow ? "ring-glow" : undefined} style={{ position: "relative", width: size, height: size, flexShrink: 0, "--glow": glow } as React.CSSProperties}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={cx} cy={cx} r={r} fill="none" stroke={track} strokeWidth={sw} />
        <circle cx={cx} cy={cx} r={r} fill="none"
          transform={`rotate(-90 ${cx} ${cx})`}
          stroke={color} strokeWidth={sw} strokeLinecap="round"
          strokeDasharray={ringDash(clamp(pct), r)}
          style={{ transition: "stroke-dasharray .6s cubic-bezier(.4,0,.2,1), stroke .35s ease" }}
        />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", lineHeight: 1, gap: 1 }}>
        {children}
      </div>
    </div>
  );
}
