import { useEffect, useRef } from "react";
import type { Account } from "../helpers";
import { getSettings } from "../pages/SettingsPage";
import { notify } from "./useNotify";

const MIN_TARGET = 30;
const MARGIN = 15;
const DEBOUNCE_SEC = 300;

export function useAutoSwitch(
  accounts: Account[],
  currentNode: string | undefined,
  run: (id: string, args: string[], msg: string) => Promise<void>,
): void {
  const accountsRef = useRef(accounts);
  const currentRef = useRef(currentNode);
  const lastSwitchRef = useRef(0);
  accountsRef.current = accounts;
  currentRef.current = currentNode;

  useEffect(() => {
    const check = () => {
      const settings = getSettings();
      if (!settings.autoSwitchEnabled) return;

      const accts = accountsRef.current;
      const cur = currentRef.current;
      const now = Date.now() / 1000;

      if (!cur || now - lastSwitchRef.current < DEBOUNCE_SEC) return;

      const active = accts.find(a => a.aid === cur);
      if (!active || active.tightest < 0) return;

      if (active.tightest >= settings.autoSwitchThreshold) return;

      let best: Account | null = null;
      for (const a of accts) {
        if (a.aid === cur || a.status === "dead" || a.status === "cool" || a.tightest < 0) continue;
        if (a.tightest >= MIN_TARGET && a.tightest > active.tightest + MARGIN) {
          if (!best || a.tightest > best.tightest) best = a;
        }
      }

      if (best) {
        lastSwitchRef.current = now;
        run("auto-switch", ["switch", best.node], `自动切号: ${active.node}(${active.tightest}%) → ${best.node}(${best.tightest}%)`);
        notify("自动切号", `${active.node} 额度低(${active.tightest}%)，已切到 ${best.node}(${best.tightest}%)`);
      }
    };

    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, [run]);
}
