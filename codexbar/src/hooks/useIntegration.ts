import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/**
 * 装机链路总闸 —— 「这台机器敲 `codex` / `cxp` 到底会不会走轮换」。
 *
 * ## 为什么这个 hook 存在
 *
 * 用户 2026-09-19 报「下载了 CodexBar，敲 `codex` 没走 rotateproxy」。查下来**四处缺口
 * 每一处单独就足以让轮换失效，而它们全都静默**：`.dmg` 不含 `proxy/`；`INSTALL.md` 不装
 * `codex` wrapper；profile 缺失时 codex **不报错**只是退回单号直连；而 App 这边
 * `useStore.run()` 把 `run_rotate` 的 stdout 整个丢掉 —— 所以 `health` 里既有的那几道闸
 * **一个字都到不了界面**。用户看到的是「一个看起来正常的空池」。
 *
 * ★ 判定逻辑**一行都不在这里** —— 真源是 `codex-rotate` 的 `codex_integration_gate()`，
 *   `health` 与本 hook 共用它。本仓在额度色阈值上有过两份实现各自演化的教训。
 */
export type IntegrationState =
  | "ready"          // 全通
  | "no_accounts"    // 接线齐全但池子空（琥珀）
  | "broken"         // 装了但断了（红）
  | "not_installed"  // 只装了看板那一半（中性，不是故障）
  | "unknown";       // 判定不了 —— ★ 绝不折叠成 ready

export interface IntegrationCheck {
  id: string;
  label: string;
  state: "ok" | "bad" | "unknown";
  detail: string;
  fix: string;
}

export interface Integration {
  level: "ok" | "warn" | "unknown";
  state: IntegrationState;
  checks: IntegrationCheck[];
  lines: string[];
  port: number;
  accounts: number | null;
}

/**
 * 读不到时合成的值。
 *
 * ★★ **刻意不沿用 §7.0b 的「保留旧值 + 标 stale」。** 那条规矩保护的是**历史数据**
 *   （用量序列、账本）——丢了就永远回不来。而这道闸描述的是**此刻的接线状态**，
 *   保留一个旧的 `ready` 意味着在接线已经断掉之后继续显示绿色，那正是它要消灭的东西。
 *   这里没有历史可丢，所以正确答案是如实说「判定不了」。
 */
function unknownFrom(reason: string): Integration {
  return {
    level: "unknown",
    state: "unknown",
    checks: [],
    lines: [`⚠️ 接入闸：判定不了 —— 这不等于「没问题」。（${reason}）`],
    port: 0,
    accounts: null,
  };
}

export function useIntegration(): {
  integration: Integration | null;
  reload: () => void;
} {
  const [integration, setIntegration] = useState<Integration | null>(null);

  const reload = useCallback(() => {
    void (async () => {
      try {
        const raw = await invoke<string>("read_integration");
        setIntegration(JSON.parse(raw) as Integration);
      } catch (e: unknown) {
        setIntegration(unknownFrom(String(e).slice(0, 80)));
      }
    })();
  }, []);

  useEffect(() => {
    reload();
    // 加号 / 切号 / 改配置都会广播 `state-changed`，接线状态可能随之变化。
    // ★ 不加定时器：这不是会自己漂移的量，只在有人动过东西之后才需要重算。
    const un = listen("state-changed", () => reload());
    return () => {
      void un.then((f) => f());
    };
  }, [reload]);

  return { integration, reload };
}
