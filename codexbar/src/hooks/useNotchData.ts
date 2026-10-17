import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { AppState } from "../helpers";
import type { AgySnapshot } from "../agy";

/** `state-changed` 两次重读之间至少隔这么久。代理每个成功响应都写一次 state.json（`last_aid`），
 *  重度使用时 Rust 的 1s mtime 监视会每秒推一次 —— 刘海条只是瞄一眼的东西，2s 粒度足够。 */
const STATE_MIN_GAP_MS = 2000;

/**
 * 刘海条的取数：**只听推送，不轮询**（用户 2026-10-17：「把刘海网页进程改成数据变化时再推送」）。
 *
 * ★ 为什么不复用 `useStore` / `useAgyQuota`：那两个是给主界面和菜单栏的，自带定时器 ——
 *   `useStore` 每 30s 读一次 state + **全部 token**、另有一个 1s 的冷却倒计时；
 *   `useQuotaSidecar` 每 30s 判一次新鲜度，过期还会 `run_agy_quota`（起 python）。
 *   刘海窗口常驻且恒为 visible，这些在它身上就是白跑。实测打开刘海条时它的 WebContent 进程
 *   60s 平均 0.25% CPU（2026-10-17，同时段主进程另算）。
 * ★ 推送源都是现成的：`lib.rs` 那个 1s 的 mtime 监视在 state.json 变化时发 `state-changed`、
 *   在 agy sidecar 变化时发 `agy-quota-updated`。这里**只读不取**：取额度是采样器和
 *   主界面的事，刘海条从不发起 RPC 或起 python。
 * ★★ 这里的 agy 只是**本机 RPC 那份**，不能单独拿来画（自 agy 1.2 起它恒 `csrf_required`，
 *   剩下的是几周前的 `last_good`）。刘海画的是池里当前号的那份：`NotchHud` 用 `useAgyPool(false)`
 *   （只读池文件、只收 `agy-pool-updated` / `agy-live-changed`），本机这份只在 `snapshotOf` 能证明归属时才用。
 * ★ 随时间变的那部分（窗口过了重置点、冷却结束、倒计时文字）不在这里 —— 数据没变，
 *   变的是 `now`。由 `NotchHud` 按「下一个时间点」定一次闹钟，见那里。
 */
export function useNotchData(): { state: AppState; agy: AgySnapshot | null } {
  const [state, setState] = useState<AppState>({});
  const [agy, setAgy] = useState<AgySnapshot | null>(null);

  useEffect(() => {
    let dead = false;
    let last = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const readState = () => {
      last = Date.now();
      invoke<AppState>("read_state").then((s) => { if (!dead) setState(s); }).catch(() => {});
    };
    // 限流：窗口内来的推送合并成窗口结束时的一次读，不丢最后一次
    const onState = () => {
      const wait = STATE_MIN_GAP_MS - (Date.now() - last);
      if (wait <= 0) { readState(); return; }
      if (timer) return;
      timer = setTimeout(() => { timer = undefined; readState(); }, wait);
    };
    const readAgy = () => {
      invoke<string | null>("read_agy_quota").then((raw) => {
        if (dead || !raw) return;
        let d: AgySnapshot;
        try { d = JSON.parse(raw) as AgySnapshot; } catch { return; }
        // 与 useQuotaSidecar 同口径：`fetched_at` 单调，只采纳更新的
        setAgy((prev) => (prev && prev.fetched_at >= d.fetched_at ? prev : d));
      }).catch(() => {});
    };

    readState();
    readAgy();
    const subs = [listen("state-changed", onState), listen("agy-quota-updated", readAgy)];
    return () => {
      dead = true;
      if (timer) clearTimeout(timer);
      subs.forEach((p) => { void p.then((f) => f()); });
    };
  }, []);

  return { state, agy };
}
