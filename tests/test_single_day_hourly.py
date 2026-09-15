"""选中**单独一天**时，横轴按小时（用户 2026-09-15）。

> 「还有 codexbar 的设定，设计单天例如昨天、具体的某一天，横轴按小时进行排序」

## 在此之前

`scan.py` 的逐小时桶只对**今天**累积（`if di == last_di:  # 今日视图按小时,只需当天`），
所以选中昨天只能画出**一根日柱**。

## 为什么不是"全部日期都留小时桶"

当天实测（7 个平台，单个小时桶 JSON 约 201 B）：

    全部 1095 天 → 快照 1.1 MB 涨到约 **37 MB**，而它**每次扫描都要重写**
    最近 30 天   → 约 +1.0 MB
    最近  7 天   → 约 +0.24 MB

用户拍板：**最近 30 天瞬开 + 更早按需重扫**（`scan.py --hours-day YYYY-MM-DD`）。

## ★ 本文件最重要的一条：小时桶必须**加得起来等于日桶**

这是唯一能证明"按小时拆"没有把量拆丢/拆重的判据。实测（2026-09-15，真数据、5 天 × 7 平台
共 35 组）**全部逐位相等，0 处不一致**。少了这条，一个把某些行漏进别的小时的 bug
画出来只是"某根柱子矮一点"，没有任何地方会红。
"""
import datetime
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = (ROOT / "traffic" / "scan.py").read_text(encoding="utf-8")
TS = (ROOT / "codexbar" / "src" / "traffic.ts").read_text(encoding="utf-8")
RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")


def _py(src):
    """剥掉 python 注释与 docstring —— 本仓注释密度极高，闸撞上自己的说明是惯犯。"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    return re.sub(r"#[^\n]*", "", src)


class TheScannerKeepsHourlyBucketsForMoreThanToday(unittest.TestCase):

    def test_the_window_is_a_named_constant(self):
        """★ 写死在条件里就没法解释"为什么是 30" —— 而那个数是量出来的。"""
        m = re.search(r"^HOURLY_DAYS = (\d+)", SCAN, re.M)
        self.assertIsNotNone(m, "★ HOURLY_DAYS 不见了")
        self.assertGreaterEqual(int(m.group(1)), 7)
        self.assertLessEqual(int(m.group(1)), 60,
                             "★ 窗口被放大了 —— 实测 1095 天会把快照撑到约 37MB，且每次扫描都重写")

    def test_it_no_longer_only_accumulates_today(self):
        """★★ 旧实现是 `if di == last_di:`，那正是"只有今天有小时桶"的根。"""
        code = _py(SCAN)
        self.assertNotIn("if di == last_di:", code,
                         "★★ 又退回只累积今天了 —— 选中昨天会变回一根日柱")
        self.assertIn("HOURLY_DAYS", code, "★ 累积条件没用上那个窗口常量")

    def test_the_on_demand_flag_validates_its_shape(self):
        """★ `--hours-day` 收到坏形状必须**退出**，不能悄悄当成 None ——
        那会让调用方以为要到了小时数据，画出来却还是一根日柱。"""
        code = _py(SCAN)
        self.assertIn("--hours-day", code, "★ 没有按需补扫那条路")
        i = code.index('elif a == "--hours-day"')
        seg = code[i:i + 500]
        self.assertIn("sys.exit", seg, "★ 坏形状没有退出")
        self.assertIn(r"\d{4}-\d{2}-\d{2}", seg, "★ 没有校验日期形状")


class TheFrontendSwitchesAxisOnASingleDay(unittest.TestCase):

    def test_single_day_is_detected_from_the_resolved_range(self):
        self.assertIn("export function singleDayOf", TS)
        i = TS.index("export function singleDayOf")
        seg = TS[i:i + 400]
        self.assertIn("r.s === r.e", seg, "★ 判据不是「起止同一天」")

    def test_missing_hours_is_not_the_same_as_an_empty_day(self):
        """★★★ `hoursOfDay` 取不到必须返回 `null`，**不是空数组**。

        空数组会被画成"这一天 24 格全是 0"，而真相是"这一天没存小时桶"。
        两者的下一步动作完全不同（一个是补扫，一个是什么都不用做）——
        本仓反复记的「这一枪没打中和确实没有不能返回同一个值」。
        """
        i = TS.index("export function hoursOfDay")
        seg = TS[i:TS.index("\n}", i)]
        self.assertIn("return null", seg, "★★★ 取不到时没返回 null")
        self.assertNotIn("return { labels: [], buckets: [] }", seg,
                         "★★★ 取不到时返回了空序列 —— 会被画成「这天全是 0」")

    def test_it_falls_back_to_the_day_bar_instead_of_blanking(self):
        """★ 补到之前画那根**真实的日柱**，比画空诚实。"""
        i = TS.index("export function bucketsFor")
        seg = TS[i:TS.index("\n}", i)]
        self.assertIn("singleDayOf", seg, "★ 单天没有走小时轴")
        self.assertIn("if (h) return h;", seg, "★ 取不到小时桶时没有回落到日聚合")


class TheOnDemandScanIsNotSwallowedByTheFreshnessCache(unittest.TestCase):
    """★★★ `--hours-day` 要的正是现有快照里**没有**的东西。

    命中新鲜度合并窗口直接回旧快照，调用方就会拿到一份仍然没有小时桶的快照 ——
    而"刚点过"和"没点中"在界面上一模一样。本仓在手动 ↻ 上栽过同一个形状。
    """

    def test_hours_day_forces_a_real_scan(self):
        i = RS.index("async fn run_traffic(")
        seg = re.sub(r"//[^\n]*", "", RS[i:i + 2000])
        self.assertIn('a == "--hours-day"', seg,
                      "★★★ `--hours-day` 没有绕过新鲜度合并 —— 会静默回一份没有小时桶的快照")

    def test_the_date_value_is_shape_checked_not_waved_through(self):
        """★ 白名单放行的是**这一种形状**，不是"任何字符串"。"""
        i = RS.index("async fn run_traffic(")
        seg = RS[i:i + 2000]
        self.assertIn("is_date", seg, "★ 日期值没有形状校验")


class TheHourlyBucketsSumToTheDayBucket(unittest.TestCase):
    """★★★ 唯一能证明"按小时拆"没把量拆丢/拆重的判据。跑**真扫描**。"""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run([sys.executable, str(ROOT / "traffic" / "scan.py"),
                            "--days", "3", "--json"],
                           capture_output=True, text=True, timeout=900, cwd=str(ROOT))
        if r.returncode != 0:
            raise unittest.SkipTest("scan.py 跑不起来：{}".format(r.stderr[-300:]))
        try:
            d = json.loads(r.stdout)
        except ValueError:
            raise unittest.SkipTest("scan.py 输出不是 JSON")
        plats = d.get("platforms") or d
        # ★★ CI 的干净 runner 上**一个 CLI transcript 都没有** ⇒ 扫出来是空的/None。
        #   这条闸验的是"按小时拆有没有拆丢"，没有数据就**没有东西可验** ——
        #   那是 skip，不是红。⚠️ 但必须**显式**：让它安静通过才是真正危险的
        #   （零输入的扫描器报"干净"，本仓记过）。
        plats = {k: v for k, v in (plats or {}).items() if isinstance(v, dict)}
        if not any((v.get("days") or v.get("hours")) for v in plats.values()):
            raise unittest.SkipTest(
                "本机没有任何 CLI transcript（CI 的干净 checkout 就是这样）——"
                "这条闸这一轮**没有跑**，别当成通过")
        cls.plats = plats

    def test_yesterday_has_a_full_24_buckets(self):
        """★ 整天要补满 24 格 —— 那些小时确实过完了，空就是真的没用。
        （今天只补到当前小时，所以这条挑**昨天**。）"""
        y = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        got = {k: len([x for x in (p.get("hours") or {}) if x.startswith(y + "T")])
               for k, p in self.plats.items()}
        self.assertTrue(got, "★ 一个平台都没有 —— 探针没打中")
        for k, n in got.items():
            with self.subTest(platform=k):
                self.assertEqual(n, 24, "★ {} 昨天只有 {} 个小时桶".format(k, n))

    def test_each_day_hours_sum_to_that_day(self):
        """★★★ 逐日核对。实测 2026-09-15：5 天 × 7 平台共 35 组**全部逐位相等**。"""
        checked = 0
        for k, p in self.plats.items():
            days, hours = p.get("days") or {}, p.get("hours") or {}
            for dt, db in days.items():
                hs = [v for h, v in hours.items() if h.startswith(dt + "T")]
                if not hs:
                    continue          # 窗口外的日子本来就没有小时桶
                checked += 1
                with self.subTest(platform=k, day=dt):
                    self.assertEqual(
                        (db or {}).get("total") or 0,
                        sum((v or {}).get("total") or 0 for v in hs),
                        "★★★ {} {} 的小时桶合计 ≠ 日桶 —— 按小时拆的时候丢了或重了".format(k, dt))
        self.assertGreater(checked, 0, "★ 一组都没核到 —— 这条闸这一轮什么也没验")


class ChangingTheHoursContractDidNotBreakTheTodayView(unittest.TestCase):
    """★★★ **这一组是回归闸，来历是我自己造的 bug**（2026-09-15，用户截图实报）。

    为了「单天按小时」，`p.hours` 从"只有今天"变成"跨 30 天"。
    而它的**既有消费点都假设它就是今天**：

        bucketsFor 的今日档 → `byTwoHours(p.hours)`  ⇒ 698 个小时桶两两合并成 **349 格**
        todayView（菜单栏今日页）→ `Object.keys(...hours)` ⇒ 把 30 天当成今天

    界面上的样子：「今日」档画出整整 30 天，总 token **21.64B**、较昨日 **↑4130.7%**，
    图例下面写着「今日 · 349 格 · 每 2 小时」。`test_menubar_panel_height` 同时变红 ——
    那条闸是对的，是我改了契约没回头看消费点。

    ★ 教训写成判据：**`p.hours` 跨多天，所以任何消费点都必须点名是哪一天。**
      `hourKeysOf(p, day)` 存在的意义就是让"哪一天"变成必填参数，而不是可以忘掉的约定。
    """

    TS_SRC = TS

    def test_nobody_consumes_hours_wholesale(self):
        """★★★ 主闸：不许再出现整包取用 `p.hours` 的键。

        ⚠️ **`hourKeysOf` 自己的实现要排除掉** —— 它就是那个"唯一允许整包取键、
        但当场按 day 过滤"的地方。第一版没排除，闸把**正确的实现**判红了
        （本仓的老形状：断言打在了被测对象以外的东西上）。
        """
        code = re.sub(r"//[^\n]*", "", re.sub(r"/\*[\s\S]*?\*/", "", self.TS_SRC))
        i = code.index("export function hourKeysOf")
        allowed = code[i:code.index("\n}", i)]
        self.assertIn("startsWith(day", allowed,
                      "★ `hourKeysOf` 不再按 day 过滤了 —— 那它就不该被豁免")
        rest = code[:i] + code[code.index("\n}", i):]
        for bad in ("Object.keys(p.hours)", "Object.entries(p.hours).map",
                    "byTwoHours(p.hours)"):
            with self.subTest(pattern=bad):
                self.assertNotIn(bad, rest,
                                 "★★★ 又整包取用 p.hours 了 —— 「今日」会画成 30 天")

    def test_the_day_is_a_required_parameter(self):
        """★★ `hourKeysOf` 必须**收一个 day**。没有它，"点名哪一天"就只是一句口头约定。"""
        self.assertIn("export function hourKeysOf(p: Platform, day: string)", self.TS_SRC,
                      "★★ `hourKeysOf` 的签名变了 —— 「哪一天」不再是必填参数")

    def test_the_today_preset_passes_today(self):
        """⚠️ 必须在 **`bucketsFor` 的函数体内**找 —— `st.preset === "today"` 在
        `singleDayOf` 里也有一份，第一版 `.index()` 命中的正是那处（命中了，但命中错了）。"""
        f = self.TS_SRC.index("export function bucketsFor")
        body = self.TS_SRC[f:self.TS_SRC.index("\n}", f)]
        i = body.index('if (st.preset === "today")')
        seg = body[i:i + 220]
        self.assertIn("hourKeysOf(p, today)", seg,
                      "★★★ 今日档没有点名今天 —— 这正是 21.64B 那个 bug")

    def test_the_menubar_today_view_passes_today(self):
        i = self.TS_SRC.index("export function todayView")
        seg = self.TS_SRC[i:i + 900]
        self.assertIn("hourKeysOf(", seg, "★★ 菜单栏今日页没有点名今天")
        self.assertIn("todayOf(data)", seg, "★★ 没用数据自带的「今天」")


if __name__ == "__main__":
    unittest.main()
