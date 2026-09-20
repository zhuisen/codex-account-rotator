import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { Theme } from "../theme";

/**
 * 账号池接入面板（Connector）。
 *
 * ## 为什么它长这样
 *
 * 用户 2026-09-19 定的流程是**两段同意**：总览只负责**提示**并跳过来，
 * 真正动手在这里、由用户逐项决定。所以这个面板必须满足三件事：
 *
 *   ① **先说清楚要改什么** —— 每一步都能展开看**将要写入的原文**，不是「点了才知道」；
 *   ② **逐项可选** —— 尤其「让 `codex` 本身也走轮换」那一步改变裸 `codex` 的行为，
 *      默认**不勾**；
 *   ③ **可撤销** —— 撤销按钮就在旁边，且两段确认（与 `ProbeButton` 同一范式）。
 *
 * ## 四态，颜色各不相同
 *
 * | 状态 | 色 | 含义 | 复选框 |
 * |---|---|---|---|
 * | `todo` | 琥珀 | 没装 | 默认勾上（`wrapper` 除外） |
 * | `done` | 绿 | 我们装的 | 禁用 |
 * | `external` | 蓝 | **你自己装的，正在工作** | 禁用，且文案说明不会碰 |
 * | `blocked` | 红 | 这份安装缺运行时文件 | 禁用，整块不可用 |
 *
 * ★★ `external` 单独一档是**实测逼出来的**：第一版把作者机器上手工配好的
 *   provider/profile 报成 `todo`，等于建议用户去覆盖自己正在用的配置。
 */
interface Step {
  id: string;
  title: string;
  why: string;
  state: "todo" | "done" | "external" | "blocked";
  detail: string;
  preview: string;
  optional: boolean;
}

interface Plan {
  steps: Step[];
  runtime: string;
  inplace: boolean;
  ready: boolean;
  blocked: boolean;
  port: number;
  codex_home: string;
  local_bin: string;
}

const TONE: Record<Step["state"], { c: string; label: string }> = {
  todo: { c: "#E0901C", label: "待装" },
  done: { c: "#27B26B", label: "已装" },
  external: { c: "#2BA0C0", label: "你自己装的" },
  blocked: { c: "#E0524D", label: "装不了" },
};

/**
 * 默认勾选规则：只勾没装的；`optional` 的那一步（改 `codex` 行为）**永远不默认勾**。
 *
 * ★★ `blocked` 时**一个都不勾**。像素验证抓到（2026-09-19）：这份安装缺运行时文件、
 *   红条已经说了「装不了」，可复选框仍是勾选态、按钮还写着「接入（N 项）」——
 *   一个说不能装、一个邀请你去装，用户只会相信后者。
 */
function defaultPicks(steps: Step[], blocked: boolean): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const s of steps) out[s.id] = !blocked && s.state === "todo" && !s.optional;
  return out;
}

export default function ConnectorPanel({ t }: { t: Theme }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [picks, setPicks] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "apply" | "remove">("");
  /** 哪个按钮正在跑 —— 三个入口共用一条 `apply` 链路，只有它能把「接入中…」显示对地方。 */
  const [running, setRunning] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  /** 逐项明细默认**收起**（用户 2026-09-21：「接入内容太复杂了」）。 */
  const [advanced, setAdvanced] = useState(false);

  const load = useCallback(() => {
    void (async () => {
      try {
        const raw = await invoke<string>("connector_plan");
        const p = JSON.parse(raw) as Plan;
        setPlan(p);
        setPicks(defaultPicks(p.steps, !!p.blocked));
      } catch (e: unknown) {
        // ★ 读不到就如实说，**不合成一个「一切正常」** —— 本仓铁律。
        setPlan(null);
        setMsg(`读不到接入状态：${String(e).slice(0, 120)}`);
      }
    })();
  }, []);

  useEffect(() => {
    load();
    const un = listen("state-changed", () => load());
    return () => { void un.then((f) => f()); };
  }, [load]);

  const chosen = plan ? plan.steps.filter((s) => picks[s.id]).map((s) => s.id) : [];
  const extCount = plan ? plan.steps.filter((s) => s.state === "external").length : 0;

  /**
   * 一键要做的那几步。
   *
   * ★★ 判据是 `state === "todo"`，**不是**"全部步骤" —— `done` / `external` 重跑一遍
   *   没有意义，而 `external` 那几项是用户自己装的，Connector 的既定契约就是不碰。
   * ★ `withWrapper` 决定带不带那个改变裸 `codex` 行为的可选步 —— 界面上是**两个按钮**，
   *   所以"要不要接管 codex"这个决定仍然由用户做，只是不必先读懂六步再做。
   */
  const todoIds = (withWrapper: boolean) => plan
    ? plan.steps.filter((s) => s.state === "todo" && (withWrapper || !s.optional)).map((s) => s.id)
    : [];
  const needCount = todoIds(false).length;
  const wrapperStep = plan?.steps.find((s) => s.optional) ?? null;
  const wrapperTodo = wrapperStep?.state === "todo";

  const runApply = async (ids: string[], tag: string) => {
    // ★ `blocked` 也要挡在这里，不能只靠按钮变灰 —— 变灰只是样式，点击照样会跑。
    //   像素验证抓到的那次，红条说「装不了」而按钮仍可点。
    if (!ids.length || busy || plan?.blocked) return;
    setBusy("apply");
    setRunning(tag);
    setMsg(null);
    try {
      // ★ `runtime` 是其它步骤的前提（symlink 与服务都指向它）。用户没勾也要带上，
      //   否则会建出一堆指向不存在目录的入口 —— 悬空 symlink 是静默失败。
      const steps = ids.includes("runtime") ? ids : ["runtime", ...ids];
      const raw = await invoke<string>("connector_apply", { steps });
      const r = JSON.parse(raw) as { ok: boolean; done: string[]; notes: string[]; error: string | null };
      setMsg(r.ok
        ? `✓ 已接入：${r.done.join(" · ")}${r.notes.length ? "\n" + r.notes.join("\n") : ""}`
        : `✗ ${r.error ?? "失败"}`);
    } catch (e: unknown) {
      setMsg(`✗ ${String(e).slice(0, 200)}`);
    } finally {
      setBusy("");
      setRunning("");
      load();
    }
  };

  const apply = () => void runApply(chosen, "advanced");

  const remove = async () => {
    if (busy) return;
    if (!confirmRemove) {
      setConfirmRemove(true);
      // 两段确认：5s 内没有第二次点击就退回（与 ProbeButton 同一范式）
      setTimeout(() => setConfirmRemove(false), 5000);
      return;
    }
    setConfirmRemove(false);
    setBusy("remove");
    setMsg(null);
    try {
      const raw = await invoke<string>("connector_remove", { dropRuntime: false });
      const r = JSON.parse(raw) as { removed: string[]; kept: string[] };
      setMsg(`✓ 已撤销：${r.removed.join(" · ") || "没有可撤销的"}`
        + (r.kept.length ? `\n未动（不是我们装的）：${r.kept.join(" · ")}` : ""));
    } catch (e: unknown) {
      setMsg(`✗ ${String(e).slice(0, 200)}`);
    } finally {
      setBusy("");
      load();
    }
  };

  const mono = "'JetBrains Mono', ui-monospace, monospace";

  return (
    <div data-connector style={{ marginTop: 26 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: t.muted, marginBottom: 12 }}>
        账号池接入（Connector）
      </div>

      {!plan ? (
        <div style={{ fontSize: 11, color: t.muted }}>{msg ?? "读取中…"}</div>
      ) : (
        <>
          <div style={{ fontSize: 10.5, color: t.text2, lineHeight: 1.6, marginBottom: 10 }}>
            把这台机器接进<b>账号池轮换</b>。全部落在用户级目录，<b>不需要管理员密码</b>；
            只在托管标记之间写 <code style={{ fontFamily: mono }}>{plan.codex_home}/config.toml</code>，
            标记之外你自己的内容一个字节都不动。
            <br />
            ★ <b>绝不会调用 <code style={{ fontFamily: mono }}>codex login</code> / <code style={{ fontFamily: mono }}>logout</code></b>
            —— 那两条命令会在服务端吊销当前账号。加号请自己跑 <code style={{ fontFamily: mono }}>codex-rotate login</code>。
          </div>

          {plan.blocked && (
            <div style={{ fontSize: 10.5, color: "#E0524D", border: "1px solid rgba(224,82,77,.4)",
                          background: "rgba(224,82,77,.08)", borderRadius: 8, padding: "7px 10px",
                          marginBottom: 10 }}>
              这份安装缺少运行时文件，无法自动接入。请改用 clone 安装（见 docs/INSTALL.md），
              或升级到包含运行时的版本。
            </div>
          )}

          {/* ★★ 一键区（用户 2026-09-21：「接入内容太复杂了，有没有一键无脑的操作」）。
              在这之前六步连同长解释一起摊开，读起来像要做六个决定 —— 而其中五步
              **根本没得选**（不装就是不能用），只有最后一步是真的取舍。
              所以：把"没得选的五步"合成一个主按钮，把"真的取舍"单独做成第二个按钮。
              ★ 用户在三个方案里选的就是**两个按钮并排**，不是让一键默默接管 `codex`。 */}
          {!plan.blocked && (needCount > 0 || wrapperTodo) && (
            <div style={{ display: "flex", gap: 10, alignItems: "center",
                          flexWrap: "wrap", marginBottom: 12 }}>
              {needCount > 0 && (
                <div>
                  <span data-connector-oneclick onClick={() => void runApply(todoIds(false), "one")}
                        style={{ display: "inline-block", fontSize: 13, fontWeight: 700,
                                 padding: "9px 20px", borderRadius: 9, cursor: busy ? "default" : "pointer",
                                 color: t.accentText, background: t.accent,
                                 border: `1px solid ${t.accent}`, opacity: busy ? .6 : 1 }}>
                    {running === "one" ? "接入中…" : "一键接入"}
                  </span>
                  <div style={{ fontSize: 9.5, color: t.muted, marginTop: 4, textAlign: "center" }}>
                    {needCount} 项 · 可撤销
                  </div>
                </div>
              )}
              {wrapperTodo && (
                <div>
                  <span onClick={() => void runApply(todoIds(true), "all")}
                        title={wrapperStep?.detail}
                        style={{ display: "inline-block", fontSize: 11.5, fontWeight: 600,
                                 padding: "9px 14px", borderRadius: 9, cursor: busy ? "default" : "pointer",
                                 color: t.text2, background: "transparent",
                                 border: `1px solid ${t.divider}`, opacity: busy ? .6 : 1 }}>
                    {running === "all" ? "接入中…" : "连 codex 一起接管"}
                  </span>
                  <div style={{ fontSize: 9.5, color: t.muted, marginTop: 4, textAlign: "center" }}>
                    {/* ★ 代价写在按钮底下，不藏进 title —— 只写进悬浮等于没写（本仓 §5d）。 */}
                    敲 <code style={{ fontFamily: mono }}>codex</code> 也走轮换 ·{" "}
                    <code style={{ fontFamily: mono }}>cxd</code> 保持直连
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ★★ 折叠用 **CSS 控制可见性**，不用条件渲染（本仓 §5c）：条件渲染会让内容
              离开 DOM，而接入面板的行为闸都在 `--dump-dom` 的静态 DOM 上断言 ——
              一改就全部静默失效（"测试还在、但什么也没验"）。 */}
          <div onClick={() => setAdvanced(!advanced)}
               style={{ fontSize: 11, color: t.accent, cursor: "pointer", userSelect: "none",
                        marginBottom: advanced ? 4 : 0 }}>
            {advanced ? "▾" : "▸"} 逐项选择（高级）—— 看每一步会写什么、单独装或跳过
          </div>

          <div data-connector-steps style={{ display: advanced ? "block" : "none" }}>
          {plan.steps.map((s) => {
            const tone = TONE[s.state];
            const fixed = s.state !== "todo";
            return (
              <div key={s.id} style={{ borderBottom: `1px solid ${t.divider}`, padding: "9px 0" }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 9 }}>
                  <input type="checkbox" disabled={fixed || plan.blocked}
                         checked={!!picks[s.id]}
                         onChange={(e) => setPicks({ ...picks, [s.id]: e.target.checked })}
                         style={{ marginTop: 3, accentColor: t.accent, cursor: fixed ? "default" : "pointer" }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12.5, fontWeight: 600, color: t.text }}>{s.title}</span>
                      <span style={{ fontFamily: mono, fontSize: 9, fontWeight: 700, color: tone.c,
                                     border: `1px solid ${tone.c}66`, borderRadius: 5, padding: "1px 5px" }}>
                        {tone.label}
                      </span>
                      {s.optional && (
                        <span style={{ fontFamily: mono, fontSize: 9, color: t.muted,
                                       border: `1px solid ${t.divider}`, borderRadius: 5, padding: "1px 5px" }}>
                          可选
                        </span>
                      )}
                      {s.preview && (
                        <span onClick={() => setOpen(open === s.id ? null : s.id)}
                              style={{ fontSize: 10, color: t.accent, cursor: "pointer", marginLeft: "auto" }}>
                          {open === s.id ? "收起" : "看将要写入的内容"}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 10, color: t.muted, marginTop: 2, lineHeight: 1.5 }}>{s.why}</div>
                    <div style={{ fontSize: 10, color: t.text2, marginTop: 2, lineHeight: 1.5,
                                  whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{s.detail}</div>
                    {open === s.id && (
                      <pre style={{ fontFamily: mono, fontSize: 9.5, lineHeight: 1.5, color: t.text2,
                                    background: t.cardBg, border: `1px solid ${t.divider}`,
                                    borderRadius: 7, padding: "8px 10px", marginTop: 6,
                                    whiteSpace: "pre-wrap", wordBreak: "break-all", maxHeight: 220,
                                    overflowY: "auto" }}>{s.preview}</pre>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

            <div style={{ marginTop: 11 }}>
              <span onClick={() => apply()}
                    style={{ fontSize: 11.5, fontWeight: 700, padding: "7px 14px", borderRadius: 8,
                             cursor: chosen.length && !busy && !plan.blocked ? "pointer" : "default",
                             color: chosen.length && !plan.blocked ? t.accentText : t.muted,
                             background: chosen.length && !plan.blocked ? t.accent : "transparent",
                             border: `1px solid ${chosen.length && !plan.blocked ? t.accent : t.divider}`,
                             opacity: running === "advanced" ? .6 : 1 }}>
                {running === "advanced" ? "接入中…" : chosen.length ? `接入（${chosen.length} 项）` : "没有要做的"}
              </span>
            </div>
          </div>

          <div style={{ display: "flex", gap: 9, alignItems: "center", marginTop: 13, flexWrap: "wrap" }}>
            <span onClick={() => void remove()}
                  title="移除我们装的入口、服务与托管配置区。你自己放的东西一律不动。"
                  style={{ fontSize: 11, padding: "7px 12px", borderRadius: 8, cursor: "pointer",
                           color: confirmRemove ? "#E0524D" : t.muted,
                           border: `1px solid ${confirmRemove ? "#E0524D" : t.divider}`,
                           opacity: busy === "remove" ? .6 : 1 }}>
              {busy === "remove" ? "撤销中…" : confirmRemove ? "再点一次确认撤销" : "撤销接入"}
            </span>
            {plan.ready && !plan.blocked && (
              <span style={{ fontSize: 10.5, color: "#27B26B" }}>✓ 这台机器已经接入轮换</span>
            )}
            {/* ★ 直接回答「为什么我一项都勾不上」。用户 2026-09-19 报过这个困惑 ——
                当每一步都是 done/external 时，复选框全禁用、按钮写「没有要做的」，
                看起来像功能坏了。**说出原因**比让人猜强。 */}
            {!plan.blocked && !chosen.length && extCount > 0 && (
              <span style={{ fontSize: 10.5, color: t.muted }}>
                其中 {extCount} 项是你自己装的（蓝色「你自己装的」），Connector 不会去覆盖 ——
                所以没有可勾选的。
              </span>
            )}
          </div>

          {msg && (
            <div style={{ fontSize: 10.5, color: msg.startsWith("✗") ? "#E0524D" : t.text2,
                          marginTop: 10, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{msg}</div>
          )}

          <div style={{ fontSize: 10, color: t.muted, marginTop: 10, lineHeight: 1.6 }}>
            运行时目录：<code style={{ fontFamily: mono }}>{plan.runtime}</code>
            {plan.inplace
              ? "（仓库安装，原地使用）"
              : "（复制到数据目录 —— 刻意不放在 App 内部，否则 App 更新或删除会把常驻服务弄断）"}
          </div>
        </>
      )}
    </div>
  );
}
