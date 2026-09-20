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

/** 按下那一刻量到的槽位矩形（整轮拖拽不变）。 */
export interface SlotRect { left: number; top: number; right: number; bottom: number }

/**
 * 拖拽命中：指针落在第几个**槽位**里，被拖的卡片就去第几位。
 *
 * ★★★ **必须按槽位序号判定，绝不能按「这个槽位原来住着谁」。**
 *
 * 槽位矩形是按下时冻结的，所以 `slots[i]` 的身份永远是 *baseIds[i]*；而预览顺序 `ids`
 * 每帧都在变。拿冻结的身份去 `ids.indexOf(...)` 求落点，这个操作就**不是幂等的**：
 *
 * | 第几次 move | 命中槽位原住户 | from → to | 结果 ids |
 * |---|---|---|---|
 * | 1 | B | 0 → 1 | `[B,A,C]` |
 * | 2 | B | 1 → 0 | `[A,B,C]` ← 翻回去了 |
 * | 3 | B | 0 → 1 | `[B,A,C]` |
 *
 * **指针一动不动，顺序每帧翻一次。** 实测（2026-09-20，harness 同坐标连发 8 次 move）：
 * 布局在两个状态之间反复横跳，于是 170ms 的让位过渡每 ~8ms 被重启一次、**永远播不完**，
 * 卡片停在过渡起点附近持续抖动 —— 这就是用户连报四轮的「不流畅」。
 * 它还有一个对外可见的副作用：**最终落盘的顺序取决于 pointermove 次数的奇偶**。
 *
 * 改成按序号之后 `ids.indexOf(aid) === to`，同一坐标再调用就直接原样返回。
 *
 * ★ 不跳过自己的槽位：指针挪回原处时，`to` 就是原位，卡片正确地回去。
 */
export function reorderByHit(ids: string[], aid: string, slots: SlotRect[],
                             x: number, y: number): string[] {
  const from = ids.indexOf(aid);
  if (from < 0) return ids;
  let to = -1;
  for (let i = 0; i < slots.length; i++) {
    const s = slots[i];
    if (x >= s.left && x <= s.right && y >= s.top && y <= s.bottom) { to = i; break; }
  }
  if (to < 0 || to >= ids.length) return ids;   // 落在网格空白处 ⇒ 保持现状，不是"回到开头"
  return moveItem(ids, from, to);
}
