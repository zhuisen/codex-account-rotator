import React from "react";
import type { Theme } from "../theme";
import { relayRouteNote, type RouteStatus } from "../relay";

/**
 * 路由选择条 —— **账号池与中转站互斥单选**（用户 2026-09-09 定稿）。
 *
 * ## 为什么是一条互斥选择器，而不是两个开关
 *
 * 底层只有**一个** `relay/route.local.json`，`cxp` 每次启动读它决定用哪个 profile。
 * 也就是说"同时开着账号池和中转站"在物理上不存在。两个独立开关会让 UI 表达出一个
 * 后端表达不了的状态，而用户据此判断"钱扣在哪里" —— 这一类不一致给出的是**错误答案**。
 *
 * ## 三条不能省的实话
 *
 * ① **切到中转站 = 每次 `codex` 都在花钱。** 实测一句 trivial prompt 就 $0.0863
 *    （tokens used 39,513 —— 系统提示 + 工具定义就这么大，prompt 多短都没用）。
 *    所以中转站那一档照 `ProbeButton` 的先例走**两段确认**，账号池那一档不用。
 * ② **三种状态下代理会悄悄退回账号池**（`orphan` / `relay_disabled` / `route_corrupt`）——
 *    用户以为在按量付费，实际扣的是订阅额度。加上 `profile_missing`（codex 对它不报错，
 *    直接退回 base 配置：直连单号、不轮换、WS 全开），这四条是静默失败**唯一**会出声的地方。
 *    健康时不展开，只在异常时占视觉 —— 常亮的告警会被训练成噪音。
 * ③ **生效范围只有交互 shell 里的 `codex`**（它是 cxp 的 alias）。`\codex` / `cx` /
 *    VS Code / `omc ask codex` 走 PATH wrapper，不受此开关影响 —— 不写这一行，
 *    用户会以为切了之后所有入口都改了。
 */
/**
 * 路由状态说明条。**不再自己做选择器**（用户 2026-09-10：
 * 「单纯让路由不同的按钮选择，我感觉还是不适合目前项目的设计语言」）——
 * 选哪一条路由现在是**点卡片**，与账号池完全同一套词汇（`当前` 药丸徽章、
 * accent 描边、`切换` 实心按钮），见 `RelaySection`。
 *
 * 这里只剩两件事，都是"卡片上放不下、但少了会出人命"的话：
 * ① **六态里的异常态**。其中 `orphan` / `relay_disabled` / `route_corrupt` 三种下
 *    代理都会**退回账号池** —— 用户以为在按量付费、实际扣的是订阅额度。
 *    健康时用 muted 收敛，异常才上语义色。
 * ② **生效范围**。路由只影响走本地代理的那些入口；`cxd` 是单号直连的逃生口。
 */
export default function RouteNote({ t, route }: {
  t: Theme;
  route: RouteStatus | undefined;
}): React.ReactElement {
  const n = route ? relayRouteNote(route) : null;
  const tone = n?.tone === "ok" ? t.accent : n?.tone === "warn" ? "#E0901C" : "#E0524D";
  return (
    <div data-card="route" style={{
      background: t.cardBg, border: `1px solid ${n?.tone === "ok" ? t.cardBorder : tone}`,
      borderRadius: 13, padding: "10px 13px", marginBottom: 12,
    }}>
      {n && (
        <div data-route-state={route?.state}
             style={{ fontSize: 11.5, lineHeight: 1.6,
                      color: n.tone === "ok" ? t.muted : tone }}>
          <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 4,
                         background: tone, marginRight: 7 }} />
          <b style={{ color: n.tone === "ok" ? t.text : tone }}>{n.title}</b> —— {n.body}
        </div>
      )}
      <div style={{ fontSize: 10.5, color: t.muted, marginTop: 7, opacity: 0.85 }}>
        生效范围：走本地代理的入口（<code>codex</code> / <code>\codex</code> /
        VS Code / <code>omc ask codex</code>）。需要**单号直连**（例如跑 <code>/usage</code>
        看重置卡）用 <code>cxd</code>，它绕过代理、不受此选择影响。
      </div>
    </div>
  );
}
