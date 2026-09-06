import { useCallback, useEffect, useRef, useState } from "react";
import { emit, listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

/**
 * **跨 webview 的「正在进行中」镜像。**
 *
 * ## 它补的缺口（用户 2026-09-06：「菜单栏点了刷新，进主界面没显示正在刷新」）
 *
 * 两个 webview 早就共用**数据**（`.traffic-latest.json` + `traffic-updated` 广播）和
 * **完成信号**（Rust 在 `run_rotate` 末尾 `emit("state-changed")`），但**进行态**
 * （`loadingAction` / `busy`）一直是各自的 React state。于是对方只在动作**结束**时才知情 ——
 * 整个执行期间它显示得像什么都没发生，而那恰恰是最需要反馈的一段。
 *
 * ## 三条独立的熄灯路径（缺一条就会留一盏永远亮着的灯）
 *
 * ★★ 镜像来的状态是**别人告诉我的**，我无法确认它还成立 —— 所以它必须能自己熄灭。
 * 本仓对「长亮又无从消除的灯」判过死刑（它训练用户忽略所有指示器）。
 *
 * ① **对方发的结束事件** —— 正常路径，`announce(null)` 在 `finally` 里发；
 * ② **Rust 发的完成信号**（`state-changed` / `traffic-updated`）—— 这条**不经过发起方**，
 *    所以对方 webview 崩溃/重载也照样能熄。`run_rotate` 在成功与失败两条路径上都 emit
 *    （`lib.rs` 里那句在 `status.success()` 判断**之前**），所以失败也能熄；
 * ③ **硬超时** `STUCK_SEC` —— 前两条都没来时的兜底。宁可少显示一会儿，也不要长亮。
 *
 * ## 不回放自己的事件
 *
 * Tauri 的 `emit` 会广播给**包括自己在内**的所有窗口。不按窗口标签过滤的话，
 * 发起方会把自己的广播当成"远端状态"收回来，`finally` 清掉本地态之后镜像还亮着 ——
 * 表现为按钮转圈停不下来。
 */

/** 镜像态最多亮这么久。探针全池是最慢的动作（逐号计费请求 + 重试），留足余量后取 3 分钟。 */
const STUCK_SEC = 180;

interface BusyMsg { action: string | null; at: number; from: string }

export interface BusyMirror {
  /** 别的 webview 正在跑的动作 id；`null` = 据我所知没有。 */
  remote: string | null;
  /** 开始时传 actionId，结束时传 `null`。**必须放在 `finally` 里**，异常路径也要熄灯。 */
  announce: (action: string | null) => void;
}

export function useBusyMirror(): BusyMirror {
  const [remote, setRemote] = useState<string | null>(null);
  const selfLabel = useRef<string>("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    try { selfLabel.current = getCurrentWindow().label; } catch { /* harness/非 tauri 环境 */ }
  }, []);

  const clearTimer = () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
  };

  useEffect(() => {
    const subs = [
      listen<BusyMsg>("action-busy", (e) => {
        const m = e.payload;
        // ★ 自己发的不收 —— 否则 `finally` 清了本地态，镜像还亮着，按钮转圈停不下来。
        if (!m || m.from === selfLabel.current) return;
        clearTimer();
        if (!m.action) { setRemote(null); return; }
        setRemote(m.action);
        // ③ 硬超时兜底
        timer.current = setTimeout(() => setRemote(null), STUCK_SEC * 1000);
      }),
      // ② 不经过发起方的熄灯路径:这两个是 Rust / 扫描器在动作真正结束时发的。
      //    对方 webview 崩溃或重载时，①永远不会到，只有这条能救。
      listen("state-changed", () => { clearTimer(); setRemote(null); }),
      listen("traffic-updated", () => { clearTimer(); setRemote(null); }),
    ];
    return () => {
      clearTimer();
      for (const s of subs) void s.then((f) => f());
    };
  }, []);

  const announce = useCallback((action: string | null) => {
    void emit("action-busy", { action, at: Date.now() / 1000, from: selfLabel.current });
  }, []);

  return { remote, announce };
}
