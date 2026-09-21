import { useCallback, useEffect, useRef, useState } from "react";
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
  /** 在途请求数（只许 1 个）+ 期间来过新事件吗。见下面 `load` 的注释。 */
  const inflight = useRef(false);
  const pending = useRef(false);

  const load = useCallback(() => {
    if (!enabled) return;
    // ★★ **在途只许一个，期间的事件合并成一次尾随刷新。**
    //   每次读都要 spawn 一个 python（≈200ms），而 `state-changed` 是会**成串**来的
    //   （代理换号 + quotad 刷额度 + 用户点一下，能在一秒内连发好几条）。
    //   没有这道合流，N 条事件就是 N 个子进程 —— 2026-09-21 那次回环之所以能烧到
    //   66 个/秒，回环是点火，**没有合流是助燃**。codex 评审实测：注入连续 20 条外部
    //   事件，只改 IPC 之后仍会产生 21 次读取。
    //   ★ 合流不是 debounce：尾随那一次**保证会跑**，所以期间发生的变更最终一定被读到
    //     （丢掉末次刷新 = 界面停在旧数字，那正是本仓最不能容忍的那类静默过期）。
    if (inflight.current) { pending.current = true; return; }
    inflight.current = true;
    void (async () => {
      try {
        // ★★★ **必须走专用的只读 IPC，绝不能复用 `run_rotate`。**
        //   `run_rotate` 无条件 `emit("state-changed")`，而下面那个 effect 正是
        //   监听同一个事件来刷新自己 ⇒ 自激回环（实测 12 秒 789 个 python 子进程，
        //   两个 webview 一起闪）。闸：`tests/test_no_event_feedback_loop.py`。
        const raw = await invoke<string>("read_rotation_board");
        setBoard(JSON.parse(raw) as Board);
        setErr(null);
      } catch (e: unknown) {
        // ★ 读不到**不清空**已有的板子：保留上一次 + 记下原因，
        //   与本仓「失败不覆盖已读到的」同一条规矩。
        setErr(String(e).slice(0, 160));
      } finally {
        // ★ 必须在 `finally` —— 抛错那条路也要放行，否则一次失败就把后面**所有**刷新
        //   永久堵死，而症状是「数字从某一刻起再也不动」，不报任何错。
        inflight.current = false;
        if (pending.current) { pending.current = false; load(); }
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
