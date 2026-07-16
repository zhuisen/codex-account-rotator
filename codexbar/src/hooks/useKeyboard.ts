import { useEffect } from "react";
import type { Window as TauriWindow } from "@tauri-apps/api/window";

export function useKeyboard(
  win: TauriWindow,
  refresh: () => void,
  setPage?: (page: string) => void,
  onSwitchByIndex?: (index: number) => void,
): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.metaKey) return;
      switch (e.key) {
        case "w": e.preventDefault(); win.hide(); break;
        case "q": e.preventDefault(); win.hide(); break;
        case "m": e.preventDefault(); win.minimize(); break;
        case ",": e.preventDefault(); setPage?.("settings"); break;
        case "r": if (!e.shiftKey) { e.preventDefault(); refresh(); } break;
        default:
          if (e.key >= "1" && e.key <= "9" && onSwitchByIndex) {
            e.preventDefault();
            onSwitchByIndex(parseInt(e.key) - 1);
          }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [win, refresh, setPage, onSwitchByIndex]);
}
