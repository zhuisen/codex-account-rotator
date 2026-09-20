import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { reorderByHit } from "../cardOrder";

/**
 * 卡片拖拽排序的手感层。
 *
 * ## ★★★ 核心设计：**拖拽期间 DOM 顺序一动不动**
 *
 * 前三版都在「拖动中就让 React 重排」，于是每换一个落点 React 就移动一批 DOM 节点，
 * 而我同时在这些节点上写 `transform`、量位置、播 FLIP 动画。三方踩同一批节点，
 * 结果是一串各自独立的 bug：
 *
 *   · React 的内联 `transform` 把 hook 写的位移整个抹掉 ⇒ 卡片只剩 `scale`、完全不跟手；
 *   · CSS 里留着 `transform` 过渡 ⇒「清空后立刻量位置」量到**过渡中间值**
 *     （实测量到 1437 而真实槽位 685，跟手补偿算反、卡片离指针 600px）；
 *   · 连续拖动时 FLIP 动画重叠，量到的「旧位置」是动画中间态 ⇒ 卡片**停在半空**
 *     （实测拖完后有卡片落在 `(517, 313)`，而网格列在 72/379/687 —— 正是用户
 *      2026-09-20 截图里那个互相重叠的坏状态）。
 *
 * **这一版把那个交叉点拆掉：拖拽全程 React 不重渲染、DOM 顺序不变。**
 *
 *   · 按下时量一次槽位矩形，整轮拖拽都用这一份（它们不会动，所以不需要重量）；
 *   · 每张卡该待在哪，用 `transform = 目标槽位 − 自己的槽位` 表达 —— **纯写样式，不读 DOM**；
 *   · 让位动画交给 **CSS `transition: transform`**，不需要 FLIP、不需要 WAAPI；
 *   · 被拖的那张关掉过渡、直接跟指针；
 *   · **松手才提交一次**：React 重排 DOM，同一个 layout effect 里把内联 transform 清掉 ——
 *     此刻每张卡的自然位置正好等于它 transform 后所在的位置，所以视觉无缝。
 *
 * ★ 跟手公式因此退化成最简的一条：`translate = Pt − P0`。
 *   旧设计里那个 `+ (L0 − L_target)` 补偿项是**给「React 边拖边移动节点」**准备的，
 *   这一版 DOM 不动，照搬会让卡片偏出去一整格（实测偏 623px）。
 *
 * ★ 不引入依赖（dnd-kit / framer-motion）：这套逻辑约 150 行，而拖拽库会把布局策略、
 *   传感器、碰撞算法一起带进来，也不会替你解决身份、落盘与业务取消语义。
 */

/** 让位过渡时长。★ 起点参数，不是实测结论。 */
const FLIP_MS = 170;
const EASING = "cubic-bezier(.2,.7,.3,1)";
const LIFT = 1.03;
/** 位移多少像素才算「真的在拖」—— 防止手抖把一次点击变成排序。 */
const START_SLOP = 4;

interface Slot {
  aid: string; el: HTMLElement;
  left: number; top: number; right: number; bottom: number;
}

interface Session {
  aid: string;
  p0x: number; p0y: number;
  /** 按下时这张卡的**中心**（命中判定用它，不用指针 —— 见 onMove）。 */
  c0x: number; c0y: number;
  /** 按下那一刻的槽位（整轮不变）。 */
  slots: Slot[];
  baseIds: string[];
  /** 当前预览顺序。**只存在 ref 里** —— 拖拽期间不进 React。 */
  ids: string[];
  moved: boolean;
}

export interface CardDragWiring {
  hint: string;
  isDragging: boolean;
  onStart: (x: number, y: number) => void;
  onMove: (x: number, y: number) => void;
  onEnd: (commit: boolean) => void;
}

export function useCardDrag(gridSelector = "[data-cards-grid]"): {
  dragAid: string | null;
  preview: string[] | null;
  makeDrag: (aid: string, baseIds: string[], hint: string,
             commit: (next: string[]) => void | Promise<unknown>) => CardDragWiring;
} {
  /** 只在开始/结束各变一次 —— 拖拽过程中它不变，所以不会引起重渲染。 */
  const [dragAid, setDragAid] = useState<string | null>(null);
  /** 提交之后的顺序。**拖拽过程中恒为 null**，让 DOM 顺序保持不动。 */
  const [preview, setPreview] = useState<string[] | null>(null);
  const ses = useRef<Session | null>(null);
  const escRef = useRef<(() => void) | null>(null);
  /** 提交之后要把内联 transform 清掉（在同一个 layout effect 里，避免看见跳变）。 */
  const needsClear = useRef(false);

  const allCards = useCallback(
    () => Array.from(document.querySelectorAll<HTMLElement>(`${gridSelector} > div[data-aid]`)),
    [gridSelector]);

  const measure = useCallback((): Slot[] => allCards().map((el) => {
    const r = el.getBoundingClientRect();
    return { aid: el.dataset.aid ?? "", el,
             left: r.left, top: r.top, right: r.right, bottom: r.bottom };
  }), [allCards]);

  /** 按当前预览顺序，把每张卡摆到它该在的槽位。**纯写样式，一次 DOM 读取都没有。** */
  const layout = useCallback((px: number, py: number) => {
    const s = ses.current;
    if (!s) return;
    for (const sl of s.slots) {
      const target = s.ids.indexOf(sl.aid);          // 它该去第几个槽位
      if (target < 0 || target >= s.slots.length) continue;
      const tgt = s.slots[target];
      if (sl.aid === s.aid) {
        // ★★★ 被拖的那张：**不需要任何补偿**，直接 `Pt − P0`。
        //   因为这一版 DOM 顺序整轮不动，它始终渲染在自己原来的槽位上：
        //     视觉位置 = l0 + tx，而要让抓取点贴住指针就是 l0 + tx = Pt − (P0 − l0)
        //     ⇒ tx = Pt − P0。
        //   ⚠️ 旧设计里那个 `+ (L0 − L_target)` 补偿项是**给「React 边拖边移动节点」**
        //     准备的；照搬到这一版会让卡片偏出去一整格（实测偏 623px）。
        const tx = px - s.p0x;
        const ty = py - s.p0y;
        sl.el.style.transform = `translate3d(${tx}px, ${ty}px, 0) scale(${LIFT})`;
      } else {
        const dx = tgt.left - sl.left;
        const dy = tgt.top - sl.top;
        sl.el.style.transform = dx || dy ? `translate3d(${dx}px, ${dy}px, 0)` : "";
      }
    }
  }, []);

  const clearStyles = useCallback(() => {
    for (const el of allCards()) {
      el.style.transition = "";
      el.style.transform = "";
      el.style.zIndex = "";
      el.style.willChange = "";
    }
  }, [allCards]);

  /**
   * 提交之后清掉所有内联 transform。
   *
   * ★★ 必须 `useLayoutEffect`：React 刚把 DOM 排成新顺序，此刻每张卡的**自然位置**
   *   正好等于它 transform 之后所在的位置。在绘制之前清掉，视觉上完全无缝；
   *   放 `useEffect` 里会先画一帧「双重偏移」的画面。
   */
  useLayoutEffect(() => {
    if (!needsClear.current) return;
    needsClear.current = false;
    clearStyles();
  }, [preview, clearStyles]);

  /** Esc 取消：自定义 pointer 拖拽**不会**自动收到 `pointercancel`。 */
  useLayoutEffect(() => {
    if (!dragAid) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      escRef.current?.();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [dragAid]);

  const makeDrag = useCallback((aid: string, baseIds: string[], hint: string,
                                commit: (next: string[]) => void | Promise<unknown>): CardDragWiring => {
    const finish = (ok: boolean) => {
      const s = ses.current;
      if (!s) return;
      const next = [...s.ids];
      const changed = next.join() !== s.baseIds.join();
      ses.current = null;
      escRef.current = null;
      setDragAid(null);

      if (!ok || !changed) {
        // 取消 / 没变动：滑回原位（CSS 过渡还在），过渡结束再把样式清干净
        for (const sl of s.slots) { sl.el.style.transform = ""; sl.el.style.zIndex = ""; }
        window.setTimeout(clearStyles, FLIP_MS + 40);
        return;
      }
      // ★ 提交：React 重排 DOM，随后在同一个 layout effect 里清掉 transform（见上）
      needsClear.current = true;
      setPreview(next);
      void Promise.resolve(commit(next));
    };

    return {
      hint,
      isDragging: dragAid === aid,
      onStart: (x, y) => {
        const slots = measure();
        const mine = slots.find((sl) => sl.aid === aid);
        if (!mine) return;
        ses.current = {
          aid, slots, baseIds: [...baseIds], ids: [...baseIds],
          p0x: x, p0y: y, moved: false,
          c0x: (mine.left + mine.right) / 2, c0y: (mine.top + mine.bottom) / 2,
        };
        escRef.current = () => finish(false);
      },
      onMove: (x, y) => {
        const s = ses.current;
        if (!s) return;
        if (!s.moved) {
          if (Math.abs(x - s.p0x) < START_SLOP && Math.abs(y - s.p0y) < START_SLOP) return;
          s.moved = true;
          setDragAid(aid);
          // 让位动画交给 CSS；被拖的那张关掉过渡，要瞬时跟手
          for (const sl of s.slots) {
            sl.el.style.transition = sl.aid === aid ? "none" : `transform ${FLIP_MS}ms ${EASING}`;
            sl.el.style.willChange = "transform";
            if (sl.aid === aid) sl.el.style.zIndex = "5";
          }
        }
        // 命中：用**按下时量的固定槽位**，整轮不动 —— 结构上不可能有反馈回路。
        // ★★★ 判定按**槽位序号**，不按「这个槽位原来住着谁」：后者不幂等，
        //   会让顺序每帧来回翻、让位过渡永远播不完。整段推导与实测在 cardOrder.ts。
        //
        // ★★★ 喂进去的是**被拖卡片的中心**，不是指针。
        //   手柄在卡片右上角，所以指针天然比卡片超前大半格：按指针判，卡片才挪
        //   一点点、邻居就让位了；而用户看到的是「卡片都过去一半了，邻居还杵着不动」
        //   —— 同一个错误的两个方向，取决于你从哪儿抓的。2026-09-20 用户截图报的就是它。
        //   中心 = 原中心 + 指针位移（DOM 不动，所以位移就是 transform 的量）。
        const cx = s.c0x + (x - s.p0x);
        const cy = s.c0y + (y - s.p0y);
        s.ids = reorderByHit(s.ids, s.aid, s.slots, cx, cy);
        layout(x, y);          // 纯写样式，零重渲染
      },
      onEnd: finish,
    };
  }, [dragAid, measure, layout, clearStyles]);

  return { dragAid, preview, makeDrag };
}
