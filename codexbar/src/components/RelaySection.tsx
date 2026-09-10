import React, { useEffect, useState } from "react";
import type { Theme } from "../theme";
import Toast from "./Toast";
import OutletCards from "./relay/OutletCards";
import RelayTable from "./relay/RelayTable";
import { RelayForm, relayCard } from "./relay/RelayBits";
import { useRelayConfig } from "../hooks/useRelayConfig";
import { useRelayUsage } from "../hooks/useRelayUsage";
import { invalidateSidecar } from "../hooks/useQuotaSidecar";
import { useStore } from "../hooks/useStore";
import type { RelayRow } from "../relay";

/**
 * 中转站「账号」块 —— 1:1 复刻 `design_handoff_codexbar/中转站-交接说明.md` §1/§2/§6。
 *
 * 版面：`当前出口` 两张同权卡 → 生效范围 → 中转站表格（`···` 菜单）→ 新增表单。
 *
 * ## 与上一版（大卡片阵列）的差别，以及为什么换
 *
 * 设计稿的三个目标：① 一眼看出「现在走哪个出口」；② 中转站从大卡片压成表格行、
 * 操作收进图标；③ 用量改为每模型小图卡。前两条落在这一块。
 * 上一版每个中转站一张大卡，两三家就把一屏撑满，而这一屏真正要回答的第一个问题是
 * "现在走哪个出口" —— 那个答案原来被埋在一排同权卡片里。
 *
 * ## ★ 按设计稿去掉了「切到中转站」的两段确认
 *
 * 上一版我给切换加了两段确认（理由：切过去之后每次 codex 都扣余额，实测一句 trivial
 * prompt $0.0863）。设计稿 §6 的交互是**点行即切 + toast**，本次按稿复刻。
 * 代价是**误点一行就开始花钱**；补偿是成本在同屏三处可见（`按量 · 真扣余额` 琥珀 pill、
 * 卡上的余额/今日实扣、表格里的日均实扣）。要恢复两段确认说一声。
 * 删除仍保留二次确认 —— 设计稿 §6 自己也写着"删除（二次确认）"。
 */
export default function RelaySection({ t }: { t: Theme }): React.ReactElement {
  const { cfg, note, setNote, acting, act } = useRelayConfig();
  const { snap } = useRelayUsage();
  const store = useStore();
  const [editing, setEditing] = useState<Partial<RelayRow> | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const card = relayCard(t);

  useEffect(() => {
    if (!toast) return;
    const h = setTimeout(() => setToast(null), 1800);
    return () => clearTimeout(h);
  }, [toast]);

  const relays = cfg?.relays ?? [];
  const route = cfg?.route;
  const activeId = route?.state === "relay" ? (route.profile ?? null) : null;
  // 出口卡上那一家：优先当前路由指向的，否则第一个启用的（"切到中转站"要有个目标）。
  const cur = relays.find((r) => r.id === activeId)
    ?? relays.find((r) => r.enabled)
    ?? relays[0];
  const curUsage = (snap?.relays ?? []).find((x) => x.id === cur?.id);

  /** ★★ 改完配置**立刻**让用量重取（P2 #30）。不然「已停用」与 KPI 里还加着它的余额
   *  最长 5 分钟同时挂在屏幕上 —— 那不是"数据有延迟"，是"我刚点的东西没生效"。 */
  const afterConfigChange = (msg: string): void => {
    setToast(msg);
    invalidateSidecar("run_relay_usage");
  };

  const pick = async (target: string, msg: string): Promise<void> => {
    const d = await act("route", target);
    // ★★ 失败的原因藏在 `route.detail` 里（`cmd_route` 的 payload 顶层没有 detail）。
    //    只读顶层的话，切到一个已停用的中转站会显示"✗ 未知错误"，
    //    而路由文件**已经改了**、代理会静默退回账号池 —— 用户既不知道失败了、也不知道钱扣在哪。
    if (d && d.ok === false) {
      // `act` 返回的是 `Record<string, unknown>`；`route` 是嵌套对象，取它要先窄化。
      const rt = d.route as { detail?: string } | undefined;
      setNote("✗ " + (d.detail || rt?.detail || d.state || "未知错误"));
      return;
    }
    if (d) afterConfigChange(msg);
  };

  return (
    <div data-section="relay" style={{ position: "relative" }}>
      {note && (
        <div data-card="note" style={{ ...card, borderColor: "#E0524D", color: "#E0524D",
                                       fontSize: 12 }}>{note}</div>
      )}

      {/* ★ 读失败与「没配过」必须分开。后者是一句关于事实的假陈述。 */}
      {cfg === null && (
        <div data-card="cfgerr" style={{ ...card, fontSize: 12.5, color: "#E0901C" }}>
          读不到中转站配置 —— <b>这不等于你没配过</b>。上面的红字是原因。
        </div>
      )}

      <OutletCards
        route={route} cur={cur} curUsage={curUsage}
        poolAccounts={store.counts.total}
        poolPct={store.hero?.tightestWin ? store.hero.tightestWin.pct / 100 : null}
        onPool={() => void pick("pool", "已切换到账号池 · 逐请求轮换")}
        onRelay={() => {
          if (!cur) { setToast("还没有中转站，先点「+ 新增」"); return; }
          if (!cur.enabled) { setToast(`${cur.label} 已停用，请先启用`); return; }
          void pick(cur.id, `已切换到中转站 · ${cur.label}`);
        }}
      />

      {cfg !== null && relays.length === 0 && !editing ? (
        <div data-card="empty" style={{ ...card, fontSize: 12.5, color: t.muted }}>
          还没有中转站。点「+ 新增中转站」加一个 —— 加完它会作为一行出现在这里。
        </div>
      ) : (
        <RelayTable
          t={t} rows={relays} usage={snap?.relays ?? []} activeId={activeId} acting={acting}
          onPick={(id) => {
            const r = relays.find((x) => x.id === id);
            if (!r) return;
            void pick(id, `已切换到中转站 · ${r.label}`);
          }}
          onTest={(id) => void act("test", id)}
          onEdit={(r) => setEditing({ ...r, key: "" } as Partial<RelayRow>)}
          onToggle={(r) => {
            // ★ 停用/启用走 CLI 而不是前端记一份：真源是 relays.local.json，
            //   代理在 app 没开时也要读它 —— 两个真源迟早分叉。
            void act("set", undefined, { ...r, key: "", enabled: !r.enabled }).then((d) => {
              if (!d) return;
              afterConfigChange(`${r.label} ${r.enabled ? "已停用" : "已启用"}` +
                (r.enabled && activeId === r.id ? " · 出口回落到账号池" : ""));
            });
          }}
          onRemove={(id) => void act("remove", id).then((d) => {
            if (d) afterConfigChange("已删除");
          })}
          onAdd={() => setEditing({})}
        />
      )}

      {editing && (
        <div style={{ marginTop: 12 }}>
          <RelayForm t={t} editing={editing} setEditing={setEditing}
                     onSave={(payload) => act("set", undefined, payload).then((d) => {
                       if (d) afterConfigChange("已保存");
                       return d;
                     })}
                     acting={acting === "set"} />
        </div>
      )}

      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
