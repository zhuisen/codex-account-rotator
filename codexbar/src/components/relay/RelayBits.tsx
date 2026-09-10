import React, { useEffect, useState } from "react";
import type { Theme } from "../../theme";
import type { RelayRow } from "../../relay";

/** 数字一律等宽 + tabular-nums（本仓 UI 规范：这是它读起来像仪表的原因）。 */
export const MONO = "'JetBrains Mono', monospace";
export const NUM: React.CSSProperties = {
  fontFamily: MONO, fontVariantNumeric: "tabular-nums", textAlign: "right",
  // ★ **数字永不断行。** 本仓把断字当 bug：`$30.00` 折成两行既难读又把行高撑乱，
  //   而 harness 的 `wrapped` 探针实测报过 10 处（2026-09-09 模型表）。
  whiteSpace: "nowrap",
};
/** 金额琥珀（本仓语义色，与告警琥珀 #E0901C 区分）。 */
export const MONEY = "#E0A21C";

export const relayCard = (t: Theme): React.CSSProperties => ({
  background: t.cardBg, border: `1px solid ${t.cardBorder}`, borderRadius: 13,
  padding: 14, marginBottom: 12,
});

export const relayBtn = (t: Theme) => (primary = false): React.CSSProperties => ({
  fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 8, cursor: "pointer",
  userSelect: "none", border: `1px solid ${primary ? t.accent : t.ghostBorder}`,
  background: primary ? t.accent : "transparent", color: primary ? t.accentText : t.text,
  whiteSpace: "nowrap",
});

export function Stat({ t, k, v, sub, dim }: {
  t: Theme; k: string; v: string; sub?: string; dim?: boolean;
}): React.ReactElement {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: t.muted, letterSpacing: 0.2 }}>{k}</div>
      {/* ★ `tabular-nums`：这些数每 5 分钟刷新一次，等宽数字才不会在跨位数时跳动。 */}
      <div style={{ fontSize: 15, fontWeight: 700, color: dim ? t.muted : t.text,
                    fontFamily: MONO, fontVariantNumeric: "tabular-nums" }}>{v}</div>
      {sub && <div style={{ fontSize: 9.5, color: t.muted, opacity: 0.8 }}>{sub}</div>}
    </div>
  );
}

// ★ 这里原有 `DailyChart` / `RELAY_RANGES` / `relayRangeLabel`，已随「用量」版块
//   改成与「AI用量信息」同结构而删除（图表现在直接用 `StackedArea` + `KpiStrip` + `Seg`，
//   见 `components/RelayUsage.tsx`）。**不留骨架** —— 一份没人调用的图表组件会让
//   下一个人以为还有第二条渲染路径。要恢复请从 git 历史取。

export function RelayForm({ t, editing, setEditing, onSave, acting }: {
  t: Theme;
  editing: Partial<RelayRow> | null;
  setEditing: (v: Partial<RelayRow> | null) => void;
  onSave: (p: unknown) => Promise<unknown>;
  acting: boolean;
}): React.ReactElement {
  const card = relayCard(t);
  const btn = relayBtn(t);
  /**
   * ★★ **「模型」字段已从表单去掉**（用户 2026-09-10 拍板）。
   *
   *    它曾经能填、会落盘、还被 `_relay_upstream()` 装进 `up["model"]` ——
   *    但代理**从没有任何读者**（`_open` 把 body 原样透传），而提示语写着
   *    「留空 = 沿用 config.toml 里的 model」，反过来暗示填了会生效。
   *    一个能填却没用的输入框正是本仓反复栽过的**孤儿字段**：用户按它做判断，
   *    而它什么也不做，且不会报错。
   *
   *    ⚠️ `relays.local.json` 里的 `model` 键**保留**（老配置不该因为一次 UI 改动
   *    就被静默丢弃），但不再收集、不再展示。真要做「按站覆盖模型」时，
   *    必须同时在页面上标出「已被 X 覆盖」—— 悄悄改掉用户要的模型 =
   *    行为与计费都变了却看不见。
   */
  const [f, setF] = useState<Record<string, string>>({});
  useEffect(() => {
    if (editing) {
      setF({
        id: editing.id ?? "", label: editing.label ?? "",
        base_url: editing.base_url ?? "", key: "",
      });
    }
  }, [editing]);
  const input: React.CSSProperties = {
    background: "transparent", border: `1px solid ${t.ghostBorder}`, borderRadius: 7,
    padding: "5px 8px", fontSize: 12, color: t.text, outline: "none", width: "100%",
  };
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: e.target.value }));
  return (
    <div data-card="form" style={card}>
      <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 10 }}>
        {editing?.id ? `编辑 ${editing.id}` : "新增中转站"}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "88px 1fr", gap: 8, alignItems: "center" }}>
        <label style={{ fontSize: 11.5, color: t.muted }}>id</label>
        <input data-f="id" style={input} value={f.id ?? ""} onChange={set("id")}
               placeholder="小写字母/数字/_/-，2–31 位（同时是 profile 文件名）"
               disabled={!!editing?.id} />
        <label style={{ fontSize: 11.5, color: t.muted }}>显示名</label>
        <input data-f="label" style={input} value={f.label ?? ""} onChange={set("label")} placeholder="TokenDun" />
        <label style={{ fontSize: 11.5, color: t.muted }}>base_url</label>
        <input data-f="base_url" style={input} value={f.base_url ?? ""} onChange={set("base_url")}
               placeholder="https://api.example.com/v1（只到 /v1，不要带 /chat/completions）" />
        <label style={{ fontSize: 11.5, color: t.muted }}>API key</label>
        {/* ★★ `type=password`，且**编辑时留空 = 沿用原 key**。
            绝不把 `key_fp` 回填进来 —— 那串指纹非空、会通过校验、被当成真 key 写进配置，
            中转站当场 401，而症状与「key 真的过期了」一模一样。 */}
        <input data-f="key" type="password" style={input} value={f.key ?? ""} onChange={set("key")}
               placeholder={editing?.id ? "留空 = 沿用原 key" : "sk-…"} />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        {/* ★★ 只有**成功**才退出编辑态。原来无条件退出：保存失败后表单照样翻回
            "新增中转站"、id 框重新可编 —— 一个成功形状的转场，而红字可能已在屏幕外。
            ★ 成功后立刻清空表单 state：明文 key 不该在 React 内存里多留一秒。 */}
        <span data-act="save" style={btn(true)}
              onClick={() => void onSave(f).then((d) => {
                if (d && (d as { ok?: boolean }).ok) { setEditing(null); setF({}); }
              })}>
          {acting ? "保存中…" : "保存"}
        </span>
        <span data-act="cancel" style={btn()} onClick={() => setEditing(null)}>取消</span>
      </div>
    </div>
  );
}
