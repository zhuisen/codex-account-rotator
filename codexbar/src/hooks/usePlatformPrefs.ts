import { useState, useEffect, useCallback } from "react";
import { emit, listen } from "@tauri-apps/api/event";
import { EMPTY_PREFS, type PlatformPrefs } from "../traffic";

const KEY = "codexbar_platform_prefs";
const EVT = "platform-prefs-changed";

function load(): PlatformPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return EMPTY_PREFS;
    const p = JSON.parse(raw) as Partial<PlatformPrefs>;
    // 手改坏了/换了版本时不能整页崩,缺什么补什么
    return { order: Array.isArray(p.order) ? p.order : [], by: p.by && typeof p.by === "object" ? p.by : {} };
  } catch {
    return EMPTY_PREFS;
  }
}

/**
 * 平台的本机呈现偏好:改名 / 改色 / 停用 / 列表顺序。
 *
 * ★ 与 `usePrivacy` / `useCacheMode` 同一范式,理由也同一个:主窗口和菜单栏是**两个独立 webview**,
 * localStorage 同源但**改动不互相通知**。只靠 localStorage 的话,在设置页停用了 Kimi、菜单栏
 * 「今日」还照旧把它算进总数 —— 两个界面对同一份数据给出不同的合计,正是这个项目反复修过的那类
 * 不一致。所以额外走一次 Tauri 事件广播。
 *
 * 故意**不写进 `state.json`**:纯展示偏好,不该混进那个被五个进程同读写的文件。
 * 也**不写 `traffic/sources.local.json`**:那个是给 `scan.py` 用的"要不要解析",
 * 停在这里意味着扫描仍会跑、数据仍在缓存里,随时能开回来,不用重扫 13 秒。
 */
export function usePlatformPrefs(): {
  prefs: PlatformPrefs;
  setPrefs: (next: PlatformPrefs) => void;
} {
  const [prefs, setLocal] = useState<PlatformPrefs>(load);

  useEffect(() => {
    const un = listen<PlatformPrefs>(EVT, (e) => setLocal(e.payload));
    return () => { void un.then((f) => f()); };
  }, []);

  const setPrefs = useCallback((next: PlatformPrefs) => {
    setLocal(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* 无痕/配额满:本窗口仍生效 */ }
    emit(EVT, next).catch(() => {});
  }, []);

  return { prefs, setPrefs };
}
