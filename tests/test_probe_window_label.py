"""探针打印的窗口标签必须**现算**,不能写死(2026-09-05)。

## 事故

`cmd_probe` 原来打印 `周已用 X% → Y%`,但取的数是 `quota["primary"]`。
而 `primary` 是**槽位名不是窗口时长** —— 它的语义随套餐而变:

    Plus 号   primary.window_minutes = 300    ⇒ 5h 窗口
    Pro  号   primary.window_minutes = 10080  ⇒ 周窗口

5h 窗口 2026-08-25 回归之后,Plus 号探针打印出来的 **5h 数字被标成了「周」**。
用户照着它判断额度,必然判错 —— 而且这个错**看起来完全正常**,没有任何东西会红。

★ 前端(`helpers.ts::winLabel`)与 Rust 托盘早就改成按 `window_minutes` 分档了,
  `codex-rotate` 里也早有 `_win_tag()` —— **只有这条 CLI 打印路径漏掉**。
  三份实现里漏一份,正是本仓反复出现的「同一规则的 N 个副本漂移」。

## 断言

① 标签由 `window_minutes` 决定,不是由槽位名决定;
② 缺 `window_minutes` 时给 `?`,**不许**编出一个「0h 窗口」;
③ 打印路径里不得再出现写死的窗口名。
"""
import importlib.machinery
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CR = ROOT / "codex-rotate"


def load():
    loader = importlib.machinery.SourceFileLoader("cr_probe_label", str(CR))
    spec = importlib.util.spec_from_loader("cr_probe_label", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


class WindowTagIsDurationDriven(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def test_plus_primary_is_5h_not_week(self):
        """★★ 事故本体:Plus 号的 primary 是 5h,绝不能标成「周」。"""
        self.assertEqual(self.m._win_tag({"window_minutes": 300}), "5h")

    def test_pro_primary_is_week(self):
        """同一个槽位、不同套餐 ⇒ 不同标签。这就是"不能写死"的原因。"""
        self.assertEqual(self.m._win_tag({"window_minutes": 10080}), "周")

    def test_same_slot_name_yields_different_labels(self):
        """把①②合起来断言一次:**槽位名相同、标签必须不同**。

        没有这条,①②可以靠"两个常量恰好对"而通过,却测不到"标签是从时长推出来的"。
        """
        plus = self.m._win_tag({"window_minutes": 300})
        pro = self.m._win_tag({"window_minutes": 10080})
        self.assertNotEqual(plus, pro,
                            "两种套餐的 primary 标签相同 —— 说明标签没跟着时长走")

    def test_month_and_days(self):
        self.assertEqual(self.m._win_tag({"window_minutes": 43200}), "月")
        self.assertEqual(self.m._win_tag({"window_minutes": 2880}), "2天")

    def test_missing_duration_is_unknown_not_zero_hours(self):
        """★ 缺值给 `?`,不给 `0h`。

        「0 小时窗口」是不存在的东西;把「不知道多长」印成它,就是拿编出来的事实顶替未知。
        """
        for w in ({}, {"window_minutes": None}, {"window_minutes": 0}, None):
            with self.subTest(w=w):
                self.assertEqual(self.m._win_tag(w), "?")


class ProbePrintHasNoHardcodedWindowName(unittest.TestCase):
    """③ 打印路径里不得再出现写死的窗口名。"""

    def setUp(self):
        src = CR.read_text(encoding="utf-8")
        i = src.index("def cmd_probe(")
        # 只看函数体,别扫全文件 —— 别处出现「周」是合法的
        self.body = src[i:src.index("\ndef ", i + 10)]

    def test_anchor_found(self):
        """★ 先证明切出来的是真的函数体,否则下面的断言在空串上恒绿。"""
        self.assertIn("_billed_probe", self.body)
        self.assertGreater(len(self.body), 500)

    def test_no_hardcoded_window_word_in_probe_output(self):
        # 注释里解释这条规则时会写到「周」,所以先剥掉注释再查
        code = re.sub(r"#[^\n]*", "", self.body)
        for bad in ("周已用", "5h已用", "月已用"):
            with self.subTest(token=bad):
                self.assertNotIn(bad, code,
                                 "探针打印又写死了窗口名 {} —— 它必须由 _win_tag 现算".format(bad))

    def test_label_comes_from_win_tag(self):
        """⚠️ 第一版查的是 `self.body`（**含注释**），而注释里写着 "`_win_tag()` 早就存在"。
        删掉真调用、改成写死错标签,4 条断言仍然全绿(2026-09-06 评审实测)。
        必须查剥掉注释后的代码。"""
        code = re.sub(r"#[^\n]*", "", self.body)
        self.assertIn("_win_tag(", code,
                      "探针打印没有调用 _win_tag —— 标签又变回写死的了")
        self.assertRegex(code, r"\{wl\}已用",
                         "标签变量没有真的用在输出里")

    def test_none_percent_does_not_crash_the_format(self):
        """★ `after` 可能是 None(只有 secondary 有值的套餐),裸 `:.0f` 会 TypeError。

        这是同一处的相邻缺陷:改标签时若只改标签,这个崩溃仍然留着。
        """
        code = re.sub(r"#[^\n]*", "", self.body)
        self.assertNotIn("{after:.0f}", code,
                         "对可能为 None 的 after 直接做 :.0f 格式化,会崩")


if __name__ == "__main__":
    unittest.main()
