import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { moveItem } from "../cardOrder";

/**
 * 卡片拖拽排序的手感层。
 *
 * ## 三轮反馈换来的设计（2026-09-19 ~ 20）
 *
 * 用户要的是「像手机拖拽应用程序图标那种，放在一个位置后其他卡片要后移让位置」，
 * 并在第一版之后反馈「流畅性和 UI 交互性不好」。三条各自独立的原因：
 *
 * 1. **被拖的卡片不跟手** —— 只有 `scale`，人还待在自己格子里；
 * 2. **其余卡片瞬移不是滑动** —— **CSS 对 grid 位置变化不做 transition**，
 *    唯一不加依赖的通用解是 FLIP；
 * 3. **每次 `pointermove` 都做命中 + `setState`** —— 事件频率远高于刷新率。
 *
 * ## 四条关键不变量（都被实测或评审抓到过）
 *
 * ★★★ **跟手位移必须补偿布局基准的变化。**
 *   重排之后卡片自己的槽位也变了。只算 `指针位移` 的话，每换一格就额外跳一格：
 *
 *       translate = (Pt - P0) + (L0 - Lt)
 *
 *   `L0` 是按下时的布局位置，`Lt` 是当前槽位位置，两者都取 viewport 坐标。
 *
 * ★★★ **命中测试只能用「布局矩形」，不能用 `getBoundingClientRect()` 的实时结果。**
 *   后者**包含 transform**：跟手之后被拖的卡永远盖着指针，FLIP 之后其余卡片的命中区
 *   还在动 —— 拿它排序会形成反馈回路，表现为落点来回跳。所以槽位矩形**缓存**下来，
 *   只在重排/窗口变化时重量。
 *
 * ★★ **FLIP 要可中断。** 连续拖动时上一段动画往往还没跑完。必须从**当前视觉位置**接续，
 *   而不是从旧起点重播。用原生 Web Animations API（`element.animate()`）——
 *   它能 `cancel()` 并让元素立刻回到自然位置，便于「先集中读、再集中写」。
 *
 * ★★ **落盘完成前继续显示新顺序。** codex 档写 `state.json` 要等一次 IPC + 刷新；
 *   期间若清掉 preview，显示会**闪回旧序**。所以等权威顺序追上来再清。
 *
 * ★ 不引入依赖（dnd-kit / framer-motion）：这套逻辑约 200 行，而拖拽库会把布局策略、
 *   传感器、碰撞算法一起带进来，也不会替你解决身份、落盘与业务取消语义。
 */

/** 让位动画时长。★ 起点参数不是实测结论 —— 太长会让连续拖动时卡片还在飞、落点又变了。 */
const FLIP_MS = 160;
const FLIP_EASING = "cubic-bezier(.2,.7,.3,1)";
const LIFT = 1.03;
/** 位移多少像素才算「真的在拖」——防止手抖把一次点击变成排序。 */
const START_SLOP = 4;

interface Slot { aid: string; left: number; top: number; right: number; bottom: number }

interface Session {
  aid: string;
  /** 按下时的指针位置与卡片布局位置（viewport 坐标）。 */
  p0x: number; p0y: number;
  l0x: number; l0y: number;
  /** 卡片**当前**槽位的布局位置，每次重排后更新。 */
  ltx: number; lty: number;
  /** 最新指针位置（每个事件都写，每帧才用）。 */
  px: number; py: number;
  el: HTMLElement | null;
  /** 缓存的槽位矩形（**不含 transform**）。 */
  slots: Slot[];
  /** 与 React state 同步的预览顺序 —— 帧内要读它，不能等重渲染。 */
  ids: string[];
  /** 重排前各卡的**视觉**位置，FLIP 的 First。 */
  first: Map<string, DOMRect>;
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
  const [dragAid, setDragAid] = useState<string | null>(null);
  const [preview, setPreview] = useState<string[] | null>(null);
  const ses = useRef<Session | null>(null);
  const anims = useRef<Map<string, Animation>>(new Map());

  const cards = useCallback(
    () => Array.from(document.querySelectorAll<HTMLElement>(`${gridSelector} > div[data-aid]`)),
    [gridSelector]);

  /** 量出所有卡片的**布局**矩形。★ 先把 transform 全清掉再统一读，避免读到动画中间值。 */
  const measureSlots = useCallback((): Slot[] => {
    const els = cards();
    const saved: string[] = [];
    for (const el of els) { saved.push(el.style.transform); el.style.transform = ""; }
    const out = els.map((el) => {
      const r = el.getBoundingClientRect();
      return { aid: el.dataset.aid ?? "", left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    });
    els.forEach((el, i) => { el.style.transform = saved[i]; });
    return out;
  }, [cards]);

  /** 把被拖的卡片摆到指针下。**直接改 DOM，不经过 React。** */
  const paint = useCallback(() => {
    const s = ses.current;
    if (!s?.el) return;
    const tx = (s.px - s.p0x) + (s.l0x - s.ltx);
    const ty = (s.py - s.p0y) + (s.l0y - s.lty);
    s.el.style.transform = `translate3d(${tx}px, ${ty}px, 0) scale(${LIFT})`;
  }, []);

  /**
   * FLIP 的 Last + Play。**先集中读、再集中写**（逐卡交替读写会反复触发同步布局）。
   *
   * ★ 必须 `useLayoutEffect`：要在浏览器绘制**之前**把动画挂上去，
   *   用 `useEffect` 的话用户会先看到卡片跳过去，动画从终点开始 = 等于没有。
   */
  useLayoutEffect(() => {
    const s = ses.current;
    if (!s || !s.first.size) return;
    const els = cards();

    // ① 取消在飞的动画 —— cancel 后元素立刻回到自然（新）位置，便于统一读
    for (const el of els) {
      const a = anims.current.get(el.dataset.aid ?? "");
      if (a) { a.cancel(); anims.current.delete(el.dataset.aid ?? ""); }
    }
    // ② 集中读
    const last = new Map<string, DOMRect>();
    for (const el of els) {
      const aid = el.dataset.aid;
      if (!aid) continue;
      if (aid === s.aid) { el.style.transform = ""; }   // 被拖的那张由 paint 接管
      last.set(aid, el.getBoundingClientRect());
    }
    // ③ 集中写
    for (const el of els) {
      const aid = el.dataset.aid;
      if (!aid || aid === s.aid) continue;
      const f = s.first.get(aid);
      const l = last.get(aid);
      if (!f || !l) continue;
      const dx = f.left - l.left;
      const dy = f.top - l.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
      const anim = el.animate(
        [{ transform: `translate3d(${dx}px, ${dy}px, 0)` }, { transform: "translate3d(0,0,0)" }],
        { duration: FLIP_MS, easing: FLIP_EASING, fill: "none" });
      anims.current.set(aid, anim);
      anim.finished.then(() => anims.current.delete(aid)).catch(() => { /* cancel */ });
    }
    // ④ 被拖卡片的槽位变了 ⇒ 跟手基准要更新，否则它会"跳"一格（见 docstring 的公式）
    const mine = last.get(s.aid);
    if (mine) { s.ltx = mine.left; s.lty = mine.top; }
    s.slots = measureSlots();
    s.first.clear();
    paint();
  }, [preview, cards, measureSlots, paint]);

  /**
   * 每次 `pointermove` 做的全部工作：跟手 + 判落点。
   *
   * ★★ **刻意不做 rAF 合并。** 评审建议把整套移动处理放进 rAF，那条针对的是
   *   「每次 move 都做 DOM 读取」的写法；而这里槽位矩形已经**缓存**下来，
   *   单次代价只有「写 1 个 transform + 比 9 个数字」，合并省不下什么。
   * ★★★ 而代价是实打实的：**`requestAnimationFrame` 在 Chrome headless 的
   *   `--virtual-time-budget` 下根本不触发**（2026-09-20 实测：单起一个 rAF 探针，
   *   300ms 内 `rafFired === false`）。把正确性挂在 rAF 上 = 让端到端闸**永远测不到**
   *   这条路径，而「测不到」和「测过了」在报告里长得一模一样。
   *   真正昂贵的 `setState` 仍然只在**落点真的变了**时才发生。
   */
  const onPointerMoved = useCallback((commitPreview: (ids: string[]) => void) => {
    const s = ses.current;
    if (!s) return;
    paint();
    // 命中用**缓存的槽位矩形**，不是实时 rect（后者含 transform，会形成反馈回路）
    let over: string | null = null;
    for (const sl of s.slots) {
      if (sl.aid === s.aid) continue;
      if (s.px >= sl.left && s.px <= sl.right && s.py >= sl.top && s.py <= sl.bottom) {
        over = sl.aid; break;
      }
    }
    if (!over) return;
    const from = s.ids.indexOf(s.aid);
    const to = s.ids.indexOf(over);
    if (from < 0 || to < 0 || from === to) return;
    // First：重排**之前**各卡的视觉位置（含在飞动画的当前位置）
    s.first = new Map(cards().map((el) => [el.dataset.aid ?? "", el.getBoundingClientRect()]));
    s.ids = moveItem(s.ids, from, to);
    commitPreview(s.ids);
  }, [paint, cards]);

  const finish = useCallback((ok: boolean,
                             commit: (next: string[]) => void | Promise<unknown>,
                             baseIds: string[]) => {
    const s = ses.current;
    if (!s) return;
    const next = s.ids;
    const el = s.el;
    ses.current = null;
    setDragAid(null);

    if (el) {
      // 回落：从当前跟手位置滑回它现在的格子
      const cur = el.style.transform;
      el.style.transform = "";
      const a = el.animate([{ transform: cur }, { transform: "none" }],
                           { duration: FLIP_MS, easing: FLIP_EASING, fill: "none" });
      a.finished.catch(() => { /* cancel */ });
      el.style.willChange = "";
    }

    // ★ 取消（Esc / 系统打断）**放弃**这次排序：codex 档的顺序就是计费顺序。
    if (!ok || next.join() === baseIds.join()) { setPreview(null); return; }
    // ★★ 落盘完成前**继续显示新顺序** —— 否则等 IPC + 刷新那段时间会闪回旧序。
    void Promise.resolve(commit(next)).finally(() => setPreview(null));
  }, []);

  /**
   * ★★ Esc 取消。**自定义 pointer 拖拽不会因为按 Esc 而收到 `pointercancel`** ——
   *   那是 HTML5 DnD 的行为。而 `useKeyboard` 只处理带 Meta 的键，也接不到。
   *   所以在拖拽期间自己挂一个全局监听。2026-09-20 由 codex 评审指出这条缺口。
   */
  const escRef = useRef<(() => void) | null>(null);
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
                                commit: (next: string[]) => void | Promise<unknown>): CardDragWiring => ({
    hint,
    isDragging: dragAid === aid,
    onStart: (x, y) => {
      const slots = measureSlots();
      const mine = slots.find((sl) => sl.aid === aid);
      const el = cards().find((e) => e.dataset.aid === aid) ?? null;
      ses.current = {
        aid, el, slots, ids: [...baseIds],
        p0x: x, p0y: y,
        l0x: mine?.left ?? 0, l0y: mine?.top ?? 0,
        ltx: mine?.left ?? 0, lty: mine?.top ?? 0,
        px: x, py: y, moved: false,
        first: new Map(),
      };
      if (el) el.style.willChange = "transform";
      // Esc 走同一条收尾路径，只是 `ok = false`（放弃排序）。在这里挂，因为只有
      // 这一刻才知道该用哪个 `commit` / `baseIds`。
      escRef.current = () => finish(false, commit, baseIds);
    },
    onMove: (x, y) => {
      const s = ses.current;
      if (!s) return;
      s.px = x; s.py = y;
      // ★ 位移够了才算真的在拖 —— 否则手抖会把一次点击变成排序
      if (!s.moved) {
        if (Math.abs(x - s.p0x) < START_SLOP && Math.abs(y - s.p0y) < START_SLOP) return;
        s.moved = true;
        setDragAid(aid);
        setPreview([...s.ids]);
      }
      onPointerMoved(setPreview);
    },
    onEnd: (ok) => finish(ok, commit, baseIds),
  }), [dragAid, cards, measureSlots, onPointerMoved, finish]);

  return { dragAid, preview, makeDrag };
}
