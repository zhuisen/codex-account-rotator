import type { Theme } from "../theme";

/**
 * 分段控件(今日｜7d｜14d｜30d｜90d / 分模型｜总量)。
 *
 * ★ 必须定义在**模块作用域**,不能写在页面组件的 render 里。写在 render 里时它每次渲染都是一个
 * **新的组件类型**,React 会把整组控件卸载重建 —— 声明的 CSS transition 变成死代码,并且每次
 * hover/切档都在做 DOM 增删,表现为点击档位的卡顿掉帧(用户 2026-08-09 报"明显的卡顿和掉帧",
 * 三方评审此前也标过同一条)。
 */
export default function Seg<T extends string | number>({ opts, cur, on, label, t }: {
  opts: readonly T[];
  cur: T;
  on: (v: T) => void;
  label: (v: T) => string;
  t: Theme;
}): React.ReactElement {
  return (
    <div style={{ display: "flex", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`, borderRadius: 9,
                  // ★ 900px 实测:六个档位「分模型/总量/今日/7d/14d/30d」被压成三行竖排
                  //   (探针:内容高 48/行高 13)。与总览头部按钮同一个病根。
                  flexWrap: "wrap", rowGap: 2 }}>
      {opts.map((o) => (
        <span key={String(o)} onClick={() => on(o)} style={{
          whiteSpace: "nowrap", flexShrink: 0,
          padding: "4px 11px", borderRadius: 7, fontSize: 11, cursor: "pointer", userSelect: "none",
          fontFamily: "'JetBrains Mono'", transition: "background .2s, color .2s",
          fontWeight: cur === o ? 700 : 400,
          color: cur === o ? t.accentText : t.muted,
          background: cur === o ? t.accent : "transparent",
        }}>{label(o)}</span>
      ))}
    </div>
  );
}
