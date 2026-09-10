"""中转站配置的并发写与跨平台导入。

## 为什么这两条放一起

它们是同一个东西的两半：`_store_lock()` 用 `fcntl.flock`，
而 `fcntl` 在 Windows 上不存在。锁没闸 = 删掉它全绿；
导入没闸 = Windows 上整个 `relay-ctl` ImportError，
而 Rust 收到空 stdout、页面同时渲染"还没有配置中转站" —— 一句关于事实的假陈述。

两条都是 Fable 复核抓到的：锁**当时确实是零闸**（`with _store_lock()` 那行删掉全绿），
`import fcntl` 是**回归**（`codex-rotate:23` 与 `proxy.py:22` 早就是 try/except 写法）。
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relay import store  # noqa: E402


class TopLevelFcntlWouldBreakWindows(unittest.TestCase):
    """★★ 本仓是双平台。`codex-rotate` 与 `proxy.py` 都用
    `try: import fcntl / except ModuleNotFoundError: import portalock as fcntl`。
    裸导入是**回归**，而它在开发机上永远复现不了。"""

    # 会被打进 app、在 Windows 上也要跑的 Python 文件。
    SHIPPED = ["codex-rotate", "relay-ctl", "grok-quota", "agy-quota",
               "relay/store.py", "relay/monitor.py", "relay/relay-key",
               "proxy/proxy.py", "traffic/scan.py"]

    def test_no_shipped_file_imports_fcntl_unguarded(self):
        offenders = []
        for rel in self.SHIPPED:
            p = ROOT / rel
            if not p.exists():
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # 只看**顶层**的裸 import（try 体里的不算 —— 那正是正确写法）。
                if isinstance(node, ast.Import) and any(a.name == "fcntl" for a in node.names):
                    if not self._inside_try(tree, node):
                        offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [], f"裸 import fcntl（Windows 上会 ImportError）: {offenders}")

    @staticmethod
    def _inside_try(tree, target):
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    if child is target:
                        return True
        return False

    def test_the_probe_would_catch_a_bare_import(self):
        """★ 先证探针有效 —— 一个永远找不到东西的扫描器会恒绿。"""
        tree = ast.parse("import fcntl\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Import))
        self.assertFalse(self._inside_try(tree, node))

    def test_it_accepts_the_guarded_form(self):
        tree = ast.parse("try:\n    import fcntl\nexcept ModuleNotFoundError:\n    pass\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Import))
        self.assertTrue(self._inside_try(tree, node), "把正确写法也判成违规了")


class ConcurrentWritesDoNotLoseFields(unittest.TestCase):
    """★★ 原子写只保证**文件完整**，不保证**不丢更新**。

    真实场景：`relay-ctl usage`（落盘探到的计费端点）与 UI 的 `set` 是两个进程，
    而在 app 里它们走**两把不同的 Rust 锁**、可以并发；中转站不可达时 `usage`
    最长跑 100s —— 正是用户最想改配置的那一刻。

    原实现 `row = get(rid); upsert({**row, ...})` 的 RMW **跨在锁外**：
    `get` 与 `upsert` 之间落进来的修改会被那份旧快照原样盖回去，
    flock 只序列化了两次 `save()`，等于没锁。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._env = {k: os.environ.get(k) for k in ("CODEX_ROTATE_STORE", "CODEX_HOME")}
        os.environ["CODEX_ROTATE_STORE"] = str(Path(self.tmp.name) / "store")
        os.environ["CODEX_HOME"] = str(Path(self.tmp.name) / "home")
        Path(os.environ["CODEX_HOME"]).mkdir(parents=True)
        self.addCleanup(self._restore)
        store.upsert({"id": "r1", "label": "L0", "base_url": "https://a.test/v1",
                      "key": "sk-TESTONLY-1"})

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_patch_and_upsert_interleaved_lose_nothing(self):
        """★ 一边反复 `patch(usage_path=…)`（monitor 那条路），
        一边反复 `upsert(label=…)`（UI 那条路）。结束后两边的最后一次写都必须还在。"""
        N = 40

        def patcher():
            for i in range(N):
                store.patch("r1", usage_path=f"/u{i}")

        def setter():
            for i in range(N):
                store.upsert({"id": "r1", "label": f"L{i}",
                              "base_url": "https://a.test/v1", "key": "sk-TESTONLY-1"})

        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(lambda f: f(), [patcher, setter]))

        row = store.get("r1")
        self.assertIsNotNone(row, "并发之后行整个没了")
        self.assertEqual(row["label"], f"L{N-1}", "UI 的最后一次修改被覆盖了")
        self.assertIsNotNone(row["usage_path"], "monitor 的写入被覆盖了")
        self.assertEqual(row["key"], "sk-TESTONLY-1", "key 在并发里丢了")

    def test_the_store_never_becomes_unparseable(self):
        """★ 原子写守的是这一条 —— 读者绝不能读到半截 JSON。"""
        def churn(n):
            for i in range(n):
                store.patch("r1", model=f"m{i}")

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(churn, [25] * 4))
        json.loads(store.store_path().read_text(encoding="utf-8"))

    def test_an_edit_payload_without_usage_path_does_not_clear_it(self):
        """★★ 前端编辑表单只送 id/label/base_url/key/model。整行重建会把
        `usage_path` 清回 None（下次白跑 3 个探测），把 CLI 停用的中转站**静默重新启用**
        —— 后者是"用户明确关掉的东西自己回来了"，最不该发生的一类。"""
        store.patch("r1", usage_path="/usage", enabled=False)
        store.upsert({"id": "r1", "label": "改个名", "base_url": "https://a.test/v1",
                      "key": "sk-TESTONLY-1"})
        row = store.get("r1")
        self.assertEqual(row["usage_path"], "/usage", "编辑把探测结果清掉了")
        self.assertFalse(row["enabled"], "编辑把用户停用的中转站又打开了")

    def test_an_explicit_enabled_still_wins(self):
        """★ 反方向：显式传了就得听它的，否则"沿用旧值"会变成"永远改不了"。"""
        store.patch("r1", enabled=False)
        store.upsert({"id": "r1", "label": "L", "base_url": "https://a.test/v1",
                      "key": "sk-TESTONLY-1", "enabled": True})
        self.assertTrue(store.get("r1")["enabled"])


class TheLockIsActuallyTaken(unittest.TestCase):
    """★ 判据是**源码里那几个写入口都在锁内**。上面的并发测试在单机上可能
    恰好不撞车而假绿；这条是结构闸，两条挡的是同一件事的不同侧。"""

    SRC = Path(store.__file__).read_text(encoding="utf-8")

    def _body(self, name):
        i = self.SRC.index(f"def {name}(")
        j = self.SRC.find("\ndef ", i + 1)
        return self.SRC[i:j if j > 0 else len(self.SRC)]

    def test_every_read_modify_write_entrypoint_holds_the_lock(self):
        for fn in ("patch", "upsert", "remove"):
            with self.subTest(fn=fn):
                self.assertIn("_store_lock()", self._body(fn),
                              f"{fn} 的 read-modify-write 在锁外")

    def test_the_locked_helper_documents_that_it_must_not_relock(self):
        """★ flock 在同进程用第二个 fd 取会**阻塞**。将来谁在锁内调 `upsert()`
        就是静默堵住 UI —— 而"卡住"和"在算"看起来一样。把约定写在函数里。"""
        self.assertIn("持锁调用", self._body("_upsert_locked"))


if __name__ == "__main__":
    unittest.main()
