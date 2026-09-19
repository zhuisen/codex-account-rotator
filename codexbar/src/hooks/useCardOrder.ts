import { useState, useEffect, useCallback } from "react";
import { emit, listen } from "@tauri-apps/api/event";

import { type CardOrder, applyOrder, moveItem } from "../cardOrder";

export { applyOrder, moveItem };
export type { CardOrder };

const KEY = "codexbar_card_order";
const EVT = "card-order-changed";

function load(): CardOrder {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const p = JSON.parse(raw) as unknown;
    if (!p || typeof p !== "object") return {};
    // 手改坏了/换了版本时不能整页崩：只收下形状正确的那几档
    const out: CardOrder = {};
    for (const [k, v] of Object.entries(p as Record<string, unknown>)) {
      if (Array.isArray(v) && v.every((x) => typeof x === "string")) out[k] = v as string[];
    }
    return out;
  } catch {
    return {};
  }
}

/** 落盘 + 广播。★ 两个 setter 共用这一份 —— 各写各的迟早只改一处。 */
function persist(next: CardOrder): CardOrder {
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* 无痕/配额满:本窗口仍生效 */ }
  emit(EVT, next).catch(() => {});
  return next;
}

/**
 * 总览卡片的自定义顺序（用户 2026-09-19 要的拖拽排序）。
 *
 * ★ 与 `usePlatformPrefs` / `usePrivacy` 同一范式，理由也同一个：主窗口和菜单栏是
 *   **两个独立 webview**，localStorage 同源但**改动不互相通知**。不广播的话，在总览里
 *   拖完顺序、菜单栏仍是旧序 —— 两个界面对同一批卡片给出不同排法，正是本仓反复修过的
 *   那类不一致。
 *
 * ★ 故意**不写进 `state.json`**：纯展示偏好，不该混进那个被五个进程同读写的文件。
 */
export function useCardOrder(): {
  order: CardOrder;
  setOrderFor: (platform: string, ids: string[]) => void;
  resetFor: (platform: string) => void;
} {
  const [order, setLocal] = useState<CardOrder>(load);

  useEffect(() => {
    const un = listen<CardOrder>(EVT, (e) => setLocal(e.payload));
    return () => { void un.then((f) => f()); };
  }, []);

  const setOrderFor = useCallback((platform: string, ids: string[]) => {
    setLocal((cur) => persist({ ...cur, [platform]: ids }));
  }, []);

  const resetFor = useCallback((platform: string) => {
    setLocal((cur) => {
      const next = { ...cur };
      delete next[platform];
      return persist(next);
    });
  }, []);

  return { order, setOrderFor, resetFor };
}
