"""`cxp resume/fork` 的路由与「开场挑最满的号」(2026-09-06)。

## 缺口

用户:「我通过 `codex resume` 进去具体的任务，不是走代理的，而是连具体的号的，
因此号额度没了就停任务了，没得自动切号。」

`cxp` **有意**让 resume/fork 绕过代理:codex 给每个会话盖 `model_provider` 戳记，
而 resume 的 **picker 只列当前 provider 的会话** —— 走代理就看不到 `openai` 戳记的历史
(实测最近 200 个会话:openai 54.5% / rotateproxy 45.5%,这个代价是真的)。
代价是整段会话钉在一个号上,中途换不了(`AuthManager` 缓存凭证)。

## 修法(两条,各自零代价)

★ **那条 picker 限制只在「不带 session id」时才付。** 带了 id,picker 根本不参与:

    带 id  → 走代理,拿到逐请求轮换。**零代价**。
    不带 id → 保持直连(picker 完整),但**开场先切到额度最充裕的号**。

## ★★ 「最充裕」必须按**最紧的窗口**判

`primary` 是槽位名不是窗口时长(Plus 的 primary 是 5h、Pro 的是周)。于是一个
**周额度 100% 烧光、但 5h 窗口刚重置回 0%** 的号,按 primary 看是全池最空的 ——
本机 plus3 实测就是这样被 `proxy.py::_used()` 排到第一位的。
本仓 8 月已在 UI 层定过这条(`helpers.ts`「单个汇总数字一律取最紧的窗口」)。
⚠️ `proxy.py::_used()` **仍是旧口径**,那处 docstring 明写「要改先定策略」,不在本次范围。

## 未做(依赖未决)

「resume 全部走代理」要先确认 codex 的 WS 通道真被 `supports_websockets = false` 关掉了
(`responses_websocket` 硬编码 `wss://chatgpt.com`、不认 `base_url`)。
没确认之前全量改路由 = 轮换没拿到、picker 还白白变短。判定见
`scratch/verify_ws_bypass_20260906.py`。
"""
import importlib.machinery
import importlib.util
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CXP = ROOT / "proxy" / "cxp"

_loader = importlib.machinery.SourceFileLoader("cr", str(ROOT / "codex-rotate"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
CR = importlib.util.module_from_spec(_spec)
_loader.exec_module(CR)


def win(mins, used):
    return {"window_minutes": mins, "used_percent": used, "resets_at": None}


def slot(label, primary=None, secondary=None, **kw):
    q = {"primary": primary or {}, "secondary": secondary or {}}
    return {"label": label, "quota": q, **kw}


class HeadroomUsesTheTightestWindow(unittest.TestCase):
    """★★ 这条是整份测试的核心。"""

    def test_weekly_exhausted_account_has_zero_headroom(self):
        """**5h 刚重置回 0% 但周额度烧光** —— 按 primary 看是全池最空,实际一点都不剩。
        本机 plus3 的真实形态。"""
        s = slot("plus3", primary=win(300, 0.0), secondary=win(10080, 100.0))
        self.assertEqual(CR._headroom(s), 0.0,
                         "只看了 primary —— 周额度烧光的号会被当成最充裕的")

    def test_five_hour_exhausted_also_counts(self):
        s = slot("plus4", primary=win(300, 100.0), secondary=win(10080, 64.0))
        self.assertEqual(CR._headroom(s), 0.0)

    def test_pro_has_only_one_real_window(self):
        s = slot("Pro1", primary=win(10080, 34.0), secondary={})
        self.assertEqual(CR._headroom(s), 66.0)

    def test_unknown_quota_is_none_not_zero_and_not_full(self):
        """★ 读不到额度 ⇒ `None`。给 0 会把它排到最后、给 100 会让它被优先选中 ——
        两个方向都是拿「没观测」当成一个观测。"""
        self.assertIsNone(CR._headroom(slot("new")))

    def test_empty_slot_windows_are_skipped(self):
        """Codex 仍会返回空槽 `{window_minutes: 0}`,不能当成一个 100% 空闲的窗口。"""
        s = slot("x", primary={"window_minutes": 0, "used_percent": None},
                 secondary=win(10080, 20.0))
        self.assertEqual(CR._headroom(s), 80.0)


class PickBest(unittest.TestCase):
    def _pool(self):
        return {"slots": {
            "a": slot("plus3", primary=win(300, 0.0), secondary=win(10080, 100.0)),
            "b": slot("plus6", primary=win(300, 44.0), secondary=win(10080, 50.0)),
            "c": slot("Pro1", primary=win(10080, 34.0)),
            "d": slot("dead", primary=win(300, 0.0), auth_dead=True),
        }}

    def test_picks_the_most_headroom(self):
        self.assertEqual(CR._pick_best(self._pool()), "c")   # Pro1 剩 66

    def test_never_picks_a_dead_account(self):
        s = self._pool()
        s["slots"]["c"]["auth_dead"] = True
        self.assertNotIn(CR._pick_best(s), ("c", "d"))

    def test_never_picks_a_cooling_account(self):
        import time
        s = self._pool()
        s["slots"]["c"]["cooling_until"] = time.time() + 3600
        self.assertEqual(CR._pick_best(s), "b")

    def test_returns_none_when_nothing_is_readable(self):
        """★ 全都读不到额度时**不猜** —— 调用方据此保持当前号不变。"""
        self.assertIsNone(CR._pick_best({"slots": {"a": slot("x"), "b": slot("y")}}))


class CxpRouting(unittest.TestCase):
    """★ 行为闸:打桩一个假 codex,看真实的 `cxp` 把参数路由到哪。
    判据是**它实际执行了什么**,不是源码里有没有那几个字。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cxp-route-")
        stub = Path(cls.tmp, "codex")
        stub.write_text("#!/bin/bash\necho \"ROUTE: $*\"\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def route(self, *args):
        env = dict(os.environ, PATH=self.tmp + os.pathsep + os.environ["PATH"],
                   # ★ 指向一个不存在的 store,`switch --best` 会安静失败 ——
                   #   正好验证「优化失败绝不能挡住 resume」。绝不碰真实 state.json。
                   CODEX_ROTATE_STORE=os.path.join(self.tmp, "nostore"))
        p = subprocess.run(["bash", str(CXP), *args], env=env,
                           capture_output=True, text=True, timeout=90)
        m = [l for l in p.stdout.splitlines() if l.startswith("ROUTE:")]
        self.assertTrue(m, "cxp 没能走到 codex：%s / %s" % (p.stdout[-300:], p.stderr[-300:]))
        return m[-1][len("ROUTE: "):]

    def test_picker_mode_stays_direct(self):
        for args in (("resume",), ("fork",), ("resume", "--last"), ("resume", "--all")):
            with self.subTest(args=args):
                self.assertNotIn("--profile rotateproxy", self.route(*args),
                                 "picker 模式走了代理 —— 会看不到 openai 戳记的历史会话")

    def test_explicit_session_id_goes_through_the_proxy(self):
        for args in (("resume", "01a0763a-f6f"), ("fork", "abc123"),
                     ("resume", "--all", "01a0763a-f6f")):
            with self.subTest(args=args):
                self.assertIn("--profile rotateproxy", self.route(*args),
                              "带了 session id 却没走代理 —— 白白放弃了零代价的轮换")

    def test_everything_else_still_goes_through_the_proxy(self):
        self.assertIn("--profile rotateproxy", self.route("exec", "hi"))

    def test_switch_failure_does_not_block_resume(self):
        """★★ 「开场挑最满的号」只是优化。store 不存在时它必然失败,
        而 resume **仍须照常启动** —— 一个优化把主功能挡死是最糟的形态。"""
        self.assertEqual(self.route("resume"), "resume")


class SwitchBestIsWiredIn(unittest.TestCase):
    def test_cxp_calls_switch_best_in_picker_mode(self):
        src = "\n".join(l for l in CXP.read_text(encoding="utf-8").splitlines()
                        if not l.lstrip().startswith("#"))
        self.assertIn("switch --best", src)
        # ★ 必须容错:`|| true`,否则挑号失败会让 resume 起不来
        i = src.index("switch --best")
        self.assertIn("|| true", src[i:i + 120], "挑号失败没有兜底 —— 会挡住 resume")

    def test_cli_exposes_the_flag(self):
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        self.assertIn('"--best" in args', src)


if __name__ == "__main__":
    unittest.main()
