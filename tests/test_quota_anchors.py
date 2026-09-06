"""锚点账本的不变量(2026-09-06)。

## 它要挡的东西

`resetAnchorUnknown` 是**单样本点估计**,它结构性地分不出「闲置浮动」和「刚锚定」——
两者的 `resets_at − captured_at` 都等于整窗。账本用**时间序列**补上那个信息:
浮动的 reset 每轮跟着 `now` 挪,锚定的一动不动。

## 最要命的那条

★★ **合并锚点时更新 `row["reset"]` 会把要抓的东西认证成它的反面。**
采样间隔小于容差时(quotad 的活动驱动路径最快 20s 一次,容差 60s),
一个每轮滑 20s 的浮动 reset 会**永远落在容差内**;若每次合并都把行里的 reset 跟着改掉,
这一行就再也不会分裂,`last_seen − first_seen` 一路涨到超过 `HOLD_SECS`,
于是**闲置窗口被判成「锚点已确认」**——正好是这本账存在的理由的反面,而且它看上去完全正常。

`test_floating_window_polled_faster_than_jitter_is_never_anchored` 就是这条的变异闸。
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "quota_anchors", ROOT / "traffic" / "quota_anchors.py")
QA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(QA)

T0 = 1_800_000_000.0
WIN_5H = 300 * 60


class AnchorIdentity(unittest.TestCase):
    """同一个窗口的多次读数必须并成一条,不同窗口必须分开。"""

    def test_same_reset_within_jitter_merges(self):
        a = QA.empty()
        QA.record(a, "codex", "acct/300", 5000, 10, T0)
        QA.record(a, "codex", "acct/300", 5000 + QA.JITTER_SECS - 1, 12, T0 + 300)
        rows = QA.rows(a, "codex", "acct/300")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["n"], 2)

    def test_reset_beyond_jitter_opens_a_new_row(self):
        a = QA.empty()
        QA.record(a, "codex", "acct/300", 5000, 0, T0)
        QA.record(a, "codex", "acct/300", 5000 + QA.JITTER_SECS + 1, 0, T0 + 300)
        self.assertEqual(len(QA.rows(a, "codex", "acct/300")), 2)

    def test_merge_never_rewrites_the_row_reset(self):
        """★★ 见模块头。行的 `reset` 是**第一次见到的值**,后来的读数只能相对它判断。"""
        a = QA.empty()
        QA.record(a, "codex", "acct/300", 5000, 0, T0)
        QA.record(a, "codex", "acct/300", 5050, 0, T0 + 50)
        self.assertEqual(QA.rows(a, "codex", "acct/300")[0]["reset"], 5000,
                         "合并把行的 reset 改成了新值 —— 浮动窗口会因此永远不分裂")

    def test_sources_do_not_collide(self):
        a = QA.empty()
        QA.record(a, "codex", "w", 5000, 10, T0)
        QA.record(a, "grok", "w", 5000, 90, T0)
        self.assertEqual(QA.rows(a, "codex", "w")[0]["max_used"], 10)
        self.assertEqual(QA.rows(a, "grok", "w")[0]["max_used"], 90)


class PeakHold(unittest.TestCase):
    """★ 已用百分比在一个周期内只涨不跌。服务端只回整数,而滚动窗口下水位会回升 ——
    取最大值才能回答「这个周期最多烧到过多少」。"""

    def test_max_used_never_drops(self):
        a = QA.empty()
        QA.record(a, "codex", "k", 5000, 40, T0)
        QA.record(a, "codex", "k", 5000, 12, T0 + 300)
        self.assertEqual(QA.rows(a, "codex", "k")[0]["max_used"], 40)

    def test_later_reading_raises_the_peak(self):
        a = QA.empty()
        QA.record(a, "codex", "k", 5000, 12, T0)
        QA.record(a, "codex", "k", 5000, 40, T0 + 300)
        self.assertEqual(QA.rows(a, "codex", "k")[0]["max_used"], 40)


class Verdict(unittest.TestCase):
    def test_first_reading_is_unknown_not_a_denial(self):
        """★ 三态。一次读数推不出任何结论,而把它讲成 floating 就是拿"还没看够"冒充"确定没启动"。"""
        a = QA.empty()
        QA.record(a, "codex", "k", 5000, 0, T0)
        self.assertEqual(QA.verdict(a, "codex", "k", 5000, T0)["state"], "unknown")

    def test_reset_that_holds_still_is_anchored(self):
        a = QA.empty()
        reset = int(T0 + WIN_5H)
        for i in range(0, int(QA.HOLD_SECS) + 300, 300):
            QA.record(a, "codex", "k", reset, 7, T0 + i)
        v = QA.verdict(a, "codex", "k", reset, T0 + QA.HOLD_SECS + 300)
        self.assertEqual(v["state"], "anchored")
        self.assertGreaterEqual(v["held_secs"], QA.HOLD_SECS)

    def test_reset_sliding_with_now_is_floating(self):
        """闲置窗口:服务端每轮回「此刻 + 整窗」,所以 Δreset == Δt。"""
        a = QA.empty()
        last = 0
        for i in range(0, 4):
            t = T0 + i * 300
            last = int(t + WIN_5H)
            QA.record(a, "codex", "k", last, 0, t)
        v = QA.verdict(a, "codex", "k", last, T0 + 900)
        self.assertEqual(v["state"], "floating")
        self.assertGreaterEqual(v["slides"], QA.MIN_SLIDES)

    def test_floating_window_polled_faster_than_jitter_is_never_anchored(self):
        """★★ **这条是整个模块的守门员。**

        quotad 的活动驱动路径最快 20s 一次(`MIN_GAP_SECS`),比容差(60s)还密。
        若合并时跟着改行里的 reset,这一行就永不分裂,一小时后 `held_secs` 会涨到 3600
        ⇒ 闲置窗口被判 `anchored`。断言直接钉死这个结果。
        """
        a = QA.empty()
        last = 0
        for i in range(0, 3600, 20):
            t = T0 + i
            last = int(t + WIN_5H)
            QA.record(a, "codex", "k", last, 0, t)
        v = QA.verdict(a, "codex", "k", last, T0 + 3600)
        self.assertNotEqual(v["state"], "anchored",
                            "浮动窗口被判成锚点已确认 —— 合并逻辑改写了行的 reset")
        self.assertEqual(v["state"], "floating")

    def test_anchoring_after_a_drift_run_stops_reporting_floating(self):
        """★ 闲置一段时间之后**真的开始用了**:此后 reset 不再动,判定必须跟着翻过来,
        不能被前面那串漂移一直拖着报 floating。"""
        a = QA.empty()
        for i in range(0, 4):
            t = T0 + i * 300
            QA.record(a, "codex", "k", int(t + WIN_5H), 0, t)
        anchored_at = T0 + 1200
        reset = int(anchored_at + WIN_5H)
        for i in range(0, int(QA.HOLD_SECS) + 300, 300):
            QA.record(a, "codex", "k", reset, 9, anchored_at + i)
        v = QA.verdict(a, "codex", "k", reset, anchored_at + QA.HOLD_SECS + 300)
        self.assertEqual(v["state"], "anchored")

    def test_unknown_reset_does_not_borrow_another_rows_history(self):
        a = QA.empty()
        for i in range(0, int(QA.HOLD_SECS) + 300, 300):
            QA.record(a, "codex", "k", 5000, 7, T0 + i)
        v = QA.verdict(a, "codex", "k", 999_000, T0 + QA.HOLD_SECS)
        self.assertEqual(v["held_secs"], 0)
        self.assertEqual(v["samples"], 0)


class Trimming(unittest.TestCase):
    def test_rows_are_capped_and_the_newest_survive(self):
        """浮动窗口每轮开一行 —— 没有上限它会无限增长。裁掉的必须是**最旧**的。"""
        a = QA.empty()
        for i in range(QA.MAX_ROWS + 30):
            QA.record(a, "codex", "k", 10_000 + i * 1000, 0, T0 + i * 1000)
        rows = QA.rows(a, "codex", "k")
        self.assertEqual(len(rows), QA.MAX_ROWS)
        self.assertEqual(rows[-1]["reset"], 10_000 + (QA.MAX_ROWS + 29) * 1000)


class Cycles(unittest.TestCase):
    def test_spans_are_positive_and_only_the_last_can_be_current(self):
        a = QA.empty()
        for i in range(3):
            t = T0 + i * WIN_5H
            QA.record(a, "codex", "k", int(t + WIN_5H), 30, t)
        cy = QA.cycles(a, "codex", "k", WIN_5H, now=T0 + WIN_5H * 2.5)
        for c in cy:
            self.assertGreater(c["end"], c["start"])
        self.assertLessEqual(sum(1 for c in cy if c["current"]), 1)

    def test_idle_drift_does_not_manufacture_a_history(self):
        """★ 闲置漂移会攒出一串锚点,但那不是一串真周期。没有 confirmed 的只留最新一条。"""
        a = QA.empty()
        for i in range(6):
            t = T0 + i * 300
            QA.record(a, "codex", "k", int(t + WIN_5H), 0, t)
        self.assertEqual(len(QA.cycles(a, "codex", "k", WIN_5H, now=T0 + 1800)), 1)


class FailOpen(unittest.TestCase):
    """★★ 纯附加的次要功能**绝不能有能力搞挂主路径**(2026-09-05 事故)。"""

    def test_load_of_garbage_returns_empty_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.json"
            p.write_text("{not json at all", encoding="utf-8")
            self.assertEqual(QA.load(str(p)), QA.empty())

    def test_load_of_wrong_schema_version_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.json"
            p.write_text(json.dumps({"v": QA.SCHEMA_V + 1, "sources": {"codex": {}}}),
                         encoding="utf-8")
            self.assertEqual(QA.load(str(p)), QA.empty())

    def test_missing_file_returns_empty(self):
        self.assertEqual(QA.load("/nonexistent/dir/anchors.json"), QA.empty())

    def test_note_on_an_unwritable_path_still_returns_a_verdict_shape(self):
        v = QA.note("codex", "k", 5000, 3, now=T0, path="/nonexistent/dir/anchors.json")
        for field in ("state", "held_secs", "samples", "slides", "used_max"):
            self.assertIn(field, v)
        self.assertEqual(v["state"], "unknown")

    def test_note_round_trips_through_a_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = str(Path(tmp) / "a.json")
            reset = int(T0 + WIN_5H)
            for i in range(0, int(QA.HOLD_SECS) + 300, 300):
                v = QA.note("codex", "k", reset, 7, now=T0 + i, path=p)
            self.assertEqual(v["state"], "anchored")
            self.assertFalse([f for f in os.listdir(tmp) if ".tmp" in f],
                             "临时文件没清理干净")

    def test_bad_reset_is_dropped_not_recorded_as_zero(self):
        """`reset=None/0` 是「没有重置时间」,记成 0 会造出一个 1970 年的周期。"""
        a = QA.empty()
        for bad in (None, 0, -1, "nope"):
            self.assertFalse(QA.record(a, "codex", "k", bad, 5, T0))
        self.assertEqual(QA.rows(a, "codex", "k"), [])


class NoImportTimeSideEffects(unittest.TestCase):
    """★ 纯核:import 不许读环境变量、不许碰盘。否则测试换不了目录,
    而「按路径 import」这条本仓允许的做法就会带上副作用。"""

    def test_default_path_follows_the_env_at_call_time(self):
        # ★ 必须先摘掉测试隔离口(`tests/test_isolation_bootstrap.py` 设的),
        #   否则这里验的是那个 override 而不是 `CODEX_ROTATE_STORE` 的回退链。
        saved = {k: os.environ.get(k)
                 for k in ("CODEX_ROTATE_STORE", "CODEXBAR_QUOTA_ANCHORS")}
        try:
            os.environ.pop("CODEXBAR_QUOTA_ANCHORS", None)
            os.environ["CODEX_ROTATE_STORE"] = "/tmp/codexbar-anchor-probe"
            self.assertTrue(QA.default_path().startswith("/tmp/codexbar-anchor-probe"))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_isolation_override_wins_over_the_store(self):
        """★ 优先级必须是 override > store。反过来的话,测试隔离口在
        `CODEX_ROTATE_STORE` 也被设置时就失效 —— 而那恰恰是 app 起子进程的常态。"""
        saved = {k: os.environ.get(k)
                 for k in ("CODEX_ROTATE_STORE", "CODEXBAR_QUOTA_ANCHORS")}
        try:
            os.environ["CODEX_ROTATE_STORE"] = "/tmp/codexbar-store-x"
            os.environ["CODEXBAR_QUOTA_ANCHORS"] = "/tmp/codexbar-override-y.json"
            self.assertEqual(QA.default_path(), "/tmp/codexbar-override-y.json")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_module_source_has_no_toplevel_io(self):
        src = (ROOT / "traffic" / "quota_anchors.py").read_text(encoding="utf-8")
        head = src.split("def default_path")[0]
        for bad in ("os.environ.get(", "open(", "Path.home()"):
            self.assertNotIn(bad, head.split('"""')[-1],
                             "模块顶层出现了 %s —— import 就有副作用" % bad)


if __name__ == "__main__":
    unittest.main()
