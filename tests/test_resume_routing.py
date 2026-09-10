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
实测 2026-09-08(4230 个会话,picker 口径 = archived=0 + has_user_event=1 + source in cli/vscode):
**openai 238 : rotateproxy 2**。
★★ 这里原本写着「最近 50 个里 rotateproxy 占 76%、往后只增不减」—— **实测推翻**:
最近 50 条里 rotateproxy 只有 2 条,2026-08 及以前**每月都是 0**。
大概率是 wrapper 里那个已删的 `repair_codex_session_visibility()` 一直在把 DB 的
rotateproxy 改写成 openai(238 这个数基本就是它的产物);另一部分是 69 条 VS Code 会话,
那条路根本不经过 cxp。**两者分不干净,别当已知事实用。**
可确认的只有一条:repair 移除后(2026-09-08),新交互会话稳稳戳 rotateproxy(当天 14:22/14:30 两条已验),
所以 238 是**存量、不再增长**。

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


@unittest.skipUnless(sys.platform == "darwin", "cxp 是 macOS 专用入口；见类 docstring")
class CxpRouting(unittest.TestCase):
    """★ 行为闸:打桩一个假 codex,看真实的 `cxp` 把参数路由到哪。
    判据是**它实际执行了什么**,不是源码里有没有那几个字。

    ⚠️ **只在 macOS 上跑。** `cxp` 用 `exec command codex …`,而 `command` 是 shell 内建:
    macOS 的 bash 3.2 允许 `exec` 走内建,**Linux 的 bash 5.x 会去 PATH 找一个叫 `command`
    的可执行文件**并报 `exec: command: not found`(2026-09-07 CI 实测,8 条 subTest 全红)。
    这不是产品缺陷 —— `cxp` 是 macOS 专用入口(Windows 走 `install-windows.ps1`,没有 cxp),
    但**测试必须如实标注平台**,否则 CI 上的红灯会被当成真缺陷追一轮。
    ★ 静态断言(`test_no_leftover_exception_branch`)不受影响,继续全平台跑 ——
      「例外分支有没有回来」这件事和平台无关。"""

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



class NoLeftoverExceptionBranch(unittest.TestCase):
    """★ 全平台都跑:「例外分支有没有回来」与平台无关,不该被上面那个 macOS 门连带跳过。"""

    def test_every_exec_path_carries_the_same_profile_decision(self):
        """★ 判据换过两次,记清楚它守的是什么。

        原判据「只有一条 exec」→ 可选的原生补丁入口合法地多出一条,会被误判。
        次判据「每条 exec 字面带 `--profile rotateproxy`」→ 2026-09-08 又失效:
        codex 0.154 起对非运行时子命令带 profile 会**硬报错**
        （`codex doctor` / `update` / `plugin` 全死,见 tests/test_cxp_profile_scope.py）,
        所以 profile 必须变成按子命令算出来的 `${cxp_profile[@]}`,不能再是字面量。

        ⚠️ 要守的不变量三次都没变:**没有一条 exec 路径绕过代理**
        （绕过 = WS 直连 = 单号烧到停,B36）。字面量与计数都只是当时恰好等价的代理判据。
        ★ 「运行时子命令确实还带着 profile」这件事**本文件判不了** —— 它是行为,
        判它的是 `test_cxp_profile_scope.py::RuntimeSubcommandsKeepTheProxy`(真跑 cxp)。
        这里只守「每条 exec 都用同一个决策,没有谁自己另开一条」。"""
        src = "\n".join(l for l in CXP.read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertNotIn("resume|fork)", src, "旧的例外分支(resume/fork 不走代理)回来了")
        execs = re.findall(r"exec [^\n]*", src)
        self.assertGreaterEqual(len(execs), 1, "一条 exec 都没有")
        for e in execs:
            self.assertIn('"${cxp_profile[@]}"', e,
                          f"有一条 exec 没带公共的 profile 决策 —— 它可能绕过代理:{e}")
        # 决策只能算一次;两份 case 表迟早会漂移成「同一台机器两种行为」。
        # ★ 2026-09-09 判据又换了一次:profile 名不再是字面量,而是由**路由**决定
        #   (账号池 `rotateproxy` / 某个中转站)。所以改成数赋值点。
        self.assertEqual(src.count("cxp_profile=(--profile"), 1, "profile 决策被算了不止一次")
        self.assertIn('cxp_profile=(--profile "$cxp_route")', src,
                      "profile 名写死了 —— 那样路由切换不会生效")
        # ★★ 静默失败的闸必须在 cxp 里,不能只在 UI 的路由卡上:
        #    codex 对「profile 文件不存在」不报错,而那一刻发生在 exec,不是在你打开 UI 时。
        self.assertIn("$cxp_home/$cxp_route.config.toml", src, "缺少 profile 文件的硬检查")


class NoPatchedBinaryEntry(unittest.TestCase):
    """★★★ `cxp` 只准 exec **官方** codex —— 打补丁的本地构建这条路已废弃
    （用户 2026-09-08 拍板:「不要弄补丁的,改为官方版」,理由是它会挡住后续官方版更新）。

    三条独立理由,任何一条单独成立就足够:
    ① ★ **它当场炸掉了全部工具调用。** codex 按**自己可执行文件的同级目录**解析辅助进程,
       而 `scripts/native-resume/build.py` 只 `shutil.copy2` 了 `codex` 一个文件 ——
       官方 vendor 是 4 件套(`codex` / `codex-code-mode-host` / `codex-resources/` /
       `codex-path/`)。`code_mode_host` 是 stable/true,spawn 不到 ⇒ `tools::router`
       **fail closed** ⇒ 模型一个工具都调不动。
       ⚠️ 而它**没有任何「配置坏了」的迹象**:`codex doctor` 全绿、`config.toml parse ok`、
          auth ok、MCP 8 个都在 —— 所以人必然先去翻配置,而配置是干净的。
    ② **它把版本钉死。** 补丁对着 0.153.4,npm 当天已到 0.154.0-alpha.6;`codex update`
       更新 npm 那份,**跑的却是被钉住的补丁**,二者越差越远且无声。
    ③ 每次官方发版都要重新 apply + 重编 + 重验,这个成本没人会长期付。
    """

    def _src(self):
        return "\n".join(l for l in CXP.read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))

    def test_the_only_exec_target_is_the_installed_codex(self):
        """★ 不变量是「**只有一条** exec 分支，且它交给 PATH 上装好的 codex」。

        ⚠️ 锚点从 `exec command codex` 改成 `exec codex`（2026-09-10）：
           `command` 在这里从来不是语义的一部分 —— `exec` 从不运行 shell 内建，
           它要一个真文件，而 `/usr/bin/command` **只有 macOS 有**。
           同一份脚本因此在 Linux 上 `exec: command: not found`（CI 红了 33 条，
           本机全绿）。去掉它零语义变化：alias 不进非交互 shell，function 要 `export -f`。
        """
        execs = re.findall(r"^\s*exec .*", self._src(), re.M)
        self.assertEqual(len(execs), 1, f"多了一条 exec 分支:{execs}")
        self.assertIn("exec codex", execs[0])
        # ★ 反向：`command` 不许回来 —— 它会让这个脚本重新变成 macOS 专属。
        self.assertNotIn("exec command", execs[0],
                         "`exec command` 依赖 macOS 专属的 /usr/bin/command")

    def test_no_patched_binary_hook_survives(self):
        """★ 逐个点名 —— 只查 `native-codex` 会漏掉换个目录名重新接回来的情况。"""
        src = self._src()
        for token in ("native-codex", "CODEX_NATIVE_BIN",
                      "codex-wrapper-with-logout-guard.sh"):
            self.assertNotIn(token, src, f"补丁入口的残留:{token}")
        # ★ `CODEX_ROTATE_STORE` **不在**这张表里,它是全仓统一的数据目录变量
        #   (`codex-rotate` / `traffic/*` 都读),只是恰好也被补丁分支用过。
        #   我拆补丁时顺手删过一次 —— 那是把公共设施当成残留。
        self.assertIn("CODEX_ROTATE_STORE", src, "误删了公共的数据目录变量")

    def test_the_patched_binary_is_not_shipped_in_the_repo(self):
        """★ 入口拆了但二进制还躺在仓库里 ⇒ 下一个人会把它接回去。
        归档在 ~/archive/codex-account-rotator/native-codex-dropped-20260908/。"""
        for p in (ROOT / "native-codex", ROOT / "output" / "native-codex"):
            self.assertFalse(p.exists(), f"补丁二进制还在仓库里:{p}")


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
