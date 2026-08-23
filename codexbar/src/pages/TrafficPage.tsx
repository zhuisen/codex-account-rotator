import { useEffect, useMemo, useState } from "react";
import { type Theme, modelColor } from "../theme";
import { fmtUSD } from "../rates";
import StackedArea, { type Layer } from "../components/StackedArea";
import Seg from "../components/Seg";
import KpiStrip, { type Kpi, UP, DOWN } from "../components/KpiStrip";
import CacheChip from "../components/CacheChip";
import { useIntro, introEnabled } from "../hooks/useIntro";
import type { TrafficData, Bucket, Range, CacheMode, PlatformPrefs } from "../traffic";
import { RANGES, rangeLabel, bucketsFor, sumBuckets, costOfBucket, savingOfBucket, fmtTok, topModels, colorOf, countsCacheRead, orderedKeys, coveragePct, coverageNote } from "../traffic";
import type { Coverage } from "../traffic";

const AMBER = "#E0A21C";

/** AI用量信息 · 总览（交接稿 §1–§4）。数据源是各 CLI 自己写在本机的 transcript,零额度消耗。 */
const IconRefresh = ({ spin }: { spin?: boolean }) => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       style={{ animation: spin ? "cbSpin .8s linear infinite" : "none", transformOrigin: "center" }}>
    <path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4" />
  </svg>
);

export default function TrafficPage({ t, data, raw, cacheMode, prefs, range, setRange, onDrill, busy, err, onRefresh }: {
  t: Theme;
  /** 已按缓存口径重塑 —— 一切合计/图表/费用都用它 */
  data: TrafficData | null;
  /** **只未套「缓存口径」这一层,平台偏好已经套过**(否则停用的平台会混进缓存占比的分母)。
   *  只给缓存占比那一格用(它要的正是缓存重塑时被清零的那个数),别拿它算展示合计 */
  raw: TrafficData | null;
  cacheMode: CacheMode;
  /** 平台呈现偏好。**这里只用它的 `order` 排列表** —— 停用/改名/改色已在 `useTraffic` 出口生效。 */
  prefs: PlatformPrefs;
  range: Range;
  setRange: (r: Range) => void;
  onDrill: (platform: string) => void;
  busy: boolean;
  err: string | null;
  onRefresh?: () => void;
}): React.ReactElement {
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const isToday = range === "today";
  // ★ 依赖是**数据集身份**不是数据 —— 拿 data 当依赖会让页面每 2 分钟自动刷新时重播一次动画。
  const intro = useIntro(String(range));

  const view = useMemo(() => {
    if (!data) return null;
    const keys = Object.keys(data.platforms);
    const series = keys.map((k) => {
      const { labels, buckets } = bucketsFor(data, k, range);
      return { key: k, name: data.platforms[k].name, labels, buckets };
    });
    const labels = series[0]?.labels ?? [];
    const per = series.map((s) => {
      const agg = sumBuckets(s.buckets);
      return { ...s, agg, total: agg.total, rounds: agg.rounds, cost: costOfBucket(agg, s.key),
             saving: savingOfBucket(agg, s.key) };
    });
    // ★ per 恒按占比降序。**图层顺序、`最大占比` KPI 都靠它**,不能被用户的排列顺序影响
    //    (「占大头的铺满基线」是 2026-08-09 看了两版实物定的)。
    per.sort((a, b) => b.total - a.total);
    // 用户排的顺序**只用于列表与图例**(2026-08-12 定稿)。没排过的跟在后面按占比降序。
    const byKey = new Map(per.map((x) => [x.key, x]));
    const list = orderedKeys(per.map((x) => x.key), prefs, (k) => byKey.get(k)?.total ?? 0)
                   .map((k) => byKey.get(k)!)
                   .filter(Boolean);
    const grand = per.reduce((s, p) => s + p.total, 0);
    const grandRounds = per.reduce((s, p) => s + p.rounds, 0);
    const grandCost = per.reduce((s, p) => s + p.cost, 0);
    const grandSaving = per.reduce((s, p) => s + p.saving, 0);
    return { labels, per, list, grand, grandRounds, grandCost, grandSaving };
  }, [data, range, prefs]);

  /**
   * 环比基准 = **与当前窗口等长的上一段**(今日 → 昨日整天;7d → 再往前 7 天;以此类推)。
   *
   * App 恒按 `--days 90` 取数,所以 7/14/30 档都有完整上期;**90d 档没有上一个 90 天,返回 null,
   * UI 显示「—」** —— 拿不足 90 天的一段当上期算出来的百分比是假的,宁可不给。
   */
  const prev = useMemo(() => {
    if (!data) return null;
    let tok = 0, cost = 0, ok = false;
    for (const k of Object.keys(data.platforms)) {
      const p = data.platforms[k];
      const days = Object.keys(p.days).sort();
      if (isToday) {
        const yd = days[days.length - 2];
        if (yd) { ok = true; tok += p.days[yd].total; cost += costOfBucket(p.days[yd], k); }
      } else {
        const n = range as number;
        const win = days.slice(-2 * n, -n);
        if (win.length === n) {
          ok = true;
          for (const d of win) { tok += p.days[d].total; cost += costOfBucket(p.days[d], k); }
        }
      }
    }
    return ok ? { tok, cost } : null;
  }, [data, range, isToday]);


  const delta = (now: number, base: number) => {
    if (!base) return null;
    const p = ((now - base) / base) * 100;
    return { up: p >= 0, txt: `${p >= 0 ? "↑" : "↓"}${Math.abs(p).toFixed(1)}%` };
  };

  // ★ 图层自下而上 = 占比**降序**(大的贴基线,小的压在上面) —— 用户 2026-08-09 定稿。
  //   曾按用户要求反成升序,同日看到实物后又改回:占大头的那家铺满基线、小的作为顶上的带,
  //   比"85% 悬在半空、15% 被压在轴线上"清楚得多。`per` 已是降序,直接用,别再 reverse。
  const layers: Layer[] = (view?.per ?? []).map((p) => ({
    key: p.key, name: p.name, color: colorOf(data, p.key),
    values: p.buckets.map((b) => b.total),
  }));

  const top = view?.per[0];
  const dTok = prev ? delta(view?.grand ?? 0, prev.tok) : null;
  const dCost = prev ? delta(view?.grandCost ?? 0, prev.cost) : null;

  // ★ 缓存披露独立成一格(用户 2026-08-09 定稿,原来是首格底下的一行小字):`total` 里 96%+ 是
  //   缓存重读(同一段历史被反复重发),只给一个 561M 会让人以为真烧了 5.6 亿新内容。
  //
  // ★★ 必须从 `raw` 算:`data` 已按口径重塑,里面 cache_read 恒为 0,拿它算缓存占比会永远得到
  //     0.0% —— 那不是"没有缓存",是"我把它减掉了",两回事。
  //     (只在计入缓存读时才会用到这个数,其余口径下这一格根本不渲染。)
  const rawCacheShare = useMemo(() => {
    if (!raw) return 0;
    let cache = 0, tot = 0;
    for (const k of Object.keys(raw.platforms)) {
      const agg = sumBuckets(bucketsFor(raw, k, range).buckets);
      cache += agg.cache_read; tot += agg.total;
    }
    return tot ? (cache / tot) * 100 : 0;
  }, [raw, range]);

  const kpis: Kpi[] = [
    { k: "总 token", v: fmtTok(view?.grand ?? 0), n: view?.grand ?? 0, fmt: fmtTok,
      sub: dTok ? `环比 ${dTok.txt}` : "环比 —",
      subC: dTok ? (dTok.up ? UP : DOWN) : t.muted },
    isToday
      ? { k: "较昨日", v: dTok?.txt ?? "—", c: dTok ? (dTok.up ? UP : DOWN) : undefined }
      : { k: "日均", v: fmtTok((view?.grand ?? 0) / Math.max(1, view?.labels.length ?? 1)),
          n: (view?.grand ?? 0) / Math.max(1, view?.labels.length ?? 1), fmt: fmtTok },
    { k: "总费用", v: fmtUSD(view?.grandCost ?? 0), n: view?.grandCost ?? 0, fmt: fmtUSD, c: AMBER,
      sub: view?.grandSaving ? `缓存已省 ${fmtUSD(view.grandSaving)}` : undefined },
    isToday
      ? { k: "费用较昨日", v: dCost?.txt ?? "—", c: dCost ? (dCost.up ? UP : DOWN) : undefined }
      : { k: "日均费用", v: fmtUSD((view?.grandCost ?? 0) / Math.max(1, view?.labels.length ?? 1)),
          n: (view?.grandCost ?? 0) / Math.max(1, view?.labels.length ?? 1), fmt: fmtUSD, c: AMBER },
    { k: "最大占比",
      v: top ? `${top.name} ${((top.total / Math.max(1, view!.grand)) * 100).toFixed(1)}%` : "—",
      c: top ? colorOf(data, top.key) : undefined },
  ];
  // 缓存排最后(用户 2026-08-09 定稿):它是对首格「总 token」的**限定**而不是并列指标,
  // 夹在前面会把「总量 → 环比 → 费用」这条主线打断。
  // ★ 不计入缓存读时**整格删除**(用户 2026-08-11 定稿),不是显示 0.0%、也不是改说「已排除 X」——
  //   前者会被读成"没用到缓存"(与事实相反),后者等于换个说法把这个指标请回来。
  //   KpiStrip 是 space-evenly,少一格自动重新均分,不会留空位。
  if (countsCacheRead(cacheMode)) {
    kpis.push({ k: "缓存", v: raw ? `${rawCacheShare.toFixed(1)}%` : "—" });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%", overflow: "auto" }}>
      {/* 顶栏 */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 9 }}>
        <span style={{ fontSize: 22, fontWeight: 700, whiteSpace: "nowrap" }}>AI用量信息</span>
        {/* 开关在设置页,被它改变的数字在这里 —— 不挂个牌子,页面就会静默地把 34.2B 显示成 0.46B */}
        <CacheChip mode={cacheMode} />
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          {/* ★ 刷新按钮:页面画的是**上次扫描的快照**(所以进来不再白屏几秒),不点就一直是那一份。
              时间戳本身就是按钮 —— 「这数是几点的」和「重取」本来是同一件事,不必再占一格。 */}
          {data && (
            <span onClick={busy ? undefined : onRefresh}
                  title={busy ? "扫描中…" : "重新扫描本机 CLI 记录(只读本地文件,不消耗额度)"}
                  style={{ fontSize: 10.5, color: busy ? t.accent : t.muted, whiteSpace: "nowrap",
                           fontFamily: "'JetBrains Mono'", display: "inline-flex", alignItems: "center",
                           gap: 5, cursor: busy || !onRefresh ? "default" : "pointer", userSelect: "none",
                           transition: "color .15s" }}>
              <IconRefresh spin={busy} />
              上次刷新 {new Date(data.generated_at * 1000).toTimeString().slice(0, 5)}
              <StaleHint t={t} generatedAt={data.generated_at} />
            </span>
          )}
          <Seg opts={RANGES} cur={range} on={setRange} label={rangeLabel} t={t} />
        </div>
      </div>

      <KpiStrip t={t} items={kpis} intro={intro} />

      {err && <div style={{ fontSize: 11, color: "#E0524D", marginBottom: 8 }}>✗ {err}</div>}
      {busy && !data && <div style={{ fontSize: 12, color: t.muted }}>首次扫描三家 transcript 中(约 18s,之后走缓存)…</div>}

      {!!view?.labels.length && (
        // ★ `key={range}` 不是可有可无的:图表的 hover 是"某个数据集里的索引",换档必须让实例作废。
        //    详见 StackedArea 里 `hv` 上方的注释(靠组件自清试过两次,都被用户实测推翻)。
        <div className={introEnabled() ? "cb-wipe" : undefined} key={`w:${range}:${view.labels[0]}`}>
        <StackedArea key={`${range}:${view.labels[0]}`}
                     labels={view.labels} layers={layers} height={156} fmt={fmtTok} t={t}
                     dimmed={hoverKey} onPick={onDrill}
                     tipTitle={(i) => (isToday ? `今日 ${view.labels[i].slice(11)}:00` : view.labels[i])} />
        </div>
      )}

      {/* 平台图例行 */}
      <div style={{ marginTop: 9 }}>
        {view?.per.map((p) => {
          const c = colorOf(data, p.key);
          return (
            <div key={p.key} onClick={() => onDrill(p.key)}
                 onMouseEnter={() => setHoverKey(p.key)} onMouseLeave={() => setHoverKey(null)}
                 style={{ display: "flex", alignItems: "center", gap: 9, height: 28, cursor: "pointer",
                          borderTop: `1px solid ${t.divider}`, padding: "0 4px",
                          background: hoverKey === p.key ? "rgba(255,255,255,.04)" : "transparent",
                          transition: "background .15s" }}>
              <span style={{ width: 12, height: 12, borderRadius: 4, background: c, flexShrink: 0 }} />
              <span style={{ width: 92, fontSize: 12.5, fontWeight: 600 }}>{p.name}</span>
              <div style={{ flex: 1, height: 8, borderRadius: 4, background: t.barTrack, overflow: "hidden", minWidth: 40 }}>
                <div style={{ width: `${(p.total / Math.max(1, view.per[0].total)) * 100}%`,
                              height: "100%", background: c }} />
              </div>
              <span style={{ width: 74, textAlign: "right", fontSize: 13, fontWeight: 700,
                             fontFamily: "'JetBrains Mono'", fontVariantNumeric: "tabular-nums" }}>{fmtTok(p.total)}</span>
              <span style={{ width: 52, textAlign: "right", fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
                {((p.total / Math.max(1, view.grand)) * 100).toFixed(1)}%
              </span>
              {/* ★ 轮数是**要读的数字**。此处曾用 `t.faint`(#454d57,深色底实算 **2.21:1**,远低于 WCAG 4.5)
              被就地换掉 —— 那个 token 已于 2026-08-23 删除,中性文字统一成三级且每级都过 4.5,
                  `t.muted` 只留给纯装饰(箭头 →、"vs 昨日"这种词缀)。用户 2026-08-10 报"太灰了"。 */}
              <span style={{ width: 74, textAlign: "right", fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
                {p.rounds.toLocaleString()}轮
              </span>
              <span style={{ width: 64, textAlign: "right", fontSize: 11.5, fontWeight: 700, color: AMBER,
                             fontFamily: "'JetBrains Mono'" }}>{fmtUSD(p.cost)}</span>
              <span style={{ width: 14, textAlign: "right", color: t.muted, fontSize: 12 }}>→</span>
            </div>
          );
        })}
      </div>

      {/* 平台卡片 / 今日饼图卡片 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 11, marginTop: 10,
                    paddingBottom: 4 }}>
        {view?.list.map((p) => (
          <PlatformCard key={p.key} t={t} name={p.name} color={colorOf(data, p.key)} buckets={p.buckets}
                        total={p.total} cost={p.cost} isToday={isToday}
                        yTotal={isToday ? yesterdayOf(data, p.key) : 0}
                        coverage={data?.platforms[p.key]?.coverage}
                        onDrill={() => onDrill(p.key)} rangeTxt={rangeLabel(range)} />
        ))}
        {/* ★ 占位卡只在**没坐满一行**时出现,而且文案是通用的:平台由 `traffic/scan.py` 的注册表
            决定,写死某一家的名字会在加/停平台后变成谎话(上一版写的是「Gemini 待接入」,
            而实测 Antigravity 根本不落用量、官方 gemini CLI 又是另一个东西)。 */}
        {(view?.per.length ?? 0) < 4 && (
          <div style={{ border: `1px dashed ${t.ghostBorder}`, borderRadius: 13, display: "grid",
                        placeItems: "center", color: t.muted, fontSize: 11.5, minHeight: 118,
                        textAlign: "center", lineHeight: 1.6, padding: "0 10px" }}>
            更多平台<br />
            <span style={{ fontSize: 10 }}>在 traffic/scan.py 的注册表加一行</span>
          </div>
        )}
      </div>
    </div>
  );
}

function yesterdayOf(data: TrafficData | null, key: string): number {
  if (!data) return 0;
  const days = Object.keys(data.platforms[key]?.days ?? {}).sort();
  const yd = days[days.length - 2];
  return yd ? data.platforms[key].days[yd].total : 0;
}

/** §1 平台卡片 / §4 今日模型饼图卡片 */
function PlatformCard({ t, name, color, buckets, total, cost, isToday, yTotal, onDrill, rangeTxt, coverage }: {
  t: Theme; name: string; color: string; buckets: Bucket[]; total: number; cost: number;
  isToday: boolean; yTotal: number; onDrill: () => void; rangeTxt: string; coverage?: Coverage;
}): React.ReactElement {
  const [hov, setHov] = useState(false);
  const c = color;
  const cur = buckets.length ? buckets[buckets.length - 1].total : 0;
  const shown = isToday ? total : cur;
  const d = yTotal ? ((total - yTotal) / yTotal) * 100 : null;
  const tops = topModels(buckets, 3);

  const box: React.CSSProperties = {
    background: t.isDark ? "#10161d" : t.cardBg, borderRadius: 13, padding: "11px 11px",
    border: `1px solid ${hov ? c : t.cardBorder}`, cursor: "pointer",
    transform: hov ? "translateY(-2px)" : "none", transition: "transform .15s ease, border-color .15s",
    minWidth: 0, display: "flex", flexDirection: "column",
  };

  return (
    <div style={box} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} onClick={onDrill}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
        <span style={{ width: 9, height: 9, borderRadius: "50%", background: c, flexShrink: 0 }} />
        <span style={{ fontSize: 13.5, fontWeight: 700 }}>{name}</span>
        {/* ★ 采集不完整的平台必须当场标出来。没有这枚徽章,一个偏小的数字会被读成
            「这家用得少」而不是「只统计了一部分」—— 本项目已经因为这类静默降级栽过多次。
            用琥珀(警告语义)而不是红:数据本身没错,只是不全。 */}
        <CoverageBadge t={t} coverage={coverage} />
        <span style={{ marginLeft: "auto", fontSize: 10, color: t.muted, whiteSpace: "nowrap" }}>明细 →</span>
      </div>

      {/* ★ 今日视图 = 纯左右分区:左环右字,**没有底部横条也没有分隔线**。
          原来底部那行 `今日 → $197.61` 的标签是冗余的(整张卡就是今日),而 token 数环心已经给过;
          金额并进右栏,卡片从"上下三段"变成"左右两块",信息密度不变、少一条分隔线和一整行。 */}
      {isToday ? (
        <Donut t={t} tops={tops} total={total} delta={d} cost={cost} />
      ) : (
        <>
          <div style={{ fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>今日</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{ fontSize: 22, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtTok(shown)}</span>
          </div>
          <Spark values={buckets.map((b) => b.total)} color={c} />
          <div style={{ borderTop: `1px solid ${t.divider}`, marginTop: 8, paddingTop: 7,
                        display: "flex", flexDirection: "column", gap: 3, fontSize: 10 }}>
            <Row t={t} k="Top" v={tops[0] ? `${short(tops[0].model)} · ${(tops[0].share * 100).toFixed(0)}%` : "—"} />
            <Row t={t} k={rangeTxt} v={`${fmtTok(total)} · ${fmtUSD(cost)}`} amber />
          </div>
        </>
      )}
    </div>
  );
}

/** 采集完整度徽章。`coverage` 缺席 = 该平台本就是全量,**什么都不渲染**。 */
function CoverageBadge({ t, coverage }: {
  t: Theme; coverage?: Coverage;
}): React.ReactElement | null {
  const pct = coveragePct(coverage);
  if (pct == null) return null;
  return (
    <span title={coverageNote(coverage)}
          style={{ fontSize: 8.5, fontWeight: 700, fontFamily: "'JetBrains Mono'",
                   letterSpacing: ".02em", padding: "1.5px 4px", borderRadius: 4,
                   color: AMBER, background: t.isDark ? "rgba(224,144,28,.14)" : "rgba(224,144,28,.12)",
                   whiteSpace: "nowrap", flexShrink: 0 }}>
      覆盖 {pct < 1 ? "<1" : pct.toFixed(0)}%
    </span>
  );
}

/**
 * 数据有多旧。**关掉「后台自动刷新」后这是唯一能看出数据陈旧的地方** ——
 * 没有它，这个开关就成了「一个能静默显示旧数字的开关」，正是本项目反复在防的那类东西。
 *
 * 分级而不是一见旧就报警（长亮的灯会被训练成看不见）：
 *   < 4 分钟   什么都不显示（自动刷新开着时的常态，别加噪音）
 *   4~30 分钟  灰字补一句「N 分钟前」——是信息不是警告
 *   > 30 分钟  转琥珀（这时候你多半已经忘了自己关过自动刷新）
 * 用**分钟数**而不是只染色：颜色只说「有问题」，数字才说「多旧」。
 */
function StaleHint({ t, generatedAt }: { t: Theme; generatedAt: number }): React.ReactElement | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // 30s 一跳，与 useTraffic 的节拍同频；只更新这一个小标签，不触发任何扫描。
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => { clearInterval(id); };
  }, []);
  const mins = Math.floor((now - generatedAt * 1000) / 60_000);
  if (mins < 4) return null;
  const hrs = Math.floor(mins / 60);
  return (
    <span style={{ color: mins > 30 ? AMBER : t.muted, fontWeight: mins > 30 ? 700 : 400 }}>
      · {hrs >= 1 ? `${hrs} 小时前` : `${mins} 分钟前`}
    </span>
  );
}

const short = (m: string) => m.replace(/^claude-|^gpt-|^grok-/, "");

function Row({ t, k, v, amber }: { t: Theme; k: string; v: string; amber?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 6, fontFamily: "'JetBrains Mono'" }}>
      <span style={{ color: t.muted, whiteSpace: "nowrap" }}>{k} →</span>
      <span style={{ color: amber ? AMBER : t.text2, fontWeight: amber ? 700 : 400,
                     overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v}</span>
    </div>
  );
}

function Spark({ values, color }: { values: number[]; color: string }) {
  if (!values.length) return null;
  const peak = Math.max(1, ...values);
  const W = 200, H = 36;
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * W},${(1 - v / peak) * H}`);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
         style={{ width: "100%", height: 30, marginTop: 3, display: "block" }}>
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={2}
                vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** §4 今日模型占比环形图:Top3 模型 + 其他 */
function Donut({ t, tops, total, delta, cost }: {
  t: Theme; tops: { model: string; share: number }[]; total: number;
  delta?: number | null; cost?: number;
}) {
  const R = 34, C = 2 * Math.PI * R;
  let off = 0;
  const segs = tops.map((m) => {
    const len = m.share * C;
    const s = { color: modelColor(m.model), len, off };
    off += len;
    return s;
  });
  const rest = Math.max(0, C - off);
  return (
    // 环放大到 92(原 66),图例整体压到右侧一条窄栏:原来图例 flex:1 会横铺到卡片边缘,
    // 模型名和 100% 之间拉开一大段空白,视觉上环显得更小(用户 2026-08-09 指出)。
    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
      <svg viewBox="0 0 92 92" style={{ width: 100, height: 100, flexShrink: 0 }}>
        <g transform="rotate(-90 46 46)">
          <circle cx={46} cy={46} r={R} fill="none" stroke="#454d57" strokeWidth={13}
                  strokeDasharray={`${rest} ${C - rest}`} strokeDashoffset={-off} />
          {segs.map((s, i) => (
            <circle key={i} cx={46} cy={46} r={R} fill="none" stroke={s.color} strokeWidth={13}
                    strokeDasharray={`${s.len} ${C - s.len}`} strokeDashoffset={-s.off} />
          ))}
        </g>
        <text x={46} y={45} textAnchor="middle" fontSize={15} fontWeight={700} fill={t.text}
              fontFamily="'JetBrains Mono'">{fmtTok(total)}</text>
        <text x={46} y={57} textAnchor="middle" fontSize={8} fill={t.muted}>今日</text>
      </svg>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
        {tops.map((m) => (
          <div key={m.model} style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 10,
                                      fontFamily: "'JetBrains Mono'", lineHeight: 1.25 }}>
            <span style={{ width: 7, height: 7, borderRadius: 2, background: modelColor(m.model), flexShrink: 0 }} />
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                           color: t.text2 }}>{short(m.model)}</span>
            <span style={{ color: t.muted, flexShrink: 0 }}>{(m.share * 100).toFixed(0)}%</span>
          </div>
        ))}
        {delta != null && (
          <div style={{ fontSize: 9, marginTop: 4, fontFamily: "'JetBrains Mono'",
                        color: delta >= 0 ? "#27B26B" : "#E0524D", whiteSpace: "nowrap" }}>
            {delta >= 0 ? "↑" : "↓"}{Math.abs(delta).toFixed(1)}% <span style={{ color: t.muted }}>vs 昨日</span>
          </div>
        )}
        {cost != null && (
          <div style={{ fontSize: 13, fontWeight: 700, color: AMBER, marginTop: 6,
                        fontFamily: "'JetBrains Mono'", fontVariantNumeric: "tabular-nums",
                        whiteSpace: "nowrap" }}>{fmtUSD(cost)}</div>
        )}
      </div>
    </div>
  );
}
