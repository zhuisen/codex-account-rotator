import { useState } from "react";
import type { Theme } from "../theme";
import type { RangeState } from "../traffic";
import { DEFAULT_RANGE, PILLS, diffDays, matchPreset, md, rangeLabel, resolveRange } from "../traffic";
import RangePopover from "./RangePopover";

const MONO = "'JetBrains Mono'";

const Chevron = ({ up }: { up: boolean }) => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
       style={{ stroke: "currentColor", strokeWidth: 3 }}>
    <path d={up ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"} />
  </svg>
);

/**
 * 标题行右侧的时间段控件（交接稿 `自定义范围-交接说明.md` §1/§4，1:1 复刻）。
 *
 * `今日 · 7d · 30d · 年度 · 范围▾`，选了自定义之后「范围▾」原地变成**范围芯片**
 * `08-14 → 09-05 23d ▾ │ ✕`。
 *
 * ★★ **14d / 90d 从 pill 里移除**，退到弹层预设列。理由是标题行零挤压：
 *   7 个 pill + 双日期框在 960px 下必然折行，而这一行还有「上次刷新」。
 * ★ 这个组件**同时拥有弹层**（而不是让页面去管 open 状态）：弹层要贴着控件定位
 *   （`right:22px; top:58px`），拆开就得把坐标知识复制到页面里。
 */
export default function RangeBar({ st, today, onChange, onToast, t }: {
  st: RangeState;
  today: string;
  onChange: (next: RangeState) => void;
  onToast: (msg: string) => void;
  t: Theme;
}): React.ReactElement {
  const [open, setOpen] = useState(false);
  const isCustom = st.preset === "custom";
  const r = resolveRange(st, today);

  const seg = (on: boolean): React.CSSProperties => ({
    padding: "5px 12px", borderRadius: 7, cursor: "pointer", whiteSpace: "nowrap",
    fontWeight: 700, color: on ? t.accentText : t.muted,
    background: on ? t.accent : "transparent", transition: "background .2s, color .2s",
  });

  return (
    // ★ `data-seg`：与 `Seg` 同一条探针（`segRows`）。它虽然是**另一个组件**，
    //   但对用户是同一类控件（互斥单选），折行的后果一模一样 ——
    //   只给 `Seg` 打标记，探针就正好漏掉用户红框里的另一半。
    <div data-seg="range"
         style={{ display: "flex", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`,
                  borderRadius: 9, fontFamily: MONO, fontSize: 11.5, alignItems: "center",
                  position: "relative" }}>
      {PILLS.map((p) => (
        <span key={p} style={seg(st.preset === p)}
              onClick={() => {
                setOpen(false);
                // ★★★ **切回固定档时把分格复位成 `auto`。**（2026-09-13 用户截图抓到。）
                //   `gran` 是在弹层里**为某个自定义区间**选的，而 `RangeState` 把它存成全局字段
                //   （交接稿 §7 的形状）。不复位的话它会粘在后面每一个档上：
                //   实测用户的年度档显示 `9 格 · 按月`，而 256 天按 auto 该是**按周**；
                //   更极端的是「30d 按月」—— 整整一个月缩成 1~2 格，图表等于没有。
                //   ★ 固定档的分格**按定义就是自动的**（稿子只在弹层里给了那个分段控件）。
                onChange({ ...st, preset: p, gran: "auto" });
              }}>
          {rangeLabel(p)}
        </span>
      ))}

      {isCustom ? (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 7,
                       padding: "4px 6px 4px 11px", borderRadius: 7, color: t.accentText,
                       background: t.accent, fontWeight: 700, whiteSpace: "nowrap",
                       animation: "cbFade .2s ease" }}>
          <span onClick={() => setOpen(!open)}
                style={{ display: "inline-flex", alignItems: "center", gap: 7, cursor: "pointer" }}>
            {`${md(r.s)} → ${md(r.e)}`}
            {/* 天数用 500 字重 + 75% 不透明：它是**限定**不是标题，同字重会和日期打架 */}
            <span style={{ fontWeight: 500, opacity: .75 }}>{`${diffDays(r.s, r.e)}d`}</span>
            <Chevron up={open} />
          </span>
          <span style={{ width: 1, height: 12, background: "rgba(6,35,31,.3)" }} />
          <span title="清除，回到 30d"
                onClick={() => {
                  // ★ 清除只是**回到 30d**，不丢掉这段区间 —— `lastCustom` 留着，
                  //   下次点「范围」直接预填（交接稿 §6「记忆」）。
                  setOpen(false);
                  onChange({ ...st, preset: "30d", custom: null });
                  onToast("已回到 30d · 上次范围可从「范围」恢复");
                }}
                style={{ display: "grid", placeItems: "center", cursor: "pointer",
                         width: 16, height: 16, borderRadius: 4 }}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                 style={{ stroke: "currentColor", strokeWidth: 2.6 }}><path d="M6 6l12 12M18 6L6 18" /></svg>
          </span>
        </span>
      ) : (
        <span onClick={() => setOpen(!open)}
              style={{ display: "inline-flex", alignItems: "center", gap: 6,
                       padding: "5px 8px 5px 12px", borderRadius: 7, cursor: "pointer",
                       whiteSpace: "nowrap", color: open ? t.accent : t.muted,
                       border: `1px solid ${open ? t.accentBorder : "transparent"}` }}>
          范围<Chevron up={open} />
        </span>
      )}

      {open && (
        <RangePopover
          st={st} today={today} t={t}
          onClose={() => setOpen(false)}
          onApply={({ range, gran, compare }) => {
            setOpen(false);
            // ★ 区间恰好等于某个固定档时**点亮那个 pill**，不造一个内容一样的自定义芯片。
            //   判据是区间相等（`matchPreset`），所以手动选出同一段也走同一条路。
            const hit = matchPreset(range, today);
            onChange(hit
              ? { ...st, preset: hit, custom: null, lastCustom: range, gran: "auto", compare }
              : { ...st, preset: "custom", custom: range, lastCustom: range, gran, compare });
            onToast(`范围已应用 · ${md(range.s)} → ${md(range.e)}`);
          }} />
      )}
    </div>
  );
}

/** 供页面在空白处点击时收起弹层用的默认值。 */
export const RESET_RANGE = DEFAULT_RANGE;
