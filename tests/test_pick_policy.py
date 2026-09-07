"""代理选号策略:**Plus 优先、Pro 保底**,档内按**最紧窗口**排(2026-09-07)。

## 两件事一起做，但性质不同

**① 策略（用户 2026-09-07 定的 C）**：Plus 号平时承担轮换，**Pro 只在没有可用 Plus 时才动**。
   这是产品决定，不是 bug 修复 —— `_used()` 的 docstring 原本明写「要改先定策略，别顺手改」，
   现在策略定了。

**② 一个真 bug**：`_used()` 按 `(primary, secondary)` 字典序排，而 `primary` 是**槽位名不是
   窗口时长**（Plus 的 primary 是 5h、Pro 的是周）。于是「周额度 100% 烧光、但 5h 刚重置回 0%」
   的号按 primary 看是**全池最空的**。2026-09-07 用实况跑生产函数确认：plus3（周 100%）
   被排到**全池第一**，每次 5h 重置都会重排第一、白撞一次 429。

★ ② 是 ① 的前提：不修它的话，档内第一名仍然是那个烧光的号，策略 C 等于没生效。

## ★★ 迟滞必须跟着改，否则策略被绕过

`PICK_HYSTERESIS` 那段原来只比 `primary` 百分比。一个粘在 Pro 上的会话会因为
「Pro 没比最省的 Plus 贵多少」而**一直粘在 Pro 上** —— 「Pro 保底」就被静默绕过了。
所以**跨档不粘**。
"""
import importlib.util
import os
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CODEX_ROTATE_STORE", str(ROOT))
_spec = importlib.util.spec_from_file_location("px", ROOT / "proxy" / "proxy.py")
PX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PX)          # ★ 顶层只有常量，server 在 __main__ 下，import 无副作用


def win(mins, used):
    return {"window_minutes": mins, "used_percent": used, "resets_at": None}


def slot(label, plan, primary=None, secondary=None, **kw):
    return {"label": label, "plan": plan,
            "quota": {"primary": primary or {}, "secondary": secondary or {}}, **kw}


def order(slots):
    """按生产排序键排出的 label 顺序。"""
    rows = [(PX._plan_tier(sl), PX._tightest_used(sl), sl["label"]) for sl in slots]
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows]


class ProIsTheFallback(unittest.TestCase):
    """① 策略 C。"""

    def test_pro_sorts_after_every_plus_even_when_it_is_the_emptiest(self):
        """★★ Pro 剩得最多也排最后 —— 这正是「保底」的含义。"""
        got = order([
            slot("Pro1", "pro", primary=win(10080, 1.0)),      # 只用了 1%
            slot("plus4", "plus", primary=win(300, 86.0), secondary=win(10080, 78.0)),
            slot("plus5", "plus", primary=win(300, 9.0), secondary=win(10080, 13.0)),
        ])
        self.assertEqual(got[-1], "Pro1", "Pro 没排最后 —— 它会替 Plus 挡流量")
        self.assertEqual(got, ["plus5", "plus4", "Pro1"])

    def test_pro_is_still_reachable_when_it_is_the_only_one(self):
        """保底要真的能兜底 —— 只剩 Pro 时它必须被选中。"""
        self.assertEqual(order([slot("Pro1", "pro", primary=win(10080, 50.0))]), ["Pro1"])

    def test_tier_reads_plan_not_label(self):
        """★ 老号从 Plus 升 Pro 时 **label 一个字都不变** —— 按名字判会让它继续当主力。"""
        self.assertEqual(PX._plan_tier(slot("plusOld", "pro")), 1)
        self.assertEqual(PX._plan_tier(slot("Pro9", "plus")), 0)

    def test_unknown_plan_is_treated_as_plus_not_fallback(self):
        """★ 读不到 plan ⇒ 归 Plus 档。归到保底档会让一个刚加进来、还没解出 plan 的号
        **永远排最后、拿不到流量**,而它大概率就是 Plus。"""
        self.assertEqual(PX._plan_tier({"label": "new", "quota": {}}), 0)

    def test_plan_type_from_quota_is_a_fallback_source(self):
        self.assertEqual(PX._plan_tier({"label": "x", "quota": {"plan_type": "pro"}}), 1)


class TightestWindowNotPrimary(unittest.TestCase):
    """② 那个真 bug。"""

    def test_weekly_exhausted_account_sorts_last_within_its_tier(self):
        """★★ **本机 plus3 的真实形态**:5h=0%、周=100%。
        旧口径按 primary(5h) 看它是全池最空的,会被排第一、每次 5h 重置白撞一次 429。"""
        got = order([
            slot("plus3", "plus", primary=win(300, 0.0), secondary=win(10080, 100.0)),
            slot("plus5", "plus", primary=win(300, 9.0), secondary=win(10080, 13.0)),
        ])
        self.assertEqual(got[0], "plus5",
                         "周额度烧光的号又被排到了前面 —— 口径退回 primary 了")

    def test_takes_the_worst_of_both_windows(self):
        self.assertEqual(PX._tightest_used(
            slot("x", "plus", primary=win(300, 20.0), secondary=win(10080, 90.0))), (0, 90.0))

    def test_unknown_sorts_after_known(self):
        """★ 「没有读数」不许当成「最空」—— 拿没发生的观测当最有利的观测是本仓反复栽的那类。"""
        known = PX._tightest_used(slot("a", "plus", primary=win(300, 99.0)))
        unknown = PX._tightest_used(slot("b", "plus"))
        self.assertLess(known, unknown)

    def test_empty_slot_windows_are_ignored(self):
        """Codex 仍返回空槽 `{window_minutes: 0}`,不能当成一个 100% 空闲的窗口。"""
        self.assertEqual(PX._tightest_used(
            slot("x", "plus", primary={"window_minutes": 0, "used_percent": None},
                 secondary=win(10080, 30.0))), (0, 30.0))


class HysteresisCannotBypassTheTier(unittest.TestCase):
    """★★ 迟滞跨档就等于把「Pro 保底」静默绕过。判据打在源码上 ——
    行为要构造 `last_aid` + 完整 state,而这条规则本身是「比较里必须含档位」。"""

    @classmethod
    def setUpClass(cls):
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        i = src.index("if PICK_HYSTERESIS > 0:")
        # ★ 剥注释:注释里正解释着这条规则,对着原文匹配会恒绿(本仓点名过的空守卫形态)
        cls.body = "\n".join(l for l in src[i:src.index("return avail[0][0]", i)].splitlines()
                             if not l.lstrip().startswith("#"))

    def test_compares_the_tier(self):
        self.assertIn("_plan_tier", self.body,
                      "迟滞没比档位 —— 粘在 Pro 上的会话会一直粘着,保底被绕过")
        self.assertIn("lt == bt", self.body)

    def test_uses_tightest_not_primary(self):
        self.assertIn("_tightest_used", self.body)
        self.assertNotIn('"primary"', self.body,
                         "迟滞还在只看 primary —— 跨套餐比大小本就不成立")


class PickerActuallyUsesThem(unittest.TestCase):
    """★ 判据打在 `_pick` 的真实排序调用上 —— 定义了函数不等于接上了。"""

    def test_sort_key_is_wired_in(self):
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        i = src.index("def _pick(")
        body = src[i:src.index("\ndef ", i + 10)]
        self.assertIn("_plan_tier(kv[1]), _tightest_used(kv[1])", body,
                      "排序键没接进 _pick —— 策略只存在于注释里")


if __name__ == "__main__":
    unittest.main()
