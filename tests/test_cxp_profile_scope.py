"""`cxp` 只能把 `--profile rotateproxy` 交给**运行时**子命令（2026-09-08）。

## 来历

用户报「甚至现在 codex 的本地工具都用不了了」。真因不在本仓,在上游:
npm 的 `@openai/codex` 当天 12:02 自动升到 **0.154.0-alpha.6**,而 0.154 起
codex 对非运行时子命令带 `--profile` 从「静默忽略」改成**硬报错**:

    Error: --profile only applies to runtime commands and `codex mcp`: `codex`, `codex exec`,
    `codex review`, `codex resume`, `codex queue`, `codex archive`, `codex delete`,
    `codex unarchive`, `codex fork`, `codex mcp`, `codex sandbox`, and `codex debug prompt-input`.

而 `alias codex=cxp` 给**每一个**子命令都塞了 profile ⇒ `codex doctor` / `update` /
`plugin` / `features` / `completion` 一句话就死。运行时那半完全正常,所以症状是
「会话能开、工具全废」,很容易误判成本仓的 resume 改动把什么弄坏了。

## ★ 一个会让你以为没事的坑

**别用 `codex <sub> --help` 去探这个**:clap 在 `--help` 上短路,profile 校验根本没跑到,
26 个子命令会**全绿**。我第一轮扫描就是这么扫出「全部 ok」的,与事实相反。
必须发真实调用。本测试用 PATH 上的 stub `codex` 打印 argv,所以每一条都是真实调用路径。

## 为什么是黑名单而不是白名单

白名单会把裸 prompt(`codex 修一下这个 bug`)判成「未知子命令」而丢掉 profile ——
那等于静默退回单号直连、不轮换,是比报错更坏的失败(它不出声)。
黑名单只认几个确定不是运行时的名字;prompt 和未来新增的运行时子命令都继续走代理。
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CXP = ROOT / "proxy" / "cxp"
SCOPE = CXP.parent / "codex-profile-scope.sh"
WRAPPER = CXP.parents[1] / "scripts" / "codex-wrapper-with-logout-guard.sh"

# codex --help(0.154.0-alpha.6)里的非运行时子命令。带 profile 会被 0.154 直接拒。
NON_RUNTIME = [
    "doctor", "update", "plugin", "features", "completion", "apply", "a",
    "agents", "login", "logout", "app", "app-server", "remote-control",
    "migrate-rollouts", "cloud", "exec-server", "help",
]
# 上游错误文案里逐字列出的允许集(去掉裸 `codex`)。
RUNTIME = [
    "exec", "review", "resume", "queue", "archive", "delete", "unarchive",
    "fork", "mcp", "sandbox",
]


class _Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-profile-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "codex"
        # 每个参数一行 —— 中文 prompt 带空格,用空格分隔会切错。
        stub.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n')
        stub.chmod(0o755)
        # ★ cxp 现在会硬检查 `$CODEX_HOME/<route>.config.toml` 是否存在（codex 对缺失
        #   **不报错**、静默退回 base 配置，所以闸放在 cxp 里）。测试必须自带这个文件，
        #   否则它其实是在依赖真实 `~/.codex/rotateproxy.config.toml` 碰巧存在。
        self.home = self.tmp / "codex-home"
        self.home.mkdir()
        (self.home / "rotateproxy.config.toml").write_text('model_provider = "rotateproxy"\n')

    def argv(self, *args):
        """`cxp` 只 `exec command codex`,所以把 stub 放 PATH 最前面就拿到了真实 argv。
        （补丁二进制那条分支已废,见 test_resume_routing.py::NoPatchedBinaryEntry。）"""
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["CODEX_HOME"] = str(self.home)
        env["CODEX_ROTATE_STORE"] = str(self.tmp / "store")
        p = subprocess.run([str(CXP), *args], capture_output=True, text=True,
                           env=env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.splitlines()


class NonRuntimeSubcommandsGetNoProfile(_Harness):
    def test_every_non_runtime_subcommand_is_passed_through_untouched(self):
        for sub in NON_RUNTIME:
            with self.subTest(sub=sub):
                self.assertEqual(
                    self.argv(sub), [sub],
                    f"`codex {sub}` 仍带着 --profile —— 0.154 会直接报 "
                    f"'--profile only applies to runtime commands'")
        # ★ `logout` 这条还有第二层意义:PATH wrapper 的拦截写的是 `[ "$1" = "logout" ]`,
        #   profile 曾恒占 `$1` ⇒ 那条「logout 会在服务端 revoke 当前号」的守卫一直是空的。

    def test_global_options_before_the_subcommand_do_not_hide_it(self):
        """`codex -C /tmp doctor` / `codex --model x doctor`:带值选项要跳 2 个 token,
        否则解析停在 `-C` 上、把 `doctor` 当不了子命令,profile 照塞。"""
        self.assertEqual(self.argv("-C", "/tmp", "doctor"), ["-C", "/tmp", "doctor"])
        self.assertEqual(self.argv("--model", "gpt-6-astra", "update"),
                         ["--model", "gpt-6-astra", "update"])
        self.assertEqual(self.argv("--json", "doctor"), ["--json", "doctor"])

    def test_debug_is_denied_except_prompt_input(self):
        """上游允许集里 `debug` 只放行了 `debug prompt-input` 一个子子命令。"""
        self.assertEqual(self.argv("debug", "seatbelt"), ["debug", "seatbelt"])
        self.assertEqual(
            self.argv("debug", "prompt-input")[:2], ["--profile", "rotateproxy"],
            "`debug prompt-input` 是上游明确允许的,不该被一起降级")


class RuntimeSubcommandsKeepTheProxy(_Harness):
    """丢掉 profile = 静默退回单号直连,**不轮换、WS 直连照开**。
    这个方向的失败不出声,比报错危险。"""

    def test_every_runtime_subcommand_still_gets_the_profile(self):
        for sub in RUNTIME:
            with self.subTest(sub=sub):
                self.assertEqual(
                    self.argv(sub)[:3], ["--profile", "rotateproxy", sub],
                    f"`codex {sub}` 丢了代理 —— 它会跑在 auth.json 那一个号上")

    def test_bare_codex_keeps_the_profile(self):
        self.assertEqual(self.argv(), ["--profile", "rotateproxy"])

    def test_a_bare_prompt_is_not_mistaken_for_an_unknown_subcommand(self):
        """★ 这条就是「为什么是黑名单」。首个非选项 token 是 prompt 的第一个词,
        白名单实现会在这里丢掉 profile。"""
        self.assertEqual(self.argv("修一下这个 bug"),
                         ["--profile", "rotateproxy", "修一下这个 bug"])
        self.assertEqual(self.argv("doctor the patient, please")[:2],
                         ["--profile", "rotateproxy"],
                         "整句 prompt 恰好以 `doctor` 开头 —— 但它不是子命令 token")

    def test_resume_with_a_session_id_keeps_the_profile(self):
        sid = "0199aa41-0000-7000-8000-000000000000"
        self.assertEqual(self.argv("resume", sid),
                         ["--profile", "rotateproxy", "resume", sid])


class TheDenylistMatchesTheUpstreamMessage(unittest.TestCase):
    def test_no_runtime_name_leaked_into_the_denylist(self):
        """两张表不能有交集 —— 交集意味着某个运行时命令被降级成直连。"""
        self.assertEqual(set(NON_RUNTIME) & set(RUNTIME), set())

    def test_source_denylist_is_the_one_the_tests_exercise(self):
        r"""闸的意义在于它守的是**源码里那张表**,不是测试自己抄的一份。

        ★ 2026-09-09 起这张表搬到了 `proxy/codex-profile-scope.sh` —— `cxp` 与
          PATH wrapper(`omc ask codex` / VS Code / `\codex` 都走它)共用同一份。
          原来两边各有一份实现,而同一条规则的两份实现必然在边界输入上分叉,
          分叉的后果是**静默退回单号直连、不轮换**。
        """
        src = SCOPE.read_text()
        # 只取 case 分支那一行,不要注释里同名的字。
        line = next(l for l in src.splitlines()
                    if l.strip().startswith("agents|login|logout|"))
        names = set(line.strip().rstrip(")").split("|"))
        self.assertEqual(names, set(NON_RUNTIME) - {"debug"},
                         "源码的黑名单和测试对不上了")

    def test_both_entrypoints_share_one_denylist(self):
        """★★ `cxp` 与 PATH wrapper 都必须 **source** 那份共享判据,而不是各抄一份。
        这条一旦松掉,`codex` 与 `omc ask codex` 会在某些 argv 上走向不同的 provider,
        而两者都不报错。"""
        for f in (CXP, WRAPPER):
            src = f.read_text()
            self.assertIn("codex-profile-scope.sh", src, f"{f.name} 没有引用共享判据")
            self.assertIn("codex_wants_profile", src, f"{f.name} 没有调用共享判据")
            self.assertNotIn("agents|login|logout|", src,
                             f"{f.name} 里还留着一份自己的黑名单 —— 两份必然分叉")


class TheProfileIsAlwaysRotateproxy(_Harness):
    """★★ 2026-09-09 定稿：**cxp 不再读路由文件**。

    中转站从"第二个 codex profile"改成"同一个代理的另一个上游"之后，codex 眼里永远
    只有 `rotateproxy` 一个 `model_provider`。账号池 ↔ 中转站的切换整个发生在
    `proxy.py::_relay_upstream` 里。

    为什么这条要单独钉住：`codex resume` 的 picker **按 `model_provider` 过滤，且
    0.154 里没有任何配置键能放宽它**（二进制里含 provider 的键逐个查过）。cxp 这边
    只要再注入第二个 provider id，会话列表就会立刻分裂成两份互相看不见的历史。
    """

    def _write_route(self, text):
        d = self.tmp / "store" / "relay"
        d.mkdir(parents=True, exist_ok=True)
        (d / "route.local.json").write_text(text)

    def test_pool_route_uses_rotateproxy(self):
        self._write_route('{"profile": "rotateproxy"}')
        self.assertEqual(self.argv("resume")[:2], ["--profile", "rotateproxy"])

    def test_relay_route_still_uses_rotateproxy(self):
        """★ 最要紧的一条：路由指着中转站时，cxp 传的**仍然**是 rotateproxy。
        传中转站 id 就等于给 codex 造了第二个 provider ⇒ 会话列表分裂。"""
        self._write_route('{"profile": "tokendun"}')
        self.assertEqual(
            self.argv("resume")[:2], ["--profile", "rotateproxy"],
            "cxp 把中转站 id 当成了 profile —— codex 会看到第二个 model_provider，"
            "`codex resume` 的历史当场分裂成两份")

    def test_a_corrupt_route_file_does_not_break_codex(self):
        """★ 路由文件坏了不再是 cxp 的事（它不读了）。代理会**退回账号池** ——
        判不准时往免费那档倒，最坏结果是"没按预期扣费"而不是"不知情地花钱"。"""
        for bad in ('not json at all', '{"profile": "../evil"}', '{"profile": ""}', '{}'):
            with self.subTest(bad=bad):
                self._write_route(bad)
                self.assertEqual(self.argv("resume")[:2], ["--profile", "rotateproxy"])

    def test_no_route_file_at_all(self):
        self.assertEqual(self.argv("resume")[:2], ["--profile", "rotateproxy"])

    def test_missing_pool_profile_is_still_a_hard_error(self):
        """★★ **这条闸不许删。** codex 对「`--profile X` 但 `X.config.toml` 不存在」
        **不报错**，直接静默退回 base 配置（直连单号、不轮换、WS 全开）——
        和正常运行长得一模一样。闸必须在 exec 这一刻。"""
        (self.home / "rotateproxy.config.toml").unlink()
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["CODEX_HOME"] = str(self.home)
        env["CODEX_ROTATE_STORE"] = str(self.tmp / "store")
        p = subprocess.run([str(CXP), "resume"], capture_output=True, text=True,
                           env=env, timeout=30)
        self.assertEqual(p.returncode, 78, "profile 缺失必须硬失败，不能静默跑起来")
        self.assertIn("rotateproxy.config.toml", p.stderr)
