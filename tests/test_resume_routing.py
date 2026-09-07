"""`cxp` 的路由:**所有子命令一律走代理**(2026-09-07)。

## 来历

用户报「`codex resume` 进去的任务号额度没了就停,没得自动切号」,然后一句话点破:
「走的是代理的端口样式,代理的端口调用不同的号做到自动轮换的效果」——
原来的设计本来就是对的,只是 `resume`/`fork` 被排除在外了。

代理这条路一举解决两件事:
  ① **逐请求轮换** —— 代理按额度挑号,烧完一个自动换下一个;
  ② **关掉 WS 直连** —— codex 的 `responses_websocket` 硬编码 `wss://chatgpt.com`、
     不认 `base_url`;`[model_providers.rotateproxy]` 设了 `supports_websockets = false`,
     而**内置 provider 把它硬编码成 true 且不可覆盖**
     (`merge_configured_model_providers` 对内置 id 用 `or_insert`)。
     所以「不走代理」= WS 必开 = 单号烧到停。

## 代价(已知、已量,不是 bug)

resume picker 按 provider **逐字**过滤(`ProviderMatcher::matches`),`openai` 戳记的
历史会话不出现在列表里 —— **不是消失**,`codex resume <id>` 照样能进。
实测 2026-09-07(4179 个会话):最近 50 个里 rotateproxy 占 **76%**、最近 500 个占 64%,
往后新会话全是 rotateproxy 戳记。

## ★★ 一条走过的弯路,别再试

曾新建 `openai-nows` provider 当默认、只关 WS 不走代理。它错在**没有任何存量会话
带这个戳记**,于是 picker **直接空了**(不是变短)。provider 过滤是逐字相等的,
换 id 就等于清空列表。已回滚。

## `_headroom` / `_pick_best` 为什么还留着

`codex-rotate switch --best` 仍是有用的手动入口(按**最紧窗口**判、只看 Plus),
只是不再由 `cxp` 自动调用 —— 走代理之后"开场挑一个号"已无必要,代理每个请求都在挑。
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


def slot(label, plan=None, primary=None, secondary=None, **kw):
    """★ `plan` 显式传:`_pick_best` 按它筛 Plus,不按 label。"""
    q = {"primary": primary or {}, "secondary": secondary or {}}
    out = {"label": label, "quota": q, **kw}
    if plan:
        out["plan"] = plan
    return out


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
    """★★ **只在 Plus 号里挑**（用户 2026-09-06:「pro 号用不着这样用」）。

    除了产品意图,还有一条技术理由:**跨套餐比大小本来就不成立** ——
    Pro 的 primary 是**周**窗口、Plus 的是 **5h**,把两者的剩余% 排在同一条轴上
    是拿两把不同的尺量同一根线。限定 Plus 之后,`_headroom` 的比较才有意义。
    """

    def _pool(self):
        return {"slots": {
            "a": slot("plus3", "plus", primary=win(300, 0.0), secondary=win(10080, 100.0)),
            "b": slot("plus6", "plus", primary=win(300, 44.0), secondary=win(10080, 50.0)),
            "c": slot("Pro1", "pro", primary=win(10080, 34.0)),
            "d": slot("dead", "plus", primary=win(300, 0.0), auth_dead=True),
        }}

    def test_never_picks_a_pro_even_when_it_has_the_most_room(self):
        """★★ Pro1 剩 66% 是全场最高,仍**不能**被选中。
        改动前正是它被挑走的 —— 用户当场指出这不对。"""
        self.assertEqual(CR._pick_best(self._pool()), "b",
                         "挑到了 Pro 号 —— 轮换池这套是给 Plus 用的")

    def test_plan_is_read_from_plan_not_label(self):
        """老号从 Plus 升 Pro 时 label 一个字都不变,按名字挑会把 Pro 拉进来。"""
        s = {"slots": {"x": slot("plusOld", "pro", primary=win(10080, 10.0))}}
        self.assertIsNone(CR._pick_best(s))

    def test_never_picks_a_dead_account(self):
        s = self._pool()
        s["slots"]["b"]["auth_dead"] = True
        self.assertIsNone(CR._pick_best(s))   # 只剩见底的 plus3/plus4

    def test_never_picks_a_cooling_account(self):
        import time
        s = self._pool()
        s["slots"]["b"]["cooling_until"] = time.time() + 3600
        self.assertIsNone(CR._pick_best(s))

    def test_returns_none_when_nothing_is_readable(self):
        """★ 全都读不到额度时**不猜** —— 调用方据此保持当前号不变。"""
        self.assertIsNone(CR._pick_best({"slots": {"a": slot("x", "plus"),
                                                   "b": slot("y", "plus")}}))

    def test_does_not_switch_to_an_account_that_is_also_empty(self):
        """★★ 最好的 Plus 也几乎见底时**不换**。
        从一个还有余量的号切到一个空号,比不动更糟 —— 而「挑了个最好的」
        这句话会让人以为情况变好了。"""
        s = {"slots": {
            "a": slot("plus3", "plus", primary=win(300, 98.0)),
            "b": slot("plus4", "plus", primary=win(300, 100.0)),
        }}
        self.assertIsNone(CR._pick_best(s))


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

    def test_every_subcommand_goes_through_the_proxy(self):
        """★★ **没有例外分支。** resume/fork 曾被排除在外,代价就是那条会话钉死在
        一个号上、且 WS 必开(内置 provider 硬编码 supports_websockets=true 且不可覆盖)。"""
        for args in (("resume",), ("fork",), ("resume", "--last"), ("resume", "--all"),
                     ("resume", "01a0763a-f6f"), ("fork", "abc123"), ("exec", "hi"), ()):
            with self.subTest(args=args):
                self.assertIn("--profile rotateproxy", self.route(*args),
                              "%s 没走代理 —— 那条会话拿不到轮换,且 WS 会绕开代理" % (args,))

    def test_no_leftover_exception_branch(self):
        """★ 源码里不许再出现「resume 直连」那条分支。剥注释后查 ——
        注释里正解释着这段历史,对着原文匹配会恒绿。"""
        src = "\n".join(l for l in CXP.read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertNotIn("resume|fork", src, "例外分支还在")
        self.assertEqual(src.count("exec command codex"), 1,
                         "有多于一条 exec 路径 —— 说明还有分支")


class SwitchBestStillWorksAsAManualEntry(unittest.TestCase):
    """`switch --best` 不再被 cxp 自动调用,但仍是有用的手动入口 —— 保留并继续守它的口径。"""

    def test_cli_exposes_the_flag(self):
        self.assertIn('"--best" in args', (ROOT / "codex-rotate").read_text(encoding="utf-8"))

    def test_cxp_no_longer_calls_it(self):
        """★ 走代理之后「开场挑一个号」已无必要 —— 代理每个请求都在挑。
        留着调用只会在每次 resume 前多起一个 python、还会改 active 号。"""
        src = "\n".join(l for l in CXP.read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertNotIn("switch --best", src)


if __name__ == "__main__":
    unittest.main()
