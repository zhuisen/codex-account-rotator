import { useEffect, useState, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { type AppState, type TokenInfo, type Account, type Slot, slotToAccount, recommended, poolRefreshedAt, poolFreshness, CARD_WARN_DAYS } from "../helpers";

export interface StoreCounts {
  total: number; live: number; cool: number; dead: number;
}

export function useStore() {
  const [state, setState] = useState<AppState>({});
  const [tokens, setTokens] = useState<Record<string, TokenInfo>>({});
  const [cooldowns, setCooldowns] = useState<Record<string, number>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((msg: string) => {
    if (toastRef.current) clearTimeout(toastRef.current);
    setToast(msg);
    toastRef.current = setTimeout(() => setToast(null), 2100);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [s, tk] = await Promise.all([
        invoke<AppState>("read_state"),
        invoke<Record<string, TokenInfo>>("read_auth_tokens"),
      ]);
      setState(s);
      setTokens(tk);
      const now = Date.now() / 1000;
      const cds: Record<string, number> = {};
      for (const [aid, sl] of Object.entries(s.slots ?? {})) {
        const cd = (sl.cooling_until ?? 0) - now;
        if (cd > 0) cds[aid] = Math.round(cd);
      }
      setCooldowns(cds);
    } catch {
      // read_state / read_auth_tokens failure — silently retry on next tick
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const u = listen("state-changed", () => refresh());
    return () => { u.then(f => f()); };
  }, [refresh]);

  useEffect(() => {
    const id = setInterval(() => {
      setCooldowns(prev => {
        const next = { ...prev };
        let changed = false;
        for (const aid of Object.keys(next)) {
          if (next[aid] > 0) { next[aid]--; changed = true; }
          if (next[aid] <= 0) delete next[aid];
        }
        return changed ? next : prev;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const run = useCallback(async (actionId: string, args: string[], msg: string) => {
    setLoadingAction(actionId);
    showToast(`${msg}…`);
    try {
      await invoke("run_rotate", { args });
      await refresh();
      showToast(`✓ ${msg}`);
    } catch (e) {
      const errMsg = String(e).slice(0, 80);
      showToast(`✗ 失败: ${errMsg}`);
    }
    setLoadingAction(null);
  }, [refresh, showToast]);

  const slots: Record<string, Slot> = state.slots ?? {};
  const accounts: Account[] = Object.entries(slots)
    .map(([aid, sl]) => {
      const a = slotToAccount(aid, sl, tokens);
      if (cooldowns[aid] != null) a.cooldownSec = cooldowns[aid];
      if (a.cooldownSec > 0 && a.status !== "dead") a.status = "cool";
      return a;
    })
    .sort((a, b) => {
      if (a.status === "dead" && b.status !== "dead") return 1;
      if (b.status === "dead" && a.status !== "dead") return -1;
      return b.tightest - a.tightest || a.node.localeCompare(b.node);
    });

  const currentNode = state.active;
  const hero = recommended(accounts);
  const counts: StoreCounts = {
    total: accounts.length,
    live: accounts.filter(a => a.status === "live" || a.status === "low").length,
    cool: accounts.filter(a => a.status === "cool").length,
    dead: accounts.filter(a => a.status === "dead").length,
  };

  // Relative time re-renders for free: refresh() replaces `state` every 30s, so no extra timer.
  const lastRefreshAt = poolRefreshedAt(slots);
  // ★★ `lastRefreshAt` 取的是**全池最大值**,它只能回答「最近有账号被刷新过」——
  //    **不能**读成「全池都是新的」。实测踩过:一个 token 已失效、快照陈旧 3.8 天的号,
  //    被每 300s 刷新的活号盖成「刚刚」,于是那件事在 UI 上完全看不见。
  //    覆盖度才回答「有几个是新的」。两个都下发,让消费方各取所需。
  const freshness = poolFreshness(slots);

  // Pool-wide banner subject = the single most urgent expiring card (design handoff §4).
  const cardAlert = accounts
    .filter(a => a.status !== "dead" && a.cards > 0 && a.cardDays != null && a.cardDays <= CARD_WARN_DAYS)
    .sort((x, y) => (x.cardDays ?? 0) - (y.cardDays ?? 0))[0] ?? null;

  return { state, tokens, accounts, hero, currentNode, slots, counts, lastRefreshAt, freshness, cardAlert,
           loadingAction, toast, refresh, run, showToast };
}
