import { useEffect, useRef } from "react";
import type { Account } from "../helpers";
import { notify } from "./useNotify";

/**
 * Proactively alert when an account's token dies — you should never have to open the app and squint at
 * a stale number to discover a node is gone.
 *
 * Why this hook exists: useExpiryWatch only covers subscription expiry and local JWT expiry, and NEITHER
 * can see a server-side revocation. The account that most needs an alert is exactly the one with zero
 * coverage — plus7 was revoked while its local JWT still had 201h left, so no existing notification
 * could ever fire for it; it silently sat behind a stale "0% remaining" that read as quota exhaustion.
 * codex-rotate now marks auth_dead from the usage API's 401, so this hook turns that into an alert.
 *
 * Fires once per DEATH EVENT, not per launch: the notified set is persisted, and an aid is dropped from
 * it as soon as the account comes back — so a later re-death alerts again, while restarts stay quiet.
 */
const KEY = "codexbar_dead_notified";

function loadNotified(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set<string>(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set<string>();
  }
}

function saveNotified(s: Set<string>): void {
  try { localStorage.setItem(KEY, JSON.stringify([...s])); } catch { /* ignore */ }
}

/** Pool-level sentinel keys share the persisted set but are NOT account ids. */
const SENTINEL = "__";

export function useDeadWatch(accounts: Account[], currentNode: string | undefined): void {
  const accountsRef = useRef(accounts);
  const currentRef = useRef(currentNode);
  // Seen-dead-last-tick, in memory: a death must persist across two ticks before we alert. A single
  // transient 401 (observed in the wild) marks an account dead for one 180s cycle and then self-heals;
  // without this an alert would fire — and re-fire on every future blip, since recovery clears the
  // notified entry. Not persisted: after a restart the notified set already suppresses old deaths.
  const pendingRef = useRef<Set<string>>(new Set());
  accountsRef.current = accounts;
  currentRef.current = currentNode;

  useEffect(() => {
    const check = () => {
      const accts = accountsRef.current;
      if (accts.length === 0) return;           // state not loaded yet — don't alert on an empty pool
      const cur = currentRef.current;
      const notified = loadNotified();
      let changed = false;

      const dead = accts.filter(a => a.status === "dead");
      const alive = accts.filter(a => a.status !== "dead");
      const deadIds = new Set(dead.map(a => a.aid));

      // Revived accounts become eligible to alert again on a future death. Sentinels are skipped —
      // they are not account ids, so they can never be in deadIds; deleting them here would re-arm the
      // pool alerts every single tick and spam a notification every 60s (verified by simulation).
      // Their lifecycle is owned by the two else-if branches below.
      for (const aid of [...notified]) {
        if (aid.startsWith(SENTINEL)) continue;
        if (!deadIds.has(aid)) { notified.delete(aid); changed = true; }
      }

      const pending = pendingRef.current;
      for (const a of dead) {
        if (notified.has(a.aid)) continue;
        if (!pending.has(a.aid)) { pending.add(a.aid); continue; }  // first sighting — wait one tick
        notified.add(a.aid); changed = true;
        const isCurrent = a.aid === cur;
        notify(
          isCurrent ? "⚠️ 当前号已失效" : "账号失效",
          `${a.node} (${a.email}) token 已被服务端作废` +
          (isCurrent ? " — 当前号不可用,请切号或 codex-rotate login 重登" : " — codex-rotate login 重登即可恢复"),
        );
      }
      for (const aid of [...pending]) if (!deadIds.has(aid)) pending.delete(aid);

      // Pool-level alerts. Keyed in the same persisted set so they also fire once per occurrence.
      if (alive.length === 0 && !notified.has("__pool_empty")) {
        notified.add("__pool_empty"); changed = true;
        notify("🚨 全部账号已失效", `${accts.length} 个号全部不可用 — 需要 codex login 重登`);
      } else if (alive.length > 0 && notified.has("__pool_empty")) {
        notified.delete("__pool_empty"); changed = true;
      }

      if (alive.length === 1 && accts.length > 1 && !notified.has("__pool_last")) {
        notified.add("__pool_last"); changed = true;
        notify("⚠️ 仅剩 1 个可用账号", `只有 ${alive[0].node} 还能用 — 建议尽快重登其他号`);
      } else if (alive.length !== 1 && notified.has("__pool_last")) {
        notified.delete("__pool_last"); changed = true;
      }

      if (changed) saveNotified(notified);
    };

    check();
    const id = setInterval(check, 60_000);
    return () => clearInterval(id);
  }, []);
}
