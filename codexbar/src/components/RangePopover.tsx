import { useEffect, useState } from "react";
import type { Theme } from "../theme";
import type { DateRange, Granularity, RangeState } from "../traffic";
import {
  MAX_RANGE_DAYS, addDays, diffDays, presetList, resolveRange, toD,
} from "../traffic";

const MONO = "'JetBrains Mono'";
const GRANS: [Granularity, string][] = [["auto", "自动"], ["day", "天"], ["week", "周"], ["month", "月"]];

/**
 * 自定义时间范围 · 日历弹层（交接稿 `自定义范围-交接说明.md` §2–§3，1:1 复刻）。
 *
 * ★★ **草稿态与已应用态是两份数据。** 弹层里点日期只改 `ds/de` 草稿，点「应用」才写回
 *   `RangeState`。不分开的话，选完起点、还没选终点的那一刻，全页会按一个**一天**的区间
 *   重算一遍（KPI 跳一下再跳回来），而那段数据用户根本没要。
 *
 * ★ 日期算术全程走 `YYYY-MM-DD` 字符串 + UTC（交接稿 §8）。一旦中途转本地 `Date`，
 *   半小时偏移的时区会让「加一天」偶尔停在同一天。
 */
export default function RangePopover({ st, today, onApply, onClose, t }: {
  st: RangeState;
  /** 数据里的"今天"（不是挂钟 —— 桶是按本地日切的，午夜前后会差一天）。 */
  today: string;
  onApply: (next: { range: DateRange; gran: Granularity; compare: boolean }) => void;
  onClose: () => void;
  t: Theme;
}): React.ReactElement {
  const seed = resolveRange(st, today);
  const [ds, setDs] = useState<string | null>(seed.s);
  const [de, setDe] = useState<string | null>(seed.e);
  /** hover 预览的终点（交接稿 §3：选完起点后，hover 任何更晚的日期即实时预览区间）。 */
  const [hov, setHov] = useState<string | null>(null);
  const [gran, setGran] = useState<Granularity>(st.gran);
  const [cmp, setCmp] = useState(st.compare);
  // 左月 = 草稿起点所在月（交接稿 §2）
  const [vy, setVy] = useState(Number(seed.s.slice(0, 4)));
  const [vm, setVm] = useState(Number(seed.s.slice(5, 7)));

  const dn = ds && de ? diffDays(ds, de) : (ds && hov && hov > ds ? diffDays(ds, hov) : 0);
  const over = dn > MAX_RANGE_DAYS;
  const canApply = !!ds && !!de && !over;

  // Esc 关闭 · Enter 应用（交接稿 §6「键盘」）
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      if (e.key === "Enter" && ds && de && !over) {
        e.preventDefault();
        onApply({ range: { s: ds, e: de }, gran, compare: cmp });
      }
    };
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("keydown", k); };
  }, [ds, de, over, gran, cmp, onApply, onClose]);

  const pickDay = (d: string) => {
    // 第一下 = 开始（结束清空）；第二下 = 结束；点到更早的日期则改为新开始。
    if (!ds || de) { setDs(d); setDe(null); setHov(null); }
    else if (d < ds) setDs(d);
    else { setDe(d); setHov(null); }
  };

  const ry = vm === 12 ? vy + 1 : vy, rm = vm === 12 ? 1 : vm + 1;
  // 右月已经到（或超过）当前月时，› 置灰 —— 未来没有数据可选。
  const nextOk = ry * 100 + rm < Number(today.slice(0, 4)) * 100 + Number(today.slice(5, 7));

  const month = (y: number, m: number) => {
    const first = new Date(Date.UTC(y, m - 1, 1));
    const nDays = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const off = (first.getUTCDay() + 6) % 7;          // 周一为一周起点
    const lo = ds, hi = de ?? (hov && ds && hov > ds ? hov : null);
    const cells: React.ReactElement[] = [];
    for (let i = 0; i < off; i++) cells.push(<div key={`p${i}`} style={{ width: 24, height: 24 }} />);
    for (let d = 1; d <= nDays; d++) {
      const iso = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const fut = iso > today;
      const edge = iso === ds || iso === de || (!de && iso === hi);
      const inR = !!lo && !!hi && iso >= lo && iso <= hi;
      cells.push(
        <div key={iso}
             onClick={() => { if (!fut) pickDay(iso); }}
             onMouseEnter={() => { if (!fut && ds && !de) setHov(iso); }}
             style={{
               width: 24, height: 24, display: "grid", placeItems: "center",
               fontSize: 10.5, fontFamily: MONO, cursor: fut ? "not-allowed" : "pointer",
               // ★ 端点圆角、区间内**不圆角** —— 圆角会把连续色带断成一颗颗，
               //   而色带正是"这是一段"的唯一视觉表达（交接稿 §2）。
               borderRadius: edge ? 6 : 0,
               background: edge ? t.accent : (inR ? t.accentSoft : "transparent"),
               color: edge ? t.accentText : (fut ? t.muted : (iso === today ? t.accent : t.text2)),
               opacity: fut ? .45 : 1,
               fontWeight: edge || iso === today ? 700 : 400,
             }}>{d}</div>,
      );
    }
    return cells;
  };

  const cal = (y: number, m: number, side: "left" | "right") => (
    <div style={{ flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                    marginBottom: 6, fontFamily: MONO, fontSize: 11.5 }}>
        {side === "left"
          ? <span onClick={() => { const nm = vm === 1 ? 12 : vm - 1; setVy(vm === 1 ? vy - 1 : vy); setVm(nm); }}
                  style={{ width: 20, height: 20, display: "grid", placeItems: "center",
                           color: t.muted, borderRadius: 5, cursor: "pointer" }}>‹</span>
          : <span style={{ width: 20 }} />}
        <b style={{ color: t.text }}>{`${y}-${String(m).padStart(2, "0")}`}</b>
        {side === "right"
          ? <span onClick={() => { if (!nextOk) return; const nm = vm === 12 ? 1 : vm + 1; setVy(vm === 12 ? vy + 1 : vy); setVm(nm); }}
                  style={{ width: 20, height: 20, display: "grid", placeItems: "center",
                           color: nextOk ? t.muted : t.ghostBorder, borderRadius: 5,
                           cursor: nextOk ? "pointer" : "default" }}>›</span>
          : <span style={{ width: 20 }} />}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,24px)", gap: 2, marginBottom: 2 }}>
        {["一", "二", "三", "四", "五", "六", "日"].map((w) => (
          <span key={w} style={{ textAlign: "center", fontSize: 9, color: t.muted, fontFamily: MONO }}>{w}</span>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,24px)", gap: "2px 0" }}>{month(y, m)}</div>
    </div>
  );

  const field = (v: string | null, placeholder: string, active: boolean) => (
    <span style={{
      padding: "5px 9px", background: t.popFieldBg, borderRadius: 7, minWidth: 86,
      border: `1px solid ${active ? t.accentBorder : t.ghostBorder}`,
      color: v ? t.text : t.muted, fontFamily: MONO, fontSize: 11,
      fontVariantNumeric: "tabular-nums",
    }}>{v ?? placeholder}</span>
  );

  const presets = presetList(today);
  return (
    <div onClick={(e) => e.stopPropagation()}
         style={{
           position: "absolute", right: 22, top: 58, width: 580, zIndex: 5,
           background: t.popBg, border: `1px solid ${t.ghostBorder}`, borderRadius: 12,
           boxShadow: t.popShadow, display: "flex", overflow: "hidden",
           animation: "cbFade .18s ease",
         }}>
      {/* 左：预设列 */}
      <div style={{ width: 124, flex: "none", borderRight: `1px solid ${t.divider}`,
                    padding: "10px 6px", display: "flex", flexDirection: "column", gap: 1,
                    fontFamily: MONO, fontSize: 11 }}>
        {presets.map((p, i) => p.sep
          ? <span key={`s${i}`} style={{ height: 1, background: t.divider, margin: "4px 6px" }} />
          : (() => {
              // ★ 判据是"草稿**恰好等于**这个预设"，不是"用户点过它" ——
              //   点完再手动改一天，高亮就该灭掉，否则它在说一件不成立的事。
              const on = p.r.s === ds && p.r.e === de;
              return (
                <span key={p.label}
                      onClick={() => {
                        setDs(p.r.s); setDe(p.r.e); setHov(null);
                        setVy(Number(p.r.s.slice(0, 4))); setVm(Number(p.r.s.slice(5, 7)));
                      }}
                      style={{ padding: "6px 10px", borderRadius: 6, cursor: "pointer",
                               color: on ? t.accent : t.text2,
                               background: on ? t.accentSoft : "transparent",
                               fontWeight: on ? 700 : 400 }}>{p.label}</span>
              );
            })())}
      </div>

      {/* 右：双月日历 + 两行底栏 */}
      <div style={{ flex: 1, padding: "12px 14px 10px", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", gap: 18 }}>{cal(vy, vm, "left")}{cal(ry, rm, "right")}</div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10,
                      fontFamily: MONO, fontSize: 11, whiteSpace: "nowrap" }}>
          {field(ds, "开始", !!ds && !de)}
          <span style={{ color: t.muted }}>→</span>
          {field(de ?? (hov && ds && hov > ds ? hov : null), "结束", !!de || !ds)}
          <span style={{ fontWeight: 700, color: over ? "#E0524D" : t.accent }}>
            {dn ? `${dn} 天` : ""}
          </span>
          <span style={{ marginLeft: "auto", color: t.muted, fontSize: 10.5 }}>分格</span>
          <div style={{ display: "flex", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`,
                        borderRadius: 6, fontSize: 10.5 }}>
            {GRANS.map(([k, label]) => (
              <span key={k} onClick={() => setGran(k)}
                    style={{ padding: "2px 8px", borderRadius: 4, cursor: "pointer", fontWeight: 700,
                             color: gran === k ? t.accentText : t.muted,
                             background: gran === k ? t.accent : "transparent" }}>{label}</span>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10,
                      paddingTop: 9, borderTop: `1px solid ${t.divider}` }}>
          <span onClick={() => setCmp(!cmp)}
                style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 10.5,
                         color: t.text2, fontFamily: MONO, cursor: "pointer" }}>
            <span style={{ width: 26, height: 15, borderRadius: 999, position: "relative",
                           display: "inline-block", transition: "background .15s",
                           background: cmp ? t.accent : t.ringTrack }}>
              <span style={{ position: "absolute", top: 2, left: cmp ? 13 : 2, width: 11, height: 11,
                             borderRadius: "50%", transition: "left .15s",
                             background: cmp ? t.accentText : t.muted }} />
            </span>
            环比上一等长周期
          </span>
          {/* ★ 越界是**红字 + 应用置灰**，不弹窗（交接稿 §3）。弹窗会打断选择过程，
              而用户下一步多半就是把终点往回拖一格。 */}
          <span style={{ fontSize: 10.5, color: "#E0524D", fontFamily: MONO }}>
            {over ? `超过 ${MAX_RANGE_DAYS} 天上限` : ""}
          </span>
          <span onClick={onClose}
                style={{ marginLeft: "auto", fontSize: 11.5, color: t.muted,
                         padding: "6px 10px", cursor: "pointer" }}>取消</span>
          <span onClick={() => { if (canApply) onApply({ range: { s: ds!, e: de! }, gran, compare: cmp }); }}
                style={{ fontSize: 11.5, fontWeight: 700, color: t.accentText, background: t.accent,
                         padding: "6px 14px", borderRadius: 8,
                         cursor: canApply ? "pointer" : "default", opacity: canApply ? 1 : .4 }}>应用</span>
        </div>
      </div>
    </div>
  );
}

/** 这一天是不是今天（给调用方复用同一套 UTC 口径）。 */
export const isToday = (iso: string, today: string): boolean => toD(iso).getTime() === toD(today).getTime();
/** 给「昨日」这类预设用。 */
export const yesterday = (today: string): string => addDays(today, -1);
