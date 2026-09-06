"""quotad 的到点判断(2026-09-06)。

两个缺陷,共同点是**症状是"少发生了一件事"**,而少发生的事在日志里没有形状:

① **墙钟回拨会静默推迟每一条循环。** `now - last >= T` 在 `now` 被 NTP/用户/快照恢复
   往回拨之后会变成负数,于是下一次执行被推迟**整整一个回拨的量**(可能几小时)。
   额度数字停在旧值,看上去与"这段时间没人用 codex"一模一样。
   ⇒ `_due()`:超过容差的负数直接判到点。

② **窗口跨过重置时刻后,最坏要挂 300s 的"未知"。** 旧读数在重置那一刻语义上就作废
   (本仓铁律:读不到就是读不到,绝不编一个"满额"),UI 如实显示未知 —— 而那正是
   用户最想看到新数的时候。⇒ `_reset_crossed()` 给全池扫描加第二个触发口。

## 这份测试**不启动 daemon**

只按路径 import 那两个纯函数。`quota_daemon.py` 顶层会用 `SourceFileLoader` 把
`codex-rotate` 整个载进来(那是它的既有设计),而 `codex-rotate` 顶层只有常量,
所以 import 不会碰网络、不会碰 `state.json`。真正的循环在 `main()` 里,不调它。
"""
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader(
    "quota_daemon", str(ROOT / "daemon" / "quota_daemon.py"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
QD = importlib.util.module_from_spec(_spec)
_loader.exec_module(QD)

NOW = 1_800_000_000.0


class DueHandlesAClockThatMovedBackwards(unittest.TestCase):
    def test_normal_forward_progress(self):
        self.assertFalse(QD._due(NOW, NOW - 100, 300))
        self.assertTrue(QD._due(NOW, NOW - 300, 300))
        self.assertTrue(QD._due(NOW, NOW - 301, 300))

    def test_first_run_is_due(self):
        """`last = 0` 是启动态 —— 必须立刻扫一次,不是等一个周期。"""
        self.assertTrue(QD._due(NOW, 0.0, QD.USAGE_SECS))

    def test_small_backward_jitter_still_waits(self):
        """★ 小幅回拨是时钟抖动,不该当成到点 —— 否则每次 NTP 微调都触发一轮全池扫描。"""
        self.assertFalse(QD._due(NOW, NOW + 10, 300))
        self.assertFalse(QD._due(NOW, NOW + QD.CLOCK_BACK_TOL_SECS - 1, 300))

    def test_large_backward_jump_is_due_instead_of_stalling(self):
        """★★ 这条是缺陷①的闸。回拨一小时后,朴素写法会让下一次扫描推迟一小时,
        而**没有任何症状**。"""
        self.assertTrue(QD._due(NOW, NOW + 3600, 300),
                        "时钟回拨一小时后仍判定「没到点」 —— 扫描会静默停摆一小时")

    def test_every_loop_deadline_goes_through_due(self):
        """★ 判据打在**源码**上:三条循环里任何一条漏用 `_due`,那一条就会独自带着
        缺陷①。断言前先剥掉注释 —— 注释里正解释着这条规则,对着原文匹配是空守卫。"""
        src = (ROOT / "daemon" / "quota_daemon.py").read_text(encoding="utf-8")
        body = src[src.index("def main("):]
        body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn(">= USAGE_SECS", body)
        self.assertNotIn(">= TICK_SECS", body)
        self.assertNotIn(">= MIN_GAP_SECS", body)
        for name in ("last_usage, USAGE_SECS", "last_tick, TICK_SECS",
                     "last_event_refresh, MIN_GAP_SECS"):
            with self.subTest(deadline=name):
                self.assertIn("_due(now, %s)" % name, body)


class ResetCrossedTriggersAnImmediateSweep(unittest.TestCase):
    @staticmethod
    def _state(captured_at, resets_at, **slot_extra):
        slot = {"quota": {"captured_at": captured_at,
                          "primary": {"used_percent": 30, "window_minutes": 300,
                                      "resets_at": resets_at},
                          "secondary": None}}
        slot.update(slot_extra)
        return {"slots": {"user-a": slot}}

    def test_snapshot_taken_before_a_reset_that_has_now_passed_is_due(self):
        self.assertTrue(QD._reset_crossed(self._state(NOW - 600, NOW - 10), NOW))

    def test_reset_still_in_the_future_is_not_due(self):
        self.assertFalse(QD._reset_crossed(self._state(NOW - 600, NOW + 600), NOW))

    def test_a_snapshot_taken_after_the_reset_is_not_due(self):
        """★★ 这条锁死"自我清零"。判据若写成"重置时刻已过"(不比 `captured_at`),
        服务端迟迟不更新 `resets_at` 时它会**恒为真** —— 兜底节拍变成每 60s 一扫,
        在 /usage 的 bot challenge 面前就是自找 403。"""
        self.assertFalse(QD._reset_crossed(self._state(NOW - 10, NOW - 600), NOW))

    def test_dead_accounts_do_not_trigger_sweeps(self):
        """失效号的读数永远追不上它的 reset,不排除就会**永久**把扫描顶在地板频率上。"""
        st = self._state(NOW - 600, NOW - 10, auth_dead=True)
        self.assertFalse(QD._reset_crossed(st, NOW))

    def test_secondary_window_counts_too(self):
        st = {"slots": {"user-a": {"quota": {
            "captured_at": NOW - 600,
            "primary": {"resets_at": NOW + 600},
            "secondary": {"resets_at": NOW - 10}}}}}
        self.assertTrue(QD._reset_crossed(st, NOW),
                        "只看了 primary —— Plus 的周窗口现在正落在 secondary 上")

    def test_missing_or_malformed_quota_is_not_due(self):
        for st in ({"slots": {}},
                   {"slots": {"a": {}}},
                   {"slots": {"a": {"quota": {}}}},
                   {"slots": {"a": {"quota": {"captured_at": None,
                                              "primary": {"resets_at": NOW - 10}}}}},
                   {"slots": {"a": {"quota": {"captured_at": NOW - 600, "primary": "junk"}}}},
                   {"slots": {"a": "junk"}},
                   {}):
            with self.subTest(state=st):
                self.assertFalse(QD._reset_crossed(st, NOW))

    def test_sweep_is_gated_by_a_floor(self):
        """★ 重置触发必须有地板:扫描失败时 `captured_at` 不前进,条件仍成立,
        没有地板就会每秒重试一次。"""
        src = (ROOT / "daemon" / "quota_daemon.py").read_text(encoding="utf-8")
        body = src[src.index("def main("):]
        self.assertIn("_due(now, last_reset_sweep, RESET_SWEEP_MIN_GAP)", body)
        self.assertGreaterEqual(QD.RESET_SWEEP_MIN_GAP, 30)

    def test_floor_is_evaluated_before_walking_the_pool(self):
        """★ 顺序也是判据的一部分:`_reset_crossed` 每秒都会遍历整个池子。
        把地板放在 `and` 左边,绝大多数 tick 直接短路掉。"""
        src = (ROOT / "daemon" / "quota_daemon.py").read_text(encoding="utf-8")
        i = src.index("reset_due = ")
        seg = src[i:i + 200]
        self.assertLess(seg.index("RESET_SWEEP_MIN_GAP"), seg.index("_reset_crossed"),
                        "每个 tick 都在遍历账号池 —— 地板要短路在前")


if __name__ == "__main__":
    unittest.main()
