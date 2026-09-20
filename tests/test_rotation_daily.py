"""每号 × 每天在岗（用户 2026-09-21 从三个口径里选的：「优先级到底生效没」）。

## 这张表存在的理由

总览把拖拽顺序标成「轮换优先级」，而**它到底有没有被执行**在任何既有视图上都看不出来。
实测当天：排 #1/#2 的号（5530 / mou）被 `rotate_off` 挡在池外，**8 天一次都没跑过**，
而界面上它们看着是最优先的。

## 每格三态，合并任意两个都是 bug

| 值 | 含义 | 合并的后果 |
|---|---|---|
| `{secs, requests, tokens}` | 这天用了它 | —— |
| `null` | 这天**没选中它**（我们有这天的完整数据，确实是 0） | —— |
| `"unknown"` | 这天**我们没读到**（在 `covers_from` 之前） | 画成 `—` 就是拿"没看到"冒充"没用过" |

## 还有一条独立的披露：中转站

实测 2026-09-19：那天 40 次 POST 里 **39 次走了中转站**，账号池只用了 1 次。
中转站流量按设计不进泳道，所以那一整列都是 `—` —— 没有「中转站」那一行，
它会被读成「这天没用 codex」。**「没走账号池」≠「没用」。**
"""
import importlib.util
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rot_daily", ROOT / "traffic" / "rotation.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

DAY = 86400.0
HOUR = 3600.0


def _seg(acc, t0, t1, requests=10, tokens=1_000_000):
    return {"acc": acc, "start": t0, "end": t1, "requests": requests,
            "tokens": tokens, "by_model": {}, "enter_reason": "new"}


def _slots(**kw):
    """`{aid: slot}`，kw 形如 `A=dict(label="A", rotate_off=True)`。"""
    return {k: v for k, v in kw.items()}


#: 本地正午，避开任何时区把「一天」切在边界上的歧义
def _noon(days_ago):
    t = time.localtime(time.time() - days_ago * DAY)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 12, 0, 0, 0, 0, -1))


class TheDaysAreContinuousCalendarDays(unittest.TestCase):
    """★ 必须按自然日算术生成、空白天显式补上 —— 不能只列「有数据的那几天」。

    后者会让同一个窗口在不同机器/时区下天数都不一样，而图表看不出区别
    （与 `scan.py` 那条「窗口按自然日切」同源）。
    """

    def test_an_empty_middle_day_still_gets_a_column(self):
        now = time.time()
        segs = [_seg("A", _noon(4), _noon(4) + HOUR), _seg("A", _noon(1), _noon(1) + HOUR)]
        d = R._daily(segs, now - 5 * DAY, now, _slots(a=dict(label="A")), {})
        self.assertGreaterEqual(len(d["days"]), 5, f"天数不连续：{d['days']}")
        row = next(r for r in d["rows"] if r["acc"] == "A")
        self.assertEqual(len(row["cells"]), len(d["days"]),
                         "★ 格子数与天数对不上 —— 表会整体错位")
        self.assertIn(None, row["cells"], "★ 中间那些没用过的天没有显式补上")


class TheThreeCellStatesNeverCollapse(unittest.TestCase):
    """★★★ 「这天没选中它」与「这天我们没读到」必须是两个不同的值。"""

    def setUp(self):
        self.now = time.time()
        self.start = self.now - 5 * DAY
        self.segs = [_seg("A", _noon(1), _noon(1) + 2 * HOUR)]
        self.slots = _slots(a=dict(label="A"))

    def test_a_day_we_read_but_did_not_use_is_none(self):
        d = R._daily(self.segs, self.start, self.now, self.slots,
                     {"covers_from": self.start - DAY})      # 整个窗口都读到了
        cells = next(r for r in d["rows"] if r["acc"] == "A")["cells"]
        self.assertNotIn("unknown", cells,
                         "★★★ 窗口完整却报「没读到」—— 会把正常的空闲天画成告警")
        self.assertIn(None, cells)

    def test_a_day_before_what_we_read_is_unknown(self):
        d = R._daily(self.segs, self.start, self.now, self.slots,
                     {"covers_from": self.now - 2 * DAY})     # 只读到最近两天
        cells = next(r for r in d["rows"] if r["acc"] == "A")["cells"]
        self.assertIn("unknown", cells,
                      "★★★ 没读到的天被画成了「没用过」—— 拿「没看到」冒充「没有」")

    def test_a_day_that_was_used_is_a_number_even_if_early(self):
        """★★ 「没读到」只能盖住**真的没数据**的格子；读到了就该显示。"""
        segs = [_seg("A", _noon(4), _noon(4) + HOUR)]
        d = R._daily(segs, self.start, self.now, self.slots,
                     {"covers_from": self.now - 2 * DAY})
        cells = next(r for r in d["rows"] if r["acc"] == "A")["cells"]
        self.assertTrue(any(isinstance(c, dict) and c["secs"] > 0 for c in cells),
                        "★★ 有数据的格子被 unknown 盖掉了")


class ASegmentCrossingMidnightLandsOnBothDays(unittest.TestCase):
    """★★ 整段记在起始日，会让跨午夜的长段把第二天说成「没用过」。"""

    def test_the_dwell_is_split_across_the_boundary(self):
        now = time.time()
        t = time.localtime(now - 2 * DAY)
        midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0, -1))
        segs = [_seg("A", midnight - HOUR, midnight + HOUR, requests=20)]
        d = R._daily(segs, now - 5 * DAY, now, _slots(a=dict(label="A")), {})
        used = [c for c in next(r for r in d["rows"] if r["acc"] == "A")["cells"]
                if isinstance(c, dict)]
        self.assertEqual(len(used), 2, f"★★ 跨午夜的段没被切开：{used}")
        self.assertAlmostEqual(sum(c["secs"] for c in used), 2 * HOUR, delta=5)
        self.assertAlmostEqual(sum(c["requests"] for c in used), 20, delta=1,
                               msg="★ 请求数没按时长分摊 —— 两侧之和应当守恒")


class AnAccountRankedFirstButNeverUsedIsVisible(unittest.TestCase):
    """★★★ 这就是这张表要回答的那件事本身。"""

    def test_a_rotate_off_account_still_gets_a_row(self):
        now = time.time()
        d = R._daily([_seg("B", _noon(1), _noon(1) + HOUR)], now - 3 * DAY, now,
                     _slots(a=dict(label="A", rotate_off=True), b=dict(label="B")), {})
        row = next((r for r in d["rows"] if r["acc"] == "A"), None)
        self.assertIsNotNone(row, "★★★ 排第一却没跑过的号整行消失了 —— 正是要看的那一行")
        self.assertTrue(row["rotate_off"], "★★ 没标出它已停用轮换")
        self.assertTrue(all(c is None or c == "unknown" for c in row["cells"]))

    def test_rows_are_ordered_by_the_users_priority(self):
        now = time.time()
        import json
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps(
                {"slots": {}, "pick_order": ["b", "a"]}), encoding="utf-8")
            old = os.environ.get("CODEX_ROTATE_STORE")
            os.environ["CODEX_ROTATE_STORE"] = tmp
            try:
                d = R._daily([], now - 2 * DAY, now,
                             _slots(a=dict(label="A"), b=dict(label="B")), {})
            finally:
                if old is None:
                    os.environ.pop("CODEX_ROTATE_STORE", None)
                else:
                    os.environ["CODEX_ROTATE_STORE"] = old
        self.assertEqual([r["acc"] for r in d["rows"]], ["B", "A"],
                         "★★ 行序不是用户排的优先级 —— 这张表就读不出「排第几」")
        self.assertEqual([r["rank"] for r in d["rows"]], [1, 2])


class RelayTrafficIsCountedSoAnEmptyColumnIsNotMisread(unittest.TestCase):
    """★★ 实测 09-19：40 次 POST 里 39 次走中转站，账号池只用 1 次。

    没有这一行，那一整列的 `—` 会被读成「这天没用 codex」。
    """

    def test_relay_posts_are_counted_per_day(self):
        now = time.time()
        days = R._day_bounds(now - 3 * DAY, now)
        t = time.localtime(_noon(1))
        line = (f"[proxy {t.tm_mon:02d}-{t.tm_mday:02d} 12:00:00 #000abc] "
                "→ POST /responses [Huohuo@relay] relay conv=x body=y")
        hits = R._relay_by_day("\n".join([line] * 7), days, now)
        self.assertEqual(sum(hits), 7, f"★★ 中转站行没被数到：{hits}")

    def test_an_account_post_is_not_counted_as_relay(self):
        """★ 判据打在 `@relay` 标签上，不是「这行里有 relay 这个词」——
        账号行的 reason 也可能是 `relay`（历史格式），撞上就会虚报。"""
        now = time.time()
        days = R._day_bounds(now - 2 * DAY, now)
        t = time.localtime(_noon(1))
        line = (f"[proxy {t.tm_mon:02d}-{t.tm_mday:02d} 12:00:00 #000abc] "
                "→ POST /responses [Yu#03b40e2e] relay conv=x body=y")
        self.assertEqual(sum(R._relay_by_day(line, days, now)), 0,
                         "★ 账号的请求被当成中转站流量了")


class TheUiOffersTheLongerWindowsAndKeepsTheOldLabels(unittest.TestCase):
    def setUp(self):
        import re
        raw = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")
        self.code = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))

    def test_the_new_windows_exist(self):
        self.assertIn("const WINDOWS = [1, 6, 24, 168, 336, 720]", self.code,
                      "★ 14d / 30d 两档没加上")

    def test_it_stops_at_30d_because_60d_gets_truncated(self):
        """★ 实测 60d 会读满 6MB 上限并截断、约 10s —— 不是随便停的。"""
        self.assertNotIn("1440", self.code, "★ 加了 60d —— 那一档实测会被上限截断")

    def test_the_existing_24h_label_did_not_change(self):
        """★ 这轮没人让我改 `24h`；顺手改成 `1d` 是在动没被要求的东西。"""
        self.assertIn("h >= 168 ?", self.code,
                      "★ winLabel 把 24h 也改成了 Nd")


if __name__ == "__main__":
    unittest.main(verbosity=2)
