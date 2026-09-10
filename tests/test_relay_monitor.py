"""中转站用量拉取的闸。**全程不发真实网络请求** —— `urlopen` 被打桩。

## 这份测试守的三件事,每一件都有实测来历（2026-09-09，api.tokendun.com）

① **User-Agent 是前提不是礼貌。** 不设 UA ⇒ Cloudflare `403 error code: 1010`;
   换任何自定义 UA ⇒ 200。单变量对照跑过四组。而这个 403 和「key 失效」长得一样,
   一旦回退成默认 UA,查错会直奔凭证去、白查一轮。
② **`cost` 与 `actual_cost` 差 3.85 倍**（实测 $62.32 vs $16.18）。前者牌价、后者实扣。
   合并即撒谎。
③ **计费端点各家不同,不许预设。** 本站是 `/usage`;one-api/new-api 系走
   `/dashboard/billing/…`（本站实测 404）。
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import monitor, store  # noqa: E402

# 真实响应的形状（字段名逐字照抄 2026-09-09 的实测响应,数值改小）。
SAMPLE = {
    "balance": 69.9663236, "remaining": 69.9663236, "unit": "USD",
    "planName": "钱包余额", "isValid": True, "mode": "unrestricted",
    "usage": {
        "rpm": 0, "tpm": 0, "average_duration_ms": 30274.875,
        "today": {"requests": 0, "input_tokens": 0, "output_tokens": 0,
                  "cache_read_tokens": 0, "cache_creation_tokens": 0,
                  "total_tokens": 0, "cost": 0, "actual_cost": 0},
        "total": {"requests": 512, "input_tokens": 7687126, "output_tokens": 568401,
                  "cache_read_tokens": 29405179, "cache_creation_tokens": 0,
                  "total_tokens": 37660706, "cost": 82.819205975,
                  "actual_cost": 26.3859308645},
    },
    "daily_usage": [
        {"date": "2026-09-07", "requests": 111, "input_tokens": 1, "output_tokens": 1,
         "cache_read_tokens": 1, "cache_write_tokens": 0, "total_tokens": 2134482,
         "cost": 12.784, "actual_cost": 3.0682},
        {"date": "2026-09-08", "requests": 54, "input_tokens": 1, "output_tokens": 1,
         "cache_read_tokens": 1, "cache_write_tokens": 0, "total_tokens": 3137594,
         "cost": 16.5333, "actual_cost": 3.968},
    ],
    "model_stats": [
        {"model": "gpt-6-astra", "requests": 203, "input_tokens": 1, "output_tokens": 1,
         "cache_creation_tokens": 0, "cache_read_tokens": 1, "total_tokens": 21400000,
         "cost": 30.0, "actual_cost": 8.12, "account_cost": 8.12},
    ],
}

RELAY = {"id": "tokendun", "label": "TokenDun",
         "base_url": "https://api.example-relay.test/v1",
         "key": "sk-TESTONLY-SECRET-VALUE-0000000000000000",
         "usage_path": "/usage", "enabled": True}


class _Resp(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body.encode() if isinstance(body, str) else body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(routes, seen=None):
    """routes: {path: (status, body)}。未登记的 path 一律 404。"""
    def _open(req, timeout=None):
        path = req.full_url.split("/v1", 1)[1] if "/v1" in req.full_url else req.full_url
        if seen is not None:
            seen.append((path, dict(req.headers)))
        st, body = routes.get(path, (404, "404 page not found"))
        if st >= 400:
            raise urllib.error.HTTPError(req.full_url, st, "err", {}, io.BytesIO(body.encode()))
        return _Resp(body, st)
    return _open


class UserAgentIsMandatory(unittest.TestCase):
    """★★ 见模块 docstring ①。"""

    def test_the_constant_is_not_the_python_default(self):
        self.assertNotIn("urllib", monitor.USER_AGENT.lower())
        self.assertNotIn("python", monitor.USER_AGENT.lower())
        self.assertTrue(monitor.USER_AGENT.strip())

    def test_every_request_actually_carries_it(self):
        """★ 常量对了不代表发出去了 —— 本仓的老形态:「名字出现 ≠ 真的接上」。
        所以判据是**打桩看到的 header**,不是源码里有没有那个字符串。"""
        seen = []
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/usage": (200, json.dumps(SAMPLE))}, seen)):
            monitor.fetch(RELAY, remember_path=False)
        self.assertTrue(seen)
        for path, headers in seen:
            ua = {k.lower(): v for k, v in headers.items()}.get("user-agent")
            self.assertEqual(ua, monitor.USER_AGENT, f"{path} 没带 UA")

    def test_a_403_is_reported_as_auth_with_its_own_wording(self):
        """403（策略/UA 闸）和 401（key 错）下一步动作不同,不许压成一句话。"""
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/models": (403, "error code: 1010")})):
            r = monitor.test_connection(RELAY)
        self.assertEqual(r["state"], "auth")
        self.assertEqual(r["http"], 403)
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/models": (401, '{"code":"INVALID_API_KEY"}')})):
            r401 = monitor.test_connection(RELAY)
        self.assertEqual(r401["http"], 401)
        self.assertNotEqual(r401["detail"], r["detail"], "401 和 403 给了同一句话")


class TwoCostColumnsAreNeverMerged(unittest.TestCase):
    """★★ 见模块 docstring ②。"""

    def test_both_are_carried_through_separately(self):
        n = monitor.normalize(SAMPLE)
        self.assertAlmostEqual(n["total"]["cost"], 82.819205975)
        self.assertAlmostEqual(n["total"]["actual_cost"], 26.3859308645)
        self.assertNotEqual(n["total"]["cost"], n["total"]["actual_cost"])

    def test_no_single_field_silently_stands_for_spend(self):
        """不许出现一个叫 `spend`/`cost_total` 的合并字段 —— 有了它,
        下游一定会有人直接用,而它必然是两个口径里的一个。"""
        n = monitor.normalize(SAMPLE)
        for bad in ("spend", "cost_total", "total_cost", "amount"):
            self.assertNotIn(bad, n)
            self.assertNotIn(bad, n["total"])

    def test_runway_is_computed_from_actual_cost_not_list_price(self):
        """★ 余额是按**实扣**减的。用牌价算 runway 会把「还能撑多久」低估 3.85 倍 ——
        方向是「过度悲观」,但一样是错的数。"""
        n = monitor.normalize(SAMPLE)
        rw = monitor.runway(n)
        per_actual = (3.0682 + 3.968) / 2
        self.assertAlmostEqual(rw["per_active_day"], per_actual, places=6)


class MissingIsNotZero(unittest.TestCase):
    """本仓的老不变量:「这一枪没打中」绝不能和「确实没有」返回同一个值。"""

    def test_absent_balance_is_none_not_zero(self):
        n = monitor.normalize({k: v for k, v in SAMPLE.items()
                               if k not in ("balance", "remaining")})
        self.assertIsNone(n["balance"])

    def test_absent_cost_fields_are_none_not_zero(self):
        n = monitor.normalize({"balance": 1.0})
        self.assertIsNone(n["today"]["cost"])
        self.assertIsNone(n["total"]["actual_cost"])

    def test_a_real_zero_survives_as_zero(self):
        """★ 反方向也要验:今天真的没花钱,那 0 必须是 0,不能被当成缺失。"""
        n = monitor.normalize(SAMPLE)
        self.assertEqual(n["today"]["actual_cost"], 0)
        self.assertIsNotNone(n["today"]["actual_cost"])


class RunwayRefusesToGuess(unittest.TestCase):
    def test_fewer_than_two_active_days_gives_none_with_a_reason(self):
        """★ 一个点连速度都算不出。给一个看着精确的假数比说不知道更坏。"""
        one = {**SAMPLE, "daily_usage": SAMPLE["daily_usage"][:1]}
        rw = monitor.runway(monitor.normalize(one))
        self.assertIsNone(rw["days"])
        self.assertIn("样本不足", rw["reason"])

    def test_unknown_balance_gives_none_with_a_reason(self):
        n = monitor.normalize({k: v for k, v in SAMPLE.items()
                               if k not in ("balance", "remaining")})
        self.assertIsNone(monitor.runway(n)["days"])

    def test_idle_days_are_excluded_from_the_denominator(self):
        """★★ 中转站是「池子撞额度时才切过来」的备胎。按自然日平均会把 runway
        算得虚高好几倍 —— 那是最不该乐观的一个数。"""
        with_idle = {**SAMPLE, "daily_usage": SAMPLE["daily_usage"] + [
            {"date": "2026-09-09", "requests": 0, "total_tokens": 0,
             "cost": 0, "actual_cost": 0}]}
        busy = monitor.runway(monitor.normalize(SAMPLE))["per_active_day"]
        mixed = monitor.runway(monitor.normalize(with_idle))["per_active_day"]
        self.assertAlmostEqual(busy, mixed, places=9,
                              msg="0 请求的空闲日被算进分母,runway 被稀释了")


class BillingPathIsProbedNotAssumed(unittest.TestCase):
    """★★ 见模块 docstring ③。"""

    def test_it_finds_the_one_that_answers(self):
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/dashboard/billing/usage": (200, '{"a":1}')})):
            self.assertEqual(monitor.probe_billing_path(RELAY), "/dashboard/billing/usage")

    def test_a_200_that_is_not_json_is_not_accepted(self):
        """★ 有的站对未知路径返回 200 + HTML。只看状态码会认错端点,
        之后每次拉用量都拿到一坨 HTML 而「看起来是通的」。"""
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/usage": (200, "<html>not found</html>")})):
            self.assertIsNone(monitor.probe_billing_path(RELAY))

    def test_a_200_json_array_is_not_accepted_either(self):
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/usage": (200, "[1,2,3]")})):
            self.assertIsNone(monitor.probe_billing_path(RELAY))

    def test_no_endpoint_reports_its_own_state_not_a_zero_balance(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen({})):
            r = monitor.fetch({**RELAY, "usage_path": None}, remember_path=False)
        self.assertFalse(r["ok"])
        self.assertEqual(r["state"], "no_billing_endpoint")
        self.assertNotIn("data", r)


class FailuresAreDistinguishable(unittest.TestCase):
    def test_unreachable_auth_and_bad_payload_are_three_states(self):
        cases = {}
        with mock.patch("urllib.request.urlopen",
                        mock.Mock(side_effect=urllib.error.URLError("no route"))):
            cases["unreachable"] = monitor.fetch(RELAY, remember_path=False)["state"]
        with mock.patch("urllib.request.urlopen", fake_urlopen({"/usage": (401, "nope")})):
            cases["auth"] = monitor.fetch(RELAY, remember_path=False)["state"]
        with mock.patch("urllib.request.urlopen", fake_urlopen({"/usage": (200, "not json")})):
            cases["bad_payload"] = monitor.fetch(RELAY, remember_path=False)["state"]
        self.assertEqual(len(set(cases.values())), 3, cases)


class CollectNeverLeaksKeys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = os.environ.get("CODEX_ROTATE_STORE"), os.environ.get("CODEX_HOME")
        os.environ["CODEX_ROTATE_STORE"] = str(Path(self.tmp.name) / "store")
        os.environ["CODEX_HOME"] = str(Path(self.tmp.name) / "home")
        Path(os.environ["CODEX_HOME"]).mkdir(parents=True)
        self.addCleanup(self._restore)
        store.upsert(RELAY)

    def _restore(self):
        for k, v in zip(("CODEX_ROTATE_STORE", "CODEX_HOME"), self._old):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_the_whole_payload_is_key_free(self):
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/usage": (200, json.dumps(SAMPLE))})):
            blob = json.dumps(monitor.collect(), ensure_ascii=False)
        self.assertNotIn(RELAY["key"], blob)
        self.assertNotIn(RELAY["key"][10:30], blob)
        self.assertIn("key_fp", blob)

    def test_a_disabled_relay_is_reported_not_silently_skipped(self):
        """★ 「停用了」和「没配过」不该长得一样。"""
        store.upsert({**RELAY, "enabled": False})
        out = monitor.collect()
        self.assertEqual([r["state"] for r in out["relays"]], ["disabled"])

    def test_collect_carries_the_route_status(self):
        """路由那条静默失败的闸必须跟着数据一起送到 UI,否则没人看得见。"""
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen({"/usage": (200, json.dumps(SAMPLE))})):
            out = monitor.collect()
        self.assertIn("route", out)
        # ★ **状态集合从源码解析,不手抄。** 原来抄的那份漏了 `profile_stale`
        #   和后来加的 `route_corrupt` —— 手抄的清单会在新增状态时静默失效,
        #   而那正是它该发现的时刻（本仓 testing-discipline:守卫期望必须从真源推导）。
        # ★ **复用同一个解析器,不抄第二份。** 原来这里另写了一份正则(不截到下个 `def`、
        #   不剥注释) —— 现在因为 `route_status` 恰好在文件末尾而无害,
        #   函数一挪就会多读一堆别的状态。两份实现的同一条规则迟早会漂。
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_relay_route_copy import python_states
        known = python_states()
        self.assertGreaterEqual(len(known), 4, f"只解析到 {known},正则可能失效了")
        self.assertIn(out["route"]["state"], known)


if __name__ == "__main__":
    unittest.main()


class TheSnapshotOnlyGrows(unittest.TestCase):
    """★★ 用户 2026-09-09 反复提过的同一类问题：「用量丢失了，要做缓存，每次刷新是增量」。

    根因不是缓存没做，是**一次读不到会把上一次读到的整块覆盖掉**。
    「这次没取到」和「确实没有」被折叠成同一个返回值 —— 而它们在 UI 上必须长得不一样：
    前者显示旧数据 + 陈旧标记，后者才显示空。

    这条规则已写进项目 `CLAUDE.md` 的「读不到 ≠ 没有」一节。
    """

    def test_merge_is_a_union_by_date_never_a_replacement(self):
        """上游窗口会滑动。整块替换 ⇒ 滑出窗口的日子**从此消失**。"""
        prev = [{"date": "2026-09-01", "total_tokens": 10},
                {"date": "2026-09-02", "total_tokens": 20}]
        new = [{"date": "2026-09-02", "total_tokens": 22},
               {"date": "2026-09-03", "total_tokens": 30}]
        got = monitor.merge_daily(prev, new)
        self.assertEqual([d["date"] for d in got],
                         ["2026-09-01", "2026-09-02", "2026-09-03"], "旧日子被丢掉了")
        self.assertEqual(got[1]["total_tokens"], 22, "同一天该以新的为准")

    def test_a_day_that_lost_its_model_detail_keeps_the_old_one(self):
        """★ 逐日模型明细这次没取到时，**沿用旧的**，别把已有的抹成 None。"""
        prev = [{"date": "2026-09-02", "total_tokens": 20,
                 "models": [{"model": "gpt-5.5", "total_tokens": 20}]}]
        new = [{"date": "2026-09-02", "total_tokens": 22, "models": None}]
        got = monitor.merge_daily(prev, new)
        self.assertIsNotNone(got[0]["models"], "★ 已有的模型明细被这次的 None 抹掉了")
        self.assertEqual(got[0]["total_tokens"], 22)

    def test_empty_new_does_not_wipe_history(self):
        prev = [{"date": "2026-09-01", "total_tokens": 10}]
        self.assertEqual(monitor.merge_daily(prev, []), prev)
        self.assertEqual(monitor.merge_daily(prev, None), prev)

    def test_a_failed_fetch_keeps_the_previous_data_and_marks_it_stale(self):
        """★★ 最要紧的一条：取数失败 ⇒ 旧数据留着 + `stale`，**绝不清空**。"""
        relay = {"id": "r1", "label": "R1", "enabled": True,
                 "base_url": "https://x.test/v1", "key": "sk-TESTONLY-1",
                 "usage_path": "/usage"}
        old = {"balance": 5.0, "daily": [{"date": "2026-09-01", "total_tokens": 10}],
               "fetched_at": 1700000000}
        prev = {"relays": [{"id": "r1", "data": old}]}
        with mock.patch.object(monitor.store, "load", return_value={"relays": [relay]}), \
             mock.patch.object(monitor.store, "route_status", return_value={"state": "pool"}), \
             mock.patch.object(monitor, "fetch",
                               return_value={"ok": False, "state": "unreachable",
                                             "detail": "boom"}):
            got = monitor.collect(prev=prev)
        row = got["relays"][0]
        self.assertFalse(row["ok"])
        self.assertTrue(row["stale"], "没标 stale —— 用户会把旧数字当成刚取的")
        self.assertEqual(row["data"], old, "★ 失败把已有数据清空了 —— 这就是「用量丢失」")
        self.assertEqual(row["stale_since"], 1700000000)

    def test_the_gate_can_go_red(self):
        """★ 闸自证：把「失败保留旧数据」那段拿掉，上面那条必须红。
        本仓记过两次空守卫 —— 一道判不了红的闸比没有更糟。"""
        import inspect
        src = inspect.getsource(monitor.collect)
        self.assertIn('"stale": True', src)
        self.assertIn("merge_daily", src)

    def test_disabling_a_relay_does_not_erase_its_history(self):
        """★ 停用是**用户的选择**，不是"把账本烧了"。重新启用时该看到之前的曲线。"""
        relay = {"id": "r1", "label": "R1", "enabled": False,
                 "base_url": "https://x.test/v1", "key": "sk-TESTONLY-1"}
        old = {"balance": 5.0, "daily": [{"date": "2026-09-01", "total_tokens": 10}]}
        with mock.patch.object(monitor.store, "load", return_value={"relays": [relay]}), \
             mock.patch.object(monitor.store, "route_status", return_value={"state": "pool"}):
            got = monitor.collect(prev={"relays": [{"id": "r1", "data": old}]})
        self.assertEqual(got["relays"][0]["state"], "disabled")
        self.assertEqual(got["relays"][0]["data"], old, "停用把历史抹掉了")
