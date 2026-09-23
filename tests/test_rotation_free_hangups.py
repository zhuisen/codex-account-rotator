"""免费请求的断连不是「计费断流」—— 代理轮换页的「断流」只数真正可能花了钱的那种。

## 起因（2026-09-23，用户：「为什么一直 200 断流？我明明没用啊」）

一个开着但闲置的 codex 0.156.0 窗口，每 270s 在后台 `GET /models` 刷新一次模型列表；
codex 给这件事的预算是 5 秒，上游首字节就要 ~2s、明文 522 KB 常常传不完 ⇒ codex 自己挂断 ⇒
代理往已关闭的 socket 上写，记一行 `stream err [...]: [Errno 32] Broken pipe`。
当天一个闲置窗口刷出 **80 个**，6h 窗口里页面显示「断流 60 / 请求 0」，
每条事件都写着「已 200 后断流,**已计费**」—— 而 `GET /models` 根本不计费。

★ 这是「同一条规则两处实现不一致」：代理自己早就按 `_billable()`（不是 GET/HEAD 才算）
  过滤了计费断流计数，而 `traffic/rotation.py` 看到 `stream err` 一律当计费。

## 判据

① 回归：用当天日志的**原样行**，GET 断连不进 markers，POST 断连照进。
② 边界：请求行在时间窗之前、断流行在窗内 —— 仍认得出是 GET。
③ rid 会复用（线程号 mod 4096 + 毫秒 mod 4096）⇒ 按行序取「最近一次」。
④ 认不出方法 ⇒ **仍按计费算**（读不到 ≠ 免费）。
⑤ 不变量：`rotation.billable_method` 与 `proxy.Handler._billable` 逐方法同答。
"""
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("rot_free_hangups", ROOT / "traffic" / "rotation.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

NOW = time.time()


def log(mins_ago, body, rid=None):
    ts = time.localtime(NOW - mins_ago * 60)
    tag = " #{}".format(rid) if rid else ""
    return "[proxy {}{}] {}".format(time.strftime("%m-%d %H:%M:%S", ts), tag, body)


def markers(text, window_mins=60):
    _r, _o, m, _l, _u, _w = R.scan_proxy_log(text, NOW, NOW - window_mins * 60, NOW)
    return m


def log_lines(text, window_mins=60):
    _r, _o, _m, lines, _u, _w = R.scan_proxy_log(text, NOW, NOW - window_mins * 60, NOW)
    return lines


# 2026-09-23 18:51 的原样三行（只换了时间）—— 闲置 codex 0.156.0 的后台模型刷新。
IDLE_REFRESH = [
    (30.00, "→ GET /models?client_version=0.156.0 [Huo#b42e395c] new conv=- body=-", "00052b"),
    (29.95, "← 200 [Huo#b42e395c]", "00052b"),
    (29.92, "stream err [Huo#b42e395c]: [Errno 32] Broken pipe", "00052b"),
]
# 同一天 09:39 那次真正的计费断流（POST）。
BILLED_BREAK = [
    (20.00, "→ POST /responses [Asen#10da0584] conv conv=01a029d3-b41 body=abc123", "0a1b2c"),
    (19.95, "← 200 [Asen#10da0584]", "0a1b2c"),
    (19.40, "stream err [Asen#10da0584]: [Errno 32] Broken pipe", "0a1b2c"),
]


def lines(rows):
    return "\n".join(log(m, b, r) for (m, b, r) in rows)


class AFreeHangupIsNotABilledStreamBreak(unittest.TestCase):
    def test_the_idle_model_refresh_leaves_no_marker(self):
        """★★★ 回归：当天的原样行。GET 断连不进泳道/KPI/事件。"""
        self.assertEqual([], markers(lines(IDLE_REFRESH)))

    def test_a_billed_break_is_still_a_marker(self):
        """★★ 反向：真正的 POST 断流**必须**还在 —— 修成「一律不数」就是把真账藏起来。"""
        m = markers(lines(BILLED_BREAK))
        self.assertEqual([k for (_t, _a, k) in m], ["stream_err"])

    def test_mixed_counts_only_the_billed_one(self):
        m = markers(lines(IDLE_REFRESH * 1 + BILLED_BREAK))
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0][1], "Asen")

    def test_the_raw_log_still_shows_the_line(self):
        """原始日志照实显示 —— 那是原文，藏掉它是另一个方向的说谎。"""
        self.assertTrue(any(b.startswith("stream err") for (_t, b) in log_lines(lines(IDLE_REFRESH))))

    def test_no_event_text_claims_it_was_billed(self):
        evs = R._events([], markers(lines(IDLE_REFRESH)))
        self.assertFalse(any("已计费" in e["text"] for e in evs))


class TheMethodLookupHoldsAtTheEdges(unittest.TestCase):
    def test_request_line_before_the_window_still_counts(self):
        """★★ 请求行落在时间窗**之前**、断流行在窗内 —— 方法必须在窗口过滤之前就记下。"""
        text = "\n".join([
            log(10.05, "→ GET /models?client_version=0.156.0 [Huo#b42e395c] new conv=- body=-", "00abcd"),
            log(9.95, "stream err [Huo#b42e395c]: [Errno 32] Broken pipe", "00abcd"),
        ])
        self.assertEqual([], markers(text, window_mins=10))

    def test_a_reused_rid_takes_the_latest_request(self):
        """★ rid 会复用：同一个 rid 先是 GET、后是 POST，断流属于后者。"""
        text = "\n".join([
            log(40, "→ GET /models [Huo#b42e395c] new conv=- body=-", "000aaa"),
            log(39.9, "← 200 [Huo#b42e395c]", "000aaa"),
            log(20, "→ POST /responses [Yu#03b40e2e] conv conv=x body=y", "000aaa"),
            log(19, "stream err [Yu#03b40e2e]: IncompleteRead(32 bytes read)", "000aaa"),
        ])
        self.assertEqual([a for (_t, a, _k) in markers(text)], ["Yu"])

    def test_and_the_other_way_round(self):
        text = "\n".join([
            log(40, "→ POST /responses [Yu#03b40e2e] conv conv=x body=y", "000bbb"),
            log(20, "→ GET /models [Huo#b42e395c] new conv=- body=-", "000bbb"),
            log(19.9, "stream err [Huo#b42e395c]: [Errno 32] Broken pipe", "000bbb"),
        ])
        self.assertEqual([], markers(text))

    def test_an_unknown_method_is_counted_as_billed(self):
        """★★ 读不到 ≠ 免费：请求行不在截取范围里时，宁可多报不可漏报。"""
        text = log(5, "stream err [Yu#03b40e2e]: [Errno 32] Broken pipe", "0fffff")
        self.assertEqual([k for (_t, _a, k) in markers(text)], ["stream_err"])

    def test_head_is_free_too(self):
        text = "\n".join([log(5, "→ HEAD /models [Huo#b42e395c] new conv=- body=-", "0ccccc"),
                          log(4.9, "stream err [Huo#b42e395c]: [Errno 32] Broken pipe", "0ccccc")])
        self.assertEqual([], markers(text))


class TheTwoBillingRulesAgree(unittest.TestCase):
    """★★★ 不变量：「这次失败会不会花钱」全仓只有一条判据，两处实现必须逐方法同答。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("proxy_billable_agree", ROOT / "proxy" / "proxy.py")
        cls.px = importlib.util.module_from_spec(spec)
        sys.modules["proxy_billable_agree"] = cls.px
        spec.loader.exec_module(cls.px)

    def test_every_method_gets_the_same_answer(self):
        for m in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=m):
                proxy_says = self.px.Handler._billable(types.SimpleNamespace(command=m))
                self.assertEqual(R.billable_method(m), proxy_says,
                                 f"★★★ {m}: rotation 与 proxy 对「会不会计费」答案不同")


if __name__ == "__main__":
    unittest.main(verbosity=2)
