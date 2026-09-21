import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/**
 * 总览顶部「续航条」的数据（用户 2026-09-21 从六个方向里选的 D + 左侧账号环）。
 *
 * ## ★★★ 为什么走 CLI 而不是前端自己算
 *
 * 「下一个请求会用谁」由 `proxy.py` 的挑号器决定。前端**有账号数据但没有挑号器** ——
 * 照着排序键在 TS 里再写一份，两份必然分叉，而症状是**界面信誓旦旦地报一个代理根本
 * 不会挑的号，且两边都不报错**。本仓已经因为"测试抄了一份排序键"栽过一次（改真排序行
 * 对闸毫无影响）。所以这里调 `codex-rotate next --json`，它 import 真的 `proxy.py`，
 * 用**同一个** `usable()` + `_sort_avail()`。
 *
 * ## 三个字段别混
 *
 * · `cur`  —— `last_aid`，代理**最近一次真的用了谁**。这是「正在使用」唯一诚实的定义；
 *              旧 Hero 用的 `active` 是**上次 CLI 切换**留下的，实测过两者不一致。
 * · `next` —— 下一个请求会用谁。逐请求轮换下它与 `cur` 本来就可能不同。
 * · `runway_active_hours` —— **活跃小时**，见下。
 *
 * ★★ 取不到就是 `null`，**绝不给 0**：「算不出来」与「撑不了多久」在这块版面上是
 *   相反的两件事，而 0 会被读成后者（本仓头号铁律在续航上的形态）。
 */
export interface BoardWin { label: string; rem: number; reset: string }
export interface BoardAcct {
  aid: string; label: string | null; email?: string | null; plan?: string | null;
  /** 置顶队列位次（1 起）；`null` = 没置顶 —— **不是 0**。 */
  pin: number | null;
  off: boolean; dead: boolean; cool_min: number;
  wins: BoardWin[];
  /** 最紧窗口还剩多少；没有可读窗口时 `null`。 */
  tightest: number | null;
  /** 周窗口剩余 —— 续航只算它：5h 每 5 小时自己回满，真正卡住你的是周。 */
  weekly: number | null;
}
export interface Board {
  cur: BoardAcct | null;
  cur_ago_min: number | null;
  next: BoardAcct | null;
  queue: BoardAcct[];
  rest: BoardAcct[];
  weekly_left_pp: number;
  burn_pp_per_active_hour: number | null;
  runway_active_hours: number | null;
  samples: number;
  last_sample_min: number | null;
}

export function useRotationBoard(enabled: boolean): { board: Board | null; err: string | null } {
  const [board, setBoard] = useState<Board | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!enabled) return;
    void (async () => {
      try {
        const raw = await invoke<string>("run_rotate", { args: ["next", "--json"] });
        setBoard(JSON.parse(raw) as Board);
        setErr(null);
      } catch (e: unknown) {
        // ★ 读不到**不清空**已有的板子：保留上一次 + 记下原因，
        //   与本仓「失败不覆盖已读到的」同一条规矩。
        setErr(String(e).slice(0, 160));
      }
    })();
  }, [enabled]);

  useEffect(() => {
    load();
    // ★ 跟着 `state-changed` 走就够：置顶/停用/切号/额度刷新都会发它。
    //   这块没有自己的定时器 —— 它读的是本机文件，没人操作时数字不会变。
    const un = listen("state-changed", () => load());
    return () => { void un.then((f) => f()); };
  }, [load]);

  return { board, err };
}
