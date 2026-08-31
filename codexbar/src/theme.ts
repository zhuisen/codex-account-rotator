/**
 * ★★ 中性文字只有**三级**，每一级都有实测对比度下限（用户 2026-08-23 定的 B 档）。
 *
 *   text   主数值            深 16.8 / 浅 6.6
 *   text2  次级、标签、邮箱   深  8.9 / 浅 6.6
 *   muted  三级:轴刻度/脚注/占比/上次刷新   深 4.55 / 浅 4.54（**最差底色**，不是最好的那个）
 *
 * ★ 阈值按**最差底色**定,不是按 appBg。用户选的 B 档原值 `#78828f`/`#6b7682` 在 appBg 上是
 *   4.85/4.08 看着达标,但在 cardBg/railBg 上只有 4.49/3.86 —— 只看一个底色就会漏掉。
 *   深色为此只亮了 1 级 RGB(肉眼无差),浅色压暗 11 级(它原本 2.74,本来就要修)。
 *
 * **原本是五级**（多出 `email` 和 `faint`），而那两个正是问题所在：
 *   · `faint` 深色底实算 **2.21:1**、浅色 **1.89:1** —— 连 WCAG 给图形的 3.0 都够不着，
 *     用户直接反馈「太灰了，快看不到了」。它被用在 41 处**要读的**内容上（轴刻度、占比、峰值）。
 *   · `email` 是按**用途**命名却占着一个**层级**，于是没人知道该用哪个 —— 五个灰的混乱由此而来。
 *
 * ⚠️ **同一个问题此前已被就地绕过两次**（`TrafficPage` 轮数、`KpiStrip` 单位，各留了一条
 *   「faint 实算 2.21:1」的注释就换了颜色）。第二次撞见同一类 bug，该交付的是**一个会变红的
 *   检查**而不是第三行注释 —— 见 `tests/test_theme_contrast.py`，它会挡住任何把中性色调暗到
 *   4.5 以下的改动。**别为了"更克制"往回调**，那条路已经走过一次了。
 *
 * 例外：饼图「其余」轨道仍用硬编码 `#454d57` —— 它是**非文字的装饰轨道**，不是要读的内容，
 * 不受这条标尺约束（`TrafficPage.tsx` 的 donut）。
 */
/**
 * 总览卡片（账号卡 + grok 卡）的**字号标尺**。
 *
 * 用户 2026-08-26 从 4 档 demo 里选的 **D 档「整体 +3（宽松）」**（起因：「里面的字太小了」）。
 * demo 留档：`~/Downloads/codexbar_card_type_demo_20260826.html`（含四档字号 × 三档配色，
 * 每档都渲染了实测真实尺寸 330×160 与最窄 207×180，并算了对比度）。
 *
 * ★★ **必须集中一处**，两个理由：
 *   ① 账号卡与 grok 卡并排在同一排网格里，字号差一点就看得出来；
 *   ② 这些数字之间**互相约束** —— 隐藏占位行要与真行等高、grok 页脚要与账号卡页脚等高，
 *      靠的就是两边读同一份数。散在两个文件里改，迟早只改一处，而症状是"卡片错开几像素"，
 *      不报错、只能靠截图发现（本轮已经栽过一次）。
 * ★ `PlanBadge` 的默认 `size` **不要动** —— 菜单栏行也用它，改默认值会连带把菜单栏放大。
 *   这里通过 `size={CARD_TYPE.planBadge}` 显式传入。
 */
export const CARD_TYPE = {
  name: 16.5, status: 12, planBadge: 10, useBadge: 10, curBadge: 10.5, delta: 11,
  email: 13, winLabel: 12, pct: 13, eta: 12, note: 12, exp: 12.5,
  ring: 58, ringR: 24, ringSw: 5, ringNum: 15, bar: 5, shortcut: 11,
  badgeFont: 12, badgeIcon: 12, badgePad: "3px 9px",
} as const;

/**
 * 平台详情页「模型消耗」宽表的**字号与列宽标尺**（用户 2026-08-26：「模型数字放大，现在太小了」）。
 *
 * 与 `CARD_TYPE` 同一口径：卡片那批用户选了 D 档「整体 +3」，这张表原本比它还小一档
 * （body 10.5 / 列头 9），所以按同样的比例抬（body 13 / 列头 11），两个界面才读起来是一套东西。
 *
 * ★★ **字号与列宽必须一起改**。这是 11 列的宽数据表，列宽是按 10.5px 的字量出来的；
 *    只放大字号会让数字列**串位或显示成 `###`** —— 而那看起来像数据错了，不像排版没跟上。
 *    列宽按 13/10.5 ≈ 1.24 缩放后重新实测自然宽，`min` 也要跟着抬（见 PlatformPage 的 TABLE_MIN）。
 * ★ 名字列一并加宽（180→210）：模型名已经在截断（`deepseek-pro/deepseek-v4-pro`），
 *   字号一大截得更狠。截断本身可接受（有 `title` 兜全称），但不该因为放大而更严重。
 */
export const TABLE_TYPE = {
  body: 13, colHead: 11, groupHead: 12, note: 11.5,
  dot: 14, name: 210, tok: 77, share: 55, rounds: 74, cost: 84,
  gap: 26, rateIn: 72, rateOut: 72, ratePerM: 92,
} as const;

export const THEMES = {
  dark: {
    isDark:true,
    appBg:"#0e1117", deskBg:"radial-gradient(130% 120% at 50% -10%, #151c26 0%, #080a0e 65%)",
    chromeBg:"#0c1015", chromeBorder:"rgba(255,255,255,.07)", titleText:"#cfd6df",
    // 标题栏内控件的 hover 底色。深色抬白、浅色压黑(设计规范:hover 在 Windows 上"变亮")。
    // Windows 的 ─ □ ✕ 用它;关闭键例外,hover 走固定的 #e81123(那是 Windows 的系统语义色)。
    chromeHoverBg:"rgba(255,255,255,.08)",
    railBg:"#0a0e12", railBorder:"rgba(255,255,255,.06)",
    text:"#eef2f7", text2:"#aab3c0", muted:"#798390",
    heroBg:"#131c20", heroBorder:"rgba(45,212,191,.25)", heroShadow:"none",
    cardBg:"#141a22", cardBorder:"rgba(255,255,255,.06)", curCardBg:"rgba(45,212,191,.07)",
    cardHoverShadow:"0 10px 26px rgba(0,0,0,.4)",
    divider:"rgba(255,255,255,.08)",
    accent:"#2dd4bf", accentText:"#06231f", accentTextSoft:"#9fe9df",
    accentSoft:"rgba(45,212,191,.10)", accentBorder:"rgba(45,212,191,.34)",
    ringTrack:"rgba(255,255,255,.09)", barTrack:"rgba(255,255,255,.09)",
    ghostBorder:"rgba(255,255,255,.12)", ghostText:"#aab3c0", ghostBg:"rgba(255,255,255,.02)",
    shadow:"0 28px 64px rgba(0,0,0,.5)",
    toastBg:"rgba(20,26,34,.94)", toastText:"#eef2f7", toastBorder:"rgba(45,212,191,.3)",
    sunBg:"transparent", sunColor:"#6b7480", moonBg:"#2dd4bf", moonColor:"#06231f",
  },
  light: {
    isDark:false,
    appBg:"#eef1f5", deskBg:"radial-gradient(130% 120% at 50% -10%, #f4f7fb 0%, #dbe1e9 100%)",
    chromeBg:"#f7f9fb", chromeBorder:"rgba(0,0,0,.1)", titleText:"#39414b",
    chromeHoverBg:"rgba(0,0,0,.06)",
    railBg:"#e7ebf0", railBorder:"rgba(0,0,0,.06)",
    text:"#161b22", text2:"#4d5663", muted:"#606b77",
    heroBg:"#ffffff", heroBorder:"rgba(14,159,142,.3)", heroShadow:"0 1px 3px rgba(0,0,0,.05)",
    cardBg:"#ffffff", cardBorder:"rgba(0,0,0,.07)", curCardBg:"rgba(14,159,142,.05)",
    cardHoverShadow:"0 10px 26px rgba(0,0,0,.12)",
    divider:"rgba(0,0,0,.1)",
    accent:"#0e9f8e", accentText:"#ffffff", accentTextSoft:"#0c8576",
    accentSoft:"rgba(14,159,142,.09)", accentBorder:"rgba(14,159,142,.4)",
    ringTrack:"rgba(0,0,0,.09)", barTrack:"rgba(0,0,0,.08)",
    ghostBorder:"rgba(0,0,0,.12)", ghostText:"#4d5663", ghostBg:"#ffffff",
    shadow:"0 28px 64px rgba(0,0,0,.18)",
    toastBg:"rgba(255,255,255,.97)", toastText:"#161b22", toastBorder:"rgba(14,159,142,.35)",
    sunBg:"#0e9f8e", sunColor:"#ffffff", moonBg:"transparent", moonColor:"#8a93a0",
  },
};

export type Theme = typeof THEMES.dark;

export const STATUS_COLORS: Record<string, string> = {
  live: "#27B26B", low: "#E0901C", cool: "#2BA0C0", dead: "#E0524D",
};
export const STATUS_TEXT: Record<string, string> = {
  live: "活", low: "低", cool: "冷却", dead: "死",
};

/** 模型配色。堆叠面积图里每个模型一条带,颜色必须稳定 —— 同一个模型在不同日期/不同窗口下
 *  换色就没法读了。未知模型走 fallback 的灰,不参与语义色。 */
export const MODEL_COLORS: Record<string, string> = {
  "gpt-5.6-sol":   "#2dd4bf",
  "gpt-5.6-luna":  "#2BA0C0",
  "gpt-5.6-terra": "#27B26B",
  "gpt-5.5":       "#8b5cf6",
  "gpt-5.4":       "#E0901C",
  "gpt-5.4-mini":  "#c08a3e",
  "gpt-5.3":       "#E0524D",

  // Claude 侧。分家族给色系,一眼能读出"这天主要在用哪一档":暖色=Opus、紫=Fable/Mythos、
  // 冷色=Sonnet/Haiku。同一家族按版本由新到旧依次变暗。
  "claude-opus-5":     "#D97757",
  "claude-opus-4-8":   "#E8A33D",
  "claude-opus-4-7":   "#B5793F",
  // 比 4-7 明显更暗:两者原来是 #B5793F / #8C6244,实测截图里图例色块几乎分不开(明度差太小)。
  // 家族内"越老越暗"既解决可辨性,本身也是自解释的。
  "claude-opus-4-6":   "#6E5138",
  "claude-fable-5":    "#7C6BF0",
  "claude-mythos-5":   "#A78BFA",
  "claude-sonnet-5":   "#2BA0C0",
  "claude-sonnet-4-6": "#2dd4bf",
  "claude-haiku-4-5":  "#27B26B",

  // Grok
  "grok-4.5-build": "#8b7cf6",
  "grok-4.5-code":  "#a78bfa",
  "grok-4":         "#6d5ce0",
  "grok-4-fast":    "#b8a9ff",

  // Kimi。平台色是粉,模型按新旧在同一色系内深浅排开(与 Claude/Grok 同规则)。
  "kimi-code/k3":     "#f472b6",
  "kimi-code/k3-256k": "#f9a8d4",
  "kimi-code/k2":     "#c2557f",
};
/** 平台品牌色(交接稿 §0/§10)。导航激活态、图层、图例、卡片描边统一走这里。 */
/**
 * 平台配色的**兜底**表。真值由 `traffic/scan.py` 的注册表随扫描结果一起下发
 * (`data.platforms[k].color`),前端优先用那个 —— 这样"加一家平台"只需改 scan.py 一处,
 * 不用再回来同步这里。这张表只在拿不到数据时(首扫前/该平台被停用)兜底。
 */
export const PLATFORM_COLORS: Record<string, string> = {
  claude: "#E0784F",
  codex:  "#2dd4bf",
  grok:   "#8b7cf6",
  kimi:   "#f472b6",
};
export const platformColor = (k: string): string => PLATFORM_COLORS[k] ?? "#5b6472";

/**
 * ★ **项目级规则:模型面积图里不出现灰色**(用户 2026-08-09 定稿)。
 *
 * 以前没登记的模型一律回落到一个死灰 `#5b6472`。问题有两层:一是灰在深色底上本来就发闷、跟
 * 背景和分隔线混在一起不好看;二是**多个未登记模型会共用同一个灰**,堆叠图上直接糊成一条带,
 * 看不出是几个模型 —— 而"新模型还没来得及登记"恰恰是最常见的状态(本机 gpt-5.6-sol、
 * kimi-code/k3 都曾是这样)。
 *
 * 所以兜底改成**按模型名做确定性散列取色**:同名恒同色(满足"同一模型换窗口不换色"这条老规矩),
 * 不同名基本不撞,且色相盘里**不含灰**。登记过的模型仍然优先用手挑的色 —— 手挑的能表达家族关系,
 * 散列表达不了。
 */
const FALLBACK_HUES = [
  "#f472b6", "#fb923c", "#facc15", "#4ade80", "#22d3ee",
  "#60a5fa", "#a78bfa", "#f87171", "#34d399", "#e879f9",
];

/** @deprecated 保留只为不破坏外部引用;新代码别用,见 `modelColor` 的散列兜底。 */
export const MODEL_FALLBACK = FALLBACK_HUES[0];

export function modelColor(m: string): string {
  const hit = MODEL_COLORS[m];
  if (hit) return hit;
  // djb2 的简化版。要的是"稳定 + 分散",不是密码学强度。
  let h = 5381;
  for (let i = 0; i < m.length; i++) h = ((h << 5) + h + m.charCodeAt(i)) | 0;
  return FALLBACK_HUES[Math.abs(h) % FALLBACK_HUES.length];
}
