import React from "react";
import { MONO } from "./RelayBits";
import { money, relayRouteNote, type RelayEntry, type RelayRow, type RouteStatus } from "../../relay";

/**
 * 「当前出口」两张同权卡 —— 1:1 复刻 `design_handoff_codexbar/中转站-交接说明.md` §1。
 *
 * ## 为什么是两张同权卡而不是一个开关
 *
 * 账号池与中转站是**同一个槽位的两个候选**，不是"主 + 备"。做成开关会暗示其中一个是默认态；
 * 做成两张同权卡，"现在走哪个出口"一眼可读，而这正是这一屏要回答的第一个问题。
 * 底层只有一个 `relay/route.local.json`，`proxy.py::_relay_upstream()` 每个请求读它决定
 * 往哪转发 —— "同时开着"在物理上不存在，所以 UI 也不该表达得出那个状态。
 *
 * ## 环的口径（设计稿 §3）
 *
 * 账号池 = 周额度 %（绿）；中转站 = `还能撑天数 / 30`，颜色按天数分档：
 * ≥14 绿 / 3–14 琥珀 / <3 或样本不足 红。
 * ★ 「样本不足」判成**红**而不是灰：它意味着"这个数我算不出来"，而余额正在被扣 ——
 *   把不确定画成中性色会让用户以为一切正常。
 */

/** 设计稿 §3 的状态色规则。`days === null` = 样本不足。 */
export function dayColor(days: number | null | undefined): string {
  if (days === null || days === undefined || days < 3) return "#E0524D";
  return days < 14 ? "#E0901C" : "#27B26B";
}

const RING = { size: 46, r: 18, w: 4.5 };
const CIRC = 2 * Math.PI * RING.r;          // 113.1

function Ring({ pct, color, label, labelSize }: {
  pct: number; color: string; label: string; labelSize: number;
}): React.ReactElement {
  const on = Math.max(0, Math.min(1, pct)) * CIRC;
  return (
    <div style={{ position: "relative", width: RING.size, height: RING.size, flex: "none" }}>
      <svg width={RING.size} height={RING.size} viewBox={`0 0 ${RING.size} ${RING.size}`}>
        <circle cx="23" cy="23" r={RING.r} fill="none"
                style={{ stroke: "rgba(255,255,255,.09)", strokeWidth: RING.w }} />
        <circle cx="23" cy="23" r={RING.r} fill="none" transform="rotate(-90 23 23)"
                style={{ stroke: color, strokeWidth: RING.w, strokeLinecap: "round",
                         strokeDasharray: `${on.toFixed(1)} ${CIRC.toFixed(1)}` }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center",
                    fontSize: labelSize, fontWeight: 700, fontFamily: MONO, color }}>
        {label}
      </div>
    </div>
  );
}

function Pill({ color, bg, children }: {
  color: string; bg: string; children: React.ReactNode;
}): React.ReactElement {
  return (
    <span style={{ fontSize: 9, fontWeight: 700, color, background: bg,
                   padding: "2px 7px", borderRadius: 999, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

/** 在用卡与未选中卡的两套皮（设计稿 §1）。 */
const SKIN = {
  on: { bg: "#0f1a1c", border: "rgba(45,212,191,.55)", shadow: "0 0 0 3px rgba(45,212,191,.08)",
        btnColor: "#06231f", btnBg: "#2dd4bf", btnBorder: "#2dd4bf" },
  off: { bg: "#10161d", border: "rgba(255,255,255,.08)", shadow: "none",
         btnColor: "#2dd4bf", btnBg: "transparent", btnBorder: "rgba(45,212,191,.4)" },
};

function Card({ active, onPick, ring, title, pill, sub, btn, id }: {
  active: boolean;
  onPick: () => void;
  ring: React.ReactElement;
  title: React.ReactNode;
  pill: React.ReactElement;
  sub: React.ReactNode;
  btn: string;
  id: string;
}): React.ReactElement {
  const s = active ? SKIN.on : SKIN.off;
  return (
    <div data-outlet={id} data-outlet-active={active ? "1" : undefined}
         onClick={active ? undefined : onPick}
         style={{ display: "flex", alignItems: "center", gap: 14, padding: "13px 16px",
                  borderRadius: 12, background: s.bg, border: `1px solid ${s.border}`,
                  boxShadow: s.shadow, cursor: active ? "default" : "pointer",
                  position: "relative", transition: "all .15s", minWidth: 0 }}>
      {active && (
        <span data-outlet-badge style={{
          position: "absolute", top: -8, left: 14, fontSize: 8.5, fontWeight: 800,
          letterSpacing: ".1em", color: "#06231f", background: "#2dd4bf",
          padding: "2px 7px", borderRadius: 4,
        }}>在用</span>
      )}
      {ring}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 15, fontWeight: 700 }}>{title}</span>
          {pill}
        </div>
        <div style={{ fontSize: 11, color: "#8a93a0", marginTop: 3, fontFamily: MONO }}>{sub}</div>
      </div>
      <span data-act={`outlet-${id}`} style={{
        fontSize: 11.5, fontWeight: 700, padding: "7px 14px", borderRadius: 8, flex: "none",
        color: s.btnColor, background: s.btnBg, border: `1px solid ${s.btnBorder}`,
        whiteSpace: "nowrap",
      }}>{btn}</span>
    </div>
  );
}

export default function OutletCards({ route, cur, curUsage, poolAccounts, poolPct,
                                      onPool, onRelay, usageBusy, onRefreshUsage }: {
  route: RouteStatus | undefined;
  /** 当前（或将要切到的）中转站。没有任何中转站时为 undefined。 */
  cur: RelayRow | undefined;
  curUsage: RelayEntry | undefined;
  poolAccounts: number;
  /** 账号池周额度剩余比例 0..1。读不到给 null —— **不画一个满环**。 */
  poolPct: number | null;
  onPool: () => void;
  onRelay: () => void;
  /** 余额/用量正在重取。★ 与用量块共用同一个 `useRelayUsage`，所以两处的转圈是同步的。 */
  usageBusy?: boolean;
  onRefreshUsage?: () => void;
}): React.ReactElement {
  const relayOn = route?.state === "relay";
  // ★ 六态的文案是**真源**（`relay.ts::relayRouteNote`），三方一致的那份 ——
  //   改版不能把它绕过去，否则 `relayRouteNote` 漏一个 case 就再也没人发现。
  //   健康的两态（pool/relay）不展开，只在异常时占视觉。
  const n0 = route ? relayRouteNote(route) : null;
  const note = route && route.state !== "pool" && route.state !== "relay" ? n0 : null;
  const d = curUsage?.data;
  /**
   * 这次没取到、显示的是上一次的余额。
   *
   * ★★ 判据取 `curUsage.stale`，**不是**自己拿 `fetched_at` 算岁数：后者分不出
   *   「这次取到了，只是数本来就没变」和「这次根本没取到」。前者由 `monitor.py`
   *   在**失败那一刻**写下（`res = {**res, "data": old, "stale": True, …}`），
   *   是一条事实，不是一个推断。
   */
  const stale = !!curUsage?.stale;
  const staleAgo = curUsage?.stale_since
    ? `${Math.max(1, Math.round((Date.now() / 1000 - curUsage.stale_since) / 60))} 分钟前`
    : "上一次";
  const days = d?.runway?.days ?? null;
  const dc = dayColor(days);
  // ★ 环上的字：`23d`。样本不足时写 `?d` —— 不写 `0d`，那是个具体的假数。
  const ringLabel = days === null ? "?d" : `${Math.round(days)}d`;
  const hint = days === null
    ? (d?.runway?.reason ?? "样本不足")
    : days < 3 ? "余额偏低" : `≈ ${Math.round(days)} 活跃日`;

  return (
    <div data-section="outlet">
      <div style={{ fontSize: 10, letterSpacing: ".1em", color: "#5b6470", fontFamily: MONO,
                    textTransform: "uppercase", marginBottom: 7 }}>
        当前出口 · 本地代理把请求发往
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 8 }}>
        <Card
          id="pool" active={!relayOn} onPick={onPool}
          ring={<Ring pct={poolPct ?? 0} color="#27B26B"
                      label={poolPct === null ? "?" : String(Math.round(poolPct * 100))}
                      labelSize={11} />}
          title="账号池"
          pill={<Pill color="#27B26B" bg="rgba(39,178,107,.14)">订阅 · 不额外花钱</Pill>}
          sub={`${poolAccounts} 个号 · 周额度 ${poolPct === null ? "—" : Math.round(poolPct * 100) + "%"} · 逐请求轮换`}
          btn={!relayOn ? "✓ 当前" : "切到账号池"}
        />
        <Card
          id="relay" active={relayOn} onPick={onRelay}
          ring={<Ring pct={days === null ? 0 : Math.min(days, 30) / 30} color={dc}
                      label={ringLabel} labelSize={9} />}
          title={`中转站 · ${cur?.label ?? cur?.id ?? "未配置"}`}
          pill={<Pill color="#E0A21C" bg="rgba(224,162,28,.14)">按量 · 真扣余额</Pill>}
          sub={
            <>
              {/* ★ 金额色**不随 stale 变**。我第一版写成 `#E0901C`(警告琥珀) vs
                  `#E0A21C`(金额琥珀) —— 两者肉眼分不出（本仓已记过这对的 ΔE 只有 2.6），
                  等于加了一个无效区分，还多造一个琥珀。旧读数靠下面那个 `*` 说。 */}
              余额 <b style={{ color: "#E0A21C" }}>{money(d?.balance ?? null, d?.unit)}</b>
              {/* ★★★ **余额是钱，所以"这是什么时候读的"必须跟着它走。**
                  在这之前这里只画一个数字：取数失败时 `monitor.py` 会保留旧 `data` 并标
                  `stale`（那是对的，"读不到"不能清空成 0），而这张卡**一个字都没说** ——
                  于是一个几小时前的余额和刚读到的余额长得一模一样。
                  ★ 琥珀不是红：数据是真的，只是旧的。红留给"确实没钱了"。 */}
              {stale && (
                <span data-relay-balance-stale
                      title={`这次没取到，显示的是${staleAgo}的读数${
                        curUsage?.detail ? ` —— ${curUsage.detail}` : ""}。点 ↻ 重取一次。`}
                      style={{ color: "#E0901C", fontWeight: 700, marginLeft: 3,
                               cursor: "help" }}>*</span>
              )}
              {/* ★ 刷新放在**余额旁边**，不是只放在下面那块用量里（本仓 §5d：
                  告警与操作要在眼睛已经在的地方）。两处走同一个 `useRelayUsage`，
                  所以点哪个都一样、转圈也同步。`/usage` 只读账单、**不计费**。 */}
              {onRefreshUsage && (
                <span data-act="relay-balance-refresh"
                      onClick={(e) => { e.stopPropagation(); if (!usageBusy) onRefreshUsage(); }}
                      title={usageBusy ? "正在重取…" : "重新取一次余额与用量（只读账单，不计费）"}
                      style={{ marginLeft: 5, fontFamily: MONO, fontSize: 10.5,
                               color: usageBusy ? "#5b6470" : "#8b93a1",
                               cursor: usageBusy ? "default" : "pointer", userSelect: "none" }}>
                  ↻
                </span>
              )}
              {" · 今日实扣 "}{money(d?.today?.actual_cost ?? null, d?.unit)}
              {" · "}<span style={{ color: dc }}>{hint}</span>
            </>
          }
          btn={relayOn ? "✓ 当前" : "切到中转站"}
        />
      </div>
      {/* ★★ 生效范围。**设计稿把 VS Code 写在"走本地代理"一侧，那一条与实测不符**：
          扩展自带 codex 二进制、从 `extensionUri` 拼路径启动、根本不查 PATH（唯一的覆盖项
          `chatgpt.cliExecutable` 自标 "DEVELOPMENT ONLY"、默认 null）；且它跑的是
          `app-server`，而 `app-server` 在 `codex-profile-scope.sh` 的黑名单里。
          两条独立理由任一条成立就够。照抄那句话会让用户在 VS Code 里以为自己在按量付费，
          而那个窗口里扣的是订阅额度 —— 所以这里**保留纠正后的文案**，版式仍按稿。 */}
      <div data-route-scope style={{ fontSize: 10.5, color: "#5b6470", marginBottom: 16,
                                     fontFamily: MONO }}>
        生效范围：codex / \codex / omc ask codex（走本地代理）·
        <b style={{ color: "#E0901C" }}> 不生效：VS Code</b>（自带二进制、不走 PATH）·
        单号直连用 cxd，不受此影响
      </div>
      {/* ★★★ **异常态必须在这里出声。**（设计稿没画异常态 —— 它的样例数据一切正常，
          但"稿里没有"不等于"可以不说"。）
          `orphan` / `relay_disabled` / `route_corrupt` 三种下代理会**退回账号池**：
          用户以为在按量付费、实际扣的是订阅额度；`profile_missing` 更隐蔽 ——
          codex 对它**不报错**，直接退回 base 配置（直连单号、不轮换、WS 全开），
          和正常运行长得一模一样。这四条是静默失败**唯一**会出声的地方。
          健康时收敛成 muted 一行，不上语义色 —— 常亮的告警会被训练成噪音。 */}
      {note && (
        <div data-route-state={route?.state}
             style={{ fontSize: 11, lineHeight: 1.6, marginTop: -10, marginBottom: 14,
                      fontFamily: MONO,
                      color: note.tone === "ok" ? "#5b6470"
                           : note.tone === "warn" ? "#E0901C" : "#E0524D" }}>
          <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 4,
                         marginRight: 7,
                         background: note.tone === "ok" ? "#27B26B"
                                   : note.tone === "warn" ? "#E0901C" : "#E0524D" }} />
          <b>{note.title}</b> —— {note.body}
        </div>
      )}
    </div>
  );
}
