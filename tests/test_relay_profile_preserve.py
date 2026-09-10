"""Phase 0 的三条新不变量：托管区保留 · `profile_stale` · 删除顺序。

每一条都是 Fable 评审用真 codex 跑出来的，不是推断。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import store  # noqa: E402

# codex 真的会往 profile overlay 里写这些（本机 rotateproxy.config.toml 里 12 行）。
CODEX_WRITEBACK = '''
[hooks.state."/Users/x/.codex/hooks.json:pre_tool_use:1:0"]
trusted_hash = "sha256:8b2b85a0548ad9ebd02f000ec8cd728101de473d1c0c47788dbb3f08fc5d7b50"

[tui.model_availability_nux]
gpt-6-astra = 4

[projects."/Users/x/Projects"]
trust_level = "trusted"
'''


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "codex-home"
        self.home.mkdir()
        self._env = {k: os.environ.get(k) for k in ("CODEX_ROTATE_STORE", "CODEX_HOME")}
        os.environ["CODEX_ROTATE_STORE"] = str(root / "store")
        os.environ["CODEX_HOME"] = str(self.home)
        self.addCleanup(self._restore)
        store.upsert({"id": "tokendun", "label": "TokenDun",
                      "base_url": "https://a.test/v1", "key": "sk-TESTONLY-1"})

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
class RemoveResetsTheRouteBeforeDeletingTheFile(_Tmp):
    """★ 顺序不能反。先删文件再复位路由的话,中间任何一次 cxp 启动都会撞上
    `profile_missing` —— 而 codex 对它不报错,直接静默退回 base 配置。"""

    def test_the_route_never_points_at_a_deleted_profile(self):
        # 手写一份**遗留** profile（新架构不再生成，但 remove() 仍要清掉它）。
        (self.home / "tokendun.config.toml").write_text(
            f'{store.MARK_BEGIN}\nmodel_provider = "tokendun"\n{store.MARK_END}\n',
            encoding="utf-8")
        store.set_route("tokendun")
        store.remove("tokendun")
        self.assertEqual(store.active_route(), store.POOL_PROFILE)
        self.assertFalse((self.home / "tokendun.config.toml").exists())

    def test_the_source_resets_the_route_first(self):
        """★ 判据是**源码里的顺序**。行为测试看不出中间那个瞬间的窗口 ——
        它只在崩溃/并发时才显形,而那正是最难复现的时刻。"""
        src = (Path(store.__file__)).read_text(encoding="utf-8")
        body = src[src.index("def remove("):src.index("def get(")]
        # ★ 2026-09-10：删文件那一步抽成了 `drop_managed_profile()`（`remove()` 与
        #   `relay-ctl cleanup` 共用一条归属判据）。**不变量没变**，锚点跟着换。
        self.assertLess(body.index("set_route(POOL_PROFILE)"),
                        body.index("drop_managed_profile("),
                        "先动文件后复位路由 —— 中间那一瞬是 profile_missing")


if __name__ == "__main__":
    unittest.main()
