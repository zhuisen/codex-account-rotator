import { useState, useEffect, useCallback } from "react";
import { emit, listen } from "@tauri-apps/api/event";
import { CACHE_MODES, type CacheMode } from "../traffic";

const KEY = "codexbar_cache_mode";
const EVT = "cache-mode-changed";

function load(): CacheMode {
  try {
    const v = localStorage.getItem(KEY);
    return (CACHE_MODES as readonly string[]).includes(v ?? "") ? (v as CacheMode) : "full";
  } catch {
    return "full";
  }
}

/**
 * 缓存计入口径(含缓存 / 不含缓存读 / 不含缓存)。
 *
 * ★ 与 `usePrivacy` 同一范式,理由也同一个:主窗口和菜单栏是**两个独立 webview**,localStorage
 * 同源可共享但**改动不会互相通知**。只靠 localStorage 的话,在设置页切了口径、菜单栏「今日」还
 * 显示旧口径的数字 —— 两个界面对同一份数据给出相差 25 倍的总量,正是刚修完的那类不一致 bug。
 * 所以额外走一次 Tauri 事件广播。
 *
 * 故意**不写进 state.json**:纯展示偏好,不该混进那个被五个进程同读写的文件。
 */
export function useCacheMode(): { mode: CacheMode; setMode: (m: CacheMode) => void } {
  const [mode, setLocal] = useState<CacheMode>(load);

  useEffect(() => {
    const un = listen<CacheMode>(EVT, (e) => setLocal(e.payload));
    return () => { void un.then((f) => f()); };
  }, []);

  const setMode = useCallback((m: CacheMode) => {
    setLocal(m);
    try { localStorage.setItem(KEY, m); } catch { /* 无痕/配额满:本窗口仍生效,只是不持久 */ }
    emit(EVT, m).catch(() => {});
  }, []);

  return { mode, setMode };
}
