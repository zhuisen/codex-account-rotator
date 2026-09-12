import type { Theme } from "../theme";
import type { Span } from "../traffic";
import { spanDays, isMonthly, MONTH_CUTOVER_DAYS } from "../traffic";

/**
 * 自定义区间的起止日期（用户 2026-09-12：「我还希望新增一个自定义的时间」）。
 *
 * ★ **共用组件,不在两个页面各写一份。** 总览与平台详情是同一类页面,§5c 定稿要求长得一样;
 *   各写一份的话,两边的日期格式/校验/粒度提示迟早会分叉,而分叉之后没有任何东西会报错。
 *
 * ★ **粒度提示写在控件里,不写在图上。** 用户选完日期之后横轴可能是天也可能是月
 *   （`isMonthly`,分界 90 天）—— 那是**选择的后果**,该在做选择的地方说,
 *   而不是等图画出来让人自己看出来。
 *
 * ⚠️ 用原生 `<input type="date">`:它自带本地化日期格式、键盘输入与系统日历。
 *   自绘一个日历控件要处理时区、闰年、locale 三件事,而这里的值**只是一个 `YYYY-MM-DD` 字符串**
 *   （`p.days` 的键就是这个形状,scan.py 按本地日分桶）——一转 `Date` 就把时区带进来了。
 */
export default function SpanPicker({ span, onChange, max, min, t }: {
  span: Span | null;
  onChange: (s: Span) => void;
  /** 数据里最新/最早的那一天,`YYYY-MM-DD`。用来钳住选择范围,别让用户选出一段空白。 */
  max?: string;
  min?: string;
  t: Theme;
}): React.ReactElement {
  const cur = span ?? { start: "", end: "" };
  const n = span ? spanDays(span) : 0;
  // ★ 三态,不是二值：没选完 / 选反了 / 选好了。把「还没填完」和「填错了」合并成一个提示，
  //   用户会以为自己填错了而去改已经填对的那一半。
  const note = !cur.start || !cur.end
    ? "选择起止日期"
    : n <= 0
      ? "结束日期早于开始日期"
      : `${n} 天 · 按${isMonthly("custom", span!) ? "月" : "天"}分格` +
        (n > MONTH_CUTOVER_DAYS ? "" : `（超过 ${MONTH_CUTOVER_DAYS} 天改按月）`);

  const box: React.CSSProperties = {
    fontFamily: "'JetBrains Mono'", fontSize: 11, color: t.text,
    background: "transparent", border: `1px solid ${t.ghostBorder}`, borderRadius: 7,
    padding: "3px 7px", colorScheme: t.appBg === "#0e1117" ? "dark" : "light",
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <input type="date" value={cur.start} max={cur.end || max} min={min} style={box}
             onChange={(e) => onChange({ ...cur, start: e.target.value })} />
      <span style={{ color: t.muted, fontSize: 11 }}>→</span>
      <input type="date" value={cur.end} min={cur.start || min} max={max} style={box}
             onChange={(e) => onChange({ ...cur, end: e.target.value })} />
      <span style={{ color: t.muted, fontSize: 11, fontFamily: "'JetBrains Mono'" }}>{note}</span>
    </div>
  );
}
