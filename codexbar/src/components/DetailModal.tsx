import type { Theme } from "../theme";
import { maskId } from "../helpers";

export interface AccountDetail {
  account_id?: string; email?: string; label?: string; plan?: string; sub_until?: string;
  last_refresh?: string; auth_dead?: boolean; file?: string;
  access_token_tail?: string; access_token_len?: number; access_exp?: number; access_iat?: number;
  refresh_token_tail?: string; refresh_token_len?: number; id_token_len?: number;
  quota_source?: string; quota_captured_at?: number;
}

export default function DetailModal({ detail, privacy, t, onClose }: { detail: AccountDetail; /** 打码:遮蔽 account_id / email / token 尾巴 —— 截图时它们和邮箱一样能认人 */ privacy: boolean; t: Theme; onClose: () => void }) {
  const fmtTs = (ts?: number) => ts ? new Date(ts * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Singapore" }) : "—";
  const rows: [string, string, string?][] = [
    ["account_id", maskId(detail.account_id, privacy, 4) || (detail.account_id ?? "—")],
    ["email", maskId(detail.email, privacy) || (detail.email ?? "—")],
    ["文件", `auth/${detail.file}`],
    ["access_token", `…${privacy ? "••••••••" : detail.access_token_tail}  (${detail.access_token_len} chars)`],
    ["access 签发", fmtTs(detail.access_iat)],
    ["access 过期", fmtTs(detail.access_exp), detail.access_exp && detail.access_exp < Date.now()/1000 ? "#E0524D" : t.accent],
    ["refresh_token", `…${privacy ? "••••••••" : detail.refresh_token_tail}  (${detail.refresh_token_len} chars)`],
    ["last_refresh", detail.last_refresh?.slice(0, 19) ?? "—"],
    ["plan", detail.plan || "—"],
    ["订阅至", detail.sub_until?.slice(0, 10) ?? "—"],
    ["quota 来源", String(detail.quota_source ?? "—")],
    ["快照时间", fmtTs(detail.quota_captured_at)],
  ];
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, backdropFilter: "blur(4px)" }}>
      <div onClick={e => e.stopPropagation()} style={{ background: t.cardBg, border: `1px solid ${t.accent}`, borderRadius: 14, padding: "20px 24px", width: 460, maxHeight: "80vh", overflow: "auto", boxShadow: "0 20px 60px rgba(0,0,0,.5)", userSelect: "text" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>{detail.label} · 账号详情</span>
          <span onClick={onClose} style={{ fontSize: 18, color: t.muted, cursor: "pointer", padding: "0 4px" }}>✕</span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, fontFamily: "'JetBrains Mono'" }}>
          <tbody>
            {rows.map(([key, val, color]) => (
              <tr key={key} style={{ borderBottom: `1px solid ${t.divider}` }}>
                <td style={{ padding: "6px 8px 6px 0", color: t.muted, whiteSpace: "nowrap", verticalAlign: "top", width: 100 }}>{key}</td>
                <td style={{ padding: "6px 0", color: color ?? t.text, wordBreak: "break-all", cursor: "text" }}>{val}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 12, fontSize: 9.5, color: t.faint, textAlign: "center" }}>点击文字可选中复制 · 完整 token 不显示(仅指纹)</div>
      </div>
    </div>
  );
}
