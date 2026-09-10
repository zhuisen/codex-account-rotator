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
  /** ★ 返回**是否真的成功**。以前是 `Promise<void>`，调用方无从判断 CLI 拒绝没拒绝，
   *  于是自动切号无条件弹「已切到 X」——而目标号被暂停时 `cmd_switch` 其实拒绝了。 */
  run: (id: string, args: string[], msg: string) => Promise<boolean>,
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
        // ★★ **被用户暂停的号不许当目标**（用户 2026-09-10：「我选了禁止轮换，
        //    还是会切换到对应的号上」）。切号 = 把它写进 live auth.json，裸 `\codex`
        //    从此全走它 —— 对一个已暂停的号做这件事，等于让那个开关当场撒谎。
        //    ★ `cmd_switch` 那边确实会拒绝，所以真正切过去的事没发生；但这里不过滤，
        //      就会每隔一轮挑中它、被拒、再挑中，而用户只看到 UI 说"已切到 plus3"。
        if (!a.rotates) continue;
        if (a.tightest >= MIN_TARGET && a.tightest > active.tightest + MARGIN) {
          if (!best || a.tightest > best.tightest) best = a;
        }
      }

      if (best) {
        lastSwitchRef.current = now;
        const target = best;
        // ★★ **成功通知必须等 CLI 真的干成了。** 原来两行并排、`notify` 无条件发 ——
        //    CLI 拒绝时用户照样收到「已切到 X」。系统通知比 toast 更难撤回，
        //    而"它说切了其实没切"正是这一整条链路最不该出现的谎。
        void run("auto-switch", ["switch", target.node],
                 `自动切号: ${active.node}(${active.tightest}%) → ${target.node}(${target.tightest}%)`)
          .then((ok) => {
            if (ok) {
              notify("自动切号",
                     `${active.node} 额度低(${active.tightest}%)，已切到 ${target.node}(${target.tightest}%)`);
            }
          });
      }
    };

    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, [run]);
}
