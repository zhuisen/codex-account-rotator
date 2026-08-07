import { useState, useEffect, useCallback } from "react";
import { emit, listen } from "@tauri-apps/api/event";

const KEY = "codexbar_privacy";
const EVT = "privacy-changed";

function load(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

/**
 * 打码模式:把能认出人的信息换成圆点,方便截图分享。
 *
 * 主窗口和菜单栏弹窗是两个独立 webview。localStorage 同源可共享,但**改动不会互相通知** —— 只靠
 * localStorage 的话,在主界面打开打码、菜单栏还照旧显示明文,而截图往往正是截菜单栏那一张。所以额外
 * 走一次 Tauri 事件广播,让两个窗口即时同步(与 `navigate-settings` 同一范式)。
 *
 * 故意**不持久化到 state.json**:这是纯展示偏好,不该混进那个被五个进程同读写的文件。
 */
export function usePrivacy(): { privacy: boolean; toggle: () => void } {
  const [privacy, setPrivacy] = useState(load);

  useEffect(() => {
    const un = listen<boolean>(EVT, (e) => setPrivacy(e.payload));
    return () => { un.then(f => f()); };
  }, []);

  const toggle = useCallback(() => {
    setPrivacy(prev => {
      const next = !prev;
      try { localStorage.setItem(KEY, next ? "1" : "0"); } catch { /* 无痕/配额满:本窗口仍生效,只是不持久 */ }
      emit(EVT, next).catch(() => {});
      return next;
    });
  }, []);

  return { privacy, toggle };
}
