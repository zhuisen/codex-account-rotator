import { useCallback, useState } from "react";
import type { Account } from "../helpers";

/**
 * 重置卡到期横幅的「关掉它」记忆（用户 2026-09-18：「这个提醒太过了，喧宾夺主，并且无法取消」）。
 *
 * ## 原来的形态是本仓判过死刑的那一种
 *
 * 横幅 60px 高、挂在 352px 宽弹窗的顶部，`CARD_WARN_DAYS = 3` 意味着它**连挂三天**，
 * 而且没有任何关闭入口 —— `plat === "codex" && cardAlert &&`，用户对它零控制。
 * 更糟的是它那颗大按钮「用卡: /usage」**点了并不用卡**（服务端要求当前周窗口
 * "需要重置"才放行，盲发会白烧一张），只弹个 toast 告诉你去终端敲命令。
 *
 * ⇒ **一盏连亮三天、关不掉、又不能真正执行的灯。** 本仓的规矩正好写着两条：
 *   · §5d「一天看一次的信息 ⇒ 折叠进角标，悬浮才展开」
 *   · 「长期亮着又灭不掉的告警，训练用户忽略告警」
 *
 * ## 判据：按**这张卡的身份**记忆，不是按「关过了」
 *
 * ★★★ 这是整个文件唯一容易写错的地方。存一个布尔「用户关过横幅」⇒
 *   **下一张卡快到期时也不会再提醒**，而那是一次全新的、真会损失东西的事件。
 *   「关掉这一条」和「以后都别提醒我」是两件事，合并成同一个值就等于静默把功能关了。
 *   所以键是 `节点:最早一张的到期日`（`a.cardExp`）——
 *   换了新卡、或者另一个号的卡进入 3 天窗口，`cardExp` 就变，横幅**重新出现一次**。
 *
 * ⚠️ 顺带：关掉之后信息**不能丢**。卡上的 `CardBadge` 常驻（琥珀 + 光晕 + `×3·1张3天`），
 *   它的悬浮说明里补了「怎么用卡」那句 —— 那本来是横幅唯一独有的内容。
 *
 * ★ 只用 `localStorage`、不广播：这条横幅**只在菜单栏**出现，主窗口没有它，
 *   所以不存在两个 webview 要同步的问题（与 `usePrivacy` / `useCacheMode` 不同族）。
 */
const KEY = "codexbar.cardBannerDismissed";

/** 这一条提醒的身份。`cardExp` 变了就是**另一张卡**，必须重新提醒。 */
export function cardAlertKey(a: Pick<Account, "node" | "cardExp"> | null | undefined): string | null {
  if (!a || !a.node) return null;
  // ★ 没有 `cardExp`（明细还没取到）时用 `?` 占位而不是返回 null：
  //   返回 null 会让横幅**永远无法被关掉**，正是这次要修的那个症状。
  return `${a.node}:${a.cardExp ?? "?"}`;
}

function load(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function useCardBannerDismiss(): {
  /** 这一条现在该显示吗。 */
  visible: (a: Pick<Account, "node" | "cardExp"> | null | undefined) => boolean;
  dismiss: (a: Pick<Account, "node" | "cardExp"> | null | undefined) => void;
} {
  const [seen, setSeen] = useState<string[]>(load);

  const visible = useCallback(
    (a: Pick<Account, "node" | "cardExp"> | null | undefined) => {
      const k = cardAlertKey(a);
      return k != null && !seen.includes(k);
    },
    [seen],
  );

  const dismiss = useCallback((a: Pick<Account, "node" | "cardExp"> | null | undefined) => {
    const k = cardAlertKey(a);
    if (k == null) return;
    setSeen((prev) => {
      if (prev.includes(k)) return prev;
      // ★ 只留最近 20 条：键随卡轮换，不封顶的话这个数组只增不减。
      const next = [...prev, k].slice(-20);
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* 存不下就只在本次会话里生效 —— 关不掉比存不下严重得多 */
      }
      return next;
    });
  }, []);

  return { visible, dismiss };
}
