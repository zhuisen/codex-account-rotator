"""`traffic/agy_quota_series.py` 的差分口径闸。

这个模块把**水位**样本差分成**消耗**,而差分是全项目最容易"凭空造出数字"的一类计算。

★★ **模型换过一次,是被真机数据推翻的**(2026-09-05)。原来假设「固定窗口 + 到点重置」,
   实测却看到 `remaining` 在 `resetTime` 完全没变的情况下**上涨**两次(+0.13% / +0.80%)——
   agy 是**滚动窗口**,旧消耗会随时间老化退出。于是三条旧规则被删:
     · 「上升 = 异常」—— 它在真机 5 个样本里就误报了 2 次,而那 2 次都是正常恢复;
     · 「跨重置 = 把旧窗口剩余算进消耗」—— 那本来就是凭空造数;
     · 整套 reset 分类(v1 看 reset 变没变 / v2 看额度变多没 / v3 看 Δreset≈Δt)——
       换模型后**根本不需要**分类,只累加下降即可,而且这样在
       「滚动窗口」和「服务端回补」两种假说下都成立。

下面的断言守的是换模型之后**仍然必须成立**的三件事:
  ① 消耗只能来自相邻两点的下降,绝不凭一个读数造数;
  ② 上升不得计入消耗(它进 `recovered_pct`,不与消耗相抵);
  ③ 采样越稀漏得越多 ⇒ 必须标下界。**它是水位计,不是流量计。**
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "agy_quota_series", ROOT / "traffic" / "agy_quota_series.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

T0 = 1788600000
RESET_A = 1789000000
RESET_B = 1789018000


def smp(ts, rem, reset=RESET_A, bid="gemini-5h", win="5h", grp="Gemini Models"):
    return {"ts": ts, "buckets": [
        {"id": bid, "group": grp, "window": win, "rem": rem, "reset": reset}]}


class SameWindowDelta(unittest.TestCase):
    def test_plain_consumption(self):
        r = S.derive([smp(T0, 99.0), smp(T0 + 60, 98.0)])["gemini-5h"]
        self.assertAlmostEqual(r["consumed_pct"], 1.0, places=4)
        self.assertEqual(len(r["spans"]), 1)
        self.assertFalse(r["lower_bound"])

    def test_accumulates_across_many_samples(self):
        pts = [smp(T0 + i * 60, 100.0 - i) for i in range(5)]
        self.assertAlmostEqual(S.derive(pts)["gemini-5h"]["consumed_pct"], 4.0, places=4)

    def test_heartbeat_sample_is_not_consumption(self):
        """静默期心跳:水位没动 ⇒ 不产生 span。心跳存在是为了区分"没动"和"没在看"。"""
        r = S.derive([smp(T0, 99.0), smp(T0 + 1800, 99.0)])
        self.assertEqual(r.get("gemini-5h", {}).get("spans", []), [])

    def test_noise_below_threshold_ignored(self):
        r = S.derive([smp(T0, 99.0), smp(T0 + 60, 98.999)])
        self.assertEqual(r.get("gemini-5h", {}).get("spans", []), [])


class OnlyDropsAreConsumption(unittest.TestCase):
    """★★ 只有下降算消耗;上升是恢复。"""

    def test_rise_is_not_consumption(self):
        r = S.derive([smp(T0, 90.0), smp(T0 + 60, 95.0)])["gemini-5h"]
        self.assertEqual(r["consumed_pct"], 0.0, "上升被算成了消耗")
        self.assertAlmostEqual(r["recovered_pct"], 5.0, places=4)
        self.assertEqual(r["spans"], [])

    def test_rise_is_not_an_anomaly(self):
        """★ 守的是**别改回去**:上升在滚动窗口下是常态,报成异常会天天误报。

        真机实证:第一版把它当异常,5 个样本里误报 2 次(+0.13% / +0.80%),
        而那两次都是正常的额度老化恢复。
        """
        r = S.derive([smp(T0, 90.0), smp(T0 + 60, 95.0)])["gemini-5h"]
        self.assertEqual(r["anomalies"], [], "上升又被当成异常了 —— 会在真机上天天误报")

    def test_consumption_never_exceeds_observed_drops(self):
        """★★ 防「凭空造数」的总闸:消耗总额 = 所有下降之和,一分不多。

        历史上真出现过的错法是跨重置时把 `prev.rem` 也算进来 ——
        一个剩 98% 的窗口会被记成"消耗了 98%"。
        """
        pts = [smp(T0, 98.0), smp(T0 + 60, 97.0), smp(T0 + 120, 99.5), smp(T0 + 180, 99.0)]
        r = S.derive(pts)["gemini-5h"]
        self.assertAlmostEqual(r["consumed_pct"], 1.0 + 0.5, places=4)
        self.assertLess(r["consumed_pct"], 98.0, "把旧窗口剩余算进消耗了 —— 凭空造数")

    def test_recovery_does_not_offset_consumption(self):
        """恢复不与消耗相抵 —— 两者是不同的量,混算会让"用了多少"凭空变小。"""
        pts = [smp(T0, 100.0), smp(T0 + 60, 90.0), smp(T0 + 120, 100.0)]
        r = S.derive(pts)["gemini-5h"]
        self.assertAlmostEqual(r["consumed_pct"], 10.0, places=4)
        self.assertAlmostEqual(r["recovered_pct"], 10.0, places=4)

    def test_reset_change_alone_creates_nothing(self):
        """★ reset 变了但水位没动 ⇒ 零消耗。旧模型会在这里造出一整段消耗。"""
        r = S.derive([smp(T0, 98.0, RESET_A), smp(T0 + 60, 98.0, RESET_B)])
        self.assertEqual(r.get("gemini-5h", {}).get("consumed_pct", 0.0), 0.0)


class IdleBucketResetSlides(unittest.TestCase):
    """★★ 实测:**没被使用过的桶,`reset` 跟着 now 滑动**(2026-09-05 真机数据)。

    新模型下这天然不成问题(只看水位差)。这组是**回归闸** —— 防止有人再把 reset
    拿回来当分类依据:那样闲置桶会每次采样都被判成重置。
    """
    S1 = {"ts": 1788542900, "buckets": [
        {"id": "3p-5h", "group": "Claude and GPT models", "window": "5h",
         "rem": 100.0, "reset": 1788561498}]}
    S2 = {"ts": 1788543111, "buckets": [
        {"id": "3p-5h", "group": "Claude and GPT models", "window": "5h",
         "rem": 100.0, "reset": 1788561711}]}

    def test_sliding_reset_on_untouched_bucket_produces_nothing(self):
        r = S.derive([self.S1, self.S2]).get("3p-5h", {})
        self.assertEqual(r.get("consumed_pct", 0.0), 0.0)
        self.assertEqual(r.get("spans", []), [])
        self.assertFalse(r.get("lower_bound", False),
                         "闲置桶被标成下界 —— 精确的 0 被伪装成不确定")

    def test_large_replenishment_is_recovery_not_consumption(self):
        """额度大幅回升 = 恢复,**不得**产生任何消耗。旧模型正是在这里造数的。"""
        lo = {"ts": 1788542900, "buckets": [
            {"id": "gemini-5h", "window": "5h", "rem": 20.0, "reset": 1788561498}]}
        hi = {"ts": 1788543111, "buckets": [
            {"id": "gemini-5h", "window": "5h", "rem": 95.0, "reset": 1788579498}]}
        r = S.derive([lo, hi])["gemini-5h"]
        self.assertEqual(r["consumed_pct"], 0.0, "回升被算成了消耗")
        self.assertAlmostEqual(r["recovered_pct"], 75.0, places=4)

    def test_first_use_is_plain_consumption(self):
        """100% 的桶第一次被用:下降就是消耗,与 reset 怎么动无关。"""
        a = {"ts": 1788542900, "buckets": [
            {"id": "gemini-5h", "window": "5h", "rem": 100.0, "reset": 1788561498}]}
        b = {"ts": 1788543111, "buckets": [
            {"id": "gemini-5h", "window": "5h", "rem": 98.9, "reset": 1788561600}]}
        r = S.derive([a, b])["gemini-5h"]
        self.assertAlmostEqual(r["consumed_pct"], 1.1, places=4)


class SparseSamplingIsALowerBound(unittest.TestCase):
    """★★ 它是水位计不是流量计:采样越稀,漏掉的消耗越多,且永远补不回来。"""

    def test_gap_longer_than_half_the_window_marks_lower_bound(self):
        gap = int(5 * 3600 * S.GAP_LOWER_BOUND_RATIO) + 60
        r = S.derive([smp(T0, 99.0), smp(T0 + gap, 98.0)])["gemini-5h"]
        self.assertTrue(r["lower_bound"],
                        "间隔超过半个窗口却没标下界 —— 中间的消耗可能已经老化掉了")

    def test_dense_sampling_is_not_a_lower_bound(self):
        r = S.derive([smp(T0, 99.0), smp(T0 + 60, 98.0)])["gemini-5h"]
        self.assertFalse(r["lower_bound"], "密集采样被误标成下界,会把准确值说成不准确")

    def test_weekly_window_uses_its_own_length(self):
        """周窗口的阈值是 3.5 天而不是 2.5 小时 —— 用错窗口长度会让周桶几乎恒标下界。"""
        r = S.derive([smp(T0, 99.0, bid="gemini-weekly", win="weekly"),
                      smp(T0 + 6 * 3600, 98.0, bid="gemini-weekly", win="weekly")])["gemini-weekly"]
        self.assertFalse(r["lower_bound"], "6 小时对周窗口来说很密集,不该标下界")


class NoObservationIsNotZero(unittest.TestCase):
    def test_bucket_absent_from_previous_sample_is_skipped(self):
        a = {"ts": T0, "buckets": [{"id": "x", "rem": 50.0, "reset": RESET_A}]}
        b = {"ts": T0 + 60, "buckets": [
            {"id": "x", "rem": 49.0, "reset": RESET_A},
            {"id": "y", "rem": 10.0, "reset": RESET_A}]}
        r = S.derive([a, b])
        self.assertIn("x", r)
        self.assertNotIn("y", r, "新出现的桶没有前一点,不能凭一个读数造出消耗")

    def test_single_sample_yields_nothing(self):
        self.assertEqual(S.derive([smp(T0, 99.0)]), {})

    def test_empty_input(self):
        self.assertEqual(S.derive([]), {})
        self.assertIsNone(S.coverage([]))


class DailySplit(unittest.TestCase):
    def test_total_is_conserved_across_midnight(self):
        """跨天摊分必须总量守恒 —— 否则图上的和对不上卡上的数。"""
        import datetime
        mid = int(datetime.datetime(2026, 9, 5, 0, 0, 0).timestamp())
        pts = [smp(mid - 3600, 100.0), smp(mid + 3600, 90.0)]
        d = S.daily(pts)
        self.assertAlmostEqual(sum(v["gemini-5h"] for v in d.values()), 10.0, places=2)
        self.assertEqual(len(d), 2, "跨午夜的区间应落在两天上")
        for v in d.values():
            self.assertAlmostEqual(v["gemini-5h"], 5.0, places=1)

    def test_same_day_is_not_split(self):
        self.assertEqual(len(S.daily([smp(T0, 99.0), smp(T0 + 60, 98.0)])), 1)


class Coverage(unittest.TestCase):
    def test_reports_window_of_observation(self):
        c = S.coverage([smp(T0, 99.0), smp(T0 + 600, 98.0)])
        self.assertEqual((c["first"], c["last"], c["n"]), (T0, T0 + 600, 2))


class ReadSamples(unittest.TestCase):
    def test_bad_lines_are_skipped_not_fatal(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join([json.dumps(smp(T0, 99.0)), "{ not json", "",
                                    json.dumps(smp(T0 + 60, 98.0))]), encoding="utf-8")
            self.assertEqual(len(S.read_samples(p)), 2, "坏行应跳过而不是毒死整个读取")

    def test_missing_file_returns_empty(self):
        self.assertEqual(S.read_samples(Path("/nonexistent/nope.jsonl")), [])

    def test_sorted_by_ts(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join([json.dumps(smp(T0 + 60, 98.0)),
                                    json.dumps(smp(T0, 99.0))]), encoding="utf-8")
            got = S.read_samples(p)
        self.assertEqual([g["ts"] for g in got], [T0, T0 + 60])
        self.assertGreater(S.derive(got)["gemini-5h"]["consumed_pct"], 0,
                           "乱序写入应得出正的消耗,而不是负的")


if __name__ == "__main__":
    unittest.main()
