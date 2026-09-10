import React, { useState } from "react";
import type { Theme } from "../theme";
import Seg from "../components/Seg";
import RelaySection from "../components/RelaySection";
import RelayUsage from "../components/RelayUsage";

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
        <div style={{ marginLeft: "auto" }} data-relay-tabs>
          <Seg opts={TABS} cur={tab} on={setTab} label={TAB_LABEL} t={t} />
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
