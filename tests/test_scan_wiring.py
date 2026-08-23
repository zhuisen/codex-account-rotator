"""`scan()` **接线**的闸 —— helper 绿不等于接线绿。

★ 由来（grok 第二轮复核）：上一轮修掉了「测试守着自己的副本」，结果我写的新用例又变成
  「测试守着 helper，而生产可以绕开 helper」。四条不变量当时**一条会红的闸都没有**：
    · 日桶消费用的是 `bisect_right(...) - 1`
    · 小时桶必须用 `strftime`（整点边界表达不了非整点 DST）
    · 文件签名必须走 `_sig()`（秒级会漏掉同秒等长改写）
    · `acc.setdefault` 必须在窗口判断**之前**（否则只有窗外数据的平台整家消失）

  最后一条是**用户可见回归**（设置页平台清单读这份输出，平台消失后再也开不回来），
  而它当时零测试 —— 下一次「把 continue 提前」会再次全绿。

前三条用 AST 静态分析（同 `test_lock_order.py` 的路子，不 import 凭证、不碰真实数据）；
第四条用真跑 `scan()` 的隔离夹具。
"""
import ast
import json
import pathlib
import shutil
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_PY = ROOT / "traffic" / "scan.py"
sys.path.insert(0, str(ROOT / "traffic"))
import scan  # noqa: E402


def _call_name(node):
    """同 `test_lock_order.py` 的 `call_name` —— 同时认 `f()` 与 `mod.f()`。

    ⚠️ 我原本只判 `node.func.id`，grok 实测指出 `bisect.bisect_right(...)` 或
       `from bisect import bisect_right as br` 都能绕过去。仓库里本来就有更强的写法，抄它。
    """
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _aliases_of(tree, real):
    """找出 `real` 在本模块里的所有可用名字（含 `import x as y` 的别名）。"""
    names = {real}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == real and a.asname:
                    names.add(a.asname)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "bisect" and a.asname:
                    names.add(a.asname)
    return names


def _scan_fn():
    tree = ast.parse(SCAN_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "scan":
            return node
    raise AssertionError("scan.py 里找不到 scan()")


class TestScanWiring(unittest.TestCase):
    """★ 这些断言必须锚在 **`scan()` 函数体**上，不是 helper、更不是测试自己的副本。"""

    def setUp(self):
        self.fn = _scan_fn()
        self.src = ast.get_source_segment(SCAN_PY.read_text(encoding="utf-8"), self.fn) or ""

    def test_hour_label_uses_strftime_not_bisect(self):
        """小时桶必须逐行 `strftime`。

        整点边界表达不了非整点 DST：`Pacific/Chatham` 02:45 切换，实测 02:45–02:59
        被整点 bisect 判进 `T03`（15 个分钟点）。所以 `scan()` 里**只能有一处** bisect（打日桶）。
        """
        tree = ast.parse(SCAN_PY.read_text(encoding="utf-8"))
        names = _aliases_of(tree, "bisect_right")
        n_bisect = sum(1 for n in ast.walk(self.fn) if _call_name(n) in names)
        self.assertEqual(n_bisect, 1,
                         f"scan() 里 bisect_right 出现 {n_bisect} 次；只该有 1 次（日桶）。"
                         "小时桶若也用整点边界，非整点 DST 会算错")
        self.assertIn('strftime("%Y-%m-%dT%H"', self.src,
                      "小时标签必须来自 strftime，不能是预算的整点边界")

    def test_signature_goes_through_sig_helper(self):
        """签名必须走 `_sig()`，不能在 `scan()` 里内联。

        内联最容易写成 `[int(st.st_mtime), st.st_size]` —— 同一秒内的等长改写会被判成未变动，
        缓存沿用旧解析结果，**没有任何症状**。
        """
        calls = [n for n in ast.walk(self.fn) if _call_name(n) == "_sig"]
        self.assertTrue(calls, "scan() 没有调用 _sig()，签名可能被内联了")
        self.assertNotIn("int(st.st_mtime)", self.src,
                         "scan() 里出现了秒级 mtime —— 同秒等长改写会被漏掉")

    def test_day_bounds_comes_from_helper(self):
        """★ 日桶边界必须来自 `_day_bounds()`，不能在 `scan()` 里内联。

        grok 复核指出：我对 `_sig` 要求了"必须调用"，对 `_day_bounds` 却只在 helper 上加了
        DST 测试 —— 有人把边界内联回 `midnight + k*86400`、同时保留那一次 `bisect_right`，
        helper 测试绿、计次 AST 绿、集成夹具又离午夜很远（且本机 `Asia/Singapore` 无 DST），
        **三道闸全绿**。所以必须钉住"接线"本身。
        """
        # ⚠️ 不要写成 `assertNotIn("86400", src)` —— 我一开始就是这么写的，结果被
        #   `cut = time.time() - max(days,90)*86400`（文件 mtime 的**粗筛**，不是日界）
        #   和一条注释里的 "86400" 打成假阳性。**检查自己制造假警报，比没有检查更糟**。
        #   精确写法：`day_bounds` 这个名字必须由 `_day_bounds(...)` 的返回值绑定。
        bound_from_helper = False
        for n in ast.walk(self.fn):
            if not isinstance(n, ast.Assign):
                continue
            targets = []
            for t in n.targets:
                targets += [e.id for e in ast.walk(t) if isinstance(e, ast.Name)]
            if "day_bounds" in targets and _call_name(n.value) == "_day_bounds":
                bound_from_helper = True
        self.assertTrue(bound_from_helper,
                        "`day_bounds` 不是由 `_day_bounds()` 绑定的 —— 日期边界被内联了，"
                        "DST 日（本地日 ≠ 86400 秒）会整体错位，而 helper 上的测试照样绿")

    def test_setdefault_precedes_window_check(self):
        """★ `acc.setdefault` 必须在窗口判断**之前**（静态形状检查，配合下面的真跑用例）。"""
        i_set = self.src.find("acc.setdefault")
        i_win = self.src.find("if di < 0 or di >= n_days")
        self.assertGreater(i_set, 0, "找不到 acc.setdefault")
        self.assertGreater(i_win, 0, "找不到窗口判断")
        self.assertLess(i_set, i_win,
                        "窗口判断跑到了 setdefault 前面 —— 只有窗外数据的平台会整家消失")


def _agy_row(ts, out=10):
    return json.dumps({"ts": ts, "conv": "C1", "model": "gemini-3.7-flash-high",
                       "input_tokens": 100, "cache_read_tokens": 0, "output_tokens": out,
                       "total_tokens": 100 + out, "status": "SUCCESS"}) + "\n"


class TestScanIntegration(unittest.TestCase):
    """真跑 `scan()`。

    ⚠️ **必须替换整个 `scan.SOURCES`,不能只改模块级的 `AGY_ROOT`** —— `SOURCES` 在 import 时
      就把根路径捕获进了那个 dict。我第一次验证这个回归时正是栽在这里：改了常量没生效,
      扫的还是真数据,于是得出「平台仍在」的**假结论**。
    ⚠️ 一律 `use_cache=False`:既不读也不写真实 `.traffic-cache.json`。
    """

    def _run(self, ledger_text, days=90):
        """★ 隔离要**从构造上**成立，不能靠 `only=[...]` 这种运行时过滤。

        grok 实测指出两处泄漏（都只读、不改结果，但与「合成夹具」的承诺不符）：
          · 我原来保留了 agy 的 `coverage: _agy_coverage` 钩子 —— 它会去读真实的
            `~/.gemini/antigravity-cli/brain/**`，一次跑打开了 **165 个**真实文件。
          · 其余 7 个源的 `root` 仍是真路径，隔离全靠 `only=["agy"]`。
            把 `only=` 去掉就会扫 **10133 个**真文件，而当时的断言**照样通过** ——
            因为没人断言"输出里只该有 agy"。

        改法：`SOURCES` 收成**单元素**、去掉 coverage 钩子，并断言输出键恰好是 `["agy"]`。
        """
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)   # 原来没清
        (d / "usage.jsonl").write_text(ledger_text, encoding="utf-8")
        agy = next(x for x in scan.SOURCES if x["key"] == "agy")
        fake = {k: v for k, v in agy.items() if k != "coverage"}
        fake["root"] = d
        orig = scan.SOURCES
        scan.SOURCES = (fake,)                                   # 单元素：其余源根本不存在
        try:
            out, st = scan.scan(days=days, use_cache=False)       # 不再依赖 only=
        finally:
            scan.SOURCES = orig
        self.assertEqual(sorted(out), ["agy"],
                         f"输出里混进了别的平台 {sorted(out)} —— 隔离没生效，扫到真数据了")
        return out, st

    def test_out_of_window_only_platform_still_appears(self):
        """★ 只有窗口外数据的平台**必须仍然出现**（一列全零桶），不能整家消失。

        设置页的平台清单读的就是这份输出 —— 平台消失后用户再也开不回来。
        """
        out, _ = self._run(_agy_row(time.time() - 200 * 86400))
        self.assertIn("agy", out, "只有窗外数据的平台消失了")
        self.assertEqual(sum(b["total"] for b in out["agy"]["days"].values()), 0,
                         "窗外数据不该被算进 90 天窗口")

    def test_in_window_data_is_counted(self):
        """反向对照：窗口内的数据必须被算进去，否则上面那条可能是"什么都没算"蒙对的。"""
        out, _ = self._run(_agy_row(time.time() - 3 * 86400, out=42))
        self.assertIn("agy", out)
        self.assertEqual(sum(b["total"] for b in out["agy"]["days"].values()), 142)

    def test_future_timestamp_not_counted_as_today(self):
        """未来时间戳不能被算进今天（末尾那条「明天零点」边界的作用，走真实 scan()）。"""
        out, _ = self._run(_agy_row(time.time() + 5 * 86400, out=7))
        self.assertIn("agy", out)
        self.assertEqual(sum(b["total"] for b in out["agy"]["days"].values()), 0,
                         "未来的记录被算进窗口了")


if __name__ == "__main__":
    unittest.main()
