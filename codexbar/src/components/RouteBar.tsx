import React, { useState } from "react";
import type { Theme } from "../theme";
import { relayRouteNote, type RelayRow, type RouteStatus } from "../relay";

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
export default function RouteBar({ t, relays, route, acting, onRoute }: {
  t: Theme;
  relays: RelayRow[];
  route: RouteStatus | undefined;
  acting: string | null;
  onRoute: (target: string) => void;
}): React.ReactElement {
  const [confirm, setConfirm] = useState<string | null>(null);
  const n = route ? relayRouteNote(route) : null;
  const tone = n?.tone === "ok" ? t.accent : n?.tone === "warn" ? "#E0901C" : "#E0524D";
  // ★ 当前选中项。`pool` 态时 `route.profile` 是 `rotateproxy`（账号池自己的 profile 名），
  //   **不是**某个中转站 id —— 用 `state` 判档位，用 `profile` 只做展示。
  const current = route?.state === "pool" ? "pool" : route?.profile ?? null;

  /**
   * ★★ 选中态必须**一眼可辨**（用户 2026-09-09：「中转站的选择池，不够明显」）。
   *
   * 原来选中只是"淡背景 + accent 描边"，与未选中的描边 chip 差别太小 ——
   * 而这是全 app **唯一一个会改变钱去哪儿**的选择器，认错的代价是真金白银。
   * 改成与 `Seg` 同一套语义：**选中 = 实心填充 + 反白文字 + 加粗**，
   * 未选中一律透明。整组套在一个带边框的容器里，形状上就说明"这几个里挑一个"。
   */
  const chip = (active: boolean, danger = false): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: 6,
    fontSize: 12, fontWeight: active ? 700 : 600, padding: "6px 14px", borderRadius: 7,
    cursor: active ? "default" : "pointer", userSelect: "none", whiteSpace: "nowrap",
    border: "1px solid transparent",
    // ★ 颜色分工:**选中恒用品牌青**（本仓规范:accent 专属"当前生效"这一个含义，
    //   两种填充色混在同一个单选组里反而读不出谁是选中）。琥珀留给两处**钱**的语义 ——
    //   未选中的中转站档用琥珀描边 + `💰按量付费`，以及点下去后那个二次确认（`danger`）。
    color: active ? (danger ? "#1b1405" : t.accentText) : danger ? "#E0A21C" : t.muted,
    background: active ? (danger ? "#E0A21C" : t.accent) : "transparent",
    transition: "background .2s, color .2s",
  });

  return (
    <div data-card="route" style={{
      background: t.cardBg, border: `1px solid ${tone}`, borderRadius: 13,
      padding: "11px 13px", marginBottom: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", rowGap: 7 }}>
        <span style={{ width: 8, height: 8, borderRadius: 4, background: tone, flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 700, color: t.text, whiteSpace: "nowrap" }}>当前路由</span>
        {/* ★ 整组套一个带边框的容器 —— 形状上就说明"这几个里挑一个"（与 `Seg` 同形）。
            分散的独立按钮读起来像"几个动作"，而这里是**互斥单选**。 */}
        <div data-route-group
             style={{ display: "flex", gap: 3, padding: 3, borderRadius: 9,
                      border: `1px solid ${t.ghostBorder}`, background: t.cardBg,
                      flexWrap: "wrap", rowGap: 3 }}>

        {/* ── 账号池档 ───────────────────────────────────────── */}
        <span data-act="route-pool" data-route-active={current === "pool" ? "1" : undefined}
              style={chip(current === "pool")}
              onClick={() => { setConfirm(null); if (current !== "pool") onRoute("pool"); }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%",
                         background: current === "pool" ? t.accent : t.muted }} />
          {acting === "route:pool" ? "切换中…" : "账号池（轮换）"}
        </span>

        {/* ── 中转站各档 ─────────────────────────────────────── */}
        {relays.map((r) => {
          const active = current === r.id;
          if (active) {
            return (
              <span key={r.id} data-act={`route-${r.id}`} data-route-active="1" style={chip(true)}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: t.accent }} />
                {r.label} · 💰按量
              </span>
            );
          }
          // ★★ 全 app 第二个会花钱的控件（第一个是 ProbeButton）。两段确认。
          return confirm === r.id ? (
            <span key={r.id} data-act={`route-confirm-${r.id}`}
                  style={{ ...chip(false, true), background: "#E0A21C", color: "#fff", borderColor: "#E0A21C" }}
                  onClick={() => { setConfirm(null); onRoute(r.id); }}>
              确认切到 {r.label}？之后每次 codex 都扣费
            </span>
          ) : (
            <span key={r.id} data-act={`route-${r.id}`} style={chip(false, true)}
                  onClick={() => setConfirm(r.id)}>
              {acting === `route:${r.id}` ? "切换中…" : `${r.label} · 💰按量付费`}
            </span>
          );
        })}

        </div>
        <span style={{ flex: 1 }} />
      </div>

      {/* ★★ **六个态都要渲染出来，健康态也是。** 一度只在异常时才画这一行，理由是
          "常亮的告警会被训练成噪音" —— 但那条理由只适用于**告警**，这一行在健康时
          是状态描述（"订阅制、不额外花钱"），不是告警。

          更要紧的是：`relayRouteNote` 漏一个 case 就返回 `undefined`，整块**不渲染**，
          而"卡片没了"和"一切正常"在截图里长得一模一样。只在异常时渲染的话，
          那条唯一能发现漏 case 的双向闸（本态标记在、另外五个不在）就失去了判别力。
          健康态用 muted 收敛视觉，异常态才上语义色。 */}
      {n && (
        <div data-route-state={route?.state}
             style={{ fontSize: 11.5, marginTop: 8, lineHeight: 1.6,
                      color: n.tone === "ok" ? t.muted : tone }}>
          <b style={{ color: n.tone === "ok" ? t.text : tone }}>{n.title}</b> —— {n.body}
        </div>
      )}
      <div style={{ fontSize: 10.5, color: t.muted, marginTop: 7, opacity: 0.85 }}>
        生效范围：终端里的 <code>codex</code> 命令。<code>\codex</code> / <code>cx</code> /
        VS Code / <code>omc ask codex</code> 走另一条入口，<b>不受此开关影响</b>。
      </div>
    </div>
  );
}
