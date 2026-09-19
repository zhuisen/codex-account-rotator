"""`codex` PATH wrapper 必须能装在**别人的**机器上。

## 这道闸在守什么

用户 2026-09-19 报「下载了 CodexBar，敲 `codex` 没走 rotateproxy」。根因之一是
**这个 wrapper 从来没被分发过** —— 它不在 `docs/INSTALL.md` 的任何一步里，也不在 `.dmg` 里。
而它之所以能一直不被发现，是因为它里面有两个**作者自己机器上恰好正确**的硬编码默认值：

    CODEX_ROTATE_STORE  默认 ${HOME}/Projects/tools/codex-account-rotator   ← 作者的 clone 路径
    CODEX_NATIVE_BIN    默认 ${HOME}/.local/npm-global/bin/codex            ← 作者的 npm prefix

任何把仓库 clone 到别处、或用 brew/volta 装 codex 的人，装上它之后 `codex` 直接 exit 78。
**「在我机器上是好的」不是玩笑，是这个 bug 的字面根因** —— 而且 `which codex` 对作者和
用户给出的是不同答案，所以本机怎么复现都复现不出来。

## 最危险的那条：不许 exec 回自己

wrapper 装在 `~/.local/bin/codex`，而它要找的官方二进制也叫 `codex`。`~/.local/bin` 通常排在
PATH 前面 ⇒ 朴素的 `command -v codex` 会解析到 wrapper 自身 ⇒ **无限递归**（fork 炸弹形态）。
`TheWrapperNeverExecsItself` 专门守这条，用例里 wrapper 就排在真二进制**前面**。
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "scripts" / "codex-wrapper-with-logout-guard.sh"


class WrapperCase(unittest.TestCase):
    """把 wrapper symlink 进一个临时 PATH，并给它一个会把 argv 打印出来的假 codex。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.bin = d / "bin"
        self.real = d / "real"
        self.bin.mkdir()
        self.real.mkdir()
        fake = self.real / "codex"
        fake.write_text("#!/bin/sh\necho \"ARGV: $*\"\n", encoding="utf-8")
        fake.chmod(0o755)
        self.link = self.bin / "codex"
        self.link.symlink_to(WRAPPER)
        # ★★ **必须给一个隔离的 CODEX_HOME。**（2026-09-19，CI 抓到）
        #    wrapper 在 exec 之前有一道硬检查：`$CODEX_HOME/rotateproxy.config.toml` 不存在
        #    就 exit 78（因为 codex 对缺 profile **不报错**，会静默退回单号直连）。
        #    不设这个变量时它读的是**跑测试那台机器的真 `~/.codex`** ——
        #    作者机器上那份存在 ⇒ 全绿；CI 的 /home/runner 上没有 ⇒ 四条全红。
        #    ⚠️ 这个文件通篇在讲「在我机器上是好的」，而它自己就犯了同一个错。
        self.codex_home = d / "codexhome"
        self.codex_home.mkdir()
        (self.codex_home / "rotateproxy.config.toml").write_text(
            'model_provider = "rotateproxy"\n', encoding="utf-8")

    def run_wrapper(self, *args, timeout=20, bare_path=False):
        env = dict(os.environ)
        if bare_path:
            # ★ 继承的 PATH 上有**本机真的** codex（作者机器 `~/.local/npm-global/bin`），
            #   所以「假装没有官方二进制」必须把 PATH 收窄，否则这条用例在作者机器上恒绿、
            #   在干净机器上才会红 —— 又是一次「在我机器上是好的」，同这个文件守的那个 bug。
            env["PATH"] = f"{self.bin}:/usr/bin:/bin"
            env["CODEX_HOME"] = str(self.codex_home)
            env.pop("CODEX_ROTATE_STORE", None)
            env.pop("CODEX_NATIVE_BIN", None)
            return subprocess.run([str(self.link), *args], capture_output=True,
                                  text=True, timeout=timeout, env=env)
        # ★ 关键：**删掉**两个环境变量，逼 wrapper 走自解析那条路 —— 本机恰好设了它们，
        #   不删的话这一整个测试文件在作者机器上会全绿而在别人机器上全红，正是它要防的事。
        env.pop("CODEX_ROTATE_STORE", None)
        env.pop("CODEX_NATIVE_BIN", None)
        env["CODEX_HOME"] = str(self.codex_home)      # 见 setUp 里那段 ★★
        # wrapper 排在真二进制**前面** —— 递归风险最大的排法。
        env["PATH"] = f"{self.bin}:{self.real}:{env.get('PATH', '')}"
        return subprocess.run([str(self.link), *args], capture_output=True,
                              text=True, timeout=timeout, env=env)


class TheWrapperWorksFromAnyCloneLocation(WrapperCase):
    def test_it_resolves_its_repo_from_its_own_path(self):
        """没有 CODEX_ROTATE_STORE 时必须自己找到仓库根，而不是 exit 78。"""
        r = self.run_wrapper("exec", "hello")
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr[-400:]}")
        self.assertIn("ARGV:", r.stdout)

    def test_it_still_injects_the_rotateproxy_profile(self):
        """★ 整套东西的目的就是这一行。丢了它 = 静默退回单号直连。"""
        r = self.run_wrapper("exec", "hello")
        self.assertIn("--profile rotateproxy", r.stdout)

    def test_a_local_tool_subcommand_passes_through_untouched(self):
        """codex 0.154 起对非运行时子命令带 --profile 会**硬报错**。"""
        r = self.run_wrapper("doctor")
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr[-400:]}")
        self.assertIn("ARGV: doctor", r.stdout)
        self.assertNotIn("--profile", r.stdout)


class TheWrapperNeverExecsItself(WrapperCase):
    """★★ wrapper 与官方二进制**同名**，而它自己通常排在 PATH 前面。"""

    def test_it_finds_the_real_binary_not_the_symlink(self):
        r = self.run_wrapper("exec", "x")
        # 真二进制会打印 ARGV:。exec 回自己的话这里会超时或栈溢出。
        self.assertIn("ARGV:", r.stdout)

    def test_it_fails_loudly_when_there_is_no_real_codex(self):
        """★ 找不到真二进制必须**报错**，不能静默成功或递归。

        「装坏了」与「你选了单号直连」必须给出不同的结果 —— 这是本仓最核心的一条。
        """
        os.remove(self.real / "codex")
        r = self.run_wrapper("exec", "x", bare_path=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("找不到官方 codex", r.stderr)
        self.assertNotIn("ARGV:", r.stdout)


class AMissingProfileFailsHardInsteadOfSilentlyDirectConnecting(WrapperCase):
    """★★ codex 对「`--profile X` 但 `X.config.toml` 不存在」**不报错**，直接退回 base 配置
    （直连单号、不轮换、WS 全开），和正常运行长得一模一样。wrapper 必须替它硬失败。

    ⚠️ 这条以前是**隐式**依赖（测试靠跑测试那台机器上真有那个文件才绿），CI 上一跑就露馅。
       现在它是一条被测行为。
    """

    def test_it_exits_78_and_says_to_use_cxd(self):
        (self.codex_home / "rotateproxy.config.toml").unlink()
        r = self.run_wrapper("exec", "x")
        self.assertEqual(r.returncode, 78)
        self.assertIn("profile 文件不存在", r.stderr)
        self.assertIn("cxd", r.stderr, "必须告诉用户单号直连该用什么")
        self.assertNotIn("ARGV:", r.stdout, "★ 静默退回直连了 —— 这正是它要防的事")


class TheKillSwitchGuardStillFires(WrapperCase):
    """`codex logout` 会 server-side 吊销当值号（本仓实测死过 3 个号）。

    ⚠️ 这条与上面的改动无关，但必须一起守：改 exec 那一段时把守卫顺序弄反过一次
    （`2026-09-10`，函数未定义 ⇒ `if` 恒假 ⇒ logout 直接放行）。
    """

    def test_logout_is_blocked(self):
        r = self.run_wrapper("logout")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("已拦截", r.stdout + r.stderr)
        self.assertNotIn("ARGV:", r.stdout, "★ logout 透传到了真二进制 —— 守卫是空的")

    def test_login_is_blocked_too(self):
        r = self.run_wrapper("login")
        self.assertNotIn("ARGV: login", r.stdout)


class TheInstallDocsShipThisWrapper(unittest.TestCase):
    """★★ 写了但没人装 = 等于不存在 —— 这正是用户这次报错的根因。

    wrapper 一直躺在 `scripts/` 里，而 `docs/INSTALL.md` 的「入口 symlink」一节
    **从来没有提过它**。所以每一个照着文档装的人，敲 `codex` 都不会走轮换。
    """

    def test_install_md_creates_the_codex_entry(self):
        txt = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
        self.assertIn("codex-wrapper-with-logout-guard.sh", txt,
                      "INSTALL.md 没有安装 codex wrapper —— 装完 `codex` 仍然不走轮换")
        self.assertIn("~/.local/bin/codex", txt)

    def test_install_md_documents_the_direct_entry(self):
        """`cxd` 是**唯一**的单号直连入口（用户 2026-09-09 定稿）。文档必须说它在哪。"""
        txt = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
        self.assertIn("cxd", txt, "INSTALL.md 没提 cxd —— 用户就没有单号直连的入口")


if __name__ == "__main__":
    unittest.main(verbosity=2)
