"""`proxy.py` 新读的那几组 `x-codex-*` 头的解析闸(2026-09-05)。

## 来历

看开源项目 `router-for-me/CLIProxyAPI` 的头白名单时发现:上游一直在发这些头,**我们一直没读**。
本仓原来只取 `x-codex-primary/secondary-*` 三件套 + `plan-type`,漏掉:

  · `x-codex-credits-*`      订阅之外的**付费余额**(balance / has-credits / unlimited)
  · `x-codex-active-limit`   当前生效的是哪一档限额
  · `x-codex-allowed` / `x-codex-limit-reached`   上游对这次请求的**结论**
  · `x-codex-<短名>-*`       具名附加限额 —— **`bengalfox` 就是这一族**

## 三条最要紧的断言

① ★★ **具名限额绝不许并入 `primary`/`secondary`。**
   本仓 v0.12.9 的事故形态正是「Pro 号上冒出一个它根本没有的 5h 窗口」。
   主窗口是套餐的,具名限额是某个模型的,混一起 UI 就会画出不存在的窗口。

② ★★ **取不到 = `None`,不折叠成 `False`/`0`。**
   「上游没说能不能用」和「上游说用不了」是两件事;`unlimited` 为真时 `balance` 不适用,
   也不能当成"余额 0"。这是本仓贯穿始终的那条铁律在新字段上的落地。

③ ★★ **具名限额必须有界、且短名要过滤。**
   中间那段短名是**上游控制**的,而结果每个请求都写进 `state.json` —— 那是轮换器的活文件。
   不设上界等于把它交给上游撑爆。
"""
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(mod_name, path):
    loader = importlib.machinery.SourceFileLoader(mod_name, str(path))
    spec = importlib.util.spec_from_loader(mod_name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


BASE = {
    "x-codex-primary-used-percent": "42",
    "x-codex-primary-window-minutes": "300",
    "x-codex-primary-reset-at": "1788600000",
}


class ExtraHeadersParsed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.px = load("crp_proxy_extra", ROOT / "proxy" / "proxy.py")

    def run_q(self, extra, status=200):
        """跑一次 `_record_quota`,拿回写进 slot 的 quota。

        ★ 打桩 `_mutate_state` —— 真实现会写**真的 state.json**(仓库铁律:测试绝不碰真数据)。
        """
        st = {"slots": {"A": {}}}
        orig = self.px._mutate_state
        self.px._mutate_state = lambda f: f(st)
        try:
            h = dict(BASE)
            h.update(extra)
            self.px._record_quota("A", list(h.items()), status)
        finally:
            self.px._mutate_state = orig
        return st["slots"]["A"]

    def ex(self, extra, status=200):
        """代理专有头的那个**兄弟键**。★ 它刻意不在 `quota` 里 —— 见下面那条
        `test_extras_are_not_inside_quota` 的说明。"""
        return self.run_q(extra, status).get("codex_headers") or {}

    def q(self, extra, status=200):
        return self.run_q(extra, status).get("quota") or {}

    def test_anchor_still_parses_the_base_windows(self):
        """★ 先证明基线没坏 —— 主窗口仍要被解析出来,否则下面每条都在测一个空对象。"""
        q = self.q({})
        self.assertEqual(q["primary"]["used_percent"], 42.0)
        self.assertEqual(q["primary"]["window_minutes"], 300.0)

    # ---- credits ----

    def test_credits_parsed(self):
        e = self.ex({"x-codex-credits-balance": "12.5",
                     "x-codex-credits-has-credits": "true",
                     "x-codex-credits-unlimited": "false"})
        self.assertEqual(e["credits_balance"],
                         {"balance": 12.5, "has_credits": True, "unlimited": False})

    def test_credits_absent_is_none_not_empty_shell(self):
        """一个字段都没有 ⇒ `None`。空壳 `{balance:None,...}` 会让 UI 以为"查过了,是空的"。"""
        self.assertIsNone(self.ex({})["credits_balance"])

    def test_unlimited_keeps_balance_distinguishable(self):
        """★ `unlimited` 为真时 balance 不适用。两个字段都要留着,让消费方自己判 ——
        在这里就把 balance 抹成 0,等于把「不适用」写成「用光了」。"""
        c = self.ex({"x-codex-credits-unlimited": "true"})["credits_balance"]
        self.assertTrue(c["unlimited"])
        self.assertIsNone(c["balance"], "unlimited 时不该凭空造一个余额数字")

    # ---- 布尔三态 ----

    def test_missing_boolean_is_none_not_false(self):
        """★★ 「没说」≠「不允许」。折叠成 False,UI 就会把未知画成"确定用不了"。"""
        e = self.ex({})
        self.assertIsNone(e["allowed"])
        self.assertIsNone(e["limit_reached"])

    def test_boolean_values(self):
        e = self.ex({"x-codex-allowed": "true", "x-codex-limit-reached": "false"})
        self.assertIs(e["allowed"], True)
        self.assertIs(e["limit_reached"], False)

    def test_garbage_boolean_is_none(self):
        """认不出来的值 ⇒ None,不猜。"""
        self.assertIsNone(self.ex({"x-codex-allowed": "maybe"})["allowed"])

    # ---- 具名附加限额（bengalfox 一族）----

    def test_named_limit_parsed_into_its_own_key(self):
        q = self.run_q({
            "x-codex-bengalfox-primary-used-percent": "88",
            "x-codex-bengalfox-primary-window-minutes": "300",
            "x-codex-bengalfox-limit-name": "GPT-5.3-Codex-Spark",
        })
        self.assertIn("bengalfox", q["codex_headers"]["additional"])
        self.assertEqual(q["codex_headers"]["additional"]["bengalfox"]["primary"]["used_percent"], 88.0)
        self.assertEqual(q["codex_headers"]["additional"]["bengalfox"]["limit_name"], "GPT-5.3-Codex-Spark")

    def test_named_limit_never_pollutes_the_main_windows(self):
        """★★ 本文件最重要的一条 —— v0.12.9 的事故形态。

        Pro 号只有周窗口。若具名限额被并进 `primary`/`secondary`,UI 上就会冒出一个
        该账号根本没有的 5h 窗口,而且**不报错**。
        """
        q = self.run_q({
            "x-codex-bengalfox-secondary-used-percent": "99",
            "x-codex-bengalfox-secondary-window-minutes": "300",
        })
        self.assertEqual(q["quota"]["primary"]["used_percent"], 42.0, "主窗口被具名限额污染了")
        self.assertIsNone(q["quota"]["secondary"]["used_percent"],
                          "具名限额爬进了 secondary —— 会画出账号没有的窗口(v0.12.9 形态)")
        self.assertIn("bengalfox", q["codex_headers"]["additional"])

    def test_code_review_limit_is_a_named_limit_too(self):
        q = self.run_q({"x-codex-code-review-primary-used-percent": "5"})
        self.assertIn("code-review", q["codex_headers"]["additional"])
        self.assertEqual(q["quota"]["primary"]["used_percent"], 42.0)

    def test_no_named_limits_yields_none(self):
        self.assertIsNone(self.ex({})["additional"])

    # ---- 边界与防御 ----

    def test_named_limits_are_bounded(self):
        """★ 短名是上游控制的,而结果每个请求都写进 state.json(轮换器的活文件)。"""
        extra = {"x-codex-n%d-primary-used-percent" % i: "1" for i in range(40)}
        q = self.run_q(extra)
        self.assertLessEqual(len(q["codex_headers"]["additional"]), self.px._MAX_ADDL,
                             "具名限额没有上界 —— 上游可以把 state.json 撑爆")

    def test_control_chars_in_limit_name_are_dropped(self):
        q = self.run_q({"x-codex-bengalfox-primary-used-percent": "1",
                        "x-codex-bengalfox-limit-name": "bad\x00name\x1b[0m"})
        self.assertNotIn("limit_name", q["codex_headers"]["additional"]["bengalfox"],
                         "带控制字符的上游文本进了 state.json")

    def test_overlong_limit_name_is_dropped(self):
        q = self.run_q({"x-codex-bengalfox-primary-used-percent": "1",
                        "x-codex-bengalfox-limit-name": "x" * 500})
        self.assertNotIn("limit_name", q["codex_headers"]["additional"]["bengalfox"])

    def test_non_numeric_values_are_skipped_not_fatal(self):
        q = self.run_q({"x-codex-bengalfox-primary-used-percent": "not-a-number"})
        self.assertTrue(q.get("quota"), "一个坏值把整次记账搞挂了")
        self.assertEqual(q["quota"]["primary"]["used_percent"], 42.0)

    # ---- 靠"头集合日志"发现的三个（服务端在发、CLIProxyAPI 没列、我们原来没读）----

    def test_reset_after_seconds_collected(self):
        """★★ 相对重置秒数。与 `resets_at` **性质不同**:后者是绝对纪元、受时钟偏移影响,
        前者免疫。本仓在"窗口是否已重置"上栽过(v0.12.9),两个量并存才能互相校验。"""
        e = self.ex({"x-codex-primary-reset-after-seconds": "1234",
                     "x-codex-secondary-reset-after-seconds": "5678"})
        self.assertEqual(e["primary_reset_after_seconds"], 1234.0)
        self.assertEqual(e["secondary_reset_after_seconds"], 5678.0)

    def test_reset_after_seconds_absent_is_none(self):
        """没发就是 None —— 绝不用 `resets_at - now` 顶替。

        顶替会造出一个**看起来是实测、其实是推算**的数,而这两者的可信度完全不同:
        推算值恰恰在时钟偏移时出错,而那正是引入这个字段要解决的场景。
        """
        self.assertIsNone(self.ex({})["primary_reset_after_seconds"])

    def test_over_secondary_limit_percent_collected(self):
        e = self.ex({"x-codex-primary-over-secondary-limit-percent": "17.5"})
        self.assertEqual(e["primary_over_secondary_limit_percent"], 17.5)

    def test_new_numbers_do_not_disturb_used_percent(self):
        """★ 新字段不得改变既有判定量 —— 选号器只吃 used_percent。"""
        q = self.q({"x-codex-primary-reset-after-seconds": "1",
                    "x-codex-primary-over-secondary-limit-percent": "99"})
        self.assertEqual(q["primary"]["used_percent"], 42.0)

    # ---- 快照语义 ----

    def test_new_fields_live_in_the_same_snapshot_object(self):
        """★★ 新字段必须与窗口同属一个 `q` 对象。

        `captured_at` 挂在对象上,整个对象是**一次响应的快照**。分开写就会出现
        「credits 来自十分钟前、窗口来自这次」而时间戳只有一个 —— 陈旧值蹭到新时间戳
        被认成现值。CLIProxyAPI 的 `QuotaState.Signals` 用的是同一条规则。
        """
        slot = self.run_q({"x-codex-credits-balance": "1", "x-codex-allowed": "true"})
        self.assertNotIn("credits_balance", slot["quota"],
                         "代理专有字段又被塞回 quota —— quota_daemon 每轮都会把它抹掉")
        for k in ("credits_balance", "allowed", "additional", "captured_at", "source"):
            self.assertIn(k, slot["codex_headers"])
        # 两个对象各有各的时间戳:混源会让陈旧值蹭到新时间戳被认成现值。
        self.assertIn("captured_at", slot["quota"])

    def test_non_2xx_still_does_not_replace(self):
        """★ 既有不变量不得被这次改动破坏:非 2xx 是不完整清单,不许整体替换。"""
        st = {"slots": {"A": {"quota": {"primary": {"used_percent": 7.0}}}}}
        orig = self.px._mutate_state
        self.px._mutate_state = lambda f: f(st)
        try:
            h = dict(BASE)
            h["x-codex-credits-balance"] = "99"
            self.px._record_quota("A", list(h.items()), 429)
        finally:
            self.px._mutate_state = orig
        self.assertEqual(st["slots"]["A"]["quota"]["primary"]["used_percent"], 7.0,
                         "429 的部分观测把完整快照替换掉了")
        self.assertNotIn("codex_headers", st["slots"]["A"],
                         "429 的部分观测写了 codex_headers —— 与 quota 同一条规则")


if __name__ == "__main__":
    unittest.main()
