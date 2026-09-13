import type React from "react";

/**
 * 账号卡动作条上的图标与按钮。**账号卡（codex）与 agy 卡共用这一份。**
 *
 * ★★ 抽出来的理由与 `KpiStrip` / `PageSub` 一字不差：两张卡各写一份图标与按钮，
 *   下次调尺寸/配色必然只改一边，而那**不会报任何错** —— 本仓已经因此漂过两次。
 *   2026-09-13 用户要求「gemini 的功能 1:1 同步上 codex」时，这份就是第一个要共用的东西。
 *
 * ★ **不用 emoji**（全局 `ui-design.md` 的「禁忌」明写）：emoji 在不同系统/字体下
 *   会变彩色、变宽窄，与等宽仪表风格直接冲突。这里是单色描边 SVG，与侧栏图标同族。
 */
/** 动作条图标。★ **不用 emoji** —— 全局 `ui-design.md` 的「禁忌」里明写「emoji 做图标」,
 *  而且 emoji 在不同系统/字体下会变彩色、变宽窄,与等宽仪表风格直接冲突。
 *  用户给了两个选项(emoji / 一两个字符),这里取后者的等价物:**单色描边 SVG**,
 *  与侧栏图标同族,尺寸与颜色都可控。全名走 `title` 悬浮。 */
export const IcRotate = ({ off }: { off: boolean }): React.ReactElement => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 12a9 9 0 0 1 15.5-6.2M21 12a9 9 0 0 1-15.5 6.2"/><path d="M18 3v4h-4M6 21v-4h4"/>
    {/* 停用态额外画一道斜杠 —— **只靠颜色区分是不够的**:红绿色盲下两态会同色 */}
    {off && <path d="M4 20 20 4" stroke="currentColor" strokeWidth="2.2"/>}
  </svg>
);
export const IcPen = (): React.ReactElement => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3z"/></svg>
);
export const IcInfo = (): React.ReactElement => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.6v.2"/></svg>
);
export const IcTrash = (): React.ReactElement => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/></svg>
);

/** 动作条上的图标按钮。**全名只在 `title` 里** —— 用户 2026-09-07:「精简成一两个字符,
 *  鼠标悬浮才展示完整的名字」。★ 一律 34×26 定宽:图标宽度不一时按钮会参差,
 *  而参差的按钮行看着就像没对齐。 */
export function IconBtn({ title, onClick, color, border, bg, children }: {
  title: string; onClick: () => void; color: string; border: string; bg?: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <span onClick={onClick} title={title} aria-label={title}
          style={{ width: 34, height: 26, flexShrink: 0, display: "grid", placeItems: "center",
                   borderRadius: 6, cursor: "pointer", color,
                   border: `1px solid ${border}`, background: bg ?? "transparent",
                   transition: "background .15s, color .15s" }}>{children}</span>
  );
}
