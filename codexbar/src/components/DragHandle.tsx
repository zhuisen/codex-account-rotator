import { CARD_TYPE as Z, type Theme } from "../theme";

/**
 * 卡片右上角的拖拽手柄（⠿）。
 *
 * ## ★★★ 为什么**不用** HTML5 drag-and-drop（2026-09-20 重做）
 *
 * 用户连报两次「能拖拽，但是改变不了卡片的位置」。真因是 **Tauri 窗口的
 * `dragDropEnabled` 默认为 `true`**，它的**原生拖放处理器会吞掉 webview 里的
 * HTML5 拖拽事件** —— `drop` 根本到不了页面。而 harness 跑在 Chrome，没有那层拦截，
 * 所以端到端闸一路绿、真机从第一步就不成立。
 *
 * ⚠️ 在此之前我还修了两条**真实但不是拦路的** WebKit 要求（`dragstart` 必须
 *   `setData`、`draggable` 不能异步打开）。它们都成立，只是上面还压着 Tauri 那一层。
 *   **「找到一个真原因」不等于「找到那个原因」** —— 这一轮的教训。
 *
 * 现在改用 **pointer 事件**：不依赖任何 DnD 语义、不会被任何原生层拦截，
 * 而且能做到用户要的**实时让位**（拖到哪儿其余卡片当场移开）——
 * 那是 HTML5 DnD 做不到的，它的拖拽影像是一张静态快照。
 *
 * ## 两处拦截都要
 *
 * `onPointerDown` 拦的是「按下就选中」，`onClick` 拦的是「松手后的点击」。
 * 缺一个都会让点击穿透成「选中并展开动作条」。
 */
export default function DragHandle({ t, dragging, hint, onStart, onMove, onEnd }: {
  t: Theme;
  dragging: boolean;
  /**
   * 悬浮说明。**两档含义不同，所以文案必须由调用方给**：
   *   · codex 档 —— 顺序**就是轮换优先级**，一拖就改变钱花在哪个号上；
   *   · gemini 档 —— 纯摆放顺序，不影响任何东西。
   * ★ 写死一句「调整卡片顺序」会在 codex 档变成**一句关于事实的假陈述**。
   */
  hint: string;
  onStart: (x: number, y: number) => void;
  onMove: (x: number, y: number) => void;
  onEnd: (commit: boolean) => void;
}) {
  return (
    <span
      data-drag-handle
      onPointerDown={(e) => {
        e.stopPropagation();
        e.preventDefault();
        // ★★ 捕获指针：之后所有 move/up 都送到这个元素，哪怕鼠标早已移出它。
        //   不捕获的话鼠标一离开这 12px 就断线 —— 而拖拽本来就是要离开它。
        e.currentTarget.setPointerCapture(e.pointerId);
        onStart(e.clientX, e.clientY);
      }}
      onPointerMove={(e) => { if (dragging) onMove(e.clientX, e.clientY); }}
      onPointerUp={(e) => {
        if (!dragging) return;
        e.stopPropagation();
        try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* 已释放 */ }
        onEnd(true);
      }}
      // ★ 取消（Esc、系统手势打断）必须**放弃**这次排序，不能当成落点 ——
      //   否则一次误操作就改掉顺序，而 codex 档的顺序就是计费顺序。
      onPointerCancel={() => { if (dragging) onEnd(false); }}
      onClick={(e) => e.stopPropagation()}
      title={hint}
      style={{
        position: "absolute", top: 4, right: 8, padding: "2px 4px",
        fontSize: Z.shortcut, lineHeight: 1,
        cursor: dragging ? "grabbing" : "grab",
        color: dragging ? t.accent : t.muted,
        opacity: dragging ? 1 : 0.55,
        fontFamily: "'JetBrains Mono'", userSelect: "none",
        touchAction: "none",          // 别让系统先把它解释成滚动
      }}
    >⠿</span>
  );
}

/** 拖拽接线的形状。两张卡片共用，省得各写一份 props。 */
export interface DragWiring {
  hint: string;
  isDragging: boolean;
  onStart: (x: number, y: number) => void;
  onMove: (x: number, y: number) => void;
  onEnd: (commit: boolean) => void;
}
