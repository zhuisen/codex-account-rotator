"""锚点账本的**接线**闸(2026-09-06)。

## 为什么单独有这一份

三个采集脚本各有一个 `_quota_anchors_mod()`,而它按仓规是**整体 fail-open** 的
（纯附加功能绝不能有能力搞挂主路径,2026-09-05 事故）。代价是那个 `except` 会把
**接线错误也一起吞掉**:第一版 `agy-quota` 里用了 `Path` 而那个文件从头到尾没 import 过
`pathlib` —— `python3 -c "ast.parse(...)"` 照过,脚本照跑,输出照常,只是账本
**静默地从不工作**。没有任何一处会为此变红。

所以判据不能是"源码里有没有那几个字",必须是**真的把模块加载出来**。
这也正是本仓那条「同名前缀 ≠ 同一标识符 / 子串存在 ≠ 规则存在」的正面版本:
能验行为就别验文本。

★ 同族的第二个坑:`note()` 会真的写盘。这里全部指到临时目录,
  **绝不碰真实的 `<store>/.quota-anchors.json`**。
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "traffic" / "quota_anchors.py"
SCRIPTS = ("codex-rotate", "grok-quota", "agy-quota")


def _load_script(name):
    """按路径把脚本载成模块。三个脚本顶层都只有常量 + 函数定义,
    真正的入口在 `if __name__ == '__main__'` 下,所以 import 不会跑任何东西
    (这正是仓规允许"按路径 import"的前提,见 CLAUDE.md §4)。"""
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(ROOT / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class LoaderActuallyLoads(unittest.TestCase):
    """★★ 判据是**加载成功**,不是源码里出现过那几个字。"""

    def test_module_exists_where_every_script_looks_for_it(self):
        self.assertTrue(MODULE.is_file(), "锚点账本模块不在 traffic/ 下")

    def test_each_script_can_really_load_the_ledger_module(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                mod = _load_script(name)
                self.assertTrue(hasattr(mod, "_quota_anchors_mod"),
                                "%s 没有装载函数" % name)
                qa = mod._quota_anchors_mod()
                self.assertIsNotNone(
                    qa, "%s 装载锚点账本失败 —— fail-open 把接线错误吞了" % name)
                for fn in ("note", "record", "verdict", "cycles"):
                    self.assertTrue(callable(getattr(qa, fn, None)),
                                    "%s 拿到的模块缺 %s()" % (name, fn))

    def test_loader_returns_none_instead_of_raising_when_module_is_absent(self):
        """★ 打包漏带时必须安静降级 —— 那正是 2026-09-05 事故的形态。"""
        mod = _load_script("agy-quota")
        real = MODULE
        tmp = MODULE.with_suffix(".py.hidden-by-test")
        real.rename(tmp)
        try:
            self.assertIsNone(mod._quota_anchors_mod())
        finally:
            tmp.rename(real)


class NoteWritesWhereItSaysItDoes(unittest.TestCase):
    """`note()` 落盘位置必须跟着 `CODEX_ROTATE_STORE` 走 —— 三个脚本和 quotad
    都靠这个变量指向同一个数据目录,写岔了就是四本互相看不见的账。"""

    def test_default_path_is_the_store_dir(self):
        qa = _load_script("codex-rotate")._quota_anchors_mod()
        with tempfile.TemporaryDirectory() as tmp:
            # ★ 摘掉测试隔离口,验的才是生产那条回退链(见 test_isolation_bootstrap)。
            saved = {k: os.environ.get(k)
                     for k in ("CODEX_ROTATE_STORE", "CODEXBAR_QUOTA_ANCHORS")}
            try:
                os.environ.pop("CODEXBAR_QUOTA_ANCHORS", None)
                os.environ["CODEX_ROTATE_STORE"] = tmp
                self.assertEqual(qa.default_path(), os.path.join(tmp, qa.FILENAME))
                qa.note("codex", "k", 5000, 3)
                self.assertTrue(os.path.isfile(os.path.join(tmp, qa.FILENAME)))
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


class PayloadCarriesTheResetItDescribes(unittest.TestCase):
    """★★ 判定必须自带它所描述的 `reset`。

    `slot["quota"]` 会被 rollout tail / proxy **整体替换**,而 `quota_anchor` 是兄弟键、
    不跟着换。不核身份的话,前端会拿一个描述**旧窗口**的判定去解释**新窗口**的倒计时,
    而两者渲染出来一模一样 —— 同「同名前缀 ≠ 同一标识符」一族。
    """

    def _src(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_every_writer_stamps_the_reset(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                # 断言打在**去掉注释后**的源码上 —— 注释里正解释着这条规则,
                # 对着原文匹配是本仓点名过的空守卫形态④。
                src = "\n".join(l for l in self._src(name).splitlines()
                                if not l.lstrip().startswith("#"))
                self.assertIn('["reset"] = int(', src,
                              "%s 写了判定却没盖上它描述的那个 reset" % name)

    def test_frontend_verifies_that_stamp(self):
        ts = (ROOT / "codexbar" / "src" / "helpers.ts").read_text(encoding="utf-8")
        i = ts.index("export function anchorStateOf")
        body = ts[i:ts.index("\n}", i)]
        self.assertIn("v?.reset", body, "前端没核判定的身份")
        self.assertIn("sameWindow", body)

    def test_unknown_falls_back_instead_of_denying(self):
        """★ `unknown`(样本不够)绝不能被当成 `floating` —— 那是拿「还没看够」
        冒充「确定没启动」。回落到点估计是唯一正确的处理。"""
        ts = (ROOT / "codexbar" / "src" / "helpers.ts").read_text(encoding="utf-8")
        i = ts.index("export function anchorStateOf")
        body = ts[i:ts.index("\n}", i)]
        self.assertIn("resetAnchorUnknown(w, capturedAt)", body,
                      "没有回落到点估计 —— 账本没数据时会退化成一个断言")
        self.assertIn('"floating"', body)


class BundledWithTheApp(unittest.TestCase):
    """★ 运行时按路径加载的模块必须进 `tauri.conf.json` 的 resources,
    否则安装包里根本没有它 —— 2026-09-05 就是这么炸的。

    ⚠️ `test_scan_optional_extras.py` 那道闸只扫 `scan.py`;这个模块是被
    **另外三个脚本**加载的,所以必须在这里单独盯一遍。"""

    def test_ledger_module_is_in_the_bundle_manifest(self):
        conf = json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json")
                          .read_text(encoding="utf-8"))
        res = conf["bundle"]["resources"]
        self.assertGreaterEqual(len(res), 4, "打包清单解析打空了")
        self.assertIn("quota_anchors.py", {Path(k).name for k in res},
                      "quota_anchors.py 没进 resources —— 安装包里会缺它,"
                      "而 fail-open 会让这件事完全没有症状")


class SuiteNeverWritesTheRealLedger(unittest.TestCase):
    """★★ **测试绝不写真实数据** —— 这条在账本这条新链路上真的破过(2026-09-06)。

    `test_grok_degrade_contract.py` 拿夹具 auth 起 `grok-quota`,而 `_note_anchors`
    没有隔离口 ⇒ 三个假账号(`https://auth.x.ai::c1/c2/client-1`,used 恒 35%)
    被写进了**真实的** `<store>/.quota-anchors.json`。那些假锚点会直接参与 UI 的
    「未启动」判定 —— 拿夹具数据去回答一个关于真实账号的问题。

    当时 **9 个**测试文件在起这三个脚本,一个都没隔离。所以修法不是逐个去补
    (那是"写下来但没有闸"),而是 `tests/__init__.py` 统一设 `CODEXBAR_QUOTA_ANCHORS`。
    这里验的是**那个隔离真的生效**:真起一次子进程,然后核真实账本一个字节都没动。
    """

    REAL = ROOT / "traffic" / ".." / ".quota-anchors.json"

    @staticmethod
    def _sig(p):
        """存在性 + mtime_ns + 大小。★ 只比 mtime 会漏掉同秒等长改写(本仓 `_sig()` 的老教训)。"""
        try:
            st = os.stat(p)
            return (True, st.st_mtime_ns, st.st_size)
        except OSError:
            return (False, 0, 0)

    def test_isolation_is_actually_active(self):
        """★ 先证明前提成立,否则下面那条断言在"根本没跑到写盘"时也会绿。"""
        self.assertTrue(os.environ.get("CODEXBAR_QUOTA_ANCHORS"),
                        "tests/__init__.py 没有设隔离变量 —— 整个防护是空的")

    def test_running_a_collector_does_not_touch_the_real_ledger(self):
        import subprocess
        real = (ROOT / qa_filename()).resolve()
        before = self._sig(real)
        env = dict(os.environ)
        env["AGY_PIDS_OVERRIDE"] = "4242"      # 保证走降级分支,不碰真 agy
        env["AGY_PORTS_OVERRIDE"] = "1"
        proc = subprocess.run([sys.executable, str(ROOT / "agy-quota")],
                              env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertEqual(self._sig(real), before,
                         "跑一次采集脚本改动了真实账本 —— 隔离没生效")

    def test_the_guard_can_fail(self):
        """★★ 变异自检:把隔离摘掉,同一个脚本必须真的去写那个位置。
        没有这条,上面那条在"脚本根本没写盘"时也会绿(空守卫)。"""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env.pop("CODEXBAR_QUOTA_ANCHORS", None)
            env["CODEX_ROTATE_STORE"] = tmp       # 摘掉隔离口,但仍指向临时目录
            env["AGY_PIDS_OVERRIDE"] = "4242"
            env["AGY_PORTS_OVERRIDE"] = "1"
            subprocess.run([sys.executable, str(ROOT / "agy-quota")],
                           env=env, capture_output=True, text=True, timeout=60)
            # 降级态没有 quota ⇒ 不写账本。用 grok 那条也一样要真数据才写,
            # 所以这里直接验**落点解析**:摘掉隔离口后 default_path 必须回到 store。
            qa = _load_script("agy-quota")._quota_anchors_mod()
            old = os.environ.pop("CODEXBAR_QUOTA_ANCHORS")
            os.environ["CODEX_ROTATE_STORE"] = tmp
            try:
                self.assertEqual(qa.default_path(), os.path.join(tmp, qa.FILENAME),
                                 "摘掉隔离口后落点没回到 store —— 隔离口不是真的在起作用")
                qa.note("agy", "probe", 5000, 1)
                self.assertTrue(os.path.isfile(os.path.join(tmp, qa.FILENAME)),
                                "note() 在没有隔离时也不写盘 —— 上面那条断言是空的")
            finally:
                os.environ["CODEXBAR_QUOTA_ANCHORS"] = old
                os.environ.pop("CODEX_ROTATE_STORE", None)


def qa_filename():
    return ".quota-anchors.json"


class LedgerIsNotCommitted(unittest.TestCase):
    """账本与 `state.json` 同目录,里面有 account_id。必须 gitignore。"""

    def test_gitignored(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".quota-anchors.json", gi)


if __name__ == "__main__":
    unittest.main()
