"""agy 探针的**归属证据**（2026-09-16）。

## 缺陷：探针花了钱，却不知道花在谁头上

`_probe_one` 跑的是「**此刻钥匙串里那个号**」——它的 `label` 形参当时**在函数体里
一次都没被用过**（AST 证实）。而钥匙串是被**多个常驻 agy 进程并发写的单槽**：
本机实测此刻 **7 个**常驻 agy，最老的跑了 8 天 23 小时，且**身份并不相同**
（日志实证：两个是 A、一个是 B）。它们各自在自己 access token 到期时把身份写回钥匙串。

于是 `probe <非当值号>` 的路径是「装进去 B → 起 agy」，中间那个窗口里 B 可能已被冲掉
⇒ **实际是 A 在跑，而我们把 ✓ 和 15k token 记在 B 头上**。
本机 `agy.log` 里「钥匙串被别的 agy 进程写回过」**已经出现 9 次**，最近一次就在当天 ——
这不是理论风险。

★ 而 `agy-quota` 早就有这道闸（`pid_identity` 读 `applyAuthResult: email=`，
  **对不上就不挂卡**）—— 额度归属有证据，探针归属没有。这次补的就是这个缺口。
  同一条纪律：**归属要有证据，没证据就不归属。**

## ⚠️ 本文件存在的第二个理由：我修它的时候又踩了一次 fail-open

第一版 `_run_identity` 写的是裸 `except Exception`，而 `agy-rotate` **当时没有 `import re`**
⇒ `re.match` 抛 `NameError` ⇒ 被整个吞掉 ⇒ `ran_as` 恒 `None` ⇒ **归属核对静默地从不工作**，
而探针输出、退出码、日志**全都完全正常**。本仓记过一模一样的形状
（`_quota_anchors_mod()` 的整体 fail-open 吞掉了 `Path` 未导入，账本静默从不记账）。

所以这里的主闸判的是「**它真的能跑出答案**」，不是「源码里有那几个字」。
"""
import ast
import json
import os
import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "agy-rotate"


def _fn(name):
    """把单个函数从 `agy-rotate` 里取出来（不 import 整个 CLI）。"""
    src = CLI.read_text(encoding="utf-8")
    return next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == name)


class TheIdentityLookupIsActuallyWired(unittest.TestCase):
    """★★★ 主闸：`_run_identity` **真的能跑出一个答案**，不是"源码里有那几个字"。

    这条直接守我自己踩的那次：`import re` 漏了 + 裸 `except Exception`
    ⇒ 恒 `None` ⇒ 归属核对形同虚设，且**没有任何症状**。
    """

    def test_the_module_imports_what_the_helper_uses(self):
        """★★ `_run_identity` 用到的每个模块都必须在顶层 import 过。

        判据打在 **AST** 上而不是"源码里有没有 `import re`"：后者会被注释里的
        任何一句说明命中（本仓空守卫形态④，踩过五次）。
        """
        src = CLI.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = set()
        for n in tree.body:
            if isinstance(n, ast.Import):
                imported |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                imported |= {a.asname or a.name for a in n.names}

        fn = _fn("_run_identity")
        # 函数体里以 `X.y(...)` 形式用到的顶层名字
        used = {n.value.id for n in ast.walk(fn)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        missing = sorted(m for m in ("re", "time") if m in used and m not in imported)
        self.assertEqual(
            missing, [],
            "★★★ `_run_identity` 用了 {} 但顶层没 import —— 它会抛 `NameError`，"
            "而 fail-open 会把这个吞掉 ⇒ 归属核对**静默地从不工作**".format(missing))

    def test_the_except_does_not_swallow_wiring_errors(self):
        """★★★ `except` 只许吞**真正的读不到**（`OSError` / `ValueError`）。

        裸 `except Exception` 会把 `NameError`/`AttributeError` 这类**接线错误**
        一起吞掉 —— 那正是本仓记过的「fail-open 把接线错误一起吞了，
        账本静默地从不工作」。
        """
        fn = _fn("_run_identity")
        handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
        self.assertTrue(handlers, "★ `_run_identity` 里没有 try —— 断言可能打空了")
        for h in handlers:
            with self.subTest(lineno=h.lineno):
                self.assertIsNotNone(h.type, "★★★ 裸 `except:` —— 什么都吞")
                names = ({h.type.id} if isinstance(h.type, ast.Name)
                         else {e.id for e in getattr(h.type, "elts", [])
                               if isinstance(e, ast.Name)})
                self.assertNotIn(
                    "Exception", names,
                    "★★★ `except Exception` 会吞掉 `NameError` —— 我 2026-09-16 就是这么"
                    "让归属核对静默失效的（漏了 `import re`，而一切看起来完全正常）")
                self.assertTrue(names <= {"OSError", "ValueError"},
                                "★ 只该吞读不到类的异常，实际吞了 {}".format(sorted(names)))

    def test_it_returns_a_real_identity_for_a_real_run(self):
        """★★★ **行为闸**：拿本机真实的 agy 日志跑一次，必须解出一个 email。

        上面两条是静态的，挡得住诚实改动；这一条才证明它**真的有用**。
        没有日志（CI / 没装 agy）就跳过并说出原因 —— 跳过不是绿。
        """
        log_dir = Path(os.environ.get(
            "AGY_LOG_DIR",
            str(Path.home() / ".gemini" / "antigravity-cli" / "log")))
        if not log_dir.is_dir():
            raise unittest.SkipTest("本机没有 agy 日志目录（CI / 没装 agy）—— 无法做行为验证")

        # 找一份**确实含 applyAuthResult** 的日志，用它的文件名时间戳当 `started_at`。
        sample = None
        for f in log_dir.glob("cli-*.log"):
            m = re.match(r"cli-(\d{8}_\d{6})\.log$", f.name)
            if not m:
                continue
            try:
                if "applyAuthResult: email=" in f.read_text(errors="replace"):
                    sample = (f, time.mktime(time.strptime(m.group(1), "%Y%m%d_%H%M%S")))
                    break
            except OSError:
                continue
        if sample is None:
            raise unittest.SkipTest("agy 日志里没有 `applyAuthResult` —— 没有已知阳性可用")

        ns = {"re": re, "time": time, "Path": Path, "os": os,
              "AGY_LOG_DIR": log_dir, "_LOG_SKEW": 5}
        exec(compile(ast.Module(body=[_fn("_run_identity")], type_ignores=[]),
                     "agy-rotate", "exec"), ns)
        got = ns["_run_identity"](sample[1])
        self.assertIsNotNone(
            got,
            "★★★ 拿一份**已知含身份**的日志都解不出来（{}）—— "
            "归属核对是死的，而它死掉时没有任何症状".format(sample[0].name))
        self.assertIn("@", got, "★ 解出来的不像 email：{!r}".format(got))


class TheProbeRefusesToAttributeWithoutEvidence(unittest.TestCase):
    """★★ 拿到证据之后**必须真的拿它做判断** —— 采了不用等于没采。"""

    @classmethod
    def setUpClass(cls):
        src = CLI.read_text(encoding="utf-8")
        i = src.index("def cmd_probe(args):")
        j = src.index("\ndef ", i + 10)
        # ★ 剥注释：本仓注释密度极高，注释里正解释着这条规则，
        #   不剥的话 `assertIn` 会命中说明文字（空守卫形态④）。
        cls.body = re.sub(r"#[^\n]*", "", src[i:j])

    def test_it_compares_the_real_identity_against_the_pool_email(self):
        self.assertIn("ran_as", self.body, "★★ 没接住实际身份")
        self.assertRegex(self.body, r"ran_as\s*!=\s*want|want\s*!=\s*ran_as",
                         "★★★ 取到了身份却**没拿它比对** —— 采了不用等于没采")

    def test_a_mismatch_does_not_count_as_a_success_for_this_account(self):
        """★★★ 对不上时 `ok` 必须翻成 False，且 `usage` 不许记在本号上。

        钱确实花了，但**花在另一个号上**。把它记成本号的成功，
        就是把「A 的 15k token」写进「B 还能干活」这个结论里。
        """
        m = re.search(r"if ran_as and want and ran_as != want:(.*?)a\[\"last_probe\"\]",
                      self.body, re.S)
        self.assertIsNotNone(m, "★ 找不到不符分支 —— 断言可能打空了")
        seg = m.group(1)
        self.assertRegex(seg, r"ok\s*=\s*False", "★★★ 归属不符却仍算成功")
        self.assertRegex(seg, r"usage\s*=\s*None",
                         "★★★ 把别的号花掉的用量记在本号头上了")

    def test_unknown_identity_does_not_flip_ok(self):
        """★★ 「认不出」≠「跑错了号」。

        把这两者合并成同一个值，正是本仓反复记的那条 ——
        一次日志读取失败就会把一个成功的探针报成失败。
        判据：不符分支的条件里**必须**要求 `ran_as` 为真。
        """
        self.assertRegex(self.body, r"if\s+ran_as\s+and\s+want\s+and\s+ran_as\s*!=\s*want",
                         "★★ 条件没要求 `ran_as` 为真 —— 认不出会被当成跑错号")

    def test_the_evidence_is_persisted(self):
        """★ 证据要落盘：事后「到底跑成了谁」只能从 `last_probe` 查。"""
        for k in ('"ran_as"', '"attributed"', '"via"'):
            with self.subTest(field=k):
                self.assertIn(k, self.body, "★ `last_probe` 没记 {}".format(k))


class TheProbeIsNeverAutomatic(unittest.TestCase):
    """★★★ 探针是 Gemini 档**唯一花钱**的动作，绝不许被任何定时器触发。

    2026-09-16 给 agy 额度加了 10 分钟自动保鲜，那条路**只许**调 `quota`。
    真把 `probe` 接进心跳，就是每 10 分钟烧一次 15k token 且无人察觉。
    """

    def test_the_auto_refresh_never_invokes_probe(self):
        hook = (ROOT / "codexbar" / "src" / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8")
        # 剥注释后再找：注释里正写着"不许自动跑 probe"
        code = re.sub(r"/\*[\s\S]*?\*/", "", hook)
        code = re.sub(r"//[^\n]*", "", code)
        i = code.index("const refreshQuotaIfStale")
        j = code.index("}, [runQuota]);", i)
        self.assertNotIn('"probe"', code[i:j],
                         "★★★ 自动保鲜路径里出现了 `probe` —— 那是每 10 分钟自动花钱")

    def test_the_shared_runner_only_ever_asks_for_quota(self):
        hook = (ROOT / "codexbar" / "src" / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8")
        code = re.sub(r"/\*[\s\S]*?\*/", "", hook)
        code = re.sub(r"//[^\n]*", "", code)
        i = code.index("const runQuota")
        j = code.index("}, [read]);", i)
        self.assertIn('args: ["quota"]', code[i:j], "★ 共用取数函数不再是 quota 了")
        self.assertNotIn("probe", code[i:j], "★★★ 共用取数函数里混进了 probe")


if __name__ == "__main__":
    unittest.main()
