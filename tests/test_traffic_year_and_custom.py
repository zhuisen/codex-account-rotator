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
import { bucketsFor, daysNeeded, isMonthly, spanDays, WINDOW_TIERS, axisTick, tickTitle }
  from "%s";

const B = (n) => ({ uncached_in: 0, cache_read: 0, cache_write: 0, output: 0,
                    total: n, rounds: 1, models: {} });

/** 2026 年 1/1 ~ 9/12 每天 1，外加 2025-12-31 一天 999（用来抓"混进上一年"）。 */
function mk() {
  const days = { "2025-12-31": B(999) };
  for (const [m, n] of [[1,31],[2,28],[3,31],[4,30],[5,31],[6,30],[7,31],[8,31],[9,12]])
    for (let d = 1; d <= n; d++)
      days[`2026-${String(m).padStart(2,"0")}-${String(d).padStart(2,"0")}`] =
        B(m >= 3 ? 1 : 0);           // 1、2 月**确实是 0**，但键存在
  return { generated_at: Date.parse("2026-09-12T12:00:00") / 1000,
           platforms: { codex: { name: "Codex", days, hours: {}, available: true } } };
}
const data = mk();
const out = {};
const year = bucketsFor(data, "codex", "year");
out.year_labels = year.labels;
out.year_totals = year.buckets.map((b) => b.total);

const short = bucketsFor(data, "codex", "custom", { start: "2026-06-01", end: "2026-06-30" });
out.short_labels = short.labels;
out.short_n = short.labels.length;

const long = bucketsFor(data, "codex", "custom", { start: "2026-03-01", end: "2026-09-12" });
out.long_labels = long.labels;
out.long_total = long.buckets.reduce((s, b) => s + b.total, 0);

out.span_inclusive = spanDays({ start: "2026-06-01", end: "2026-06-30" });
out.monthly_at_90 = isMonthly("custom", { start: "2026-06-01", end: "2026-08-29" });
out.monthly_at_91 = isMonthly("custom", { start: "2026-06-01", end: "2026-08-30" });
out.tiers = [...WINDOW_TIERS];
out.tick_hour  = axisTick("2026-09-12T09");
out.tick_day   = axisTick("2026-09-12");
out.tick_m1    = axisTick("2026-01");
out.tick_m12   = axisTick("2026-12");
out.title_m1   = tickTitle("2026-01");
out.title_day  = tickTitle("2026-09-12");
const NOW = Date.parse("2026-09-12T12:00:00");
out.need_default = daysNeeded(14, undefined, NOW);
out.need_90 = daysNeeded(90, undefined, NOW);
out.need_year = daysNeeded("year", undefined, NOW);
out.need_custom_recent = daysNeeded("custom", { start: "2026-08-01", end: "2026-09-01" }, NOW);
out.need_custom_old = daysNeeded("custom", { start: "2024-01-01", end: "2026-09-01" }, NOW);
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


class TheYearIsACalendarYear(unittest.TestCase):
    """用户 2026-09-12 选的是**自然年**（不是滚动 12 个月）。"""

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_twelve_slots_not_one_less(self):
        self.assertEqual(self.o["year_labels"],
                         [f"2026-{m:02d}" for m in range(1, 13)],
                         "★ 自然年必须 12 格 —— 少一格就是把「那个月是 0」讲成「没有那个月」")

    def test_empty_months_are_zero_not_absent(self):
        self.assertEqual(self.o["year_totals"][0], 0)
        self.assertEqual(self.o["year_totals"][1], 0)
        self.assertGreater(self.o["year_totals"][2], 0, "3 月有数据，夹具没造对")

    def test_future_months_are_zero(self):
        self.assertEqual(self.o["year_totals"][9:], [0, 0, 0], "★ 10~12 月还没到，必须是 0")

    def test_last_year_does_not_leak_in(self):
        """★★ 夹具里 2025-12-31 是 999。它一旦混进来，任何一格都会异常地大 ——
        而"异常地大"在一张按月的图上看不出来。"""
        self.assertNotIn(999, self.o["year_totals"])
        # 3~9 月每天 1：31+30+31+30+31+31+12。
        # ⚠️ 这个数我第一版写成 135（漏了两个月）—— 是**闸算错**不是代码算错。
        self.assertEqual(sum(self.o["year_totals"]), 31 + 30 + 31 + 30 + 31 + 31 + 12,
                         "★ 年度合计对不上 3~9 月的天数")


class CustomSwitchesGranularityBySpan(unittest.TestCase):
    """用户选的是「按跨度自动切换」：≤90 天按天，>90 天按月。"""

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_a_short_span_stays_daily(self):
        self.assertEqual(self.o["short_n"], 30)
        self.assertEqual(self.o["short_labels"][0], "2026-06-01")
        self.assertEqual(self.o["short_labels"][-1], "2026-06-30",
                         "★ 区间含两端 —— 少一天没人看得出来")

    def test_a_long_span_becomes_monthly(self):
        self.assertEqual(self.o["long_labels"], ["2026-03", "2026-04", "2026-05",
                                                 "2026-06", "2026-07", "2026-08", "2026-09"])

    def test_merging_into_months_loses_nothing(self):
        """★★ 合月是**求和**不是抽样。少加一天在一张月度图上完全看不出来。"""
        self.assertEqual(self.o["long_total"], 31 + 30 + 31 + 30 + 31 + 31 + 12)

    def test_the_cutover_is_exactly_at_ninety_days(self):
        """★ 两侧各钉一个。只钉一侧的话，判据从 `>` 改成 `>=` 也不会红。"""
        self.assertEqual(self.o["span_inclusive"], 30)
        self.assertFalse(self.o["monthly_at_90"], "90 天整该按天")
        self.assertTrue(self.o["monthly_at_91"], "91 天该按月")


class TheHotPathWindowIsNotWidened(unittest.TestCase):
    """★★★ 实测 `--days 90` 1.06s vs `--days 365` 7.65s。"""

    @classmethod
    def setUpClass(cls):
        cls.o = _probe()

    def test_the_default_tier_is_returned_verbatim(self):
        self.assertEqual(self.o["need_default"], 90,
                         "★★★ 默认档被量化成了别的窗口 ⇒ 心跳与菜单栏弹出从 1.0s 掉到 7.6s")
        self.assertEqual(self.o["need_90"], 90)

    def test_the_year_needs_a_wider_tier(self):
        self.assertEqual(self.o["need_year"], 365)

    def test_a_recent_custom_span_stays_on_the_hot_tier(self):
        """★ 选「上个月」不该把窗口撑到 365 —— 那是一次 7.6s 的扫描换零收益。"""
        self.assertEqual(self.o["need_custom_recent"], 90)

    def test_windows_are_quantised_not_exact(self):
        """★★ 不量化的话，用户每拖一次日期就落一份新快照、每份都要重扫一遍。"""
        self.assertIn(self.o["need_custom_old"], self.o["tiers"])
        self.assertEqual(self.o["tiers"][0], 90, "第一档必须是热路径那一档")


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

    def test_switching_window_clears_the_old_data(self):
        """★★★ `adopt` 只在 `generated_at` 更新时换数据。换窗口时新快照**可能更旧**
        ⇒ 被拒绝 ⇒ 页面继续画 90 天的数，而横轴已经写着「年度」。"""
        self.assertRegex(self.TS, r"lastDays[\s\S]{0,400}setData\(null\)",
                         "★★★ 换窗口没清空旧数据 —— 会拿 90 天的数配「年度」的轴")

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


class EveryBucketsForCallCarriesTheSpan(unittest.TestCase):
    """★★★ 漏传 `span` 的后果**不是报错，是静默算成 0**。

    `bucketsFor(..., "custom")` 拿不到区间时返回空切片。调用点漏传一个参数，
    那一格就从真值变成 0 —— 而 `0.0%` 会被读成「没用到缓存」，与事实相反。

    2026-09-12 真踩到：像素上年度档 96.3%、自定义档 **0.0%**，tsc 与全部单测**全绿**。
    同一格此前已经因为**另一个**原因显示过 0.0%（拿重塑后的 `data` 去算），
    源码里那条注释还在。**同一格、两个原因、同一个假值** —— 所以这条闸打在「所有调用点」上，
    而不是打在某一个已知的坑上。
    """

    FILES = ["codexbar/src/pages/TrafficPage.tsx", "codexbar/src/pages/PlatformPage.tsx"]

    def test_no_call_site_forgets_the_span(self):
        bad = []
        for rel in self.FILES:
            src = (ROOT / rel).read_text(encoding="utf-8")
            for m in re.finditer(r"bucketsFor\(([^;]*?)\)\.?", src):
                args = m.group(1)
                if "span" not in args:
                    ln = src[:m.start()].count("\n") + 1
                    bad.append(f"    {rel}:{ln}  bucketsFor({args[:60]}…")
        self.assertEqual(bad, [],
                         "★★★ 这些调用点没传 span ⇒ 自定义档下静默返回空切片:\n" + "\n".join(bad))

    def test_the_probe_can_actually_find_call_sites(self):
        """★ 反向自检:上面那条断言在"一个调用点都没找到"时也会通过。"""
        n = sum(len(re.findall(r"bucketsFor\(", (ROOT / f).read_text(encoding="utf-8")))
                for f in self.FILES)
        self.assertGreaterEqual(n, 4, "★ 一个 bucketsFor 调用都没找到 —— 探针坏了，不是代码干净")


if __name__ == "__main__":
    unittest.main()
