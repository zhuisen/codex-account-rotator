"""★★★ `codex-rotate login` 必须打到**真** codex，不能撞上我们自己的守卫。

## 这条闸是为一次真实回归写的（2026-09-12 用户报）

`e59de75`（2026-09-10）把 `login` 加进 PATH wrapper 的拦截名单 —— 本意是挡住
用户/agent 直接敲 `codex login`（它覆盖 `~/.codex/auth.json`，把上一个号的最新
token 丢掉，而本仓的号只存在于那一份文件里）。

但 `codex-rotate login` 内部用的是 `shutil.which("codex")`，PATH 上第一个 `codex`
**正是那个 wrapper**。于是：

    codex-rotate login
      → 把当前号的 auth.json 移开（此时本机没有任何可用凭证）
      → 调 which("codex") = ~/.local/bin/codex = 我们的 wrapper
      → wrapper 拦下 login，exit 1
      → codex-rotate 还原 auth.json，退出
    **加号这条路整个断掉。**

最坏的是那条拦截文案写着「要加号 / 重登，请改用：`codex-rotate login`」——
**它把人指向的正是当时唯一坏掉的那条路**。

## 为什么判据是「路径」不是「标志位」

用环境变量开后门（`CODEX_ROTATE_SANCTIONED=1`）会让任何 export 过它的 shell
**永久失去守卫**。直接打真二进制是**构造上**绕过，不可能被误开。
`cxd` 与 wrapper 自己早就这么做（`exec "${CODEX_NATIVE_BIN:-…npm-global/bin/codex}"`），
这份是同一条规则的第三处实现 —— 原来漏的那处。
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROTATE = ROOT / "codex-rotate"
WRAPPER = ROOT / "scripts" / "codex-wrapper-with-logout-guard.sh"
# wrapper 的身份标记。真二进制里不可能有这串。
WRAPPER_MARK = "codex-profile-scope.sh"


def _real_codex_fn():
    """把 `_real_codex` 单独抠出来跑 —— 不 import 整个 `codex-rotate`
    （它在 import 期会读 state.json / auth/，那是真数据）。"""
    src = ROTATE.read_text(encoding="utf-8")
    i = src.index("def _real_codex()")
    j = src.index("\ndef ", i + 10)
    ns = {"os": os, "Path": Path, "shutil": __import__("shutil")}
    exec(compile(src[i:j], str(ROTATE), "exec"), ns)
    return ns["_real_codex"]


class LoginNeverResolvesToOurOwnWrapper(unittest.TestCase):

    def setUp(self):
        self.fn = _real_codex_fn()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))

    def _fake(self, d, name, body):
        p = Path(d) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        p.chmod(0o755)
        return p

    def test_the_wrapper_really_is_the_first_codex_on_this_machine(self):
        """★ 先证前提成立，否则下面那条在**任何**实现下都绿。

        这条 setUp 式的断言就是本轮的教训：如果本机 PATH 上第一个 `codex`
        本来就是真二进制，那"没解析到 wrapper"什么也证明不了。
        """
        import shutil as _sh
        first = _sh.which("codex")
        if not first:
            self.skipTest("本机 PATH 上没有 codex")
        # ★ 与实现同一个读取深度。第一版两边都读 4 KiB，而标记在第 133 行 ——
        #   **实现识别不出 wrapper，而这条前提断言也看不出来**。两个都读浅了，
        #   于是"前提成立"本身是假的。判据的读取范围必须覆盖被判的那个特征。
        head = Path(first).read_bytes()[:65536]
        self.assertIn(WRAPPER_MARK.encode(), head,
                     f"★ 本机 PATH 上第一个 codex 不是 wrapper（{first}）—— "
                     "前提不成立，下面那条闸此刻没有判别力")

    def test_it_skips_the_wrapper_and_finds_the_real_binary(self):
        """★★ 造一个 PATH：wrapper 在前、真二进制在后。必须拿到后者。"""
        d = self.tmp.name
        self._fake(d + "/w", "codex",
                   # ★ 标记**故意放在 5 KB 之后** —— 还原真实 wrapper 的形状
                   #   （它在第 133 行）。读浅了的实现会在这里漏掉它。
                   "#!/bin/sh\n" + ("# filler\n" * 800) + f"# {WRAPPER_MARK}\nexit 1\n")
        real = self._fake(d + "/r", "codex", "#!/bin/sh\nexit 0\n")
        os.environ["PATH"] = f"{d}/w{os.pathsep}{d}/r"
        os.environ["HOME"] = d + "/nohome"          # 让 npm-global 那几条落空
        os.environ.pop("CODEX_NATIVE_BIN", None)
        got = self.fn()
        self.assertEqual(Path(got), real,
                         f"★★ 解析到了 wrapper（{got}）—— `codex-rotate login` 会被自己拦下")

    def test_an_explicit_override_wins(self):
        d = self.tmp.name
        real = self._fake(d + "/x", "codex", "#!/bin/sh\nexit 0\n")
        os.environ["CODEX_NATIVE_BIN"] = str(real)
        self.assertEqual(Path(self.fn()), real)

    def test_a_nonexistent_override_does_not_win(self):
        """★ 反向：`CODEX_NATIVE_BIN` 指着一个不存在的文件时必须继续找，
        不能直接返回它 —— 那会让 `subprocess.call` 抛 OSError，
        而那条路径上刚刚把 auth.json 移走了。"""
        d = self.tmp.name
        real = self._fake(d + "/r", "codex", "#!/bin/sh\nexit 0\n")
        os.environ["CODEX_NATIVE_BIN"] = d + "/definitely/not/here"
        os.environ["PATH"] = d + "/r"
        os.environ["HOME"] = d + "/nohome"
        self.assertEqual(Path(self.fn()), real)


class TheGuardStillBlocksEveryOtherPath(unittest.TestCase):
    """★★ 反向闸：修法**不能**把守卫本身弄松。
    直接敲 `codex login` / `codex logout`（含全局选项前置的写法）仍必须被拦。"""

    def _run(self, *args):
        env = dict(os.environ)
        env["CODEX_ROTATE_STORE"] = str(ROOT)
        return subprocess.run(["bash", str(WRAPPER), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_plain_login_and_logout_are_still_blocked(self):
        for argv in (["login"], ["logout"],
                     ["-C", "/tmp", "logout"], ["-c", "k=v", "login"]):
            with self.subTest(argv=argv):
                p = self._run(*argv)
                self.assertNotEqual(p.returncode, 0, f"{argv} 没被拦住")
                self.assertIn("已拦截", p.stderr)

    def test_the_block_message_points_somewhere_that_works(self):
        """★★★ 拦截文案把人指向 `codex-rotate login` —— 那条路**必须真的能走**。

        本轮的核心教训：一个把人送进死胡同的错误提示，比没有提示更糟。
        所以这里把文案里点名的那条路，与"它解析到谁"钉在一起。
        """
        p = self._run("login")
        self.assertIn("codex-rotate login", p.stderr, "文案没给出路")
        src = ROTATE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "cmd_login")
        body = ast.get_source_segment(src, fn) or ""
        self.assertNotIn('shutil.which("codex")', body,
                         "★★ `cmd_login` 又用 which 了 —— 它会解析到 wrapper，"
                         "而拦截文案正把人指向这条路")
        self.assertIn("_real_codex()", body)


class ItNeverClaimsAMoveItDidNotMake(unittest.TestCase):
    """★★ 「没做」与「做了」不许输出同一句话（本仓 §7.0b）。

    `cmd_login` 原来无论如何都打「已把 X 的 auth.json 移开」与「已恢复原来的
    auth.json」——**包括本机根本没有 auth.json 的时候**。
    排查 2026-09-12 那次回归时我就被它误导了一轮：以为恢复成功，而 `LIVE` 从未被动过，
    于是"本机此刻没有任何可用凭证"这件事晚了几分钟才被发现。

    判据打在**源码的分支结构**上：三种结果（真恢复了 / 本来就没有 / 恢复失败）
    必须各有各的话。用 AST 数分支，不 grep 文案 —— 文案会改，结构才是不变量。
    """

    SRC = ROTATE.read_text(encoding="utf-8")

    def _login_body(self):
        tree = ast.parse(self.SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "cmd_login")
        body = ast.get_source_segment(self.SRC, fn)
        self.assertTrue(body, "取不到 cmd_login 源码 —— 探针坏了")
        return body

    def test_the_move_message_is_guarded_by_whether_it_moved(self):
        """★★ 用 **AST** 判「那句 print 在不在 `if moved:` 里面」，不 grep 文本。

        ⚠️ 第一版是 `body.index("的 auth.json 移开")` 再往回找 `if moved:` ——
           而**解释这条规则的注释里就有那句话**，`index` 命中的是注释，
           往回自然找不到 `if`，于是闸自己红了。
           本仓空守卫形态④（断言打在自己的说明文字上）的又一次现形：
           **判据要打在结构上，注释没有结构。**
        """
        tree = ast.parse(self.SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "cmd_login")
        MARK = "的 auth.json 移开"

        def prints_mark(node):
            return any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                       and MARK in c.value for c in ast.walk(node))

        guarded = [n for n in ast.walk(fn)
                   if isinstance(n, ast.If)
                   and isinstance(n.test, ast.Name) and n.test.id == "moved"
                   and any(prints_mark(st) for st in n.body)]
        self.assertTrue(guarded,
                        "★★ 「已移开」那句不在 `if moved:` 里 —— 没移动也会这么说")
        # 反向：它不许同时出现在 `if moved` 之外（否则两条都会打）。
        outside = [n for n in fn.body
                   if not (isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                           and n.test.id == "moved")
                   and prints_mark(n)]
        self.assertEqual(outside, [], "那句话在守卫之外还有一份")

    def test_all_three_outcomes_say_something_different(self):
        body = self._login_body()
        # 恢复分支必须区分三态：真恢复 / 本来就没有 / 恢复失败
        self.assertIn("restored", body, "没有区分「真恢复了」的变量")
        for must in ("本机原本就没有", "没能恢复"):
            self.assertIn(must, body, f"少了一种结果的说法：{must}")

    def test_the_failed_restore_branch_tells_you_where_the_stash_is(self):
        """★ 最坏的那一档（恢复失败）必须说出**下一步做什么** ——
        此刻本机没有任何可用凭证，一句"恢复失败"帮不上忙。"""
        body = self._login_body()
        i = body.index("没能恢复")
        self.assertIn("stash", body[i:i + 300])
        self.assertIn("switch", body, "另一档也要给出路")


if __name__ == "__main__":
    unittest.main()
