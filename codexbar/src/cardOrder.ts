/**
 * 卡片顺序的**纯计算**部分 —— 零 import，所以能被 `node --experimental-strip-types` 直接跑。
 *
 * ★ 与 `hooks/useCardOrder.ts` 分开是刻意的（全局规则「保持纯核心」）：hook 要 import
 *   react 与 tauri 的 event 通道，想测 `applyOrder` 就得先 stub 那两样 —— 而「为了 import
 *   一个纯函数去搭桩」正是该**搬文件**而不是**加桩**的信号。
 *   闸在 `tests/test_card_order.py`，它真的把这个文件跑起来，不是对源码做文本断言。
 */

/** 每个平台档各自一份顺序（codex / gemini / grok 的卡片是三组不同的东西）。 */
export type CardOrder = Record<string, string[]>;

/**
 * 把保存的顺序套到当前这批卡片上。
 *
 * ★★ **没记录过的项一律追加到末尾，绝不丢弃。**
 *   这是本仓「读不到 ≠ 没有」在排序上的形态：新加的号、刚复活的号都不在旧顺序里，
 *   按「只渲染 order 里有的」写就会让它们**静默消失** —— 而用户看到的是
 *   「我加了个号，总览里没有」，完全指不到排序功能。
 *
 * ★ order 里已经不存在的 id 自动忽略（删过的号），不需要额外清理。
 * ★ `order` 为空/未定义时**原样返回**，保持默认排序 —— 没拖过的机器行为零变化。
 */
export function applyOrder<T>(items: T[], order: string[] | undefined,
                              idOf: (x: T) => string): T[] {
  if (!order || !order.length) return items;
  const rank = new Map(order.map((id, i) => [id, i]));
  const known: T[] = [];
  const fresh: T[] = [];
  for (const it of items) (rank.has(idOf(it)) ? known : fresh).push(it);
  known.sort((a, b) => (rank.get(idOf(a)) as number) - (rank.get(idOf(b)) as number));
  return [...known, ...fresh];
}

/** 把 `from` 位置的项移到 `to` 位置，返回新数组。越界或原地不动时**原样返回**。 */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) {
    return items;
  }
  const next = [...items];
  const [it] = next.splice(from, 1);
  next.splice(to, 0, it);
  return next;
}
