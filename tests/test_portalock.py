"""跨平台文件锁的**行为**契约（`portalock.py`）。

## 这个测试为什么存在

Windows 端的锁实现在开发机（macOS）上**一行都跑不到**。而它守的是本仓库最贵的那条不变量：
两个进程同时刷同一个账号的 refresh_token = 掉号（CHANGELOG B7/B8/B14 连环事故）。
「看起来对」在这里不够。

所以这份测试**同一套断言在两个平台上跑**：macOS/Linux 上验真 `fcntl.flock`，
Windows 上（由 CI 的 windows-latest leg 执行）验 `LockFileEx` 分支。
两边必须给出**同样的可观察行为** —— 那才是「等价」的定义，而不是「都没报错」。

## 覆盖的四条性质

1. **互斥**：一个进程持锁时，另一个进程的非阻塞获取失败。
2. **异常类型是 `BlockingIOError`**：`_cred_lock(nonblock=True)` 的调用方（autosync）
   靠它判断「别人正持锁，本轮跳过」。抛别的类型那条 `except` 就接不住，
   症状是 autosync **静默停摆**而不是报错。
3. **崩溃自释放**：持锁进程被 `kill -9` / `TerminateProcess` 后，锁必须没了。
   否则一次崩溃就永久堵死整个账号池，比它要防的问题严重得多。
4. **阻塞获取会真的等**，不会自己放弃。★ 这条针对 `msvcrt.locking(LK_LOCK)` 那个陷阱：
   它重试约 10 秒就放弃并抛异常，而 `.refresh.lock` 要跨一整个 OAuth POST（实测可达 30 秒）
   —— 放弃就意味着第二个刷新者拿到了它以为的锁。
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import portalock  # noqa: E402


def _holder_script(path, hold_secs):
    """一个独立进程：拿到排他锁，报告 'LOCKED'，然后持有 hold_secs 秒。"""
    return textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(ROOT)!r})
        import portalock
        f = open({str(path)!r}, "w")
        portalock.flock(f, portalock.LOCK_EX)
        print("LOCKED", flush=True)
        time.sleep({hold_secs})
    """)


def _spawn_holder(path, hold_secs):
    p = subprocess.Popen([sys.executable, "-c", _holder_script(path, hold_secs)],
                         stdout=subprocess.PIPE, text=True)
    line = p.stdout.readline().strip()          # 等它确实拿到锁再继续
    if line != "LOCKED":
        p.kill()
        raise AssertionError("持锁子进程没能拿到锁: %r" % line)
    return p


class LockContract(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="portalock-test-")
        self.path = os.path.join(self.dir, "sentinel.lock")

    def tearDown(self):
        for n in os.listdir(self.dir):
            try:
                os.unlink(os.path.join(self.dir, n))
            except OSError:
                pass
        os.rmdir(self.dir)

    def test_constants_match_fcntl_on_posix(self):
        """POSIX 上必须是**同一个函数对象** —— 兼容层不许在这里引入任何行为差异。"""
        if os.name == "nt":
            self.skipTest("Windows 上没有 fcntl 可对照")
        import fcntl
        self.assertIs(portalock.flock, fcntl.flock)
        self.assertEqual(portalock.LOCK_EX, fcntl.LOCK_EX)
        self.assertEqual(portalock.LOCK_NB, fcntl.LOCK_NB)

    def test_exclusive_lock_actually_excludes(self):
        """① 互斥。这条要是坏了，两个进程会同时刷同一个 refresh_token。"""
        holder = _spawn_holder(self.path, 5)
        try:
            with open(self.path, "w") as f:
                with self.assertRaises(BlockingIOError):
                    portalock.flock(f, portalock.LOCK_EX | portalock.LOCK_NB)
        finally:
            holder.kill(); holder.wait()

    def test_nonblocking_failure_is_blockingioerror(self):
        """② 异常类型。★ autosync 的 `except BlockingIOError` 接不住别的类型，
        而接不住的症状是它**静默停摆**，不是报错 —— 所以类型本身就是契约。"""
        holder = _spawn_holder(self.path, 5)
        try:
            with open(self.path, "w") as f:
                try:
                    portalock.flock(f, portalock.LOCK_EX | portalock.LOCK_NB)
                    self.fail("锁被别人持有时非阻塞获取竟然成功了")
                except BlockingIOError:
                    pass
                except Exception as e:  # noqa: BLE001 —— 这里就是要看到真实类型
                    self.fail("应抛 BlockingIOError，实际 %s: %s" % (type(e).__name__, e))
        finally:
            holder.kill(); holder.wait()

    def test_lock_is_released_when_holder_is_killed(self):
        """③ 崩溃自释放。留下陈旧锁的话，一次崩溃就永久堵死整个池子。"""
        holder = _spawn_holder(self.path, 30)
        holder.kill()
        holder.wait()
        deadline = time.time() + 5
        last = None
        while time.time() < deadline:            # 内核回收句柄可能略有延迟
            try:
                with open(self.path, "w") as f:
                    portalock.flock(f, portalock.LOCK_EX | portalock.LOCK_NB)
                return                            # 拿到了 = 锁确实随进程死亡释放
            except BlockingIOError as e:
                last = e
                time.sleep(0.05)
        self.fail("持锁进程已被杀死 5 秒，锁仍未释放（陈旧锁）: %r" % last)

    def test_blocking_acquire_waits_instead_of_giving_up(self):
        """④ 阻塞获取要真的等。

        ★ 这条挡的是 `msvcrt.locking(LK_LOCK)`：它重试约 10 秒后**放弃并抛异常**。
          `.refresh.lock` 要跨一整个 OAuth POST（实测可达 30 秒），中途放弃 =
          第二个刷新者拿到它以为的锁 = 两边把同一个一次性 refresh_token 互相作废。

        判据：持锁 1.5 秒，阻塞获取必须**成功**且**耗时 ≥1 秒**（证明它是在等，
        而不是恰好抢在前面）。
        """
        holder = _spawn_holder(self.path, 1.5)
        try:
            t0 = time.time()
            with open(self.path, "w") as f:
                portalock.flock(f, portalock.LOCK_EX)   # 无 LOCK_NB：必须阻塞到拿到为止
            waited = time.time() - t0
            self.assertGreaterEqual(
                waited, 1.0,
                "阻塞获取只用了 %.2fs —— 它没有真的等待，可能压根没加上锁" % waited)
        finally:
            holder.kill(); holder.wait()


class WindowsImplementationShape(unittest.TestCase):
    """静态判据：Windows 分支不许退回到 `msvcrt.locking`。

    上面那条行为测试只在 Windows 上跑才验得到这一点，而开发机是 macOS ——
    所以再加一道 AST/文本闸，让**在 macOS 上改坏它也会当场变红**。
    """

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "portalock.py").read_text(encoding="utf-8")

    def test_uses_lockfileex_not_msvcrt_locking(self):
        """★ 判据打在 **AST** 上，不是原文。

        第一版按行滤注释再做子串匹配，被本文件自己的 docstring 染红了 —— 那段正在
        解释「为什么不用 msvcrt.locking」。**注释里出现 ≠ 代码里调用**，这是本仓库
        反复出现的空守卫形态，只不过这次它是往「假红」方向坏的。
        """
        import ast
        tree = ast.parse(self.src)
        # 真实的属性访问 msvcrt.locking（无论是否被调用）
        bad = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr == "locking"
               and isinstance(n.value, ast.Name) and n.value.id == "msvcrt"]
        self.assertEqual(bad, [],
                         "代码里真的调了 msvcrt.locking —— 它约 10 秒就放弃，"
                         "而 refresh 锁要跨 30 秒的 OAuth POST")
        # 反向:LockFileEx 必须真的被调用,不能只在文档里被提到
        called = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Attribute) and n.attr == "LockFileEx"]
        self.assertTrue(called, "代码里没有真正调用 LockFileEx —— 断言可能打空了")

    def test_nonblocking_path_raises_blockingioerror(self):
        """同样打在 AST 上。

        ★ 第一版写的是 `assertIn("BlockingIOError", self.src)` —— **变异测试当场证伪**：
          把 `raise BlockingIOError(...)` 改成 `raise OSError(...)` 之后它**照样绿**，
          因为上面的 docstring 里还写着这个词。子串存在 ≠ 规则存在。
        """
        import ast
        tree = ast.parse(self.src)
        raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
        names = []
        for r in raises:
            exc = r.exc
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                names.append(exc.func.id)
            elif isinstance(exc, ast.Name):
                names.append(exc.id)
        self.assertIn("BlockingIOError", names,
                      "代码里没有真的 `raise BlockingIOError` —— autosync 的 "
                      "`except BlockingIOError` 会接不住，症状是它静默停摆而不是报错。"
                      "当前 raise 的是: %s" % (sorted(set(names)) or "什么都没有"))


if __name__ == "__main__":
    unittest.main()
