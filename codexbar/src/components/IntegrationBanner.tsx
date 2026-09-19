import type { Theme } from "../theme";
import DisclosureBanner, { type Tone } from "./DisclosureBanner";
import type { Integration, IntegrationState } from "../hooks/useIntegration";

/**
 * 「这台机器接没接上轮换」的披露条。
 *
 * ★ **不发明新组件**：直接复用 `DisclosureBanner`（本仓 §6「UI 交互不要自己发明」）。
 *   它本来就有 red / amber / muted 三档，正好对上这里要分的三种严重度。
 *
 * ★★ **五态 → 三色的映射只写在这里一份。** 总览与菜单栏两个 webview 都用它 ——
 *   两处各写一份 `state === "broken" ? 红 : 琥珀` 迟早分叉，而分叉的症状是
 *   「同一台机器，主界面说红、菜单栏说黄」，没有任何东西会为此报错。
 */
const PRESENT: Record<
  Exclude<IntegrationState, "ready">,
  { tone: Tone; badge: string; color: string; short: string }
> = {
  // 中性：不是故障，是「你只装了看板那一半」。用红色喊会让人去修一个没坏的东西。
  not_installed: { tone: "muted", badge: "未接入轮换", color: "#8a93a0",
                   short: "只装了看板那一半 · 见 INSTALL §2" },
  // 红：装了但断了 —— codex 对此不报错，会静默退回单号直连。
  broken: { tone: "red", badge: "接线断了", color: "#E0524D",
            short: "codex 正在静默直连 · 跑 codex-rotate integration" },
  // 琥珀：接线齐全，只差登录。与 broken 分开，否则只差一条命令的人会被赶去重装服务。
  no_accounts: { tone: "amber", badge: "池子为空", color: "#E0901C",
                 short: "池里没有号 · codex-rotate login" },
  // 琥珀：★ 判定不了 ≠ 没问题。绝不画成绿色或干脆不画。
  unknown: { tone: "amber", badge: "判定不了", color: "#E0901C",
             short: "配置读不到 · 跑 codex-rotate integration" },
};


/**
 * 把 CLI 那份文案整理成适合横幅的一行。
 *
 * ★ 文案归 CLI 所有（`codex_integration_gate()` 的 `lines`），这里只做**排版层**的清理，
 *   不改措辞 —— 那样「告警说什么」与「闸判什么」才永远同源。
 * ★★ 两处清理都是**像素验证抓出来的**（2026-09-19，harness 五态截图）：
 *   ① CLI 用 `**粗体**` 标重点，那是给终端看的 markdown，在 HTML 里会原样显示成星号；
 *   ② 每条都以「接入闸:」开头，而徽章里已经写了 —— 横幅上就成了「接线断了 接入闸:接线断了」。
 *   tsc 绿、测试绿、组件也确实渲染了，**只有看图才能发现**。
 */
function tidy(lines: string[]): string[] {
  return lines
    .map((l) => l.replace(/^[\u26a0\ufe0f\u2705\u2139\u2754\s]+/, "").trim())
    .map((l) => l.replace(/\*\*/g, ""))
    .map((l) => l.replace(/^接入闸[:：]\s*/, ""))
    .filter(Boolean);
}

/** 去掉正文开头与徽章重复的那几个字（像素验证抓出来的：「接线断了 · 接线断了 ——」）。 */
function dedupeBadge(text: string, badge: string): string {
  const t = text.startsWith(badge) ? text.slice(badge.length) : text;
  return t.replace(/^\s*(——|·|:|：|,|，)\s*/, "").trim() || text;
}

export default function IntegrationBanner({
  t,
  integration,
  compact = false,
}: {
  t: Theme;
  integration: Integration | null;
  /** 菜单栏 352px 下只留一行摘要；主界面给完整说明。 */
  compact?: boolean;
}) {
  // 还没读回来 —— 不画。**不是**画成绿色：这一瞬间我们确实不知道。
  if (!integration) return null;
  if (integration.state === "ready") return null;

  const p = PRESENT[integration.state];
  if (!p) return null;

  // 文案归 CLI 所有（`codex_integration_gate()` 的 `lines`），这里只负责排版。
  // ★ 这样「告警说什么」与「闸判什么」永远同源，不会出现界面还在说旧事实的情况。
  const body = tidy(integration.lines);
  const note = compact ? p.short : dedupeBadge(body.join(" "), p.badge);

  return <DisclosureBanner t={t} tone={p.tone} badge={p.badge} note={note} />;
}

/**
 * 给菜单栏用的同一份判定。
 *
 * ★★ 菜单栏 352px 下用它自己的 `.mb-banner-slim` 像素（与重置卡横幅同形），
 *   但**五态 → 颜色/徽章/文案的映射只有这一份**。两处各写一遍的症状是
 *   「主界面说红、菜单栏说黄」，而没有任何东西会为此报错。
 */
export function presentIntegration(integration: Integration | null):
  { color: string; badge: string; text: string } | null {
  if (!integration || integration.state === "ready") return null;
  const p = PRESENT[integration.state];
  if (!p) return null;
  // ★ 菜单栏只有 352px —— 给**短动作句**，全文进 `title`。第一版直接塞 `lines[0]`，
  //   实测右侧被整句裁掉（harness 352×640 截图），而裁切比不显示更糟：看不见又没有滚动提示。
  return { color: p.color, badge: p.badge, text: p.short };
}
