import { CARD_TYPE as Z, type Theme } from "../theme";

/**
 * 卡片右上角的拖拽手柄（⠿）。
 *
 * ★ 抽成一个件是因为 `AccountCard` 与 `AgyCard` 都要用 —— 同一条交互规则的两份实现
 *   必然分叉（本仓铁律）。
 *
 * ## ★★★ 为什么 `draggable` 在**手柄自己**身上，而不是在卡片根节点上
 *
 * 第一版是「按下手柄 → `setState` 打开卡片根节点的 `draggable`」。**在 WKWebView 上不工作**
 * （用户 2026-09-20 实测：能拖，但位置不变）：
 *
 *   · **WebKit 在 `mousedown` 那一刻就判定这个元素能不能拖**，而 React 的 `setState` 是异步的
 *     —— 等重渲染把 `draggable` 打开时，拖拽手势早已按「不可拖」处理掉了。
 *     Chrome 判定得晚，所以 harness 里一路绿，真机上从第一步就没起来。
 *
 * 现在手柄**恒为 `draggable`**，不需要任何异步 arming：按住它就能拖，而卡片其余部分
 * 照旧「点一下 = 选中」。拖拽影像用 `setDragImage` 换成整张卡，手感与拖卡片一致。
 *
 * ## ★★★ `setData` 不是可选的
 *
 * WebKit 要求 `dragstart` 里往 dataTransfer 写点东西，否则**拖拽数据仓为空、`drop` 根本不派发**。
 * Chrome 宽容，所以同样的代码在 harness 里能跑通 —— 这正是「Chrome headless ≠ WKWebView」
 * 那条本仓铁律的又一个实例（上次是 `zoom`）。
 *
 * ## 两处 `stopPropagation` 都要
 *
 * `onMouseDown` 拦的是「按下就选中」，`onClick` 拦的是「松手后的点击」。缺一个都会让
 * 点击穿透成「选中并展开动作条」。
 */
export default function DragHandle({ t, dragging, dragId, cardRef, onStart, onEnd }: {
  t: Theme;
  dragging: boolean;
  /** 写进 dataTransfer 的身份。★ 内容本身不重要，**有没有写**才重要（见上）。 */
  dragId: string;
  /** 卡片根节点 —— 用它当拖拽影像，否则拖起来的是这个 12px 的小手柄。 */
  cardRef: React.RefObject<HTMLDivElement | null>;
  onStart: () => void;
  onEnd: () => void;
}) {
  return (
    <span
      draggable
      onDragStart={(e) => {
        // ★★★ WebKit 没有这一句就不派发 drop。`effectAllowed` 同理要显式给。
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", dragId);
        const el = cardRef.current;
        if (el) {
          const r = el.getBoundingClientRect();
          // 拖整张卡的影像，而不是这个小手柄
          e.dataTransfer.setDragImage(el, r.width - 20, 16);
        }
        onStart();
      }}
      onDragEnd={onEnd}
      onMouseDown={(e) => { e.stopPropagation(); }}
      onClick={(e) => e.stopPropagation()}
      title="按住拖动可调整卡片顺序（⌘N 会跟着新顺序走）"
      style={{
        position: "absolute", top: 4, right: 8, padding: "2px 4px",
        fontSize: Z.shortcut, lineHeight: 1, cursor: "grab",
        color: dragging ? t.accent : t.muted,
        opacity: dragging ? 1 : 0.55,
        fontFamily: "'JetBrains Mono'", userSelect: "none",
      }}
    >⠿</span>
  );
}

/** 拖拽接线的形状。两张卡片共用，省得各写一份 props。 */
export interface DragWiring {
  /** 这张卡的身份，写进 dataTransfer（WebKit 要求非空）。 */
  dragId: string;
  onDragStart: () => void;
  onDragEnd: () => void;
  /** ★ 必须 `preventDefault()`，否则浏览器不允许在这里 drop。 */
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  isDragging: boolean;
  isOver: boolean;
}
