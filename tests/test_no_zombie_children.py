"""子进程必须被收尸（2026-09-17，用户实报「CodexBar 会留下僵尸进程」）。

## 真凶不是 App，是 `bin/agy`

第一版修复（commit 816f0ad）改的是 `lib.rs` 里两处采样器的 `let _ = ….spawn()`。
写法本身没错，但**那两条路径当时产出 0 个僵尸**（正被锁文件抑制着）。
四方评审 + 实测定位到真凶：

    ppid 1048  × 10 → /Applications/Clipsync.app          （另一个 app，不在本仓）
    ppid ×7         → ~/.local/bin/agy                     （★ 本仓 bin/agy 造的）
    ppid 26432 ×  0 → 当前 CodexBar                        （一个都没有）

`bin/agy` 用裸 `subprocess.Popen` 起采样器，紧接着 `os.execv` 换进程映像 ——
**execv 换映像不换父子关系**：采样器仍挂在这个 pid 下，而接管 pid 的 agy 真身
根本不认识它、永不 `waitpid`。⚠️ `start_new_session=True` 只 setsid，
**不改 PPID、不转移 reap 责任** —— 当时正是靠它误以为已经安全。

### 忠实复现（2026-09-17，两个方向）

    Popen + execv 成长命进程（原写法）  -> 该 pid 下僵尸 1
    双 fork   + execv 成长命进程（修后）-> 该 pid 下僵尸 0

★ **第一次复现失败过**：只写 `Popen` 而不 `execv`，两边都是 0 ——
  因为 Python 的 `subprocess` 会顺手收尸，而真实路径里 `execv` 让 Python 运行时
  整个消失、再没人收。**漏掉 execv 的复现会得出"没有 bug"的相反结论。**

## 这份闸的第一版是空守卫，重写过

原判据只认 `let _ = ….spawn()` 一种形状，实跑形状表 **7 种里抓到 1 种** ——
连它自己 docstring 声称能抓的裸 `cmd.spawn();` 都漏。
Python 侧用 `rglob("*.py")`，而本仓有 **7 个无扩展名的 python 脚本**
（`bin/agy`、`codex-rotate`、`agy-rotate`、`grok-quota`…），**覆盖率 0/7** ——
于是它在真凶所在的文件上**从未扫过一个字节**，却报告「Python 侧干净」。
"""
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src-tauri" / "src"

#: 生产 python 脚本 = `*.py` **加上无扩展名但带 python shebang 的**。
#: ⚠️ 第一版只有前半截，于是 `bin/agy`（真凶）从未被扫过。
SKIP_PREFIXES = ("tests/", "scratch/", "scripts/native-resume/",
                 "codexbar/node_modules/", "codexbar/uishot/app/",
                 "codexbar/src-tauri/target/", ".git/")


def _production_python_files():
    out = []
    for f in sorted(ROOT.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue
        if f.suffix == ".py":
            out.append(f)
            continue
        if f.suffix:                       # 有别的扩展名 ⇒ 不是我们要找的脚本
            continue
        try:
            if "python" in f.open(encoding="utf-8", errors="replace").readline():
                out.append(f)
        except OSError:
            continue
    return out


def _strip_rs(src: str) -> str:
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


class TheProbesCanSeeTheirTargets(unittest.TestCase):
    """★★★ 已知阳性自检 —— 这份文件的第一版正是**探针看不见目标**才给出假绿。"""

    def test_the_python_scan_covers_extensionless_scripts(self):
        files = {f.relative_to(ROOT).as_posix() for f in _production_python_files()}
        for must in ("bin/agy", "codex-rotate", "agy-rotate",
                     "grok-quota", "grok-quota-sampler"):
            with self.subTest(script=must):
                self.assertIn(must, files,
                              "★★★ 扫描清单漏掉了无扩展名脚本 {} —— "
                              "第一版的 `rglob(\"*.py\")` 对它们覆盖率是 0/7，"
                              "而真凶就在其中".format(must))

    def test_the_rust_scan_finds_sources(self):
        files = sorted(SRC.rglob("*.rs"))
        self.assertTrue(files, "★ 一个 .rs 都没扫到 —— 是路径错了，不是代码干净")
        self.assertTrue(any(".spawn()" in f.read_text(encoding="utf-8") for f in files),
                        "★ 没有任何 `.spawn()` —— 探针多半打空了")


class TheRustLeakDetectorCatchesEveryShape(unittest.TestCase):
    """★★★ 判据必须覆盖**所有**会丢弃 `Child` 的写法，不是只认 `let _ =`。

    七种写法留同一个僵尸。第一版只抓第一种 —— 一条只抓得住自己举的那个例子的闸，
    等于没有。
    """

    #: (写法, 是否应当被判为泄漏)
    SHAPES = (
        ("let _ = cmd.spawn();", True),
        ("cmd.spawn();", True),
        ("let _child = cmd.spawn();", True),
        ("cmd.spawn().ok();", True),
        ("drop(cmd.spawn());", True),
        ("if cmd.spawn().is_ok() {}", True),
        ("let c = cmd.spawn().unwrap();", True),
        # ── 合法写法：不许误报 ──
        ("let mut child = cmd.spawn()?;\nchild.wait_with_output()", False),
        ("spawn_and_reap(c);", False),
    )

    @staticmethod
    def leaks(code: str) -> bool:
        """→ 这段 Rust 是否丢弃了 `spawn()` 的 `Child`。

        ★ 判据是**反向**的：`spawn()` 的结果必须被绑定到一个真名字，
          且这段代码里要出现 `wait`。其余一律算泄漏 —— 白名单比黑名单安全，
          因为新的泄漏写法层出不穷，而合法写法就那么几种。
        """
        code = _strip_rs(code)
        out = []
        for m in re.finditer(r"\.spawn\(\)", code):
            head = code[:m.start()]
            line_start = head.rfind("\n") + 1
            stmt = code[line_start:].split(";", 1)[0]
            bound = re.match(r"\s*let\s+(mut\s+)?([A-Za-z][A-Za-z0-9_]*)\s*=", stmt)
            if not bound:
                out.append(m.start())          # 没绑定 ⇒ 立刻 drop
                continue
            if not re.search(r"\.wait(_with_output)?\(", code):
                out.append(m.start())          # 绑了但从不 wait ⇒ 一样是僵尸
        return bool(out)

    def test_every_leaking_shape_is_flagged(self):
        for code, should in self.SHAPES:
            with self.subTest(code=code.splitlines()[0]):
                self.assertEqual(
                    self.leaks(code), should,
                    "★★★ 判据对这种写法判错了：{!r}（应判泄漏={}）".format(code, should))

    def test_the_real_sources_are_clean(self):
        bad = []
        for f in sorted(SRC.rglob("*.rs")):
            code = _strip_rs(f.read_text(encoding="utf-8"))
            # 逐条语句判，`spawn_and_reap` 自己的定义除外（它就是那个 wait 的地方）
            for m in re.finditer(r"[^;{}]*\.spawn\(\)[^;]*;", code):
                stmt = " ".join(m.group(0).split())
                seg = code[max(0, m.start() - 400):m.start() + 400]
                if "fn spawn_and_reap" in seg:
                    continue
                if not self.leaks(seg):
                    continue
                bad.append("{}  {}".format(f.name, stmt[:90]))
        self.assertEqual(
            bad, [],
            "★★★ 这些地方丢弃了 `spawn()` 的 Child，每跑一次留一个僵尸：\n  "
            + "\n  ".join(bad)
            + "\n  → 改走 `spawn_and_reap(cmd)`。"
              "\n  ⚠️ 不要改成 `.status()`：那会阻塞 3 秒一拍的定时器。")


class ThePythonSideNeverOrphansAChild(unittest.TestCase):
    """★★★ 真凶所在的那一侧 —— 扫描范围必须含**无扩展名脚本**。"""

    def test_no_bare_popen_before_an_execv(self):
        """★★★ `Popen` + 同文件 `os.execv` = 采样器挂给 execv 之后那个进程当僵尸。

        这正是 `bin/agy` 的形状。判据刻意**只对同时出现两者的文件报警** ——
        单独的 `Popen`（后面老老实实 `wait`）不是问题。
        """
        # ⚠️ **必须走 AST，不能文本匹配。** 第一版用 `"Popen(" in code` —— 而修复之后
        #   `bin/agy` 的 docstring 里正写着「原来是一句裸 `subprocess.Popen(...)`」，
        #   当场假红（空守卫形态④：断言撞上解释这条规则的文字）。
        #   `re.sub(r"#…")` 只剥 `#` 注释，**剥不掉 docstring**。
        import ast as _ast
        bad = []
        for f in _production_python_files():
            try:
                tree = _ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            has_popen = any(
                isinstance(n, _ast.Call) and
                ((isinstance(n.func, _ast.Attribute) and n.func.attr == "Popen") or
                 (isinstance(n.func, _ast.Name) and n.func.id == "Popen"))
                for n in _ast.walk(tree))
            has_execv = any(
                isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
                and n.func.attr in ("execv", "execve", "execvp")
                for n in _ast.walk(tree))
            if has_popen and has_execv:
                bad.append(f.relative_to(ROOT).as_posix())
        self.assertEqual(
            bad, [],
            "★★★ 这些脚本在 `os.execv` 之前用裸 `Popen` 起了后台进程：{}\n"
            "  execv 换进程映像**不换父子关系** —— 接管 pid 的那个程序不认识这个孩子、"
            "永不 waitpid ⇒ 它退出后就是僵尸。\n"
            "  → 改双 fork（`fork` → `setsid` → 再 `fork` → 孙进程被 init 收养，"
            "中间进程立刻 `waitpid` 回收）。\n"
            "  ⚠️ 不要用 `signal(SIGCHLD, SIG_IGN)` 代替：它会**跨 execv 保留**，"
            "让接管者自己的 waitpid 全拿 ECHILD。".format(bad))

    def test_the_sampler_launcher_double_forks(self):
        """★★ 正向断言 `bin/agy` 真的做了双 fork，而不是只是删掉了 Popen。"""
        code = re.sub(r"#[^\n]*", "",
                      (ROOT / "bin" / "agy").read_text(encoding="utf-8"))
        i = code.index("def start_quota_sampler")
        body = code[i:code.index("\ndef ", i + 10)]
        self.assertGreaterEqual(body.count("os.fork()"), 2,
                                "★★ 只 fork 了一次 —— 孙进程不会被 init 收养")
        self.assertIn("os.setsid", body, "★ 缺 setsid")
        self.assertIn("os.waitpid", body,
                      "★★★ 没回收中间进程 —— 问题从孙进程搬到儿子身上而已")
        self.assertIn("os._exit", body,
                      "★★ 中间进程必须 `_exit`：普通 exit 会跑 atexit/flush 父进程缓冲区")


class TheAppReapsAndCleansUp(unittest.TestCase):
    """★★ 收尸函数 + 退出清理。"""

    @classmethod
    def setUpClass(cls):
        cls.lib = _strip_rs((SRC / "lib.rs").read_text(encoding="utf-8"))

    def test_the_reaper_waits_in_its_own_thread(self):
        i = self.lib.index("fn spawn_and_reap")
        body = self.lib[i:self.lib.index("\nfn ", i + 10)]
        self.assertIn("thread::spawn", body, "★★ 收尸没放进独立线程 —— 会阻塞定时器")
        self.assertRegex(body, r"\.wait\(\)", "★★★ 收尸函数里没有 `wait()`")

    def test_children_are_registered_and_deregistered(self):
        """★★ 登记要成对：只 push 不 retain，表会无限长，
        且退出时会对**已被系统复用**的 pid 发信号，打到无辜进程头上。"""
        i = self.lib.index("fn spawn_and_reap")
        body = self.lib[i:self.lib.index("\nfn ", i + 10)]
        self.assertIn("KIDS", body, "★★ 子进程没登记 —— 退出时无从清理")
        self.assertIn("retain", body, "★★★ 只登记不销号 —— 会对复用的 pid 发信号")

    def test_every_exit_path_cleans_up(self):
        """★★★ ⌘Q / quit_app / RunEvent::Exit 都要清理。

        实测过后果：pid 97371 的采样器 `PPID=1`，是**上一代 app** 起的孤儿，
        `MAX_LIFETIME_SECS = 24h` ⇒ 用户关掉 app 之后它还能查额度一整天。
        """
        self.assertIn("fn reap_all_children", self.lib, "★★ 没有清理函数")
        i = self.lib.index("fn quit_app")
        self.assertIn("reap_all_children",
                      self.lib[i:self.lib.index("\n}", i)],
                      "★★★ `quit_app` 不清理 —— 那是除 ⌘Q 外唯一的退出路径")
        self.assertIn("RunEvent::Exit", self.lib, "★★ 没有退出兜底")

    def test_cleanup_uses_sigterm_not_sigkill(self):
        """★★ 必须 `SIGTERM`：采样器的 `finally` 要有机会**删掉自己的锁**。

        `SIGKILL` 不给它这个机会 —— 那正好制造出一个陈锁，
        喂给下面 `sampler_lock_held` 那条永久闭锁。
        """
        i = self.lib.index("fn reap_all_children")
        body = self.lib[i:self.lib.index("\n}", self.lib.index("{", i))]
        self.assertIn("SIGTERM", body, "★★ 没用 SIGTERM")
        self.assertNotIn("SIGKILL", body,
                         "★★★ 用了 SIGKILL —— 采样器来不及删锁，会留下陈锁")


class StaleLocksNeverSuppressTheSamplerForever(unittest.TestCase):
    """★★★ 陈锁不许永久抑制补拉 —— 这条当时是**正在生效的线上故障**。

    实测 2026-09-17：`grok-quota-ledger/.sampler.lock` 内容 `884`、进程早已不在，
    而 `samples.jsonl` **冻结 49 小时**。grok 没有 wrapper 兜底，App 是唯一补拉路径。
    """

    @classmethod
    def setUpClass(cls):
        cls.lib = _strip_rs((SRC / "lib.rs").read_text(encoding="utf-8"))

    def test_the_gate_probes_the_pid_not_the_file(self):
        self.assertIn("fn sampler_lock_held", self.lib, "★★★ 没有存活探测")
        i = self.lib.index("fn sampler_lock_held")
        body = self.lib[i:self.lib.index("\nfn ", i + 10)]
        self.assertIn("read_to_string", body, "★★ 没读锁内容 —— 还是在判文件存在")
        self.assertIn("kill", body, "★★★ 没探 PID 存活")

    def test_no_call_site_still_checks_mere_existence(self):
        """★★ 不许再对**锁**判 `exists()`。

        ⚠️ 判据要精确到「对哪个变量」：同一段里 `Path::new(&script).exists()`
          判的是**脚本文件**在不在，那是合法的。第一版笼统禁 `exists()` 当场假红
          —— 而一条会假红的闸，用户学会的是忽略它。
        """
        hits = re.findall(r"Path::new\(\s*&\s*lock\s*\)[^;]*?\.exists\(\)", self.lib)
        self.assertEqual(
            hits, [],
            "★★★ 还在对锁文件判存在：{} —— 陈锁会让补拉永久静默".format(hits))
        # 已知阳性自检：这段代码里**确实**还有合法的 `exists()`（判脚本文件），
        # 否则上面那条 assert 是在一个空集上通过的。
        self.assertIn("Path::new(&script).exists()", self.lib,
                      "★ 连合法的脚本存在性检查都没了 —— 断言多半打空了")

    def test_unreadable_lock_fails_open(self):
        """★ 读不到 / 内容不是 PID ⇒ **去拉**（采样器的 take_lock 才是权威闸）。

        少拉一次的代价是**永久静默**，多拉一次只是一个瞬时进程 —— 两边不对等。
        """
        i = self.lib.index("fn sampler_lock_held")
        body = self.lib[i:self.lib.index("\nfn ", i + 10)]
        self.assertGreaterEqual(body.count("return false"), 2,
                                "★ 异常路径没有 fail-open 去拉")


class EarlyExitNeverLeavesALock(unittest.TestCase):
    """★★★ **行为闸**：采样器在 agy 没跑时早退，绝不能留下锁文件。

    原来是「先 take_lock 再探活」⇒ 早退路径写了锁却走不到 `finally` 的 unlink
    ⇒ 自己给自己造陈锁。grok 侧早已修好并配了同名闸，agy 侧一直没同步。
    """

    def test_agy_sampler_probes_liveness_before_taking_the_lock(self):
        src = (ROOT / "traffic" / "agy_quota_sampler.py").read_text(encoding="utf-8")
        code = re.sub(r"#[^\n]*", "", src)
        i = code.index("def main(")
        body = code[i:i + 1400]
        a, l = body.index("agy_alive()"), body.index("take_lock(")
        self.assertLess(a, l,
                        "★★★ 还是先取锁后探活 —— 早退路径会留下陈锁，"
                        "叠加 App 侧那道闸之后**永远不会再有采样器被拉起**")

    def test_it_really_leaves_no_lock(self):
        """★★★ 真跑一次：让探活必然失败，跑完断言锁文件不存在。

        静态的顺序断言挡得住诚实改动；这一条才证明它**真的不留锁**。
        """
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ,
                       CODEX_ROTATE_STORE=d,
                       AGY_SAMPLER_IDLE_SECS="1",
                       PATH="/nonexistent-so-agy-is-never-alive")
            r = subprocess.run(
                [sys.executable, str(ROOT / "traffic" / "agy_quota_sampler.py")],
                env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            leftover = list(Path(d).rglob(".sampler.lock"))
            self.assertEqual(
                leftover, [],
                "★★★ 早退之后仍留下了锁文件 {} —— 它会让补拉从此永久静默".format(leftover))


class SigtermLetsTheSamplerCleanItsLock(unittest.TestCase):
    """★★★ App 收子进程发的是 `SIGTERM`，**全部理由**就是让采样器删掉自己的锁。

    ⚠️ Python 默认的 SIGTERM 是**直接终止**：不抛异常、不跑 `finally` ⇒
      `lk.unlink()` 根本没机会执行。实测（2026-09-17）：app 退出后两个锁原样留在盘上，
      内容是刚死掉的那两个 pid。**不装处理器，选 SIGTERM 而非 SIGKILL 的理由就是空的。**
    ★ 现在 `sampler_lock_held` 会探 PID，所以陈锁已不再致命；但留一地陈锁仍是垃圾，
      而且一旦哪天有人把那条探活改回 `exists()`，它立刻变回致命。
    """

    SAMPLERS = (("agy", "traffic/agy_quota_sampler.py"), ("grok", "grok-quota-sampler"))

    def test_the_handler_is_installed(self):
        for name, rel in self.SAMPLERS:
            with self.subTest(sampler=name):
                code = re.sub(r"#[^\n]*", "", (ROOT / rel).read_text(encoding="utf-8"))
                self.assertIn("signal.SIGTERM", code, "★★ 没装 SIGTERM 处理器")
                self.assertIn("SystemExit", code,
                              "★★★ 处理器不抛 `SystemExit` —— 不展开栈就跑不到 `finally`")

    def test_sigterm_really_removes_the_lock(self):
        """★★★ **行为闸**：真起一个、真发 SIGTERM、真看锁没了。

        静态断言只能证明"装了个处理器"；只有真跑能证明 `finally` 确实被执行到。
        """
        import tempfile
        for name, rel in self.SAMPLERS:
            with self.subTest(sampler=name), tempfile.TemporaryDirectory() as d:
                env = dict(os.environ, CODEX_ROTATE_STORE=d)
                p = subprocess.Popen([sys.executable, str(ROOT / rel)], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                lock = None
                for _ in range(80):
                    found = list(Path(d).rglob(".sampler.lock"))
                    if found:
                        lock = found[0]
                        break
                    time.sleep(0.25)
                if lock is None:
                    # 探活即退的路径本来就不留锁 —— 那由 EarlyExitNeverLeavesALock 管。
                    p.terminate(); p.wait(timeout=30)
                    raise unittest.SkipTest(
                        "{} 没走到写锁那一步（本机没有它要采的目标）".format(name))
                p.terminate()                       # ← SIGTERM
                p.wait(timeout=30)
                self.assertFalse(
                    lock.exists(),
                    "★★★ {} 被 SIGTERM 之后锁还在 —— `finally` 没跑到，"
                    "app 每退出一次就留一个陈锁".format(name))


class TheDetachedSpawningDependencyIsGone(unittest.TestCase):
    """★★★ **泄漏的那次 spawn 可以不在我们的代码里。**（2026-09-18，装机版 v1.6.3 实测）

    这份文件前面每一条闸扫的都是**本仓源码**，而 v1.6.3 —— 已经含了 `bin/agy` 双 fork、
    `spawn_and_reap`、退出清理、SIGTERM 处理的那一版 —— 底下仍抓到一具僵尸：

        pid 36012  PPID 14732(CodexBar)  STAT Z  诞生于 09-18 14:47:29

    时刻正对上「设置 → 关于」里那两个外链之一被点开。链路：

        SettingsPage `openExternal()`
          → `tauri-plugin-shell::open`            (2.3.5 · src/open.rs:134)
          → `::open::that_detached`               (open-5.3.5 · src/lib.rs:267)
          → `spawn_detached()`                    (           · src/lib.rs:380)
             = `pre_exec { setsid() }` + `self.spawn().map(|_| ())`

    最后那行把 `Child` 句柄**直接 drop 掉，从不 `wait()`**。Rust 的
    `std::process::Child` 没有会收尸的 `Drop`（这是**刻意的**语言设计），
    所以 drop 句柄 = 定额留一具僵尸。

    ★ 这与本文件开头那条 `bin/agy` 是**同一个形状，换了语言**：
      `setsid()` / `start_new_session=True` 都只脱离控制终端，**不转移收尸责任**。
      两次都是靠「它 detach 了所以安全」这个错觉过的关。

    ⚠️ 判据因此必须**跨过仓库边界**：一条只扫 `src/**` 的闸对这件事是结构性沉默的，
      而沉默在报告里长得和通过一模一样。
    """

    CARGO = ROOT / "codexbar" / "src-tauri" / "Cargo.toml"
    PKG = ROOT / "codexbar" / "package.json"
    CAPS = ROOT / "codexbar" / "src-tauri" / "capabilities"

    @staticmethod
    def _open_url_body():
        """取 `open_url` 的函数体，只剥**整行**注释。

        ⚠️ 不能用 `_strip_rs`：它的 `//[^\\n]*` 不认字符串字面量，会把
        `starts_with("https://")` 里的 `//` 当成注释起点，**把白名单本身吃掉一半** ——
        于是「没有白名单」这条断言恒红，而真因与白名单毫无关系。
        （同族：本仓记过的「定长切片滑进下一段」——判据一旦依赖粗糙的文本切割，
        它红的时候不指向真因。）
        """
        rs = (SRC / "lib.rs").read_text(encoding="utf-8")
        rs = re.sub(r"(?m)^\s*//[^\n]*", "", rs)
        i = rs.index("fn open_url(")
        return rs[i:rs.index("\n}", i)]

    def test_the_rust_dependency_is_not_declared(self):
        txt = self.CARGO.read_text(encoding="utf-8")
        # ★ 打在**依赖声明**的形态上，不是打在字符串 `tauri-plugin-shell` 上 ——
        #   同一个词就写在紧挨着的注释里解释着「为什么删了它」（本仓空守卫形态④，
        #   一轮踩过五次）。所以要求行首、且后面跟着 `=`。
        decl = re.search(r"(?m)^\s*tauri-plugin-shell\s*=", txt)
        self.assertIsNone(
            decl, "★★★ `tauri-plugin-shell` 又被加回 Cargo.toml —— "
                  "它的 `open` 走 `open::that_detached`，点一次外链留一具僵尸")

    def test_the_npm_dependency_is_not_declared(self):
        import json
        pkg = json.loads(self.PKG.read_text(encoding="utf-8"))
        for field in ("dependencies", "devDependencies"):
            with self.subTest(field=field):
                self.assertNotIn("@tauri-apps/plugin-shell", pkg.get(field, {}),
                                 "★★★ npm 侧又装回了 plugin-shell")

    def test_no_frontend_file_imports_it(self):
        """★★ 删依赖不等于删用法：`node_modules` 里可能因别的包被提升而仍然存在，
        于是 `import` 照样能解析，构建也照样过。

        ⚠️ **必须先剥注释**（本仓空守卫形态④，本轮又撞了一次）：`SettingsPage.tsx` 顶上
        正写着「不要用 `@tauri-apps/plugin-shell` 的 open」这条规则本身，
        裸搜字符串会把**解释规则的那句话**判成违反规则。
        """
        hits = []
        for f in (ROOT / "codexbar" / "src").rglob("*.ts*"):
            src = re.sub(r"/\*[\s\S]*?\*/", "", f.read_text(encoding="utf-8"))
            src = re.sub(r"(?m)^\s*//[^\n]*", "", src)
            if "@tauri-apps/plugin-shell" in src:
                hits.append(f.relative_to(ROOT).as_posix())
        self.assertEqual(hits, [], "★★★ 这些文件还在 import 会泄漏的 shell 插件：{}".format(hits))

    def test_the_capability_is_revoked(self):
        """★ 权限还开着 = 那条 IPC 命令仍然可达。插件没注册时调用只是报错，
        但把权限留着等于给「顺手装回去」留了一条无声的路。"""
        for cap in self.CAPS.glob("*.json"):
            with self.subTest(cap=cap.name):
                self.assertNotIn('"shell:', cap.read_text(encoding="utf-8"),
                                 "★★ {} 还授着 shell 权限".format(cap.name))

    def test_the_replacement_command_exists_and_is_registered(self):
        """★★★ **删掉一条路必须同时接上替代路**，否则「在浏览器打开」静默变成点了没反应。

        ⚠️ 这条是反向闸：上面四条全绿也可能只是**把功能删了**。
        """
        rs = _strip_rs((SRC / "lib.rs").read_text(encoding="utf-8"))
        self.assertIn("fn open_url(", rs, "★★★ 替代命令 `open_url` 不存在")
        # 注册表里也要有 —— 定义了不注册，前端 `invoke` 一律报 "command not found"。
        handler = rs[rs.index("generate_handler!["):]
        self.assertIn("open_url", handler[:handler.index("]")],
                      "★★★ `open_url` 没进 `generate_handler!` —— 前端调不到")

    def test_the_replacement_goes_through_the_reaper(self):
        """★★★ 自己起的那一次**必须**收尸，否则只是把泄漏点从依赖搬进了本仓。"""
        body = self._open_url_body()
        self.assertIn("spawn_and_reap", body,
                      "★★★ `open_url` 没走 `spawn_and_reap` —— 泄漏点只是换了个家")
        self.assertNotIn(".spawn()", body,
                         "★★ `open_url` 里出现了裸 `spawn()`")

    def test_the_replacement_refuses_non_http_schemes(self):
        """★★ 这个参数最终交给系统的 URL 派发器（macOS `open` 会按 scheme 唤起任意应用）。
        没有白名单就等于把「让系统执行点什么」这个能力开给了前端。"""
        body = self._open_url_body()
        self.assertIn('"https://"', body, "★★ 没有 scheme 白名单")
        self.assertIn("return Err", body, "★★ 白名单没有拒绝分支 —— 检查了却不拦")


class NoZombiesAreActuallyAccumulating(unittest.TestCase):
    """★ **断言真实 `ps`** —— 前面全是静态/半静态判据，这条看现实。

    僵尸不占 CPU、几乎不占内存、app 一切正常，**永远不会自己报警**；
    所以最后要有一条真的去数进程表。
    """

    def test_no_process_we_own_has_zombie_children(self):
        if sys.platform != "darwin" and not sys.platform.startswith("linux"):
            raise unittest.SkipTest("非 unix，进程表语义不同")
        out = subprocess.run(["ps", "-Ao", "pid,ppid,stat,comm"],
                             capture_output=True, text=True, timeout=60).stdout
        rows = [l.split(None, 3) for l in out.splitlines()[1:]]
        self.assertTrue(rows, "★ ps 一行都没读到 —— 是探针坏了，不是系统干净")
        by_pid = {r[0]: (r[3] if len(r) > 3 else "") for r in rows if r}
        zombie_parents = {}
        for r in rows:
            if len(r) >= 3 and "Z" in r[2]:
                zombie_parents[r[1]] = zombie_parents.get(r[1], 0) + 1

        ours = {p: n for p, n in zombie_parents.items()
                if "codexbar" in by_pid.get(p, "").lower()}
        self.assertEqual(
            ours, {},
            "★★★ 正在运行的 CodexBar 底下有僵尸子进程：{}\n"
            "  → 说明还有一条 spawn 路径没走 `spawn_and_reap`。\n"
            "  ⚠️ 这条**只在本机装了并运行着 CodexBar 时**才有判别力；"
            "它为空不代表别的机器干净。".format(ours))


if __name__ == "__main__":
    unittest.main()
