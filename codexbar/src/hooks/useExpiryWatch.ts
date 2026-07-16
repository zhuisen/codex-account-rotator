import { useEffect, useRef } from "react";
import type { Account, TokenInfo } from "../helpers";
import { getSettings } from "../pages/SettingsPage";
import { notify } from "./useNotify";

export function useExpiryWatch(accounts: Account[], tokens: Record<string, TokenInfo>): void {
  const notifiedRef = useRef<Set<string>>(new Set());
  const accountsRef = useRef(accounts);
  const tokensRef = useRef(tokens);
  accountsRef.current = accounts;
  tokensRef.current = tokens;

  useEffect(() => {
    const check = () => {
      const settings = getSettings();
      const n = Date.now() / 1000;
      for (const a of accountsRef.current) {
        const key = `${a.aid}-${a.exp}`;
        if (notifiedRef.current.has(key)) continue;
        if (a.exp && a.exp !== "—") {
          const subTs = new Date(a.exp).getTime() / 1000;
          const daysLeft = (subTs - n) / 86400;
          if (daysLeft <= settings.subExpiryWarnDays && daysLeft > 0) {
            notify("订阅即将到期", `${a.node} 订阅还剩 ${Math.ceil(daysLeft)} 天 (${a.exp})`);
            notifiedRef.current.add(key);
          } else if (daysLeft <= 0) {
            notify("订阅已到期", `${a.node} 订阅已到期 — 续费否则无 codex 额度`);
            notifiedRef.current.add(key);
          }
        }
        const tokKey = `tok-${a.aid}`;
        if (!notifiedRef.current.has(tokKey) && tokensRef.current[a.aid]?.exp) {
          const tokH = (tokensRef.current[a.aid].exp! - n) / 3600;
          if (tokH <= settings.tokenExpiryWarnHours && tokH > 0) {
            notify("Token 即将过期", `${a.node} access token 还剩 ${Math.round(tokH)}h`);
            notifiedRef.current.add(tokKey);
          }
        }
      }
    };
    check();
    const id = setInterval(check, 60_000);
    return () => clearInterval(id);
  }, []);
}
