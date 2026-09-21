import React, { useEffect, useRef, useState } from "react";
import type { Theme } from "../theme";
import type { Board, BoardAcct } from "../hooks/useRotationBoard";
import Ring from "./Ring";
import PlanBadge from "./PlanBadge";
import { maskId } from "../helpers";

const MONO = "'JetBrains Mono'";

/**
 * 总览顶部的「续航条」（用户 2026-09-21 从六个方向里选的 **D**，左侧按他要求换成
 * 「正在使用的账号 + 额度环」）。
 *
 * ## 它取代的那条 banner 错在哪
 *
 * 旧 Hero 的两个前提**都已经不成立**：
 *   ① 标题写「当前使用中」，读的却是 `state.active` —— 那是**上次 CLI 切换**留下的，
 *      而代理是**逐请求**挑号。实测 2026-09-21 两者不一致过（active=wing，代理给 Huo），
 *      也就是说那行标题**会错，且错得没有任何迹象**。
 *   ② 「建议切到 X」按剩余最多者算，**既不看置顶也不看停用** —— 它会劝你推翻自己刚设的
 *      置顶，甚至推荐一个你已经 `rotate_off` 的号。而在「默认容量最高优先 + 置顶插队」
 *      之后，"手动挑最空的号"这件事本来就没有意义了。
 *
 * ## 这条给的是卡片网格**回答不了**的东西
 *
 * **还能撑多久** —— 用 `state.json` 的 `quota_marks`（额度跨整数百分点时记一条）算消耗速度。
 *
 * ★★★ 口径必须跟着数字一起显示，否则就是骗人：
 *   · 那是 **活跃小时**不是自然小时 —— 没在用 codex 的时候池子一点不掉；
 *   · 样本数写出来；取不到时显示 `—` 而**绝不写 0**（「算不出来」与「撑不了多久」相反）。
 *
 * ## ★★ 高度是硬约束（用户：「不要增加目前的 banner 高度，可以降低但不能增加」）
 *
 * 旧 Hero 实测 **1300 宽下 112px、880 下 128px**。所以这里：内边距 12（旧 15）、
 * 环 72（旧 80）、右侧三行都压在 12px 行高内。闸量的是**渲染后的真实高度**，
 * 不是这些数字 —— 高度由内边距 / 环 / 行高 / 换行四者合成，改任何一处都会变。
 */
export default function RunwayHero({ t, board, privacy }: {
  t: Theme; board: Board; privacy: boolean;
}): React.ReactElement | null {
  const cur = board.cur ?? board.next;
  if (!cur) return null;
  const n = board.next;
  /** 下一个与正在使用的**不是同一个号**时才多说一句 —— 相同就是噪音。 */
  const showNext = n && n.aid !== cur.aid;
  const pct = cur.tightest;
  /**
   * ★★★ **池子见底** —— `queue` 为空就是「一个能用的号都没有」。
   *
   * 这时代理走最后一层兜底：在「codex 整个不能用」与「多用一个你不想用的号」之间选后者，
   * 并把 `⚠️ 所有号都被停用了自动轮换` 写进 `proxy.log`。
   *
   * ⚠️ **而用户不会去读 proxy.log。** 2026-09-21 实测发生过一次：九个号里 5 个冷却、
   *   3 个被手动停用、1 个凭证失效 ⇒ 代理借用了一个**已停用**的号，用户看到的是
   *   「轮换失效了，禁用轮换的账号也被使用了」—— 系统推翻了他的设置，而他无从知道为什么。
   *   本仓规矩：**告警放在眼睛已经在的地方，且文本要说「做什么」**。这里就是那个地方。
   */
  const stranded = board.queue.length === 0;
  /** 最早什么时候有号回来。只看冷却中的 —— 停用/失效不会自己恢复。 */
  const backInMin = board.rest.reduce<number | null>(
    (a, e) => (e.cool_min > 0 ? (a == null ? e.cool_min : Math.min(a, e.cool_min)) : a), null);
  const nCool = board.rest.filter((e) => e.cool_min > 0 && !e.off && !e.dead).length;
  const nOff = board.rest.filter((e) => e.off).length;
  const nDead = board.rest.filter((e) => e.dead).length;
  /** 正在用的这个号本身不可用 ⇒ 代理是**借**来的，必须说出来。 */
  /**
   * ⚠️ **必须带上 `stranded`。** 第一版只判「这个号本身不可用」——
   *   而 `cur` 是 `last_aid`（代理**最近一次**用了谁），可能是几小时前的事。
   *   2026-09-21 用户截图：池子早已恢复（4 个号可用、下一个是 wing），
   *   顶部却还挂着红色的「临时借用 qq55」，说的是 **3 小时前**那次借用。
   *   一盏描述过去、却长得像现在的红灯，本仓判过死刑 ——
   *   **披露的寿命跟着它描述的那个事实走**，事实结束它就该灭。
   */
  const borrowed = stranded && (cur.off || cur.dead || cur.cool_min > 0);
  const sc = cur.dead ? "#E0524D" : pct != null && pct <= 20 ? "#E0901C" : t.accent;

  /** 色带里每一段的宽度 = 该号周窗口余量。★ `flexGrow` 用余量本身，**不归一化** ——
   *  归一化会让「全池都快空了」和「全池都满」画出一模一样的条。 */
  /** 色带的总权重 —— 每段按它算占比，用来决定**装不装得下名字**。 */
  const restW = Math.max(board.rest.length * 6, 10);
  const total = board.queue.reduce((a, e) => a + Math.max(e.weekly ?? 1, 5), 0)
              + (board.rest.length ? restW : 0);
  /**
   * 这一段宽到能写名字吗？—— **量像素，不拿占比当代理量**。
   *
   * ★★ 段宽按余量成比例（那正是这条带的意义），所以低额度的号天然很窄：
   *   实测 880 宽下 Asen 只占 12% ⇒ 21px，而名字要 22px ⇒ 装不下。
   * ⚠️ **第一版用的是「占比 ≥ 0.14」，错在把占比当成了宽度。** 同一个占比在不同
   *   窗宽下是完全不同的像素数，而阈值只能按某一档标定 ——
   *   实测 1300 宽下 `Egan` 那段占 13.1%，换算 **75px**，写 4 个字母只要 28px，
   *   却被这个按 880 标定的阈值挡掉、白白变成一条无名色块。
   *   **用一次观测标定常量 = 把那次观测当成了保证**（本仓菜单栏高度那次同一个错）。
   * ★ 所以现读色带宽度（`ResizeObserver`），按「这一段真实几像素」判。
   *   量不到时（首帧 / 没有 RO）**一个名字都不写** —— 宁可少写，
   *   也不写一个可能被截断的名字：`Ase…` 会被当成另一个号。
   */
  const barRef = useRef<HTMLDivElement>(null);
  const [barW, setBarW] = useState(0);
  useEffect(() => {
    const el = barRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setBarW(el.clientWidth));
    ro.observe(el);
    setBarW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  /** 9px JetBrains Mono 700 的字宽：ASCII 约 5.6px，CJK 是整个字身 9px。 */
  /** ⚠️ 字宽随字号一起从 9px 抬到 10px（2026-09-21 色带加粗）——**这两个数必须一起改**，
   *  否则「装不装得下名字」按错的字宽判，窄段上又会冒出被裁一半的名字。 */
  const textW = (s2: string) =>
    [...s2].reduce((a, c) => a + (c.charCodeAt(0) > 255 ? 10 : 6.2), 0);
  const fits = (w: number, label: string) =>
    barW > 0 && (w / total) * barW >= textW(label) + 8;

  const seg = (e: BoardAcct, i: number, dim: boolean) => (
    <span key={e.aid} data-runway-seg title={dim
      ? `${e.label} —— ${e.off ? "已停用轮换" : e.dead ? "凭证失效" : `冷却中 ${e.cool_min}m`}，不计入续航`
      : `${e.label} 周窗口还剩 ${e.weekly ?? "—"}%${e.pin ? ` · 置顶 #${e.pin}` : ""}`}
      style={{ flexGrow: dim ? 5 : Math.max(e.weekly ?? 1, 5), flexBasis: 0, minWidth: 0,
               height: 24, display: "grid", placeItems: "center", overflow: "hidden",
               whiteSpace: "nowrap", fontFamily: MONO, fontSize: 10, fontWeight: 700,
               color: dim ? t.muted : "#06231f",
               background: dim ? t.ghostBg : SEG_COLORS[i % SEG_COLORS.length] }}>
      {fits(Math.max(e.weekly ?? 1, 5), e.label ?? "") ? e.label : ""}
    </span>
  );

  return (
    <div data-runway-hero style={{
      display: "flex", alignItems: "center", gap: 13, flexWrap: "wrap", rowGap: 8,
      background: t.heroBg, border: `1px solid ${t.heroBorder}`, borderRadius: 14,
      padding: "10px 14px", marginBottom: 12, boxShadow: t.heroShadow,
      transition: "background-color .35s ease, border-color .35s ease",
    }}>
      <Ring pct={pct ?? 0} r={30} sw={5.5} color={pct == null ? t.ringTrack : sc}
            track={t.ringTrack} size={72}>
        <span style={{ fontSize: 17, fontWeight: 700, color: t.text,
                       fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
          {pct == null ? "—" : pct}<span style={{ fontSize: 9, color: t.muted }}>%</span>
        </span>
      </Ring>

      {/* ★ 左列**不再抢伸缩空间**（`flex: 0 1 auto`）—— 用户 2026-09-21：
          「右侧的续航条可以加大加长」。左列是定长信息（号名 + 两条窗口），
          伸得再宽也只是留白；而右侧那条色带越长，每个号的占比越读得出来。 */}
      {/* ★ 左列给**明确的 flex-basis**（不是 `auto`）：flex 分行看的是 basis
          （hypothetical main size），`auto` 取 max-content，号名一长基准就跟着涨，
          而收缩只发生在**行内**、救不回已经换行的那一下。写死一个数更可预测。
          ⚠️ **但别把这条当成某次故障的修复**：2026-09-21 曾连续两次量到 880 见底档
          hero 被撑到 167px（右列掉到第二行），改完 basis 变回 94px —— 然而事后把
          basis 改回 `auto` 也照样是 94px，四种组合 × 连跑 6 次全部 94。
          **那次现象至今没复现，成因未定**，这里不假装已经定位。真正的防线是
          `tests/test_runway_hero.py` 现在把**见底这一支也量进去了**（此前只量默认档）。 */}
      <div style={{ minWidth: 168, flex: "0 1 220px" }}>
        {/* ★「正在使用」取 `last_aid`（代理最近一次真的用了谁），并**把时间写出来** ——
            逐请求轮换下"正在"是有时效的，3 小时前那次和 3 秒前那次意义完全不同。 */}
        <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".12em",
                      color: t.accent, fontFamily: MONO }}>
          正在使用{board.cur_ago_min != null && (
            <span style={{ color: t.muted, letterSpacing: 0 }}> · {fmtAgo(board.cur_ago_min)}</span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 7, marginTop: 1 }}>
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-.01em",
                         whiteSpace: "nowrap" }}>{cur.label}</span>
          {cur.pin != null && (
            <span data-runway-pin style={{ fontSize: 10, fontWeight: 700, color: t.accent }}>
              ▲{cur.pin}
            </span>
          )}
          {/* ★★ 「这个号本来不该被用」必须写在号名旁边 —— 那是眼睛第一个落点。
              只写在下面那条告警里的话，用户仍然是先看到一个不该出现的名字。 */}
          {borrowed && (
            <span data-runway-borrowed title={
              cur.off ? "你已停用它的自动轮换，但此刻没有别的号可用，代理临时借用了它"
                      : cur.dead ? "这个号的凭证已失效" : `这个号在冷却中（还有 ${cur.cool_min} 分钟）`}
              style={{ fontSize: 9, fontWeight: 700, color: "#E0524D", cursor: "help",
                       border: "1px solid #E0524D", borderRadius: 5, padding: "0 4px",
                       // ★ 左列收窄之后它会被劈成「临时借 / 用」—— 断字在本仓算 bug。
                       //   角标是**原子**，永远不在内部断开；要让的是旁边的邮箱（它有省略号）。
                       whiteSpace: "nowrap", flexShrink: 0 }}>
              临时借用
            </span>
          )}
          <PlanBadge plan={cur.plan ?? ""} t={t} size={9} />
          <span style={{ fontSize: 11, color: t.text2, fontFamily: MONO, minWidth: 0,
                         overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {maskId(cur.email ?? "", privacy)}
          </span>
        </div>
        <div style={{ display: "flex", gap: 11, marginTop: 3, fontSize: 11,
                      color: t.text2, fontFamily: MONO, flexWrap: "wrap", rowGap: 2 }}>
          {cur.wins.map((w) => (
            <span key={w.label} style={{ whiteSpace: "nowrap" }}>
              {w.label} <b style={{ color: sc }}>{w.rem}%</b>
              {w.reset && <span style={{ color: t.muted }}> ↻{w.reset}</span>}
            </span>
          ))}
          {showNext && n && (
            <span data-runway-next style={{ whiteSpace: "nowrap", color: t.muted }}>
              · 下一个 → <b style={{ color: t.accent }}>{n.label}</b>
            </span>
          )}
        </div>
      </div>

      <div style={{ flex: "1 1 360px", minWidth: 280 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 7, flexWrap: "wrap" }}>
          {/* ★★★ 见底时**不画续航数字**。此刻 `weekly_left_pp` 是 0（可用池为空），
              算出来的「续航 ≈ 0 小时」是句假话 —— 冷却的号一小时内就会回来。
              「撑不了多久」与「暂时被锁在外面」是两件相反的事，本仓头号铁律。 */}
          {stranded ? (
            <>
              {/* ★★ **实心红底**，不是小号红字。这是整条里最重要的信号（系统正在推翻
                  用户的设置），而 9.5px 的红字会被旁边 19px 的数字整个压住 ——
                  本仓 §5d：选中/生效态用实心填充 + 反白文字，告警同理。 */}
              <span style={{ fontSize: 10, color: "#fff", fontFamily: MONO, fontWeight: 700,
                             letterSpacing: ".06em", background: "#E0524D",
                             borderRadius: 5, padding: "2px 6px" }}>池子见底</span>
              <span data-runway-stranded style={{ fontSize: 19, fontWeight: 700,
                                                  fontFamily: MONO, lineHeight: 1.1 }}>
                {board.rest.length} 个号全不可用
              </span>
              {backInMin != null && (
                <span style={{ fontSize: 10.5, color: t.text2 }}>
                  最快 <b style={{ color: t.accent }}>{backInMin}</b> 分钟后回来
                </span>
              )}
            </>
          ) : (
          <>
          <span style={{ fontSize: 9.5, color: t.muted, fontFamily: MONO }}>全池续航</span>
          {/* ★★ 取不到写 `—` **绝不写 0** —— 0 会被读成「快没了」，与「算不出来」相反。 */}
          <span data-runway-hours style={{ fontSize: 19, fontWeight: 700, fontFamily: MONO,
                                           fontVariantNumeric: "tabular-nums", lineHeight: 1.1 }}>
            {board.runway_active_hours == null ? "—" : `≈ ${board.runway_active_hours}`}
          </span>
          {/* ★ 单位有自己的钩子（`data-runway-unit`）而不是靠全条文本匹配：
              下面那行披露里也有「活跃小时」四个字，拿整条 textContent 断言的话，
              **把这里整个删掉闸照样绿**（本仓空守卫形态③：断言打在了另一个元素上）。 */}
          <span data-runway-unit style={{ fontSize: 10.5, color: t.text2 }}>活跃小时</span>
          <span style={{ fontSize: 9.5, color: t.muted, fontFamily: MONO, marginLeft: "auto",
                         whiteSpace: "nowrap" }}>
            周窗共剩 {board.weekly_left_pp}pp
            {board.burn_pp_per_active_hour != null && ` · ${board.burn_pp_per_active_hour}pp/h`}
          </span>
          </>
          )}
        </div>
        <div data-runway-bar ref={barRef} style={{ display: "flex", gap: 2, marginTop: 4,
                                      borderRadius: 6, overflow: "hidden" }}>
          {board.queue.map((e, i) => seg(e, i, false))}
          {/* ★★ 不可用的号合成**一段**，不是每号一段。实测：三个灰段各 11px 宽，
              而名字要 22px ⇒ 每一个都横向溢出（本仓算 bug），而且 11px 上的名字
              本来就读不出内容。合并之后这一段说得反而更清楚：**有几个不在池子里**。
              ★ 谁、为什么，进 `title` —— 这里它是**明细**不是主信息，与浮层那条
                「独有明细可以留在 title」同一判据。 */}
          {board.rest.length > 0 && (
            <span data-runway-rest
                  title={board.rest.map((e) => `${e.label} —— ${
                    e.off ? "已停用轮换" : e.dead ? "凭证失效" : `冷却中 ${e.cool_min}m`}`).join("\n")}
                  style={{ flexGrow: restW, flexBasis: 0,
                           minWidth: 0, height: 24, display: "grid", placeItems: "center",
                           overflow: "hidden", whiteSpace: "nowrap", cursor: "help",
                           fontFamily: MONO, fontSize: 10, fontWeight: 700,
                           color: t.muted, background: t.ghostBg }}>
              {fits(restW, `不可用 ${board.rest.length}`)
                ? `不可用 ${board.rest.length}` : board.rest.length}
            </span>
          )}
        </div>
        {/* ★★★ 这一行是**披露不是装饰**：没有它，「5.9 小时」会被读成自然小时。 */}
        <div data-runway-note style={{ fontSize: 9.5, color: t.muted, marginTop: 3,
                                       fontFamily: MONO, whiteSpace: "nowrap", overflow: "hidden",
                                       textOverflow: "ellipsis" }}>
          {/* ★★ 按 `runway_active_hours == null` 分支，**不是** `samples > 0`。
              两者能分开：样本有几条、但跨度不够半小时时速度照样算不出来 ——
              旧写法此时显示「3 条样本 · 活跃小时不是自然小时」，而上面那个数是「—」，
              **用户看到一个破折号却拿不到任何原因**。变异验证时发现：
              「样本不足」那句任何夹具都渲染不到，是一条死分支（本仓形态⑩）。 */}
          {/* ★ 文本要说「做什么」，不是只说「坏了」。停用的号是**唯一**用户此刻能动的旋钮
              （冷却要等、失效要重登），所以只在有停用号时才给那句操作提示。 */}
          {stranded
            ? `${nCool} 个冷却中 · ${nOff} 个你已停用 · ${nDead} 个凭证失效`
              + (nOff > 0 ? " —— 想立刻继续用，把某个停用的号在它卡片上打开轮换" : "")
            : board.runway_active_hours == null
            ? `续航算不出来 —— 不是「撑不了多久」（样本 ${board.samples} 条，还不够估速度）`
            : `${board.samples} 条样本 · 活跃小时不是自然小时`
              + (board.last_sample_min != null ? ` · 最后一条 ${fmtAgo(board.last_sample_min)}` : "")}
        </div>
      </div>
    </div>
  );
}

/** 色带配色。★ 与平台识别色无关 —— 这里区分的是**同一个平台里的不同账号**。 */
const SEG_COLORS = ["#2dd4bf", "#4d9fff", "#8b7cf6", "#E0A21C", "#27B26B", "#E0784F"];

/** 分钟 → 人话。★ 「3 小时前」和「刚刚」对「正在使用」这四个字的含义影响极大。 */
function fmtAgo(min: number): string {
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  return h < 24 ? `${h} 小时前` : `${Math.floor(h / 24)} 天前`;
}
