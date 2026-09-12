"""扫描缓存必须**合并**，不能整份替换（2026-09-12，用户实报）。

## 用户看到的

「用量信息做一个缓存，不要每次选择都是要重新刷新加载，这样会影响使用」

## 真因

`fresh` 只装**本次窗口访问过的文件**，而原来是 `_save_cache(fresh)` —— 整份替换。
于是跑一次 `--days 90` 会把更早的条目全剪掉，紧接着的 `--days 365` 只能从头重解析。

实测（交替跑，同一台机器）：

    连续 365 / 365 / 365   →  1.52s · 1.04s · 1.04s
    交替 90 → 365 ×3       →  365 每次 **5.2 ~ 8.3s**，90 恒 1.1s      ← 修前
    交替 90 → 365 ×3       →  365 **1.07 ~ 1.21s**                      ← 修后

★★ **不对称是判据**：宽窗口从不拖慢窄窗口，只有反过来 —— 这排除了"缓存本来就冷"这个解释。
   若只跑连续同档（我第一次就是这么量的），两者都是 1.0s，**这个缺陷完全看不见**。
"""
import ast
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "traffic" / "scan.py"
_spec = importlib.util.spec_from_file_location("scan_mod", SRC)
SCAN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SCAN)


class TheCacheIsMergedNotReplaced(unittest.TestCase):

    def test_entries_outside_this_window_survive(self):
        """★★★ 核心不变量。没有它，窄窗口每跑一次就把宽窗口的工作全作废。"""
        cached = {"old1": {"sig": 1}, "old2": {"sig": 2}, "both": {"sig": 3}}
        fresh = {"both": {"sig": 9}, "new": {"sig": 4}}
        out, _ = SCAN._merge_cache(cached, fresh)
        self.assertEqual(set(out), {"old1", "old2", "both", "new"},
                         "★★★ 本窗口没访问到的条目被剪掉了 —— 下一个宽窗口要重解析")
        self.assertEqual(out["both"]["sig"], 9, "★ 本轮的新值必须覆盖旧值")

    def test_no_write_when_the_key_set_is_unchanged(self):
        """★★ 窄窗口跑完、且没有任何文件变动时**不该落盘**。
        22MB 白写是热路径上最大的单项开销（这条曾以 8.6MB 的形态被修过一次）。"""
        cached = {"a": {"sig": 1}, "b": {"sig": 2}}
        _, changed = SCAN._merge_cache(cached, {"a": {"sig": 1}})
        self.assertFalse(changed, "★ 键集合没变却报告要落盘")

    def test_a_new_file_does_require_a_write(self):
        """★ 反向闸：只测"不写"的话，一个永远返回 False 的实现也能全绿。"""
        _, changed = SCAN._merge_cache({"a": {"sig": 1}}, {"b": {"sig": 2}})
        self.assertTrue(changed)

    def test_the_bound_evicts_the_least_recently_touched(self):
        """★★ 合并之后条目数 = 这台机器上出现过的**全部**文件，必须显式封顶 ——
        在那之前，"窄窗口剪裁"恰好也起到了上限的作用（代价是命中率）。
        淘汰顺序必须是"最久没被碰过的先走"：本轮碰过的在后面，砍前面。"""
        old = SCAN.CACHE_MAX_FILES
        try:
            SCAN.CACHE_MAX_FILES = 3
            cached = {f"old{i}": {"sig": i} for i in range(5)}
            fresh = {"hot1": {"sig": 91}, "hot2": {"sig": 92}}
            out, _ = SCAN._merge_cache(cached, fresh)
            self.assertEqual(len(out), 3)
            self.assertIn("hot1", out, "★★ 把本轮刚解析的条目淘汰掉了 —— 下轮立刻重解析")
            self.assertIn("hot2", out)
            self.assertNotIn("old0", out, "★ 最老的那条没被淘汰")
        finally:
            SCAN.CACHE_MAX_FILES = old

    def test_the_bound_is_not_smaller_than_what_this_machine_needs(self):
        """★ 上限低于真实并集时，缓存会在两个窗口之间来回颠簸 —— 症状与原缺陷一模一样，
        但原因完全不同。实测并集 12,037 条，所以下限钉在它之上。"""
        self.assertGreaterEqual(SCAN.CACHE_MAX_FILES, 15000)


class TheSaveCallGoesThroughTheMerge(unittest.TestCase):
    """★★ 判据打在**调用点**上：`_merge_cache` 存在但没人调，和它不存在是一回事，
    而前者看起来像已经修好了。"""

    TREE = ast.parse(SRC.read_text(encoding="utf-8"))

    def test_save_cache_is_never_handed_the_window_local_dict(self):
        bad = []
        for n in ast.walk(self.TREE):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_save_cache":
                a = n.args[0] if n.args else None
                if isinstance(a, ast.Name) and a.id == "fresh":
                    bad.append(n.lineno)
        self.assertEqual(bad, [],
                         f"★★★ 第 {bad} 行把只含本窗口的 `fresh` 整份写回去了 —— "
                         "窄窗口会把宽窗口的缓存剪光")

    def test_the_merge_is_actually_called(self):
        calls = [n for n in ast.walk(self.TREE) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "_merge_cache"]
        self.assertTrue(calls, "★★ `_merge_cache` 没有任何调用点 —— 它只是看起来修好了")


if __name__ == "__main__":
    unittest.main()
