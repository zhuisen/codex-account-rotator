"""「epoch → 本地日期/小时」的分桶正确性。

2026-08-24 把逐行 `strftime(localtime(ep))` 换成「预算本地午夜边界 + bisect」（148ms → 63ms）。
换算法**必须**证明它在这些地方与 `strftime` 完全一致，否则就是用速度换了一批悄悄记错日期的数据。

★ 为什么专挑这几个时区：
  · `Asia/Kolkata` **+05:30** —— 项目里那条禁令点名的形态：半小时偏移的本地午夜落在 UTC 整点
    小时的中间，任何「按 UTC 整小时记忆化」的做法都会把两天折叠成一天。
  · `America/New_York` **两次 DST 切换** —— 春季有一小时不存在、秋季有一小时出现两次。
    这两天的本地日长度不是 86400 秒，用 `midnight + k*86400` 推边界会错位。
  · `Australia/Lord_Howe` **+10:30/+11:00，DST 只跳半小时** —— 最刁钻的组合。
  · `UTC` 作为对照。

本测试**不碰真实数据**，纯算法比对。
"""
import os
import pathlib
import sys
import time
import unittest
from bisect import bisect_right
from datetime import date as _date, timedelta as _td

ZONES = ["UTC", "Asia/Kolkata", "America/New_York", "Australia/Lord_Howe",
         "Asia/Shanghai", "Europe/London", "Pacific/Chatham"]


# ★★ **调生产实现，不复制**。原来这里自己抄了一份 `_bounds` —— 于是改坏 `scan.py`
#   而不改这份副本，测试照样绿（codex 复核指出，已实测确认）。
#   断言必须锚在被测代码上，不是它的副本；否则这道闸守的是它自己。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "traffic"))
import scan  # noqa: E402

_bounds = scan._day_bounds


class TestDayBucketing(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def _run_zone(self, zone, anchor_date, days=90, step=997):
        os.environ["TZ"] = zone
        time.tzset()
        end = anchor_date
        bounds, labels = _bounds(end, days)
        # ★ 扫描范围**不能取自 `bounds`** —— 否则删掉一条边界时测试范围跟着缩水，
        #   正好绕开出问题的那一天，检查随被检查项一起退化（实测过这个假绿）。
        #   上界固定为「锚点日的次日零点」，与实现里那条边界无关。
        lo = time.mktime((end - _td(days=days - 1)).timetuple())
        hi = time.mktime((end + _td(days=1)).timetuple())
        bad = []
        ep = int(lo)
        while ep < hi:
            i = bisect_right(bounds, ep) - 1
            got = labels[i] if 0 <= i < len(labels) else None
            want = time.strftime("%Y-%m-%d", time.localtime(ep))
            if got != want:
                bad.append((ep, got, want))
                if len(bad) > 5:
                    break
            ep += step          # 与 86400 互质，扫遍一天里的各种时刻
        return bad

    def test_every_zone_matches_strftime(self):
        """整个 90 天窗口内逐点比对，含每一天的各个时刻。"""
        for zone in ZONES:
            with self.subTest(zone=zone):
                bad = self._run_zone(zone, _date(2026, 8, 24))
                self.assertEqual(bad, [], f"{zone}: 与 strftime 不一致 {bad[:3]}")

    def test_dst_transition_windows(self):
        """★ 专打两次 DST 切换那几天 —— 本地日长度不是 86400 秒的地方。"""
        cases = [
            ("America/New_York", _date(2026, 3, 12)),   # 春季前跳（窗口覆盖 3/8 前后）
            ("America/New_York", _date(2026, 11, 5)),   # 秋季回拨
            ("Australia/Lord_Howe", _date(2026, 4, 8)), # 半小时 DST
            ("Australia/Lord_Howe", _date(2026, 10, 8)),
            ("Pacific/Chatham", _date(2026, 4, 8)),     # +12:45/+13:45
        ]
        for zone, anchor in cases:
            with self.subTest(zone=zone, anchor=anchor.isoformat()):
                bad = self._run_zone(zone, anchor, days=20, step=311)
                self.assertEqual(bad, [], f"{zone}@{anchor}: {bad[:3]}")

    def test_future_timestamps_fall_outside_the_window(self):
        """★ 末尾那条「明天零点」边界的**唯一**作用：挡住未来时间戳。

        没有它，`bisect_right(bounds, ep) - 1` 对任何未来的 epoch 都会返回最后一天的下标 ——
        时钟偏移、坏时间戳、或别的机器写来的记录会被**静默算进今天**。
        （这条用例是补写的：原来的时区遍历取 `bounds[-1]` 当上界，删掉边界时它自己也缩了范围，
        于是变异测试是绿的 —— 检查随被检查项一起退化。）
        """
        for zone in ("UTC", "Asia/Shanghai", "America/New_York"):
            with self.subTest(zone=zone):
                os.environ["TZ"] = zone
                time.tzset()
                end = _date(2026, 8, 24)
                bounds, labels = _bounds(end, 90)
                tomorrow = time.mktime((end + _td(days=1)).timetuple())
                for delta in (1, 3600, 86400, 86400 * 30):
                    i = bisect_right(bounds, tomorrow + delta) - 1
                    self.assertGreaterEqual(
                        i, len(labels),
                        f"{zone}: 未来 {delta}s 的记录落进了窗口内（下标 {i}），会被算成今天")
                # 边界内侧仍必须命中今天
                i = bisect_right(bounds, tomorrow - 1) - 1
                self.assertEqual(labels[i], end.isoformat())

    def test_hour_labels_use_strftime_not_hourly_bounds(self):
        """★ 小时桶**不能**用「24 条整点边界 + bisect」—— 整点边界表达不了非整点 DST。

        `Pacific/Chatham` 在 **02:45** 切换（+12:45/+13:45）：实测 02:45–02:59 这 15 分钟
        会被整点边界判进 `T03`。

        ⚠️ **这条用例只证明「那个错法确实是错的」，它不调用生产代码、也钉不死生产代码**
        （grok 复核指出：我原本以为它能防住"顺手把小时桶改成 bisect"，其实不能）。
        真正会红的闸在 `tests/test_scan_wiring.py::test_hour_label_uses_strftime_not_bisect`，
        那条直接对 `scan()` 的 AST 断言。这里保留是为了把**反例本身**留档 ——
        没有它，将来有人会问"为什么小时桶不能也用 bisect"。
        """
        # ⚠️ 只留**真的构成反例**的日子。原来还列了 `Australia/Lord_Howe` 4-05 与
        #   `America/New_York` 11-01,实测这两天整点 bisect 的 mismatch **= 0** ——
        #   它们连反例都不是,写在这里只会让人以为覆盖面更广(grok 复核指出)。
        for zone, day in [("Pacific/Chatham", _date(2026, 4, 5)),
                          ("Pacific/Chatham", _date(2026, 9, 27))]:
            with self.subTest(zone=zone, day=day.isoformat()):
                os.environ["TZ"] = zone
                time.tzset()
                hb = [time.mktime((day.year, day.month, day.day, h, 0, 0, 0, 0, -1))
                      for h in range(24)]
                hl = [f"{day.isoformat()}T{h:02d}" for h in range(24)]
                start = time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1))
                mismatch = 0
                for k in range(0, 26 * 3600, 60):
                    ep = start + k
                    lt = time.localtime(ep)
                    if time.strftime("%Y-%m-%d", lt) != day.isoformat():
                        continue
                    want = time.strftime("%Y-%m-%dT%H", lt)
                    hi = bisect_right(hb, ep) - 1
                    if (hl[hi] if hi >= 0 else None) != want:
                        mismatch += 1
                if zone == "Pacific/Chatham":
                    self.assertGreater(
                        mismatch, 0,
                        "Chatham 的非整点 DST 竟然没被整点边界判错——这个反例失效了，"
                        "说明 tzdata 变了或日期选错，需要重新挑一天")
                # 无论哪个时区，生产代码用的 strftime 路径都必须与自身一致（恒真，作为形状检查）
                self.assertEqual(time.strftime("%Y-%m-%dT%H", time.localtime(start)),
                                 f"{day.isoformat()}T00")

    def test_naive_86400_arithmetic_would_fail(self):
        """★ 变异对照：证明这个测试**抓得住**「用 midnight + k*86400 推边界」这个错法。

        它是最容易顺手写出来的优化（省掉 90 次 mktime），在无 DST 的地区一直是对的 ——
        正因如此才需要一个会红的用例把它钉死。
        """
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        end = _date(2026, 11, 10)
        good, labels = _bounds(end, 20)
        naive = [good[0] + i * 86400 for i in range(len(good))]
        self.assertNotEqual(good, naive,
                            "该时区窗口内应当包含 DST 切换，否则这个对照用例没有意义")
        mism = 0
        ep = int(good[0])
        while ep < good[-1]:
            a = bisect_right(good, ep) - 1
            b = bisect_right(naive, ep) - 1
            if a != b:
                mism += 1
            ep += 311
        self.assertGreater(mism, 0, "86400 推算竟然没出错——说明这个对照没打中 DST")


if __name__ == "__main__":
    unittest.main()
