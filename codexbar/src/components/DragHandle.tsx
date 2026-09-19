import { CARD_TYPE as Z, type Theme } from "../theme";

/**
 * 卡片右上角的拖拽手柄（⠿）。
 *
 * ★ 抽成一个件是因为 `AccountCard` 与 `AgyCard` 都要用 —— 同一条交互规则的两份实现
 *   必然分叉（本仓铁律），而这里要一致的东西不少：`stopPropagation` 的两处、
 *   与左上角 `⌘N` 角标对称的位置、以及拖拽中的高亮色。
 *
 * ★★ `onMouseDown` 必须 `stopPropagation`：卡片本身「点一下 = 选中并展开动作条」，
 *   不拦的话按下手柄会连带触发选中。`onClick` 那处拦的是**另一件事**（松手时的点击），
 *   两处都要，缺一个都会让点击穿透过去。
 */
export default function DragHandle({ t, dragging, onDown }: {
  t: Theme;
  dragging: boolean;
  onDown: () => void;
}) {
  return (
    <span
      onMouseDown={(e) => { e.stopPropagation(); onDown(); }}
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
  onHandleDown: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: () => void;
  draggable: boolean;
  isDragging: boolean;
  isOver: boolean;
}
