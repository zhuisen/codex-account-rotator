import React, { useState } from "react";
import type { Theme } from "../theme";
import RouteNote from "./RouteBar";
import { MONO, RelayForm, Stat, relayBtn, relayCard } from "./relay/RelayBits";
import { useRelayConfig } from "../hooks/useRelayConfig";
import { useRelayUsage } from "../hooks/useRelayUsage";
import { money, runwayText, type RelayEntry, type RelayRow } from "../relay";

/**
 * 「总览」页里的中转站版块 —— **账号池的另一个槽位**（用户 2026-09-09 定稿）。
 *
 * ## 它和账号池是同一个池子里的两类槽位
 *
 * **选择方式是点卡片**，与总览的账号卡完全同一套词汇（`当前` 药丸徽章、accent 描边、
 * 实心「切换」按钮）。账号池自己也是其中一张卡 —— 它同样是一个可选项。
 * 底层只有一个 `relay/route.local.json`，代理据它决定往哪转发 ——
 * "同时开着"在物理上不存在，所以 UI 也不该表达得出那个状态。
 *
 * ## 这里只放「选哪个 / 增删改」，钱和 token 在「AI用量信息」页
 *
 * 卡片上只留最小的决策信息：余额、还能撑多久。完整的实扣/牌价/日柱图/模型表
 * 都在用量页 —— 一张卡上塞六个金额，用户分不清哪个是真付的。
 */
export default function RelaySection({ t }: { t: Theme }): React.ReactElement {
  const { cfg, note, acting, act } = useRelayConfig();
  const { snap } = useRelayUsage();
  const [editing, setEditing] = useState<Partial<RelayRow> | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [confirmSwitch, setConfirmSwitch] = useState<string | null>(null);
  const card = relayCard(t);
  const btn = relayBtn(t);

  return (
    <div data-section="relay" style={{ marginTop: 14 }}>
      <RouteNote t={t} route={cfg?.route} />

      {note && (
        <div data-card="note" style={{ ...card, borderColor: "#E0524D", color: "#E0524D", fontSize: 12 }}>
          {note}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>中转站</span>
        <span style={{ fontSize: 11, color: t.muted }}>
          点一张卡切换 · 与账号池<b>互斥</b>，同时只有一个在用
        </span>
        <span style={{ flex: 1 }} />
        {/* ★ 编辑态由 `editing` 驱动。`{}` 而不是 `null` —— `null` 表示"表单关着"。 */}
        {!editing && (
          <span data-act="add" style={btn(true)} onClick={() => setEditing({})}>+ 新增中转站</span>
        )}
      </div>

      {/* ★ 读失败与「没配过」必须分开。后者是一句关于事实的假陈述。 */}
      {cfg === null && (
        <div data-card="cfgerr" style={{ ...card, fontSize: 12.5, color: "#E0901C" }}>
          读不到中转站配置 —— <b>这不等于你没配过</b>。上面的红字是原因。
        </div>
      )}
      {cfg !== null && cfg.relays.length === 0 && !editing && (
        <div data-card="empty" style={{ ...card, fontSize: 12.5, color: t.muted }}>
          还没有中转站。点「+ 新增中转站」加一个 —— 加完它会作为一张卡出现在账号池旁边。
        </div>
      )}

      {/* ★★ 选择用**卡片**，与账号池同一套词汇（用户 2026-09-10 定稿）：
          `当前` 药丸徽章 + accent 描边 + 实心「切换」按钮。
          此前是一排独立 chip —— 那读起来像"几个动作"，而这是**互斥单选**，
          而且与总览那一屏的账号卡完全两种语言。 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
        {/* ── 账号池：它也是一个可选项，所以也是一张卡 ───────────── */}
        {(() => {
          const active = cfg?.route?.state === "pool";
          return (
            <div data-relay="pool" style={{
              ...card, marginBottom: 0,
              borderColor: active ? t.accentBorder : t.cardBorder,
              background: active ? t.curCardBg : t.cardBg,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>账号池</span>
                <span style={{ fontSize: 10.5, color: t.muted }}>代理轮换</span>
                {active && (
                  <span data-route-active="1"
                        style={{ marginLeft: "auto", fontSize: 10, fontWeight: 700, color: t.accent,
                                 border: `1px solid ${t.accentBorder}`, padding: "1px 7px",
                                 borderRadius: 999 }}>当前</span>
                )}
              </div>
              <div style={{ fontSize: 11, color: t.muted, marginTop: 6, lineHeight: 1.6 }}>
                订阅制，<b>不额外花钱</b>；逐请求轮换，撞额度要等重置。
              </div>
              <div style={{ display: "flex", gap: 7, marginTop: 11 }}>
                {active ? (
                  <span style={{ flex: 1, textAlign: "center", fontSize: 11, fontWeight: 600,
                                 color: t.accent, padding: "5px 0" }}>✓ 当前</span>
                ) : (
                  <span data-act="route-pool" title="切回账号池"
                        style={{ ...btn(true), flex: 1, textAlign: "center" }}
                        onClick={() => void act("route", "pool")}>
                    {acting === "route:pool" ? "切换中…" : "切换"}
                  </span>
                )}
              </div>
            </div>
          );
        })()}

        {(cfg?.relays ?? []).map((r) => {
          const u: RelayEntry | undefined = (snap?.relays ?? []).find((x) => x.id === r.id);
          const d = u?.data;
          const active = cfg?.route?.state === "relay" && cfg.route.profile === r.id;
          return (
            <div key={r.id} data-relay={r.id} style={{
              ...card, marginBottom: 0,
              borderColor: active ? t.accentBorder : t.cardBorder,
              background: active ? t.curCardBg : t.cardBg,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: t.text, whiteSpace: "nowrap" }}>
                  {r.label}
                </span>
                {/* ★ 与账号池卡、总览的 `AccountCard` **同一枚徽章**：accent 描边药丸。
                    此前这里是实心 `USE NOW`、那边是描边「当前」—— 同一个含义两种画法。 */}
                {active && (
                  <span data-route-active="1"
                        style={{ fontSize: 10, fontWeight: 700, color: t.accent,
                                 border: `1px solid ${t.accentBorder}`, padding: "1px 7px",
                                 borderRadius: 999 }}>当前</span>
                )}
                {!r.enabled && (
                  <span data-relay-off style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".04em",
                                 padding: "1px 6px", borderRadius: 5,
                                 border: `1px solid ${t.ghostBorder}`, color: t.muted }}>已停用</span>
                )}
                <span style={{ flex: 1 }} />
                {/* ★ 只显示指纹。列表里绝不出现完整 key。 */}
                <span data-key-fp style={{ fontSize: 10.5, color: t.muted, fontFamily: MONO }}>
                  {r.key_fp}
                </span>
              </div>
              <div style={{ fontSize: 10.5, color: t.muted, fontFamily: MONO, marginTop: 3,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.base_url}
              </div>

              {/* ★ 只放决策需要的两个数。完整口径在用量页 —— 一张卡上六个金额分不清哪个是真付的。 */}
              <div style={{ display: "flex", gap: 18, marginTop: 10, flexWrap: "wrap" }}>
                <Stat t={t} k="余额" v={money(d?.balance ?? null, d?.unit)} />
                <Stat t={t} k="还能撑" v={runwayText(d?.runway)} />
              </div>
              {u && !u.ok && u.state !== "disabled" && (
                <div data-relay-err style={{ fontSize: 11, color: "#E0901C", marginTop: 7 }}>
                  用量读不到（{u.state}）：{u.detail ?? "（对方没给原因）"}
                </div>
              )}

              <div style={{ display: "flex", gap: 7, marginTop: 11, flexWrap: "wrap" }}>
                {/* ★★ 主操作放最前，与 `AccountCard` 一致 —— 它是这张卡存在的理由。
                    ★ 切过去之后每次 codex 都在扣余额（实测一句 trivial prompt $0.0863），
                      所以照 `ProbeButton` 的先例走**两段确认**，确认态用金额琥珀。 */}
                {active ? (
                  <span style={{ flex: "1 1 auto", minWidth: 62, textAlign: "center", fontSize: 11,
                                 fontWeight: 600, color: t.accent, padding: "5px 0" }}>✓ 当前</span>
                ) : confirmSwitch === r.id ? (
                  <span data-act={`route-confirm-${r.id}`}
                        style={{ ...btn(true), background: "#E0A21C", borderColor: "#E0A21C",
                                 color: "#1b1405", flex: "1 1 auto", textAlign: "center" }}
                        onClick={() => { setConfirmSwitch(null); void act("route", r.id); }}>
                    确认？之后每次 codex 都扣费
                  </span>
                ) : (
                  <span data-act={`route-${r.id}`} title={`把路由切到 ${r.label}（按量付费）`}
                        style={{ ...btn(true), flex: "1 1 auto", minWidth: 62, textAlign: "center" }}
                        onClick={() => setConfirmSwitch(r.id)}>
                    {acting === `route:${r.id}` ? "切换中…" : "切换 · 💰按量"}
                  </span>
                )}
                <span data-act={`test:${r.id}`} style={btn()} onClick={() => void act("test", r.id)}>
                  {acting === `test:${r.id}` ? "测试中…" : "测试连接（免费）"}
                </span>
                <span data-act={`edit:${r.id}`} style={btn()}
                      onClick={() => setEditing({ ...r, key: "" } as Partial<RelayRow>)}>编辑</span>
                {/* ★ 停用/启用走 CLI 而不是前端记一份:真源是 relays.local.json,
                    代理在 app 没开时也要读它 —— 两个真源迟早分叉。 */}
                <span data-act={`toggle:${r.id}`} style={btn()}
                      onClick={() => void act("set", undefined, { ...r, key: "", enabled: !r.enabled })}>
                  {r.enabled ? "停用" : "启用"}
                </span>
                {confirmDel === r.id ? (
                  <span data-act={`del-confirm:${r.id}`}
                        style={{ ...btn(), borderColor: "#E0524D", color: "#E0524D" }}
                        onClick={() => { setConfirmDel(null); void act("remove", r.id); }}>
                    确认删除？
                  </span>
                ) : (
                  <span data-act={`del:${r.id}`} style={btn()}
                        onClick={() => setConfirmDel(r.id)}>删除</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {editing && (
        <div style={{ marginTop: 12 }}>
          <RelayForm t={t} editing={editing} setEditing={setEditing}
                     onSave={(payload) => act("set", undefined, payload)}
                     acting={acting === "set"} />
        </div>
      )}
    </div>
  );
}
