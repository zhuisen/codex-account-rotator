"""排"谁最优"只许在**所有号都测到的窗口**上比（2026-09-15 用户实报）。

> 「接下来根治解决下 gemini，出现一个 use，一个当前」

## 现场

    dbk   5h 99.x%   周 **没测到**        ⇒ min = 99.x   ← 挂上了 USE
    sam   5h 100%    周 98.78%           ⇒ min = 98.78  ← 而它才是「当前」

`99.x > 98.78`，于是 dbk 被判成"最优"。但它赢的唯一原因是**少测了一个窗口**。

## 违反的不变量

本仓 §8 早写过：「基准必须用 `tightest`，不能用 `windows[0]` —— 两把不同的尺」。
这里是同一条规则在**账号之间**的形态：`min(5h)` 与 `min(5h, 周)` 根本不是同一个量，
把它们比大小，就是在**奖励测得少的那个号**。

⚠️ 而周窗口对非当值号是**结构性测不到**的（只有本机 RPC 有；云端按账号那条没有周 ——
2026-09-15 实测：每个号 27 个模型只有 2 个桶，一个 5h、一个不限量）。
所以「等数据齐了再比」不是一个选项，**必须定义清楚在什么基础上比**。

## 判据

取所有候选**都有**的窗口（交集）当共同基准；交集为空 ⇒ 不给推荐。
★ 代价是显式的：若 dbk 的周其实只剩 5%，按 5h 比仍会推荐它 —— 我们**无法知道**。
  所以 `agyPartial` 要把"这次少看了哪些窗口"交给徽章的 `title` 如实说出来。
  **不说的话，`USE` 会被读成"全面最优"，而事实只是"在都量到的那部分上最优"。**
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
CARD = (ROOT / "codexbar" / "src" / "components" / "AgyCard.tsx").read_text(encoding="utf-8")


def _ts(src):
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


class TheRankingUsesACommonWindowBasis(unittest.TestCase):

    CODE = _ts(APP)

    def test_there_is_an_explicit_common_window_set(self):
        self.assertIn("agyCommonWins", self.CODE,
                      "★★ 没有共同基准 —— 又在拿两把不同的尺比大小")

    def test_it_is_an_intersection_not_a_union(self):
        """★★★ 并集会把"没测到"当成一格空，而空格在取 `min` 时被静默跳过 ——
        那正好等于**奖励测得少的那个号**，也就是这个 bug 本身。"""
        i = self.CODE.index("const agyCommonWins")
        seg = self.CODE[i:i + 400]
        self.assertIn("filter(l => mine.includes(l))", seg,
                      "★★★ 共同基准不是交集 —— 少测窗口的号又会赢")

    def test_the_min_is_taken_over_the_common_set_only(self):
        i = self.CODE.index("const agyRank")
        seg = self.CODE[i:i + 400]
        self.assertIn("agyCommonWins.includes(r.label)", seg,
                      "★★ `min` 又落回全部窗口了 —— 窗口不齐时结果不可比")

    def test_an_empty_basis_yields_no_recommendation(self):
        """★ 交集为空 ⇒ `agyRank` 为空 ⇒ `agyTop` 为 null ⇒ 不画 USE。
        判据打在 `Number.isFinite` 上：`Math.min()` 空集合返回 `Infinity`，
        不挡的话会冒出一个"余量 Infinity"的最优号。"""
        i = self.CODE.index("const agyRank")
        seg = self.CODE[i:i + 500]
        self.assertIn("Number.isFinite", seg,
                      "★ 空交集时 Math.min() 返回 Infinity，没挡住会造出一个假最优号")


class ThePartialComparisonIsDisclosed(unittest.TestCase):
    """★★ 少看了窗口必须说出来 —— 否则 `USE` 会被读成"全面最优"。"""

    def test_app_computes_what_was_left_out(self):
        self.assertIn("agyPartial", _ts(APP), "★ 没算「这次少看了哪些窗口」")

    def test_it_is_passed_to_the_card(self):
        """★★★ 算了不传 = 又一个孤儿字段（本仓刚在 `read_logs` 上栽过）。"""
        self.assertIn("partialWins={agyPartial}", _ts(APP),
                      "★★★ `agyPartial` 算出来没传给卡片 —— 孤儿字段")

    def test_the_badge_says_the_basis(self):
        code = _ts(CARD)
        self.assertIn("partialWins", code, "★ 卡片不接这个 prop")
        i = code.index("isBest && (")
        seg = code[i:i + 900]
        self.assertIn("title=", seg, "★★ 最优/USE 徽章没有说明这次比较的基础")


class TheMissingWeeklySaysWhatToDo(unittest.TestCase):
    """★ 「非当值号」说的是我们的内部状态；用户要知道的是**他能做什么**。

    而且这一格是**会自己消失**的：那个号下次当值时 `agy-quota` 会记下周额度（B49），
    此后显示的是真实读数（带 `~` 标龄）。所以文案描述的是一个**有终点**的状态。
    """

    def test_the_inline_text_is_actionable(self):
        self.assertIn("用过才有", CARD, "★ 行上那句话还是在描述内部状态")
        self.assertNotIn(">非当值号<", CARD)

    def test_the_tooltip_says_it_will_fill_in(self):
        i = CARD.index("const missTitle")
        seg = CARD[i:i + 900]
        self.assertIn("下次当值时会自动记下来", seg,
                      "★ 没说这一格会自己补上 —— 会被当成永久免责")
        self.assertIn("切到它", seg, "★ 没给「想立刻看到」的那条路")


if __name__ == "__main__":
    unittest.main()
