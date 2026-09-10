"""★★★ 逐日「按模型」明细的三条：不冻结半天、预算先花在今天、失败要熔断。

三条都属于同一族：**症状是数字停在旧值上或界面卡住，而没有任何东西报错。**
"""
import unittest
from unittest import mock

from relay import monitor

RELAY = {"id": "r", "base_url": "https://a.test/v1", "key": "k", "usage_path": "/usage"}
TODAY = "2026-09-10"


def days(*dates):
    return [{"date": d, "total_tokens": 1} for d in dates]


class ADayCapturedWhileItWasTodayIsRefetched(unittest.TestCase):
    """★★★ 「历史日不可变」不适用于**当时还是今天**抓的那一份。

    昨天下午抓的明细只覆盖到那一刻。第二天它变成"历史日"，原实现从此永远复用 ⇒
    那半天的模型构成被**永久冻结**，而同一天的四类 token 总量是完整的 ⇒
    「按模型加起来」≠「总量」，两个数就在同一页上。
    """

    def test_a_partial_yesterday_is_fetched_again(self):
        called = []
        with mock.patch.object(monitor, "day_models",
                               side_effect=lambda r, p, d: called.append(d) or [{"model": "m"}]):
            out = monitor.attach_day_models(
                RELAY, "/usage", days("2026-09-09", TODAY),
                {"2026-09-09": ([{"model": "old"}], True)}, TODAY)
        self.assertIn("2026-09-09", called,
                      "★★ 当时抓的半天数据被当成不可变的历史日,永久冻结")
        self.assertEqual(out[0]["models"], [{"model": "m"}])
        self.assertFalse(out[0]["models_partial"], "重取之后必须清掉 partial 标记")

    def test_a_complete_history_day_is_still_reused(self):
        """★ 反向闸：真正完整的历史日不能跟着一起重取 ——
        那会把「稳态每轮只多 1 个请求」变成每轮 N 个。"""
        called = []
        with mock.patch.object(monitor, "day_models",
                               side_effect=lambda r, p, d: called.append(d) or []):
            monitor.attach_day_models(
                RELAY, "/usage", days("2026-09-09", TODAY),
                {"2026-09-09": ([{"model": "old"}], False)}, TODAY)
        self.assertNotIn("2026-09-09", called, "完整的历史日被重取了")
        self.assertEqual(called, [TODAY])

    def test_todays_fetch_is_marked_partial(self):
        with mock.patch.object(monitor, "day_models", return_value=[{"model": "m"}]):
            out = monitor.attach_day_models(RELAY, "/usage", days(TODAY), {}, TODAY)
        self.assertTrue(out[0]["models_partial"], "★ 今天抓的没标 partial ⇒ 明天不会重取")

    def test_merge_daily_carries_the_partial_flag(self):
        """★★ 标记必须**跟着 models 一起搬**。只搬明细不搬标记的话，
        一份半天数据会摇身变成完整的历史日 —— 而漏搬它没有任何症状。"""
        prev = [{"date": "2026-09-09", "models": [{"model": "a"}], "models_partial": True}]
        new = [{"date": "2026-09-09", "models": None}]
        got = monitor.merge_daily(prev, new)
        self.assertEqual(got[0]["models"], [{"model": "a"}])
        self.assertTrue(got[0]["models_partial"], "★ partial 标记在合并时丢了")


class TheBudgetIsSpentOnTodayFirst(unittest.TestCase):
    """★★ `days` 按日期升序，预算从头花 ⇒ 上游给的天数超过 `MAX_DAY_FETCH` 时，
    **今天永远排在预算之外**，而今天是唯一每轮都在变的那天。"""

    def test_today_is_fetched_even_when_the_window_exceeds_the_budget(self):
        dates = [f"2026-07-{d:02d}" for d in range(1, 32)] + \
                [f"2026-08-{d:02d}" for d in range(1, 32)] + [TODAY]
        self.assertGreater(len(dates), monitor.MAX_DAY_FETCH, "夹具没超预算,这条闸恒绿")
        called = []
        with mock.patch.object(monitor, "day_models",
                               side_effect=lambda r, p, d: called.append(d) or []):
            monitor.attach_day_models(RELAY, "/usage", days(*dates), {}, TODAY)
        self.assertIn(TODAY, called, "★★ 预算被最老的日子花光,今天一次都没取")
        self.assertEqual(called[0], TODAY, "今天不是第一个取的")
        self.assertLessEqual(len(called), monitor.MAX_DAY_FETCH, "超预算了")


class AFailingRelayTripsTheBreaker(unittest.TestCase):
    """★★ 每个 `_get` 带 `TIMEOUT=25`。对端整个挂掉时原实现会把预算跑完：
    最坏 40×25s ≈ **17 分钟**，而这段时间网络锁一直被占着，
    UI 上表现为"刷新键点了没反应"—— 而不是任何一条错误信息。"""

    def test_it_stops_after_consecutive_failures(self):
        dates = [f"2026-08-{d:02d}" for d in range(1, 31)]
        called = []

        def boom(r, p, d):
            called.append(d)
            return None
        with mock.patch.object(monitor, "day_models", side_effect=boom):
            out = monitor.attach_day_models(RELAY, "/usage", days(*dates), {}, TODAY)
        self.assertEqual(len(called), monitor.MAX_CONSECUTIVE_FAILS,
                         f"★ 没熔断，打了 {len(called)} 次 ≈ {len(called) * 25}s")
        # ★ 没取到的日子必须留 None，不是 []。后者会被画成"这天没用过任何模型"。
        self.assertTrue(all(d["models"] is None for d in out))

    def test_an_intermittent_failure_does_not_trip_it(self):
        """★ 反向闸：偶发失败不该熔断 —— 否则一次抖动就砍掉整轮明细。"""
        dates = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", TODAY]
        seq = {}

        def flaky(r, p, d):
            seq[d] = len(seq)
            return None if len(seq) % 2 else [{"model": "m"}]
        with mock.patch.object(monitor, "day_models", side_effect=flaky):
            monitor.attach_day_models(RELAY, "/usage", days(*dates), {}, TODAY)
        self.assertEqual(len(seq), len(dates), "间歇失败把熔断触发了")


if __name__ == "__main__":
    unittest.main()
