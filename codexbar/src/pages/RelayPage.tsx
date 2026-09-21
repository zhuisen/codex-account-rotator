import React, { useState } from "react";
import type { Theme } from "../theme";
import Seg from "../components/Seg";
import RelaySection from "../components/RelaySection";
import RelayUsage from "../components/RelayUsage";
import GhostButton from "../components/GhostButton";
import { IcRefresh } from "../components/CardIcons";
import { useRelayUsage } from "../hooks/useRelayUsage";

/**
 * 中转站 —— **独立版块**，页内再分「账号 / 用量」两块（用户 2026-09-09 定稿）。
 *
 * 演进留档，免得下一个人再走一遍：
 *   ① 最初拆进「总览」+「AI用量信息」两页 → 用户否：中转站的内容自成一体，
 *      混进别的页会让两边都变成拼盘。
 *   ② 改成单页平铺 → 用户否：「ui里面有两个版块切换啊。一个是账号，一个是用量」。
 *   ③ 现在：一页两块，用与全 app 同一个 `Seg` 切换。
 *
 * ## 两块各管什么
 *
 * - **账号**：路由（**账号池 ↔ 中转站互斥单选**）+ 中转站的增删改测。
 *   这里是这一页唯一会**花钱**的地方（切到中转站 = 之后每次 codex 都扣余额）。
 * - **用量**：与「AI用量信息」页**同结构** —— 同一批组件（`KpiStrip` / `StackedArea` /
 *   `Seg`）、同一个版面顺序（档位 → KPI 条 → 堆叠图 → 图例 → 模型表）。
 *
 * ## ★★ 底层已是「一个 provider，两种上游」
 *
 * 中转站不再有自己的 codex profile。codex 永远只看见 `rotateproxy` 一个
 * `model_provider`，账号池 ↔ 中转站的切换发生在**代理内部**
 * （`proxy.py::_relay_upstream`）。所以 `codex resume` 的会话列表**不再分裂** ——
 * 而 picker 是按 `model_provider` 过滤的，0.154 里没有任何配置键能放宽它。
 */
const TABS = ["accounts", "usage"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL = (v: Tab): string => (v === "accounts" ? "账号" : "用量");

export default function RelayPage({ t }: { t: Theme }): React.ReactElement {
  const [tab, setTab] = useState<Tab>("accounts");
  const { busy: usageBusy, refresh: refreshUsage } = useRelayUsage();
  return (
    <div data-page-body="relay" style={{ padding: 16, overflowY: "auto", height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12,
                    flexWrap: "wrap", rowGap: 8 }}>
        {/* ★ 标题**永不断字**：窄窗下曾把「总览」劈成「总 / 览」（用户 2026-08-24 截图）。 */}
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.01em",
                       whiteSpace: "nowrap" }}>中转站</span>
        <span style={{ fontSize: 11, color: t.muted, minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          第三方 OpenAI 协议中转 · 按量付费 · 与账号池互斥
        </span>
        {/* ★ 用全 app 同一个 `Seg`，不是另发明一种 tab —— 两种切换器长得不一样，
            用户要多认一种结构却什么也没多得到。 */}
        {/* ★ `flexShrink: 0`：同 `PlatformPage` 那条 —— 同排的说明文字自带省略号，
            该退让的是它不是控件。不加的话这组 Tab 会在窄窗里折成两行（同一类缺陷）。 */}
        {/* ★★ 「刷新余额」放在页头（用户 2026-09-21：「没看到刷新，或者刷新不显眼」）。
            在这之前刷新只有余额旁那个 **6×14px 的裸 ↻ 字形**（实测），无边框无底色、
            还坐在一行本来就发灰的小字里 —— 对比度不是问题（5.88），**它不像个控件、
            也几乎点不中**（可点目标通常要 ≥24px）。
            ★ 用与总览「刷新全池」**同一个 GhostButton + 同一个图标**：找刷新时眼睛先去的
              就是页头，而全 app 只该有一种「刷新」长相。余额旁那个小 ↻ 保留（就近可点）。
            ★ 三处共用同一个 `useRelayUsage`：`useQuotaSidecar` 有模块级 `_inflight`
              按 `runCmd` 去重 + `_subs` 广播，所以多挂一个消费者**不会**多发一次外网请求。 */}
        <div style={{ marginLeft: "auto", flexShrink: 0, display: "flex",
                      alignItems: "center", gap: 9 }}>
          <span data-act="relay-refresh-header">
            <GhostButton t={t} onClick={() => void refreshUsage()} loading={usageBusy}
                         loadingText="取余额中…">
              <IcRefresh spin={usageBusy} />刷新余额
            </GhostButton>
          </span>
          <span data-relay-tabs>
            <Seg opts={TABS} cur={tab} on={setTab} label={TAB_LABEL} t={t} />
          </span>
        </div>
      </div>

      {/* ★★ 两块**都挂载**、用 CSS 隐藏而不是条件渲染：
          `RelayUsage` 的档位选择、`RelaySection` 的编辑表单都是本地 state，
          条件渲染会在每次切 tab 时把它们清空 —— 用户填了一半的 key 会凭空消失。 */}
      <div style={{ display: tab === "accounts" ? "block" : "none" }}>
        <RelaySection t={t} />
      </div>
      <div style={{ display: tab === "usage" ? "block" : "none" }}>
        <RelayUsage t={t} />
      </div>
    </div>
  );
}
