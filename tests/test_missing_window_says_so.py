"""★★ **缺一个额度窗口时，画出来并说明为什么 —— 不许留一行空白。**

## 由来（2026-09-13，用户连报两次）

    「我有个号缺少了5小时额度窗口」      → agy 卡
    「还存在一个问题 gemini 和 grok 缺少了 5h 额度」 → 菜单栏两行

四处都是同一个写法：`visibility: hidden` 的同构占位行（为了跨卡对齐），
于是用户看到的是**一整行空白**，连 `—` 都没有。

本仓 §5d 的规矩是「**读不到显 `—`，不显 `0`**」，而"什么都不显"比显 0 更糟：
它把「读不到」伪装成「这里本该有点什么」，而两者的下一步动作完全不同。

## ★ 两种缺失的文案**必须不同**，这是这一组闸真正在守的东西

    agy 缺「周」  = **这个号读不到**（云端按账号那条只给 5h；周窗口只有本机 RPC 有，
                    而那条只看得到当前登录的号）→ 切过去再刷新就能看到
    grok 缺「5h」 = **上游根本没有这个窗口**（实测 `window_minutes = 10080`，只有周）
                    → 永远看不到，等也没用

合并成一句话，就等于把两种状态又折叠回同一个值 —— 正是本仓反复吃亏的那一类。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / "codexbar" / "src" / "components"
TARGETS = {
    "AgyCard": C / "AgyCard.tsx",
    "AgyRow": C / "AgyRow.tsx",
    "GrokCard": C / "GrokCard.tsx",
    "GrokRow": C / "GrokRow.tsx",
}


def code(p):
    """剥注释 —— 本仓注释密度极高，闸撞上自己的说明文字已是惯犯（空守卫形态⑫）。"""
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


class NoWindowRowIsSilentlyBlank(unittest.TestCase):

    #: 窗口行的渲染入口。判据要切到**这一段**，不能整文件扫 ——
    #: `AgyCard` 的**动作条**也用 `visibility: hidden` 占位（那是对的：兄弟卡要等高），
    #: 整文件断言会把它一起判红（实测假红一次）。
    ROW_ENTRY = {"AgyCard": "slotRows.map", "AgyRow": "MB_WIN_SLOTS.map",
                 "GrokCard": "slotRows.map", "GrokRow": "className=\"mb-row-meta\""}

    def _rows_region(self, name):
        c = code(TARGETS[name])
        i = c.index(self.ROW_ENTRY[name])
        return c[i:i + 1800]

    def test_no_invisible_placeholder_rows(self):
        """★★ `visibility: hidden` 是这个缺陷的**唯一写法**，四处都曾用它。"""
        for name in TARGETS:
            with self.subTest(component=name):
                self.assertNotIn('visibility: "hidden"', self._rows_region(name),
                                 f"★★ {name} 又用隐藏行占位了 —— 用户看到的是一整行空白")

    #: 缺失行上**写给人看的那句话**。两张卡 2026-09-14 从 `—  ↻—` 改成了直接写原因
    #: （用户实报「我的 grok 五小时额度没刷新？还丢失了？」）；两行受菜单栏宽度限制仍用 `↻—`。
    #: ★ 判据因此改成「**这一行上有没有一个能读的结论**」，而不是某个字符。
    #:   上一版钉的是字面 `↻—`，于是把 `—` 换成更清楚的中文时**闸自己红了**，
    #:   而语义是变好的 —— 逐字匹配守的是"代码长什么样"，不是"用户看不看得懂"。
    SAYS = {"AgyCard": ("非当值号", "这次没读到"), "GrokCard": ("无此窗口",),
            "AgyRow": ("↻—",), "GrokRow": ("↻—",)}

    def test_every_component_can_render_a_dash(self):
        """★ 正面：四处都必须有那个缺失行。只验"没有隐藏行"的话，
        把整行删掉（对齐一起塌）也能变绿。"""
        for name, p in TARGETS.items():
            with self.subTest(component=name):
                c = code(p)
                self.assertTrue(any(w in c for w in self.SAYS[name]),
                                f"★ {name} 没有缺失窗口那一行（找不到 {self.SAYS[name]}）")

    def test_the_missing_row_still_keeps_its_height(self):
        """★★ 跨卡/跨行对齐靠这一行撑着。把它整个删掉，旁边的卡就会比它高一截，
        而 harness 的折行探针对"少了一行"是**沉默**的。
        判据：缺失分支里仍然画着**标签 + 条槽**。★ 条槽是高度的来源，所以它是这条闸的核心；
        2026-09-14 我一度把它删掉（想给中文腾地方），这条闸当场红 —— 红得对。"""
        for name, p in TARGETS.items():
            with self.subTest(component=name):
                c = code(p)
                anchor = next(w for w in self.SAYS[name] if w in c)
                i = c.index(anchor)
                seg = c[max(0, i - 900):i + 60]
                self.assertIn("barTrack", seg, f"★★ {name} 缺失行没有条槽 —— 高度对不齐")


class TheTwoKindsOfMissingAreNotTheSameSentence(unittest.TestCase):
    """★★★ 这一组才是重点：两种缺失的**原因不同、下一步动作也不同**。"""

    def test_agy_says_only_the_live_account_can_read_it(self):
        for name in ("AgyCard", "AgyRow"):
            with self.subTest(component=name):
                c = code(TARGETS[name])
                self.assertIn("当前登录", c, f"★★ {name} 没说清是「只有当值号读得到」")

    def test_grok_says_upstream_has_no_such_window(self):
        for name in ("GrokCard", "GrokRow"):
            with self.subTest(component=name):
                c = code(TARGETS[name])
                self.assertIn("只有周窗口", c, f"★★ {name} 没说清是「上游没有这个窗口」")

    def test_neither_borrows_the_others_wording(self):
        """★★★ 把 grok 的「上游没有」套到 agy 上 = 告诉用户"等也没用"，
        而事实是切过去就能看到；反过来则是让人一直等一个永远不会来的数。"""
        for name in ("AgyCard", "AgyRow"):
            with self.subTest(component=name):
                self.assertNotIn("只有周窗口", code(TARGETS[name]),
                                 f"★★★ {name} 用了 grok 的说法 —— 那会让人以为等也没用")
        for name in ("GrokCard", "GrokRow"):
            with self.subTest(component=name):
                self.assertNotIn("切过去再刷新", code(TARGETS[name]),
                                 f"★★★ {name} 用了 agy 的说法 —— 那个数永远不会来")


class TheMenubarRowsShowEveryWindowNotJustTheTightest(unittest.TestCase):
    """★★ 2026-09-13 用户实报「gemini 缺少 5h」的**直接根因**：
    `AgyRow` 此前只渲染 `agyTightest(...)` 那一格，于是当值号明明有 5h + 周两格，
    行上只看得到其中一格 —— 而旁边 codex 的行有两格。"""

    def test_agyrow_iterates_fixed_slots(self):
        c = code(TARGETS["AgyRow"])
        self.assertIn("MB_WIN_SLOTS.map", c, "★★ 又退回只画最紧的那一格")
        self.assertIn("agyWinRows", c, "★ 没有取全部窗口")

    def test_the_slots_are_fixed_not_data_driven(self):
        """★ 槽位写死成 `["5h","周"]`，不是"有什么画什么" —— 后者会让
        非当值号的行少一格、比旁边矮一截，而那个矮没有任何地方解释。"""
        c = code(TARGETS["AgyRow"])
        m = re.search(r'MB_WIN_SLOTS = \[([^\]]+)\]', c)
        self.assertIsNotNone(m, "★ 槽位表的形状变了 —— 判据看不懂了，先修闸")
        self.assertEqual(re.findall(r'"([^"]+)"', m.group(1)), ["5h", "周"])


if __name__ == "__main__":
    unittest.main()
