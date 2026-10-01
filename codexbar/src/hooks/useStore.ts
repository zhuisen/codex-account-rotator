import { useEffect, useState, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { type AppState, type TokenInfo, type Account, type Slot, slotToAccount, recommended, poolRefreshedAt, poolFreshness, CARD_WARN_DAYS } from "../helpers";
import { useBusyMirror } from "./useBusyMirror";

export interface StoreCounts {
  total: number; live: number; cool: number; dead: number;
}

export function useStore() {
  const [state, setState] = useState<AppState>({});
  const [tokens, setTokens] = useState<Record<string, TokenInfo>>({});
  const [cooldowns, setCooldowns] = useState<Record<string, number>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const { remote: remoteAction, announce } = useBusyMirror();
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

  const run = useCallback(async (actionId: string, args: string[], msg: string, opts?: { resultToast?: boolean }) => {
    setLoadingAction(actionId);
    // ★ 告诉另一个 webview「我开始跑了」。此前两边只在**结束**时靠 `state-changed` 同步,
    //   于是在菜单栏点刷新、再打开主界面,主界面整个执行期间看起来什么都没发生
    //   (用户 2026-09-06 报的就是这个)。
    announce(actionId);
    showToast(`${msg}…`);
    // ★★ **返回成功与否。** 原来无论成败都只落一个 toast、返回 `undefined` ——
    //    于是调用方**无法区分**"CLI 干成了"和"CLI 拒绝了"。
    //    自动切号就栽在这里：它无条件弹「已切到 X」，而 `cmd_switch` 其实拒绝了
    //    （目标号被用户暂停）。用户看到的是一句关于事实的假陈述。
    let ok = false;
    try {
      const out = await invoke<string>("run_rotate", { args });
      await refresh();
      // ★ 花掉不可逆东西的动作要把**结果原话**给用户（用了哪张、重置了几个窗口、还剩几张），
      //   不是一句泛泛的「✓ 用重置卡」。其余动作行为不变。
      const last = opts?.resultToast ? String(out ?? "").trim().split("\n").pop() : "";
      showToast(last ? last.slice(0, 120) : `✓ ${msg}`);
      ok = true;
    } catch (e: unknown) {
      const errMsg = String(e).slice(0, 80);
      showToast(`✗ 失败: ${errMsg}`);
    } finally {
      // ★★ **必须在 `finally`** —— 上面 `catch` 之后还有 `showToast`,任何一处再抛,
      //    不在 finally 里的熄灯就漏了,对方会一直转圈。
      setLoadingAction(null);
      announce(null);
    }
    return ok;
  }, [refresh, showToast, announce]);

  const slots: Record<string, Slot> = state.slots ?? {};
  const accounts: Account[] = Object.entries(slots)
    .map(([aid, sl]) => {
      const a = slotToAccount(aid, sl, tokens, state.pinned);
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
  /**
   * ★★ **代理此刻在用的号** —— 菜单栏跟着它走（用户 2026-09-23：「现在是代理轮换的状态，
   *   我希望菜单栏显示的账号信息跟着代理轮换走」）。
   *   `currentNode`（= `active`）保留给**切号/死号监视/自动切号**这些只关心 auth.json 的路径；
   *   显示「谁在用」一律用这个。取不到 `last_aid`（新装机、代理还没服务过任何请求）才退回 `active`。
   */
  const inUseNode = (state.last_aid && state.slots?.[state.last_aid]) ? state.last_aid : state.active;
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

  return { state, tokens, accounts, hero, currentNode, inUseNode, slots, counts, lastRefreshAt, freshness, cardAlert,
           // ★ 本地优先:自己发起的动作永远比镜像来的可信(镜像可能已经过期,见 `useBusyMirror`)。
           //   两个 surface 因此显示同一个动作 id,按钮文案/转圈逻辑一行都不用改。
           // ★ 过滤掉流量扫描:它走 `useTraffic` 的 `busy`,不是账号池动作。
           //   两个 hook 共用同一条广播通道,不筛就会把 `traffic-scan` 塞进 `loadingAction`——
           //   眼下没有按钮匹配它所以看不见,但那是"碰巧无害",下一个按钮 id 撞上就变成乱转圈。
           loadingAction: loadingAction ?? (remoteAction === "traffic-scan" ? null : remoteAction),
           /** ★ 这个动作是**别的窗口**发起的。UI 可据此弱化措辞(是"正在刷新"不是"你点的那个")。 */
           remoteAction, toast, refresh, run, showToast };
}
