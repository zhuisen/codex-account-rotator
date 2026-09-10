import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { RelayRow, RouteStatus } from "../relay";

export interface RelayConfig {
  relays: RelayRow[];
  route: RouteStatus;
}

export interface UseRelayConfig {
  /** `null` = **读失败**，不是「没配过」。两者的下一步动作完全相反。 */
  cfg: RelayConfig | null;
  note: string | null;
  setNote: (v: string | null) => void;
  /** 正在执行的动作键（`sub` 或 `sub:arg`），用于按钮的 loading 态。 */
  acting: string | null;
  act: (sub: string, arg?: string, payload?: unknown) => Promise<Record<string, unknown> | null>;
  reload: () => Promise<void>;
}

/**
 * 中转站配置与动作的**唯一**来源。
 *
 * ★★ 抽成 hook 而不是让两个页面各写一份：路由是**互斥单选**，两份状态迟早分叉成
 *    「总览说走账号池、用量页说走中转站」。而这条链路上每一个不一致都会被读成
 *    "钱扣在哪里"的错误答案。
 *
 * ★ 所有写操作都在这里 `reload()`，因为后端是文件、可被终端里的 `./relay-ctl` 改动 ——
 *   前端**不缓存推断**，一律回读。
 */
export function useRelayConfig(): UseRelayConfig {
  const [cfg, setCfg] = useState<RelayConfig | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const raw = await invoke<string>("relay_ctl", { sub: "status" });
      const d = JSON.parse(raw);
      // ★★ 配置文件损坏必须说出来。后端已经会回 `ok:false` + `store_corrupt`，
      //    前端不读它的话页面会画"还没有配置中转站" —— 一句关于事实的假陈述。
      if (d.ok === false && d.state === "store_corrupt") setNote("✗ " + d.detail);
      setCfg({ relays: d.relays ?? [], route: d.route });
    } catch (e: unknown) {
      setCfg(null);
      setNote("读配置失败：" + String(e));
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const act = useCallback(async (sub: string, arg?: string, payload?: unknown) => {
    setActing(sub + (arg ? ":" + arg : ""));
    setNote(null);
    try {
      const raw = await invoke<string>("relay_ctl", {
        sub, arg, payload: payload === undefined ? undefined : JSON.stringify(payload),
      });
      const d = JSON.parse(raw);
      // ★ `ok:false` 是**正常返回**（降级 payload），不是异常。原样显示 detail/errors ——
      //   吞掉它等于让用户对着一个没反应的按钮猜。
      // ★ `"".join()` 返回空串而非 nullish，所以 `?? d.state` 会是死代码，这里用 `||`。
      const msg = d.detail || (d.errors ?? []).join("；") || d.state || "未知错误";
      if (!d.ok) setNote("✗ " + msg);
      else if (sub === "test") setNote(`✓ 连接正常 · ${d.model_count ?? "?"} 个模型可用`);
      else if (sub === "rewrite") setNote("✓ profile 已重写");
      else if (sub === "route") setNote(arg === "pool" ? "✓ 已切回账号池" : `✓ 已切到 ${arg}`);
      await reload();
      return d;
    } catch (e: unknown) {
      setNote(String(e));
      return null;
    } finally {
      setActing(null);
    }
  }, [reload]);

  return { cfg, note, setNote, acting, act, reload };
}
