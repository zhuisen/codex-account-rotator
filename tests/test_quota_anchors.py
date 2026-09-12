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


class BilledAnchorOutranksDerivation(unittest.TestCase):
    """★★★ 「自证」优先于「推导」（2026-09-12，四方评审 #2 的修法②）。

    实测结论：一次计费探针之后，`verdict()` 还要 **897–1197s** 才肯说 `anchored`，
    这段时间 UI 对着一个**我们刚花钱启动的窗口**显示「窗口未启动」。每次探针必现。

    根因不是阈值太大，是**我们把已经知道的事实丢掉了**：探针就是那个把窗口锚定的动作，
    它手里有判定需要的全部信息，现行代码却扔掉它、再从观测里推导十几分钟。

    ★ 所以修法是加一条事实，**不是**放宽 `_slide_run` ——
      放宽它会让真正的浮动窗口被误认成锚定，方向正好是这套判据存在的理由。
      下面 `test_the_slide_judgement_itself_is_untouched` 就是钉这一点的。
    """

    SRC, KEY = "codex", "aid/300"

    def _idle_then_probe(self, sweeps=6, sweep=300, eps=3):
        """复刻真实时序：闲置漂移 → 探针**前**那次免费 GET → 计费请求锚定。
        → (账本, 探针时刻, 锚定后的 reset)"""
        a = QA.empty()
        t = T0
        for _ in range(sweeps):
            QA.record(a, self.SRC, self.KEY, t + WIN_5H, 0.0, now=t)
            t += sweep
        probe_at = t
        # ★ 这一条是整件事的枢纽：`_note_quota_anchors` 就写在 `_probe_quota` 里，
        #   所以探针前必有一条带**旧浮动 reset** 的记录，锚定后的 reset 会合并进它。
        QA.record(a, self.SRC, self.KEY, (probe_at - eps) + WIN_5H, 0.0, now=probe_at - eps)
        return a, probe_at, probe_at + WIN_5H

    def test_without_the_mark_it_still_says_floating(self):
        """★ 先证**基线是红的**。没有这一条，下一条测的可能是「它永远说 anchored」。"""
        a, p, R = self._idle_then_probe()
        QA.record(a, self.SRC, self.KEY, R, 0.0, now=p + 12)
        self.assertEqual(QA.verdict(a, self.SRC, self.KEY, R, now=p + 12)["state"],
                         "floating", "★ 基线不成立 —— 这组闸下面全部无效")

    def test_the_mark_makes_it_anchored_immediately(self):
        a, p, R = self._idle_then_probe()
        QA.mark_billed(a, self.SRC, self.KEY, R, now=p)
        QA.record(a, self.SRC, self.KEY, R, 0.0, now=p + 12)
        v = QA.verdict(a, self.SRC, self.KEY, R, now=p + 12)
        self.assertEqual(v["state"], "anchored",
                         "★★★ 刚花钱启动的窗口仍被判 floating ⇒ UI 说「未启动」")
        self.assertTrue(v["billed"], "★ 没把凭据带出来 —— 结论有了但引证没了")

    def test_the_slide_judgement_itself_is_untouched(self):
        """★★ 这条闸守的是**修法的形状**，不是它的效果。
        `slides` 必须一个都没少 —— 少了就说明有人顺手把滑动判据放宽了，
        而那会让真正的浮动窗口被认成锚定（本仓在这上面栽过一次）。"""
        a, p, R = self._idle_then_probe()
        QA.record(a, self.SRC, self.KEY, R, 0.0, now=p + 12)
        before = QA.verdict(a, self.SRC, self.KEY, R, now=p + 12)["slides"]
        QA.mark_billed(a, self.SRC, self.KEY, R, now=p)
        after = QA.verdict(a, self.SRC, self.KEY, R, now=p + 12)["slides"]
        self.assertGreaterEqual(before, QA.MIN_SLIDES, "★ 夹具没造出滑动串 —— 探针失准")
        self.assertEqual(before, after,
                         "★★ 滑动判据被改动了 —— 修法应该是**加一条事实**，不是放宽判据")

    def test_the_mark_adds_no_sample_to_the_time_axis(self):
        """★★★ 这是「只在 `/usage` 这条路径上记」那条规矩仍然成立的**全部理由**。

        那条规矩防的是**弄脏时间轴**（`first_seen`/`last_seen` 是滑动判据的坐标）。
        `mark_billed` 命中已有行时只准加 `billed_at` 一个键 —— 碰了任何一个时间轴字段，
        它就变成了一次来自另一个来源的采样，那条规矩当场被违反，而且不会有症状。
        """
        a, p, R = self._idle_then_probe()
        row = [r for r in QA.rows(a, self.SRC, self.KEY)
               if abs(r["reset"] - R) <= QA.JITTER_SECS][0]
        watched = ("first_seen", "last_seen", "n", "max_used", "reset")
        snap = {k: row.get(k) for k in watched}
        QA.mark_billed(a, self.SRC, self.KEY, R, now=p + 999)
        self.assertEqual({k: row.get(k) for k in watched}, snap,
                         "★★★ 计费标记改动了时间轴字段 ⇒ 它变成了一次采样")
        self.assertEqual(row.get("billed_at"), p + 999)

    def test_the_mark_belongs_to_one_row_not_the_whole_window_key(self):
        """★★ 标记按**行**，不按桶。两个方向都要钉，而它们不是同一件事：

        · **往回**：标记的那一刻，桶里躺着闲置期那一串旧行。按桶标会把它们一起标掉，
          于是那些**确实在漂**的窗口集体自称已锚定 —— 这是真正危险的方向。
        · **往后**：窗口走完之后的新窗口是新的一行，不继承标记。

        ⚠️ 这条闸第一版**只写了往后那半**，于是「按桶标记」这个变异照样绿
        （新行是在标记之后才建的，当然没被标到）。变异工具当场拦下了它。
        一条只覆盖单向的闸，在它没覆盖的那一向上等于不存在。
        """
        a, p, R = self._idle_then_probe()
        older = QA.rows(a, self.SRC, self.KEY)[0]["reset"]
        self.assertLess(older, R - QA.JITTER_SECS, "★ 夹具里没有更早的行 —— 探针失准")
        QA.mark_billed(a, self.SRC, self.KEY, R, now=p)
        self.assertFalse(QA.verdict(a, self.SRC, self.KEY, older, now=p)["billed"],
                         "★★★ 闲置期的旧行也被标了 ⇒ 一串确实在漂的窗口集体自称已锚定")
        nxt = R + WIN_5H                      # 下一个窗口，闲置
        QA.record(a, self.SRC, self.KEY, nxt, 0.0, now=R + 10)
        self.assertFalse(QA.verdict(a, self.SRC, self.KEY, nxt, now=R + 10)["billed"],
                         "★★ 新窗口继承了上一个窗口的计费标记 ⇒ 此后永远自称已锚定")

    def test_a_reset_never_seen_before_gets_its_own_row(self):
        """★ 探针前那次免费 GET 失败时（或间隔超过容差），没有行可以命中 ——
        必须新开一行，而不是静默什么都不做。`n=0` 诚实标注「还没有采样落在它上面」。"""
        a = QA.empty()
        self.assertTrue(QA.mark_billed(a, self.SRC, self.KEY, T0 + WIN_5H, now=T0))
        rs = QA.rows(a, self.SRC, self.KEY)
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["n"], 0, "★ 假装有过采样 —— 那是编一个我们没有的观测")
        self.assertEqual(QA.verdict(a, self.SRC, self.KEY, T0 + WIN_5H, now=T0)["state"],
                         "anchored")

    def test_note_billed_is_fail_open_and_keeps_the_shape(self):
        """★ 与 `note()` 同一条护栏：账本不可写时也不抛，且返回同一个形状。"""
        v = QA.note_billed(self.SRC, self.KEY, T0 + WIN_5H, now=T0,
                           path="/nonexistent-dir-xyz/ledger.json")
        self.assertIn("state", v)
        self.assertIn("billed", v)
