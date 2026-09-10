import React, { useState } from "react";
import type { Theme } from "../../theme";
import { MONO } from "./RelayBits";
import { dayColor } from "./OutletCards";
import { money, type RelayEntry, type RelayRow } from "../../relay";

/**
 * 中转站列表 —— 1:1 复刻 `中转站-交接说明.md` §1 的表格与 §2 的 `···` 菜单。
 *
 * 从大卡片压成表格行是设计稿的明确目标（"② 中转站从大卡片压成表格行，操作收进图标"）：
 * 两三家中转站时卡片阵列会把一屏撑满，而这一屏真正要回答的是"现在走哪个出口"。
 *
 * ★ 整行可点 = 切换出口；行内图标钮 `stopPropagation`（设计稿 §8）。
 */

const COLS = "190px 1fr 96px 190px 150px";

/** 识别色。设计稿给每站一个点色；本仓的规矩是**同名恒同色**，所以按 id 散列。 */
const DOTS = ["#4d9fff", "#2dd4bf", "#8b7cf6", "#E0A21C", "#27B26B", "#E0784F"];
export function relayDot(id: string): string {
  let h = 5381;
  for (let i = 0; i < id.length; i++) h = ((h << 5) + h + id.charCodeAt(i)) | 0;
  return DOTS[Math.abs(h) % DOTS.length];
}

function IconBtn({ title, onClick, color, children, id }: {
  title: string; onClick: (e: React.MouseEvent) => void; color?: string;
  children: React.ReactNode; id: string;
}): React.ReactElement {
  return (
    <span data-act={id} title={title} onClick={onClick}
          style={{ width: 26, height: 26, borderRadius: 7, display: "grid", placeItems: "center",
                   color: color ?? "#6b7480", border: "1px solid rgba(255,255,255,.1)",
                   cursor: "pointer", flex: "none", fontSize: 11, lineHeight: 1 }}>
      {children}
    </span>
  );
}

export default function RelayTable({ t, rows, usage, activeId, acting, onPick, onTest, onEdit, onToggle, onRemove, onAdd }: {
  t: Theme;
  rows: RelayRow[];
  usage: RelayEntry[];
  /** 当前路由指向的中转站 id；走账号池时为 null。 */
  activeId: string | null;
  acting: string | null;
  onPick: (id: string) => void;
  onTest: (id: string) => void;
  onEdit: (r: RelayRow) => void;
  onToggle: (r: RelayRow) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
}): React.ReactElement {
  const [menu, setMenu] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>中转站</span>
        <span style={{ fontSize: 11, color: "#6b7480" }}>点行切换 · 同时只有一个在用</span>
        <span data-act="add" onClick={onAdd} style={{
          marginLeft: "auto", fontSize: 11.5, fontWeight: 700, color: "#2dd4bf",
          padding: "6px 12px", border: "1px solid rgba(45,212,191,.4)", borderRadius: 8,
          cursor: "pointer",
        }}>+ 新增</span>
      </div>

      <div style={{ background: "#10161d", border: "1px solid rgba(255,255,255,.07)",
                    borderRadius: 13, overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: COLS, gap: 14, padding: "8px 16px",
                      fontFamily: MONO, fontSize: 9.5, letterSpacing: ".08em", color: "#5b6470",
                      textTransform: "uppercase",
                      borderBottom: "1px solid rgba(255,255,255,.07)" }}>
          <span>站点</span><span>endpoint / key</span>
          <span style={{ textAlign: "right" }}>余额</span>
          <span>还能撑</span>
          <span style={{ textAlign: "right" }}>日均实扣</span>
        </div>

        {rows.map((r) => {
          const u = usage.find((x) => x.id === r.id);
          const d = u?.data;
          const isCur = activeId === r.id;
          const off = !r.enabled;
          const days = d?.runway?.days ?? null;
          const dc = dayColor(days);
          const perDay = d?.runway?.per_active_day ?? null;
          return (
            <div key={r.id} data-relay={r.id} data-relay-current={isCur ? "1" : undefined}
                 onClick={off ? undefined : () => onPick(r.id)}
                 style={{ display: "grid", gridTemplateColumns: COLS, gap: 14,
                          alignItems: "center", padding: "12px 16px",
                          borderTop: "1px solid rgba(255,255,255,.05)",
                          background: isCur ? "rgba(45,212,191,.05)" : "transparent",
                          cursor: off ? "default" : "pointer", position: "relative",
                          opacity: off ? 0.45 : 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%",
                               background: relayDot(r.id), flex: "none" }} />
                <span style={{ fontSize: 14, fontWeight: 700, color: t.text,
                               whiteSpace: "nowrap", overflow: "hidden",
                               textOverflow: "ellipsis" }}>{r.label}</span>
                {isCur && (
                  <span data-route-active="1" style={{
                    fontSize: 8.5, fontWeight: 700, color: "#06231f", background: "#2dd4bf",
                    padding: "1px 6px", borderRadius: 4, flex: "none",
                  }}>当前</span>
                )}
                {off && (
                  <span data-relay-off style={{
                    fontSize: 8.5, fontWeight: 700, color: "#8a93a0",
                    border: "1px solid rgba(255,255,255,.15)", padding: "1px 6px",
                    borderRadius: 4, flex: "none",
                  }}>停用</span>
                )}
              </div>

              {/* ★ 只出指纹，列表里绝不出现完整 key。
                  ★★ 行里只画指纹的**可读前缀**（`sk-73a1…`），括号里的 sha256 前 12 位
                     放进 `title` —— 它的用途是"跨机器比对是不是同一把"，不是一眼认人，
                     摆在 1fr 的列里只会把 endpoint 挤掉、然后自己被省略号切掉，两头落空。 */}
              <div title={`${r.base_url} · ${r.key_fp}`}
                   style={{ minWidth: 0, fontFamily: MONO, fontSize: 10.5, color: "#8a93a0",
                            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {r.base_url} <span style={{ color: "#454d57" }}>·</span>{" "}
                <span data-key-fp>{(r.key_fp ?? "").split(" (")[0]}</span>
              </div>

              <span style={{ textAlign: "right", fontSize: 16, fontWeight: 700,
                             color: "#E0A21C", fontFamily: MONO,
                             fontVariantNumeric: "tabular-nums" }}>
                {money(d?.balance ?? null, d?.unit)}
              </span>

              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <div style={{ display: "flex", justifyContent: "space-between",
                              fontFamily: MONO, fontSize: 10.5 }}>
                  <span style={{ fontWeight: 700, color: dc }}>
                    {days === null ? "~? 天" : `≈ ${Math.round(days)} 活跃日`}
                  </span>
                  <span style={{ color: "#6b7480" }}>
                    {days === null
                      ? (d?.runway?.reason ?? "样本不足")
                      : `日均 ${money(perDay, d?.unit)}`}
                  </span>
                </div>
                <div style={{ height: 4, borderRadius: 2, background: "rgba(255,255,255,.08)",
                              overflow: "hidden" }}>
                  <div style={{ height: "100%", background: dc, borderRadius: 2,
                                transition: "width .4s",
                                width: `${days === null ? 6 : Math.min(days, 30) / 30 * 100}%` }} />
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end",
                            gap: 6, fontFamily: MONO }}>
                <span style={{ fontSize: 12, color: "#c3cad3",
                               fontVariantNumeric: "tabular-nums", marginRight: 2 }}>
                  {perDay === null ? "—" : `${money(perDay, d?.unit)}/日`}
                </span>
                <IconBtn id={`test:${r.id}`} title="测试连接（免费）"
                         color={acting === `test:${r.id}` ? "#2dd4bf" : undefined}
                         onClick={(e) => { e.stopPropagation(); onTest(r.id); }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                       style={{ stroke: "currentColor", strokeWidth: 2 }}>
                    <path d="M5 12l4 4L19 6" />
                  </svg>
                </IconBtn>
                <IconBtn id={`menu:${r.id}`} title="更多"
                         onClick={(e) => { e.stopPropagation(); setConfirmDel(null);
                                           setMenu((m) => (m === r.id ? null : r.id)); }}>
                  ···
                </IconBtn>
              </div>

              {menu === r.id && (
                <div data-relay-menu={r.id}
                     onClick={(e) => e.stopPropagation()}
                     style={{ position: "absolute", right: 16, top: 52, zIndex: 10, width: 132,
                              background: "#141a22", border: "1px solid rgba(255,255,255,.12)",
                              borderRadius: 9, padding: 4,
                              boxShadow: "0 12px 30px rgba(0,0,0,.5)",
                              animation: "cbFade .15s ease" }}>
                  <div data-act={`edit:${r.id}`}
                       onClick={() => { setMenu(null); onEdit(r); }}
                       style={{ padding: "7px 10px", borderRadius: 6, fontSize: 11.5,
                                color: "#c3cad3", cursor: "pointer" }}>编辑</div>
                  <div data-act={`toggle:${r.id}`}
                       onClick={() => { setMenu(null); onToggle(r); }}
                       style={{ padding: "7px 10px", borderRadius: 6, fontSize: 11.5,
                                color: "#c3cad3", cursor: "pointer" }}>
                    {r.enabled ? "停用" : "启用"}
                  </div>
                  {/* ★ 删除走**二次确认**（设计稿 §6 明写"删除（二次确认）"）。
                      与切换出口不同：切错了再点回来即可，删掉的中转站要重新填 key。 */}
                  <div data-act={confirmDel === r.id ? `del-confirm:${r.id}` : `del:${r.id}`}
                       onClick={() => {
                         if (confirmDel === r.id) { setMenu(null); setConfirmDel(null); onRemove(r.id); }
                         else setConfirmDel(r.id);
                       }}
                       style={{ padding: "7px 10px", borderRadius: 6, fontSize: 11.5,
                                color: "#E0524D", cursor: "pointer",
                                background: confirmDel === r.id ? "rgba(224,82,77,.1)" : undefined }}>
                    {confirmDel === r.id ? "确认删除？" : "删除"}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        <div data-act="add-row" onClick={onAdd}
             style={{ display: "flex", alignItems: "center", gap: 9, padding: "11px 16px",
                      borderTop: "1px dashed rgba(255,255,255,.12)", color: "#6b7480",
                      fontSize: 11.5, cursor: "pointer" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%",
                         border: "1px dashed #6b7480", flex: "none" }} />
          + 新增中转站 · 填 endpoint 与 key，测试连接免费
        </div>
      </div>
    </>
  );
}
