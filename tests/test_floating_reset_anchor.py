"""`resets_at` 是浮动占位值时,不许画一个会走的钟(2026-09-05)。

## 事故

用户报「探针了,5h 还是没有继续计时」。真因不是探针,是**倒计时**:

窗口**没被使用过**时,服务端每次都回「本次响应时刻 + 整窗」,`resets_at` 跟着 now 滑动。
实测(5h 窗口 = 300 分钟 = 18000s):

    plus4  used=0%    resets_at − captured_at = 17999.5s   差 −0.5s
    plus6  used=0%    resets_at − captured_at = 17999.4s   差 −0.6s
    plus3  used=55%   resets_at − captured_at =  3588s     差 −14411s
    plus5  used=100%  resets_at − captured_at =  2943s     差 −15057s

用过的号有真实锚点;没用过的号每轮轮询把 `resets_at` 前移一个轮询周期,
于是前端算出来的倒计时**永远停在 ~4h55m**。

★ 同族现象:Antigravity 的额度接口也是闲置桶的 resetTime 跟着 now 滑动,用过才锚定。
  所以这不是某一家的怪癖,判据值得固化。

## 三条口径(经 codex / grok / agy 三方评审收敛)

① ★★ **拿 `captured_at` 比,不是 `now()`**。闲置轮询周期恰好等于一个 tick,
   用 `now()` 会在两次写入之间误判成「已启动」、轮询一到又跳回去 —— 每 5 分钟闪一次。
② ★★ **只换掉倒计时,不动 pct、不丢窗口、不动选号器**。
   假的是**钟**不是**水位** —— 油箱确实是满的,0% 排最前正是负载均衡要的(grok 明确反对改 `_pick`)。
   窗口若从 `windows` 里丢掉,Plus 的 5h 行会整行消失,卡片看起来像 Pro,槽位对齐也会破。
③ ★★ **文案是「待确认」不是「未启动」**(codex 的反例):刚首次使用、用量被取整成 0% 的
   **真**窗口也会命中这个判据,此时断言「未启动」就是在编一个我们证不了的事实。

## 三份副本

判据在 `helpers.ts::resetAnchorUnknown` 与 `lib.rs` 托盘各一份(跨语言没法共用)。
本文件同时守住两份 —— 本仓反复出现「同一规则的 N 个副本漂移」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "codexbar" / "src" / "helpers.ts"
RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"

WINDOW_SEC = 300 * 60          # 5h
TOL = 90


def anchor_unknown(resets_at, captured_at, window_minutes):
    """判据的参考实现 —— 与两份生产副本必须同构。测试用它来验真实观测数据。"""
    if not window_minutes or not resets_at or not captured_at:
        return False
    return abs((resets_at - captured_at) - window_minutes * 60) < TOL


class CriterionMatchesRealObservations(unittest.TestCase):
    """拿 2026-09-05 的真机数据验判据本身。"""

    # (label, used_percent, resets_at − captured_at)
    REAL = [("plus4", 0.0, 17999.5), ("plus6", 0.0, 17999.4),
            ("plus3", 55.0, 3588.0), ("plus5", 100.0, 2943.0)]

    def test_idle_windows_are_flagged(self):
        for label, used, delta in self.REAL:
            if used > 0:
                continue
            with self.subTest(label=label):
                self.assertTrue(anchor_unknown(1000 + delta, 1000, 300),
                                "%s 的浮动占位没被认出来" % label)

    def test_anchored_windows_are_not_flagged(self):
        for label, used, delta in self.REAL:
            if used == 0:
                continue
            with self.subTest(label=label):
                self.assertFalse(anchor_unknown(1000 + delta, 1000, 300),
                                 "%s 有真实锚点却被判成占位 —— 会把真钟藏掉" % label)

    def test_the_two_classes_are_far_apart(self):
        """★ 证明阈值不是拍脑袋:两类观测隔着三个数量级,阈值取哪都不敏感。"""
        idle = [abs(d - WINDOW_SEC) for _, u, d in self.REAL if u == 0]
        anchored = [abs(d - WINDOW_SEC) for _, u, d in self.REAL if u > 0]
        self.assertLess(max(idle), 2)
        self.assertGreater(min(anchored), 10000)

    def test_missing_fields_are_not_flagged(self):
        """缺字段 ⇒ 不判占位。宁可漏判也不要凭空说「待确认」。"""
        self.assertFalse(anchor_unknown(None, 1000, 300))
        self.assertFalse(anchor_unknown(19000, None, 300))
        self.assertFalse(anchor_unknown(19000, 1000, None))


def strip_ts(src):
    """剥掉 TS/Rust 注释。★★ 不剥就是空守卫:2026-09-06 评审实测,把 TS 判据改成恒 false、
    Rust 改用 now_ts、阈值改成 9000,**11 条断言仍然全绿** —— 因为解释这条规则的注释里
    什么词都有。同一个坑我在这一轮的另外两个测试里也犯了。"""
    import re as _re
    src = _re.sub(r"/\*.*?\*/", "", src, flags=_re.S)
    return _re.sub(r"//[^\n]*", "", src)


class BothCopiesImplementIt(unittest.TestCase):
    """两份生产副本都要有,且都用 captured_at 而不是 now。"""

    @classmethod
    def setUpClass(cls):
        # ★ 全部用**剥掉注释**后的源码断言(见 strip_ts 的说明)
        cls.ts = strip_ts(TS.read_text(encoding="utf-8"))
        cls.rs = strip_ts(RS.read_text(encoding="utf-8"))

    def test_ts_has_the_predicate(self):
        self.assertIn("resetAnchorUnknown", self.ts)
        self.assertIn("FLOATING_RESET_TOL_SEC", self.ts)

    def test_rs_has_the_predicate(self):
        self.assertIn("anchor_unknown", self.rs, "托盘那份副本没实现 —— 菜单栏还会画假钟")

    def test_ts_compares_against_captured_at_not_now(self):
        """★★ 口径①。用 now() 会每 5 分钟闪一次。"""
        i = self.ts.index("export function resetAnchorUnknown")
        body = self.ts[i:self.ts.index("\n}", i)]
        self.assertIn("capturedAt", body)
        self.assertNotIn("now()", body, "判据用了 now() —— 会在两次轮询之间来回翻转")

    def test_rs_compares_against_captured_at_not_now(self):
        """★★ 原来这条是 `body.split("=>")[0]` —— 而真正的比较表达式**就在 `=>` 之后**,
        于是它检查的是一段不含任何逻辑的模式匹配头部,改成 now_ts 也照样绿(评审实测)。
        现在取整个绑定块,并且正向断言它用了 `cap`、反向断言没用 `now_ts`。"""
        i = self.rs.index("let anchor_unknown")
        body = self.rs[i:self.rs.index(";", self.rs.index("};", i))]
        self.assertIn("cap", body, "托盘那份没有用 captured_at 做判据")
        self.assertNotIn("now_ts", body,
                         "托盘那份用了 now_ts —— 会在两次轮询之间来回翻转,且与前端分叉")

    def test_rs_tolerance_matches_ts(self):
        """两份副本的阈值必须一致 —— 跨语言没法共用常量,只能靠这条闸盯着。"""
        import re as _re
        ts_tol = int(_re.search(r"FLOATING_RESET_TOL_SEC = (\d+)", self.ts).group(1))
        i = self.rs.index("let anchor_unknown")
        rs_tol = _re.search(r"abs\(\)\s*<\s*([0-9.]+)",
                            self.rs[i:i + 500].replace(" ", "").replace("\n", ""))
        self.assertIsNotNone(rs_tol, "托盘那份找不到阈值 —— 断言可能打空了")
        self.assertEqual(float(rs_tol.group(1)), float(ts_tol),
                         "两份副本的阈值不一致(TS=%s Rust=%s)" % (ts_tol, rs_tol.group(1)))

    def test_ts_predicate_actually_computes(self):
        """★ 防「判据被改成恒 false/恒 true」:函数体里必须**真的有那个算式**。"""
        i = self.ts.index("export function resetAnchorUnknown")
        body = self.ts[i:self.ts.index("\n}", i)]
        self.assertIn("Math.abs", body, "判据里没有算式 —— 可能被改成了恒定返回")
        self.assertIn("FLOATING_RESET_TOL_SEC", body, "没有用那个阈值常量")
        self.assertRegex(body, r"wm\s*\*\s*60", "没有拿整窗长度去比")

    def test_pct_is_not_touched(self):
        """★★ 口径②:只换倒计时。pct 被动过就说明把「水位」也当成不可信了。"""
        i = self.ts.index("const anchorUnknown = resetAnchorUnknown")
        body = self.ts[i:self.ts.index("};", i)]
        self.assertRegex(body, r"pct:\s*clamp\(pctRaw\)",
                         "pct 不再是原值 —— 假的是钟不是水位")

    def test_window_is_not_dropped(self):
        """口径②:不许因为锚点不可信就 return null（整行会消失、槽位对齐会破）。"""
        i = self.ts.index("const anchorUnknown = resetAnchorUnknown")
        body = self.ts[i:self.ts.index("};", i)]
        self.assertNotIn("return null", body)

    def test_wording_is_pending_not_not_started(self):
        """★★ 口径③:不许断言「未启动」——那是我们证不了的事实。"""
        i = self.ts.index("const anchorUnknown = resetAnchorUnknown")
        body = self.ts[i:self.ts.index("};", i)]
        self.assertIn("待确认", body)
        for forbidden in ("未启动", "未使用", "从未"):
            with self.subTest(word=forbidden):
                self.assertNotIn(forbidden, body,
                                 "断言了「%s」—— 刚首次使用、取整成 0%% 的真窗口也会命中判据"
                                 % forbidden)


if __name__ == "__main__":
    unittest.main()
