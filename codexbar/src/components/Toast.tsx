import type { Theme } from "../theme";

interface ToastProps {
  msg: string;
  t: Theme;
}

export default function Toast({ msg, t }: ToastProps) {
  return (
    <div style={{
      position: "absolute", bottom: 22, left: "50%", transform: "translateX(-50%)",
      display: "flex", alignItems: "center", gap: 9, padding: "10px 16px",
      background: t.toastBg, border: `1px solid ${t.toastBorder}`, borderRadius: 10,
      boxShadow: "0 12px 30px rgba(0,0,0,.3)", fontSize: 12.5, fontWeight: 600,
      color: t.toastText, backdropFilter: "blur(8px)",
      animation: "cbToast .25s cubic-bezier(.2,.8,.2,1)", zIndex: 50,
    }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: t.accent }} />
      {msg}
    </div>
  );
}
