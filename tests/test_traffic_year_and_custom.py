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

    def test_a_year_becomes_weekly_not_daily(self):
        self.assertLessEqual(self.o["year_n"], 53)
        self.assertGreaterEqual(self.o["year_n"], 36)

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
