import React, { useState } from "react";
import type { Theme } from "../theme";
import RouteBar from "./RouteBar";
import { MONO, RelayForm, Stat, relayBtn, relayCard } from "./relay/RelayBits";
import { useRelayConfig } from "../hooks/useRelayConfig";
import { useRelayUsage } from "../hooks/useRelayUsage";
import { money, runwayText, type RelayEntry, type RelayRow } from "../relay";

/**
 * 「总览」页里的中转站版块 —— **账号池的另一个槽位**（用户 2026-09-09 定稿）。
 *
 * ## 它和账号池是同一个池子里的两类槽位
 *
 * 上面的 `RouteBar` 是**互斥单选**：账号池（轮换）或某一个中转站，二选一。
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
  const card = relayCard(t);
  const btn = relayBtn(t);

  return (
    <div data-section="relay" style={{ marginTop: 14 }}>
      <RouteBar t={t} relays={cfg?.relays ?? []} route={cfg?.route} acting={acting}
                onRoute={(target) => void act("route", target)} />

      {note && (
        <div data-card="note" style={{ ...card, borderColor: "#E0524D", color: "#E0524D", fontSize: 12 }}>
          {note}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>中转站</span>
        <span style={{ fontSize: 11, color: t.muted }}>
          第三方 OpenAI 协议中转 · 按量付费 · 与账号池互斥
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
          还没有中转站。点「+ 新增中转站」加一个 —— 加完它就会出现在上面的路由选择里。
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
        {(cfg?.relays ?? []).map((r) => {
          const u: RelayEntry | undefined = (snap?.relays ?? []).find((x) => x.id === r.id);
          const d = u?.data;
          const active = cfg?.route?.state === "relay" && cfg.route.profile === r.id;
          return (
            <div key={r.id} data-relay={r.id} style={{
              ...card, marginBottom: 0,
              borderColor: active ? t.accentBorder : t.cardBorder,
              background: active ? t.accentSoft : t.cardBg,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: t.text, whiteSpace: "nowrap" }}>
                  {r.label}
                </span>
                {active && (
                  <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".04em",
                                 padding: "1px 6px", borderRadius: 5,
                                 background: t.accent, color: t.accentText }}>USE NOW</span>
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
