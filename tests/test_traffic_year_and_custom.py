"""年度 / 自定义两档的口径（2026-09-12，用户要求）。

用户原话：「AI用量我需要新增一个年度的纬度，然后横轴时间变成月份。我还希望新增一个自定义的时间」

## 三条不变量，每条都有一个「错了也不报错」的失败形态

★★★ ① **快照必须按窗口分文件。** `run_traffic` 的合并只看快照**时间戳**，不看它是多大的
   窗口扫出来的。共用一个文件名的话，点「年度」会拿到 90 天那一份 —— 图照画、
   标题照写「年度」，**数据是错的而且一个字都不报错**。

★★  ② **默认档的取数窗口不许被改大。** 实测热路径 `--days 90` **1.06s** / `--days 365`
   **7.65s**。把默认窗口调大是实现年度最省事的做法，代价是每 2 分钟的心跳和每次弹出
   托盘都慢 7 倍 —— 压在完全没用到年度视图的那些时刻上。

★   ③ **自然年是 12 格，一格不少。** 本机数据从 2026-03 开始；不补零的话横轴会从 3 月
   起画，看着像「今年 3 月才开始用」—— 而那是我们编的，真相是 1、2 月确实是 0。

## 为什么用 jiti 跑真代码

前端逻辑用 Python 重写过一次就错过一次（`scratch/verify_cache_mode_20260811.ts` 那条：
正则漏了未加引号的 `FALLBACK` 键，把费用算低 7%）。这里直接 import `traffic.ts` 本体。
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "codexbar"
TRAFFIC_TS = WEB / "src" / "traffic.ts"
LIB_RS = WEB / "src-tauri" / "src" / "lib.rs"
USE_TRAFFIC = WEB / "src" / "hooks" / "useTraffic.ts"

PROBE = r"""
import { bucketsFor, daysNeeded, autoGran, effGran, resolveRange, presetList,
         snapToMonths, monthSpan, monthEnd, matchPreset,
         prevRange, prevTotals, diffDays, addDays, axisTick, tickTitle,
         DEFAULT_RANGE, PILLS, WINDOW_TIERS, MAX_RANGE_DAYS, MIN_COMPARE_DAYS }
  from "%s";

const B = (n) => ({ uncached_in: 0, cache_read: 0, cache_write: 0, output: 0,
                    total: n, rounds: 1, models: {} });
const TODAY = "2026-09-12";

/** 2025-09-13 ~ 2026-09-12 每天 1（一整年都有数据，这样环比才能算）。 */
function mk() {
  const days = {}, hours = {};
  for (let i = 0; i < 365; i++) days[addDays(TODAY, -i)] = B(1);
  for (let h = 0; h < 24; h++) hours[`${TODAY}T${String(h).padStart(2,"0")}`] = B(10);
  return { generated_at: Date.parse(TODAY + "T12:00:00") / 1000,
           platforms: { codex: { name: "Codex", days, hours, available: true } } };
}
const data = mk();
const R = (o) => ({ ...DEFAULT_RANGE, ...o });
const out = {};

out.pills = [...PILLS];
out.default_preset = DEFAULT_RANGE.preset;
out.tiers = [...WINDOW_TIERS];
out.max_days = MAX_RANGE_DAYS;
out.min_cmp = MIN_COMPARE_DAYS;

// 档位 → 区间
out.r_today = resolveRange(R({ preset: "today" }), TODAY);
out.r_7d = resolveRange(R({ preset: "7d" }), TODAY);
out.r_30d = resolveRange(R({ preset: "30d" }), TODAY);
out.r_year = resolveRange(R({ preset: "year" }), TODAY);

// 粒度
out.gran = [1, 90, 91, 365, 366].map(autoGran);
out.gran_manual = effGran(R({ gran: "month" }), 10);
out.gran_year = effGran(R({ preset: "year" }), 256);
out.gran_custom_same_len = effGran(R({ preset: "custom", custom: { s: "2026-01-01", e: "2026-09-13" } }), 256);
out.gran_year_manual = effGran(R({ preset: "year", gran: "day" }), 256);

// 今日 = 每 2 小时
const td = bucketsFor(data, "codex", R({ preset: "today" }), TODAY);
out.today_n = td.labels.length;
out.today_sum = td.buckets.reduce((s, b) => s + b.total, 0);

// 30d 按天；一年按周（≤365）
const d30 = bucketsFor(data, "codex", R({ preset: "30d" }), TODAY);
out.d30_n = d30.labels.length;
out.d30_first = d30.labels[0];
out.d30_last = d30.labels[d30.labels.length - 1];
const yr = bucketsFor(data, "codex", R({ preset: "year" }), TODAY);
out.year_n = yr.labels.length;
out.year_sum = yr.buckets.reduce((s, b) => s + b.total, 0);

// 自定义：含两端 + 合并不丢量
const cu = R({ preset: "custom", custom: { s: "2026-06-01", e: "2026-06-30" } });
const cb = bucketsFor(data, "codex", cu, TODAY);
out.cu_n = cb.labels.length;
out.cu_sum = cb.buckets.reduce((s, b) => s + b.total, 0);
const wideCu = R({ preset: "custom", custom: { s: "2026-01-01", e: "2026-09-12" } });
const wb = bucketsFor(data, "codex", wideCu, TODAY);
out.wide_sum = wb.buckets.reduce((s, b) => s + b.total, 0);
out.wide_days = diffDays("2026-01-01", "2026-09-12");

// 环比
out.prev_30d = prevRange(resolveRange(R({ preset: "30d" }), TODAY));
out.cmp_on = prevTotals(data, R({ preset: "30d" }), TODAY) !== null;
out.cmp_off = prevTotals(data, R({ preset: "30d", compare: false }), TODAY);
out.cmp_short = prevTotals(data, R({ preset: "custom", custom: { s: "2026-09-10", e: "2026-09-12" } }), TODAY);
out.cmp_uncovered = prevTotals(data, R({ preset: "custom", custom: { s: "2025-09-20", e: "2025-10-19" } }), TODAY);

// 窗口档
out.need_default = daysNeeded(DEFAULT_RANGE, TODAY);
out.need_today = daysNeeded(R({ preset: "today" }), TODAY);
out.need_year = daysNeeded(R({ preset: "year" }), TODAY);
out.need_nocmp_90 = daysNeeded(R({ preset: "custom", compare: false,
                                   custom: { s: addDays(TODAY, -89), e: TODAY } }), TODAY);

// 预设列
out.presets = presetList(TODAY).map((p) => p.sep ? "—" : p.label);
out.week_start = presetList(TODAY).find((p) => !p.sep && p.label === "本周").r.s;
out.last_month = presetList(TODAY).find((p) => !p.sep && p.label === "上月").r;

// 刻度
// 交接稿 10 §3.5：月模式
out.snap_mid = snapToMonths({ s: "2026-03-14", e: "2026-06-20" }, TODAY);
out.snap_cur = snapToMonths({ s: "2026-08-14", e: "2026-09-12" }, TODAY);
out.snap_idem = snapToMonths(snapToMonths({ s: "2026-03-14", e: "2026-06-20" }, TODAY), TODAY);
out.mspan_same = monthSpan("2026-03-01", "2026-03-31");
out.mspan_cross = monthSpan("2025-11-01", "2026-06-30");
out.mend = [monthEnd(2026, 2), monthEnd(2024, 2), monthEnd(2026, 4), monthEnd(2026, 12)];

// 点预设即应用：与固定档重合就点亮 pill
out.match_30d = matchPreset({ s: addDays(TODAY, -29), e: TODAY }, TODAY);
out.match_today = matchPreset({ s: TODAY, e: TODAY }, TODAY);
out.match_year = matchPreset({ s: "2026-01-01", e: TODAY }, TODAY);
out.match_none = matchPreset({ s: "2026-08-01", e: "2026-08-31" }, TODAY);
out.match_offbyone = matchPreset({ s: addDays(TODAY, -30), e: TODAY }, TODAY);

out.tick_hour = axisTick("2026-09-12T09");
out.tick_day = axisTick("2026-09-12");
out.tick_m1 = axisTick("2026-01");
out.tick_m12 = axisTick("2026-12");
out.title_m1 = tickTitle("2026-01");
out.title_day = tickTitle("2026-09-12");
console.log("JSON:" + JSON.stringify(out));
""" % TRAFFIC_TS


def _probe():
    f = Path("/tmp/cb_traffic_probe.mjs")
    f.write_text(PROBE, encoding="utf-8")
    r = subprocess.run(["npx", "jiti", str(f)], cwd=str(WEB),
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise AssertionError("jiti 跑不起来（探针坏了，不是代码坏了）:\n" + r.stderr[-1500:])
    line = next((l for l in r.stdout.splitlines() if l.startswith("JSON:")), None)
    if not line:
        raise AssertionError("探针没有输出 —— 别把它当成「检查通过」:\n" + r.stdout[-800:])
    return json.loads(line[5:])


class ThePillRowMatchesTheHandoff(unittest.TestCase):
    """★ 交接稿 §1/§6：pill 集合 = `今日 · 7d · 30d · 年度 · 范围▾`，**默认 30d**。

    14d / 90d **从 pill 移除**、退到弹层预设列 —— 理由是标题行零挤压：
    7 个 pill + 双日期框在 960px 下必然折行，而这一行还要放「上次刷新」。
    """

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_exactly_four_fixed_pills(self):
        self.assertEqual(self.o["pills"], ["today", "7d", "30d", "year"],
                         "★ pill 集合与交接稿不一致（14d/90d 应在弹层预设列里）")

    def test_the_default_is_30d(self):
        self.assertEqual(self.o["default_preset"], "30d")

    def test_each_pill_resolves_to_the_documented_window(self):
        self.assertEqual(self.o["r_today"], {"s": "2026-09-12", "e": "2026-09-12"})
        self.assertEqual(self.o["r_7d"], {"s": "2026-09-06", "e": "2026-09-12"})
        self.assertEqual(self.o["r_30d"], {"s": "2026-08-14", "e": "2026-09-12"})
        self.assertEqual(self.o["r_year"], {"s": "2026-01-01", "e": "2026-09-12"},
                         "★ 年度是**自然年**（1 月 1 日起），不是滚动 12 个月")


class GranularityFollowsTheSpan(unittest.TestCase):
    """★ 交接稿 §6：≤90 天按天，≤365 **按周**，更长按月；手动可覆盖。

    ⚠️ 「周」这一档是这一版**新增**的 —— v1.5 只有天/月，一年的数据按天画是 365 格
    （每格不足 1px），按月又只有 12 格、丢掉了周内节奏。
    """

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_the_three_tiers(self):
        self.assertEqual(self.o["gran"], ["day", "day", "week", "week", "month"],
                         "★ 分界不对：1/90 按天，91/365 按周，366 按月")

    def test_manual_overrides_auto(self):
        self.assertEqual(self.o["gran_manual"], "month",
                         "★ 手动选了「月」却仍按 auto 算 —— 那个分段控件就是摆设")

    def test_the_year_preset_is_monthly_by_definition(self):
        """★★★ 用户 2026-09-12 提这个档时的原话：「新增一个年度的纬度，**然后横轴时间变成月份**」。

        交接稿 §6 那张 auto 表（≤365 按周）管的是**自定义区间** —— 今年到现在 256 天落在
        「≤365 → 按周」里，于是年度档一度画成 37 根周柱（用户 2026-09-13 报「怎么按周了」）。
        两条规则都对，只是适用对象不同，混在一个函数里就会互相覆盖。
        """
        self.assertEqual(self.o["gran_year"], "month")

    def test_a_custom_span_of_the_same_length_still_follows_the_table(self):
        """★★ 反向闸。把「年度按月」写成 `autoGran` 的特例，会连带改掉**所有** 256 天的
        自定义区间 —— 而那是用户自己框的一段，没有"这是一年"的语义，按周才看得出周内节奏。"""
        self.assertEqual(self.o["gran_custom_same_len"], "week")

    def test_manual_choice_still_beats_the_year_default(self):
        """★ 优先级：手动 > 年度恒月 > auto 表。少了这一条，弹层里选的分格在年度档失效。"""
        self.assertEqual(self.o["gran_year_manual"], "day")

    def test_merging_into_weeks_loses_nothing(self):
        """★★ 合并是**求和**不是抽样。少加几天在一张周线图上完全看不出来。"""
        self.assertEqual(self.o["year_sum"], 255, "2026-01-01~09-12 共 255 天，每天 1")
        self.assertEqual(self.o["wide_sum"], self.o["wide_days"])


class CustomSpansAreInclusive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_both_ends_are_included(self):
        self.assertEqual(self.o["cu_n"], 30, "★ 6/1→6/30 是 30 天 —— 少一天没人看得出来")
        self.assertEqual(self.o["cu_sum"], 30)

    def test_the_30d_pill_is_29_days_back(self):
        self.assertEqual(self.o["d30_n"], 30)
        self.assertEqual(self.o["d30_first"], "2026-08-14")
        self.assertEqual(self.o["d30_last"], "2026-09-12")


class TodayIsBucketedEveryTwoHours(unittest.TestCase):
    """★ 交接稿 §5：今日档按**每 2 小时**分格（`今日 · 12 格 · 每 2 小时`）。"""

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_twelve_buckets(self):
        self.assertEqual(self.o["today_n"], 12)

    def test_no_token_is_dropped_in_the_merge(self):
        """★★ 合并而不是隔一取一 —— 后者丢掉一半的量，而图形看上去只是"矮了一点"。"""
        self.assertEqual(self.o["today_sum"], 240, "24 小时 × 10")


class CompareSaysNothingRatherThanZero(unittest.TestCase):
    """★★★ 交接稿 §1/§6：环比 = 与**上一等长周期**比；<7 天不显示。

    三种「不该显示」合并成一个 `null`，因为调用方处置一样（显示「—」）：
    开关关着 / 区间太短 / **取数窗口没覆盖到上一周期**。
    第三种最要命 —— 把缺的天当 0 算出来的环比在说「上期没用过」，
    而事实是「我们没取到上期」，两句话差一个 ↑∞。
    """

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_the_previous_window_is_the_equal_length_one_before(self):
        self.assertEqual(self.o["prev_30d"], {"s": "2026-07-15", "e": "2026-08-13"})

    def test_it_has_a_value_when_covered(self):
        """★ 先证基线。没有这一条，下面三条测的可能是「它永远返回 null」。"""
        self.assertTrue(self.o["cmp_on"], "★ 环比恒为空 —— 下面的断言全都无效")

    def test_switch_off_means_none(self):
        self.assertIsNone(self.o["cmp_off"])

    def test_under_seven_days_means_none(self):
        self.assertIsNone(self.o["cmp_short"], "★ 3 天也给环比 —— 百分比会剧烈跳动")

    def test_an_uncovered_previous_window_means_none_not_zero(self):
        self.assertIsNone(self.o["cmp_uncovered"],
                          "★★★ 把没取到的上期当 0 ⇒ 环比说成 ↑∞，而那是我们编的")


class TheChartCaptionShareTheTokenLine(unittest.TestCase):
    """★★★ 交接稿 §1 的图表标题行是**一行**：左 `token`、右小字 `08-14 → 09-12 · 30 格 · 按天`。

    2026-09-13 用户报「年度多了个右侧滑块」。真因是我上一版把右半边做成了图表**上方新起的
    一行**（margin 12 + 行高 14），整页因此高了约 26px，把窗口推过了出滚动条的临界点。

    ★ 两处都"对"、合起来就错：单看任一视图都像稿子，**只有量高度才看得出来多了一行**。
      实测（1000×614，同一份夹具）：

          改动之前  30d 836 / 年度 838
          我上一版  30d 866 / 年度 868     ← +30
          修复之后  30d 840 / 年度 842

    所以判据打在**结构**上：caption 必须由 `StackedArea` 与 `token` 同行渲染，
    页面里不许再有一个自带 `marginTop` 的标题行。
    """

    SA = (ROOT / "codexbar" / "src" / "components" / "StackedArea.tsx").read_text(encoding="utf-8")
    PAGES = ["codexbar/src/pages/TrafficPage.tsx", "codexbar/src/pages/PlatformPage.tsx"]

    def test_the_caption_sits_on_the_token_baseline(self):
        i = self.SA.index(">token</span>")
        seg = self.SA[i:i + 700]
        self.assertIn("caption", seg, "★ caption 不在 `token` 那一行 —— 它会另起一行、整页变高")
        self.assertIn("top: -13", seg, "★ caption 没有与 `token` 共用基线")

    def test_no_page_renders_its_own_caption_row(self):
        bad = [f for f in self.PAGES
               if 'marginTop: 12, display: "flex", alignItems: "baseline"'
               in (ROOT / f).read_text(encoding="utf-8")]
        self.assertEqual(bad, [],
                         f"★★★ {bad} 又在图表上方另起了一行标题 —— 整页会高 26px")

    def test_both_pages_pass_the_caption_down(self):
        """★ 反向闸：删掉那一行却忘了把 caption 传下去 = 说明文字整个消失，而页面看着很正常。"""
        for f in self.PAGES:
            with self.subTest(file=f):
                self.assertIn("caption={capt}", (ROOT / f).read_text(encoding="utf-8"),
                              "★ 没有把 caption 传给 StackedArea —— 那行小字消失了")


class AFixedPresetResetsGranularity(unittest.TestCase):
    """★★★ 分格是在弹层里**为某个自定义区间**选的，而 `RangeState` 把它存成全局字段。

    不复位的话它会粘在后面每一个档上 —— 用户 2026-09-13 的截图里年度档显示
    `9 格 · 按月`，而 256 天按 auto 该是**按周**；更极端的是「30d 按月」，
    整整一个月缩成 1~2 格，图表等于没有。
    """

    TS = (ROOT / "codexbar" / "src" / "components" / "RangeBar.tsx").read_text(encoding="utf-8")

    def test_clicking_a_pill_resets_gran_to_auto(self):
        i = self.TS.index("PILLS.map(")
        seg = self.TS[i:i + 1200]
        self.assertRegex(seg, r'onChange\(\{ \.\.\.st, preset: p, gran: "auto" \}\)',
                         "★★★ 切固定档时没复位分格 ⇒ 弹层里选的「月」会粘到 30d 上")

    def test_applying_a_custom_range_still_honours_the_choice(self):
        """★ 反向闸：复位得太狠就把弹层那个分段控件变成摆设了。

        ⚠️ 第一版断言的是窗口里出现过 `gran,` —— 而 `onApply={({ range, gran, compare })`
        这个**解构参数**里就有一个，把它从 `onChange(...)` 里删掉闸照样绿（变异工具拦下）。
        判据必须打在**那次调用**上。"""
        self.assertRegex(
            self.TS,
            r'preset: "custom", custom: range, lastCustom: range, gran, compare',
            "★ 应用自定义区间时没有把用户选的分格写回状态 —— 那个分段控件是摆设")
        # ★ 命中固定档那一支必须**复位**成 auto：固定档的分格按定义就是自动的，
        #   带着弹层里选的「月」跳过去，30d 会缩成 1 格。
        self.assertRegex(self.TS, r'preset: hit[\s\S]{0,80}gran: "auto"',
                         "★ 命中固定档时没把分格复位 —— 30d 会按月画成 1 格")


class ThePresetColumnMatchesTheHandoff(unittest.TestCase):
    """★ 交接稿 §2：`今日 昨日 近7 近14 近30 近90 ─ 本周 本月 上月 本季度 年度`。"""

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_eleven_presets_and_one_separator(self):
        self.assertEqual(self.o["presets"],
                         ["今日", "昨日", "近 7 天", "近 14 天", "近 30 天", "近 90 天", "—",
                          "本周", "本月", "上月", "本季度", "年度"])

    def test_the_week_starts_on_monday(self):
        """★ 交接稿 §8 明写周一为起点。2026-09-12 是周六 → 本周起于 09-07（周一）。"""
        self.assertEqual(self.o["week_start"], "2026-09-07")

    def test_last_month_is_a_whole_month(self):
        """★ 「上月」是**整月**，不是"往回 30 天" —— 后者跨月时会切掉月初几天。"""
        self.assertEqual(self.o["last_month"], {"s": "2026-08-01", "e": "2026-08-31"})


class TheHotPathWindowIsNotWidened(unittest.TestCase):
    """★★★ 实测：交替窗口时 `--days 365` 曾要 5.2~8.3s（见 `test_scan_cache_merge.py`）。
    默认档必须仍落在 90 —— 它是心跳与菜单栏弹出走的那一份。"""

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_the_default_still_fits_the_hot_tier(self):
        """★★ 注意默认**开着环比**，所以 30d 实际要往回取 60 天 —— 仍在 90 档内。
        这正是把环比的回溯算进 `daysNeeded` 之后必须复验的那一条。"""
        self.assertEqual(self.o["need_default"], 90)
        self.assertEqual(self.o["need_today"], 90)

    def test_the_year_needs_a_wider_tier(self):
        self.assertIn(self.o["need_year"], [365, 1095])

    def test_turning_compare_off_keeps_a_90d_span_on_the_hot_tier(self):
        """★ 反向闸：环比关掉时 90 天区间不该被撑到 365 档 —— 那是一次无谓的宽窗扫描。"""
        self.assertEqual(self.o["need_nocmp_90"], 90)

    def test_windows_are_quantised(self):
        self.assertEqual(self.o["tiers"][0], 90, "第一档必须是热路径那一档")


class TheLimitsMatchTheHandoff(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_max_365_and_min_compare_7(self):
        self.assertEqual(self.o["max_days"], 365)
        self.assertEqual(self.o["min_cmp"], 7)


class MonthPickerSnapsToMonthBoundaries(unittest.TestCase):
    """★★ 交接稿 10 §3.5：分格切到「月」时，日历换成月份选择器，草稿自动吸附到月边界。

    不吸附的后果是**看到的区间和生效的区间不是同一个** —— 格子高亮着整个 8 月和 9 月，
    底部 ISO 框却写着 `08-14 → 09-12`，两者都"看着正常"，只有把它们并排读才发现对不上。
    """

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_start_goes_to_the_first_and_end_to_the_last(self):
        self.assertEqual(self.o["snap_mid"], {"s": "2026-03-01", "e": "2026-06-30"})

    def test_the_current_month_ends_today_not_at_month_end(self):
        """★★★ 当月的"月末"是**今天**。取 09-30 会让区间伸进没有数据的未来，
        而那几天会被当成 0 算进日均 —— 数字变小，图形完全正常。"""
        self.assertEqual(self.o["snap_cur"], {"s": "2026-08-01", "e": "2026-09-12"})

    def test_snapping_twice_changes_nothing(self):
        """★ 幂等。每次切分格都会吸附一次，不幂等的话来回切几次区间就漂了。"""
        self.assertEqual(self.o["snap_idem"], self.o["snap_mid"])

    def test_the_month_count_is_inclusive_and_crosses_years(self):
        self.assertEqual(self.o["mspan_same"], 1)
        self.assertEqual(self.o["mspan_cross"], 8, "2025-11 → 2026-06 是 8 个月（交接稿截图）")

    def test_month_end_handles_leap_years(self):
        """★ 2 月是这个函数唯一会出错的地方，而错了只差一天 —— 在月度图上看不出来。"""
        self.assertEqual(self.o["mend"], [28, 29, 30, 31])


class ThePopoverMatchesHandoffTen(unittest.TestCase):
    """★ 交接稿 10 对弹层的四处更新（§2 / §3.5 / §6）。"""

    TS = (ROOT / "codexbar" / "src" / "components" / "RangePopover.tsx").read_text(encoding="utf-8")

    def test_the_popover_is_600_wide(self):
        """★ 580 → 600：月模式那两块 `3×54px` 的年面板要放得下。"""
        self.assertIn("width: 600", self.TS)
        self.assertNotIn("width: 580", self.TS)

    def test_four_arrows_not_two(self):
        """★ `«` `‹` | `›` `»` —— 单箭头翻 1 个月，双箭头翻 1 年。"""
        # ★ 判据收在 `panel()` 的**表头 JSX** 里：光看"源码里出现过这个字符"太弱 ——
        #   一个被 `null &&` 短路掉的调用也留着那个字符（变异验证时我自己先踩了这个）。
        i = self.TS.index("const panel = (")
        head = self.TS[i:self.TS.index("{monthMode ? (", i)]
        for g in ("«", "‹", "›", "»"):
            with self.subTest(glyph=g):
                self.assertIn(f'{{arrow("{g}"', head, f"★ 表头里少了 `{g}` 这枚箭头")

    def test_month_mode_pages_by_year_on_both_arrow_kinds(self):
        """★★ 交接稿 §6「翻页」：**月视图下 `‹ ›` 与 `« »` 都翻年**。
        单箭头仍按月翻的话，两块年面板会各显示不相邻的年份 —— 而标题只写年份，看不出错。"""
        # ⚠️ 窗口必须**收到函数体内**。第一版取固定 260 字符，越过了 `};` 读到下一个函数的
        #    `if (monthMode)` —— 把 `stepBack` 那一行删掉闸照样绿（变异工具当场拦下）。
        for fn in ("stepBack", "stepFwd"):
            i = self.TS.index(f"const {fn} = ")
            seg = self.TS[i:self.TS.index("\n  };", i)]
            self.assertIn("if (monthMode)", seg, f"★ {fn} 在月模式下没有改成翻年")
            self.assertRegex(seg, r"setVy\(ly [-+] 1\)", f"★ {fn} 月模式下不是按年步进")

    def test_the_month_grid_matches_the_spec(self):
        i = self.TS.index('gridTemplateColumns: "repeat(3,54px)"')
        seg = self.TS[i:i + 700]
        self.assertIn('"repeat(3,54px)"', seg, "★ 月格不是 3 列 × 54px")
        self.assertIn("height: 30", seg, "★ 月格高度不是 30")
        self.assertIn("fontSize: 11", seg, "★ 月格字号不是 11")

    def test_the_header_spacer_is_41_not_20(self):
        """★ 占位宽度必须是 41（两枚 20 + 1 间隙）。写 20 的话标题不在面板正中，
        两块面板并排时那 21px 偏移一眼就能看出来。"""
        # ⚠️ 左右面板**各有一个**占位。第一版只断言"出现过 41"，改掉其中一个闸照样绿
        #    （变异工具当场拦下）—— 而只歪一边恰恰是最难看的那种：两块面板的标题不齐。
        i = self.TS.index("const panel = (")
        head = self.TS[i:self.TS.index("{monthMode ? (", i)]
        self.assertEqual(head.count("width: 41"), 2,
                         "★ 两个表头占位必须都是 41（两枚箭头 20+20+1 间隙）")

    def test_switching_to_month_snaps_the_draft(self):
        i = self.TS.index("GRANS.map(")
        seg = self.TS[i:i + 700]
        self.assertIn('k === "month"', seg, "★ 切到月模式时没有吸附草稿")
        self.assertIn("snapMonth(ds, de)", seg)

    def test_presets_snap_in_month_mode(self):
        """★ 交接稿 §3.5 最后一句：左列预设在月模式下也按月吸附。"""
        i = self.TS.index("presets.map(")
        seg = self.TS[i:i + 900]
        self.assertIn("monthMode ? snapMonth(p.r.s, p.r.e)", seg,
                      "★ 月模式下点预设没有按月吸附 —— 格子与 ISO 框会对不上")

    def test_the_count_switches_to_months(self):
        i = self.TS.index("个月")
        self.assertIn("monthMode ?", self.TS[max(0, i - 200):i],
                      "★ 计数没有随模式切换")


class ClickingAPresetAppliesImmediately(unittest.TestCase):
    """★ 用户 2026-09-13：「左侧今日、昨日、近 7 天等等，点击了就是直接跳转应用」。

    交接稿 §2 写的是"立即回填草稿"，还要再点一次「应用」。左列这 11 项本来就是**成品区间**，
    没有什么可以再调的 —— 多那一步只是让人确认一件已经确定的事。
    ⚠️ 需要微调的路没堵死：日历上再点一下就回到草稿态。
    """

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    RP = (ROOT / "codexbar" / "src" / "components" / "RangePopover.tsx").read_text(encoding="utf-8")
    RB = (ROOT / "codexbar" / "src" / "components" / "RangeBar.tsx").read_text(encoding="utf-8")

    def test_the_preset_click_calls_apply(self):
        i = self.RP.index("presets.map(")
        seg = self.RP[i:i + 1400]
        self.assertIn("onApply(", seg, "★★ 点预设只回填草稿，没有直接应用")

    def test_it_still_honours_the_365_limit(self):
        """★ 目前 11 项全在限内，这条是给以后加预设的人的 —— 绕过上限的路不该从这里开。"""
        i = self.RP.index("presets.map(")
        self.assertIn("MAX_RANGE_DAYS", self.RP[i:i + 1400],
                      "★ 点预设那条路绕过了 365 天上限")

    def test_a_range_equal_to_a_pill_lights_that_pill(self):
        """★★ 「今日 / 近 30 天 / 年度」与 pill 的区间**逐字相同**。造一个内容一模一样的
        自定义芯片，等于同一件事有两种长相，而其中一种还更长。"""
        self.assertEqual(self.o["match_30d"], "30d")
        self.assertEqual(self.o["match_today"], "today")
        self.assertEqual(self.o["match_year"], "year")

    def test_a_genuinely_custom_range_stays_custom(self):
        """★ 反向闸。判得太宽就会把真正的自定义区间也吞成 pill，芯片再也出不来。"""
        self.assertIsNone(self.o["match_none"])
        self.assertIsNone(self.o["match_offbyone"], "★ 差一天也必须算自定义")

    def test_the_bar_routes_through_the_match(self):
        i = self.RB.index("onApply={(")
        seg = self.RB[i:i + 700]
        self.assertIn("matchPreset(range, today)", seg,
                      "★ 应用时没有做固定档匹配 —— 会造出与 pill 内容相同的芯片")
        self.assertIn('preset: "custom"', seg, "★ 没命中固定档时仍要走自定义")


class TheMonthAxisReadsAsMonths(unittest.TestCase):
    """★ 用户 2026-09-12：「年度的横轴不要 01、02、03，味道太重。1月、2月会不会好点？」"""

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_months_render_with_a_unit_and_no_leading_zero(self):
        self.assertEqual(self.o["tick_m1"], "1月")
        self.assertEqual(self.o["tick_m12"], "12月")

    def test_the_other_two_shapes_are_unchanged(self):
        """★ 反向闸。改月份档时把日期/小时档一起改掉，是同一条 `slice` 上最容易出的事故。"""
        self.assertEqual(self.o["tick_day"], "09-12")
        self.assertEqual(self.o["tick_hour"], "09:00")

    def test_the_tooltip_keeps_the_year(self):
        self.assertEqual(self.o["title_m1"], "2026年1月")
        self.assertEqual(self.o["title_day"], "2026-09-12")

    def test_the_component_does_not_keep_its_own_slice(self):
        src = (ROOT / "codexbar" / "src" / "components" / "StackedArea.tsx").read_text(encoding="utf-8")
        self.assertNotIn('d.slice(5)', src, "★ 组件里还留着自己的一份刻度格式化")
        self.assertIn("axisTick(d)", src)


class TheSnapshotIsKeyedByWindow(unittest.TestCase):
    """★★★ 不分文件的失败形态：点「年度」拿到 90 天那份，**图照画、标题照写、零报错**。"""

    RS = LIB_RS.read_text(encoding="utf-8")

    def test_snapshot_name_depends_on_days(self):
        i = self.RS.index("fn snapshot_name(")
        body = self.RS[i:self.RS.index("\n}", i)]
        self.assertIn("days", body, "★ 快照名不随窗口变 —— 两个窗口会互相覆盖")
        self.assertIn("format!", body)

    def test_run_traffic_threads_days_into_both_sides(self):
        """★★ **读和写都要**。只改一边的后果不对称但都很糟：
        只改写 ⇒ 年度扫完写对了文件，下次读仍读到 90 天那份；
        只改读 ⇒ 年度的数据被写进 90 天那份，把热路径的数据污染掉。"""
        i = self.RS.index("async fn run_traffic(")
        body = self.RS[i:self.RS.index("\n}\n", i)]
        self.assertRegex(body, r"fresh_snapshot\(\s*days\s*,",
                         "★ 新鲜度合并没带窗口 ⇒ 会拿别的窗口的快照冒充")
        self.assertRegex(body, r"write_traffic_snapshot\(\s*days\s*,",
                         "★ 落盘没带窗口 ⇒ 年度数据会覆盖热路径那份")

    def test_the_default_name_is_unchanged(self):
        """★ 默认档必须仍写 `.traffic-latest.json` —— 托盘和菜单栏直接读这个文件名。"""
        self.assertIn('".traffic-latest.json"', self.RS)


class TheWideWindowDoesNotRunTheHeartbeat(unittest.TestCase):
    """★★ 年度一次扫描 7.6s。每 2 分钟自动跑一遍是纯浪费，而且按月看的数据不需要分钟级新鲜度。"""

    TS = USE_TRAFFIC.read_text(encoding="utf-8")

    def test_heartbeat_is_gated_on_the_default_window(self):
        i = self.TS.index("const id = setInterval(")
        head = self.TS[max(0, i - 400):i]
        self.assertIn("isDefault", head, "★ 心跳没有按窗口设闸 ⇒ 停在年度视图上每 2 分钟扫 7.6s")

    def test_switching_window_never_keeps_the_previous_ones_data(self):
        """★★★ `adopt` 只在 `generated_at` 更新时换数据。换窗口时新快照**可能更旧**
        ⇒ 被拒绝 ⇒ 页面继续画 90 天的数，而横轴已经写着「年度」。

        ★ 2026-09-13 起命中内存缓存时直接换上那一份（用户：「不要每次选择都重新加载」），
          **没命中才清空** —— 清空这一步不能省，省掉就是"拿 A 的数配 B 的轴"。
          所以判据是 `setData(命中 ?? null)`：两条路都不会留着上一个窗口的数据。"""
        self.assertRegex(self.TS, r"lastDays[\s\S]{0,600}setData\(hit \?\? null\)",
                         "★★★ 换窗口时没有「命中就换、没命中就清空」—— "
                         "留着上一个窗口的数据就是拿 A 的数配 B 的轴")

    def test_the_per_window_cache_exists(self):
        """★★ 用户 2026-09-13：「不要每次选择都是要重新刷新加载」。
        扫描侧已修（`scan.py::_merge_cache`），但没有这张表的话，来回切档仍然每次都看骨架屏。

        ⚠️ 第一版断言的是「源码里出现过 `byWindow` 这个词」—— 把声明删掉之后其它引用还在，
        闸照样绿（变异工具当场拦下）。判据必须打在**完整链路**上：写进去、读出来、喂给 setData。
        """
        self.assertRegex(self.TS, r"byWindow\.current\.set\(\s*lastDays\.current\s*,\s*data\s*\)",
                         "★ 数据到手时没有写进缓存 —— 那张表永远是空的")
        self.assertRegex(self.TS, r"const hit = byWindow\.current\.get\(days\)",
                         "★ 换窗口时没有查缓存 —— 每次切档都要重新加载")
        self.assertRegex(self.TS, r"const hit = byWindow[\s\S]{0,120}setData\(hit \?\? null\)",
                         "★★ 查了缓存却没把结果喂给 setData —— 查了等于没查")

    def test_only_the_default_window_broadcasts(self):
        """⚠️ 这条闸第一版锚在 `emit("traffic-updated")` 的**第一个**出现处，
        而那是这个文件顶部的**说明注释** —— 空心闸形态④（断言打在自己的说明文字上）。
        现在锚在真正的调用语句 `void emit(` 上。"""
        i = self.TS.index('void emit("traffic-updated")')
        self.assertIn("isDefault", self.TS[max(0, i - 300):i],
                      "★ 非默认窗口也广播 ⇒ 对方白读一次默认快照")


class TheMonthAxisReadsAsMonths(unittest.TestCase):
    """★ 用户 2026-09-12：「年度的横轴不要 01、02、03，味道太重。1月、2月会不会好点？」

    `01` 是 `"2026-01".slice(5)` 的产物 —— 那条 `slice` 本来是给日期档 `09-12` 写的，
    月份档撞进来就成了一个**没有单位的裸数字**。三种桶形态现在共用一个判据（`axisTick`），
    别再在组件里各写一份 slice。
    """

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_months_render_with_a_unit_and_no_leading_zero(self):
        self.assertEqual(self.o["tick_m1"], "1月")
        self.assertEqual(self.o["tick_m12"], "12月")

    def test_the_other_two_shapes_are_unchanged(self):
        """★ 反向闸。改月份档时把日期/小时档一起改掉，是同一条 `slice` 上最容易出的事故。"""
        self.assertEqual(self.o["tick_day"], "09-12")
        self.assertEqual(self.o["tick_hour"], "09:00")

    def test_the_tooltip_keeps_the_year(self):
        """★★ 浮层上只写「1月」时，读者**没有第二个地方**能确认是哪一年 ——
        而年度视图横跨一整年，这正是最需要确认的时候。"""
        self.assertEqual(self.o["title_m1"], "2026年1月")
        self.assertEqual(self.o["title_day"], "2026-09-12")

    def test_the_component_does_not_keep_its_own_slice(self):
        """★ 判据打在**组件里还有没有那条 slice** 上：留着一份就是两套规则，
        而它们只会在某个边界上才开始矛盾。"""
        src = (ROOT / "codexbar" / "src" / "components" / "StackedArea.tsx").read_text(encoding="utf-8")
        self.assertNotIn('d.slice(5)', src, "★ 组件里还留着自己的一份刻度格式化")
        self.assertIn("axisTick(d)", src)


class LoadingSaysNothingNotZero(unittest.TestCase):
    """★★★ 换窗口时必然有一段空窗期（年度要扫 7.6s）。那段时间显示 `0 · $0.000`
    不是骨架屏，是一句**错的陈述**。

    ⚠️ 这个洞在 2026-09-12 之前几乎摸不到：`data` 只在**从来没扫过**时才为 null。
    是「年度 / 自定义」把它从"一辈子一次"变成"每次切档都有" —— 换窗口必须先清空旧数据
    （否则会拿 90 天的数配「年度」的轴），两件事是同一个改动的两半。
    """

    TS = (ROOT / "codexbar" / "src" / "pages" / "TrafficPage.tsx").read_text(encoding="utf-8")

    def test_the_kpi_strip_has_a_loading_branch(self):
        i = self.TS.index("const kpis: Kpi[] =")
        head = self.TS[i:i + 400]
        self.assertRegex(head, r"loading\s*\?",
                         "★★★ KPI 没有加载分支 ⇒ 空窗期显示 `总 token 0 · $0.000`")

    def test_every_loading_kpi_is_a_dash(self):
        """★ 判据打在**值**上，不是"有没有那个变量"。留一格漏成 0 就是留一句假话。"""
        i = self.TS.index("const kpis: Kpi[] =")
        j = self.TS.index("] : [", i)
        branch = self.TS[i:j]
        vals = re.findall(r'v:\s*("[^"]*")', branch)
        self.assertGreaterEqual(len(vals), 5, "加载分支的格子数不对 —— 探针失准")
        self.assertEqual(set(vals), {'"—"'},
                         f"★ 加载态里有不是「—」的值: {sorted(set(vals))}")

    def test_the_cache_kpi_is_dashed_while_loading_too(self):
        """★ 它在主分支外面 push，最容易被漏掉 —— 漏了就是一格真话旁边的一格假话。"""
        i = self.TS.index('kpis.push({ k: "缓存"')
        self.assertIn("!loading", self.TS[i:i + 160],
                      "★ 缓存那一格没跟着加载态走")


class EveryBucketsForCallCarriesTheRangeState(unittest.TestCase):
    """★★★ 漏传参数的后果**不是报错，是静默算成 0**。

    `bucketsFor(data, key, st, today)` —— 漏掉 `st` 或 `today`，那一格就从真值变成 0，
    而 `0.0%` 会被读成「没用到缓存」，与事实相反。

    2026-09-12 真踩到（当时的签名带 `span`）：像素上年度档 96.3%、自定义档 **0.0%**，
    tsc 与全部单测**全绿**。同一格此前已因**另一个**原因显示过 0.0%（拿重塑后的 `data` 去算）。
    **同一格、两个原因、同一个假值** —— 所以这条闸打在「所有调用点」上，不是某个已知的坑上。
    """

    FILES = ["codexbar/src/pages/TrafficPage.tsx", "codexbar/src/pages/PlatformPage.tsx"]

    def test_no_call_site_drops_an_argument(self):
        bad = []
        for rel in self.FILES:
            src = (ROOT / rel).read_text(encoding="utf-8")
            for m in re.finditer(r"bucketsFor\(([^;]*?)\)", src):
                args = m.group(1)
                if "st," not in args or "today" not in args:
                    ln = src[:m.start()].count("\n") + 1
                    bad.append(f"    {rel}:{ln}  bucketsFor({args[:60]}…")
        self.assertEqual(bad, [],
                         "★★★ 这些调用点少传了 `st` 或 `today` ⇒ 静默返回空切片:\n" + "\n".join(bad))

    def test_the_probe_can_actually_find_call_sites(self):
        """★ 反向自检:上面那条断言在"一个调用点都没找到"时也会通过。"""
        n = sum(len(re.findall(r"bucketsFor\(", (ROOT / f).read_text(encoding="utf-8")))
                for f in self.FILES)
        self.assertGreaterEqual(n, 4, "★ 一个 bucketsFor 调用都没找到 —— 探针坏了，不是代码干净")


if __name__ == "__main__":
    unittest.main()
