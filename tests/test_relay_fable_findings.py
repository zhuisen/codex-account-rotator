"""Fable 阶段性复核（2026-09-09）抓到的 6 条，每条一个闸。

这一轮的共同形态：**我写了不变量，但只在一条路径上实现了它**。
另一条路径不但没守，还反过来做了同一条注释里明令禁止的事。
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import store  # noqa: E402


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

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def add(self, rid="tokendun", **kw):
        """登记一个中转站，并造出一份**遗留** profile（2026-09-09 之前的产物）。

        ★ 新架构不再生成这些文件，但 `remove()` 仍要负责清掉它们 —— 所以这里手写，
          而不是调一个已经删掉的 `write_profile`。
        """
        store.upsert({"id": rid, "label": "T", "base_url": "https://a.test/v1",
                      "key": "sk-TESTONLY-1", **kw})
        p = self.home / f"{rid}.config.toml"
        p.write_text(f'{store.MARK_BEGIN}\nmodel_provider = "{rid}"\n{store.MARK_END}\n',
                     encoding="utf-8")
        return p


class RemoveOnlyDeletesWhatWeOwn(_Tmp):
    """★★★ 最高危的一条。原实现不查所有权，直接 `prof.unlink()`。

    实测（修之前）：
        remove('rotateproxy') -> False        # 返回"没删到中转站"
        ~/.codex/rotateproxy.config.toml       # 但账号池的 overlay 没了
    那份文件里有 12 行 codex 回写的 hooks 信任哈希 + 项目信任，删掉之后**所有运行时
    `cxp` 直接 exit 78**。而返回值还说"什么也没删" —— 删了最要紧的东西却报告无事发生。
    Rust 侧的字符集校验放行 `rotateproxy`（它符合 id 规则），所以这条路是通的。
    """

    def test_the_account_pool_overlay_survives(self):
        pool = self.home / "rotateproxy.config.toml"
        pool.write_text("# 账号池的,含 codex 回写\n", encoding="utf-8")
        with self.assertRaises(KeyError):
            store.remove("rotateproxy")
        self.assertTrue(pool.exists(), "账号池的 overlay 被删了 —— 所有 cxp 会 exit 78")

    def test_a_hand_written_profile_survives(self):
        mine = self.home / "mine.config.toml"
        mine.write_text("# 用户手写的\n", encoding="utf-8")
        with self.assertRaises(KeyError):
            store.remove("mine")
        self.assertTrue(mine.exists())

    def test_a_registered_relay_is_still_removable(self):
        """★ 反方向:该删的必须删得掉。一个"什么都不删"的实现也能让上面两条绿。"""
        p = self.add()
        self.assertTrue(store.remove("tokendun"))
        self.assertFalse(p.exists())
        self.assertIsNone(store.get("tokendun"))

    def test_an_unmarked_file_with_a_registered_id_is_left_alone(self):
        """★ 配置在、但那个 `<id>.config.toml` 不是我们写的 ⇒ 删配置,不删文件。"""
        store.upsert({"id": "tokendun", "label": "T",
                      "base_url": "https://a.test/v1", "key": "sk-TESTONLY-1"})
        f = self.home / "tokendun.config.toml"
        f.write_text("# 别人的文件\n", encoding="utf-8")
        store.remove("tokendun")
        self.assertTrue(f.exists(), "删掉了没有托管标记的文件")


class ACorruptRouteIsNotSilentlyThePool(_Tmp):
    """★★ 同一条规则的两份实现，在边界输入上必须一致。

    `cxp` 对坏路由文件是 **exit 78**（它的注释还明写"不许当作账号池"），
    而 Python 侧原来是 `except Exception: return POOL_PROFILE` —— 正是它禁止的写法。
    症状：`health` 与 `relay-ctl status` 绿着说"路由:账号池"，
    而用户的 `codex` 一条都跑不起来。
    """

    def route(self, raw):
        d = Path(os.environ["CODEX_ROTATE_STORE"]) / "relay"
        d.mkdir(parents=True, exist_ok=True)
        (d / "route.local.json").write_text(raw, encoding="utf-8")

    def test_every_malformed_shape_is_reported_as_corrupt(self):
        for bad in ('{"profile": null}', "{", "[]", '{"profile": ""}',
                    '{"profile": 3}', '"just a string"'):
            with self.subTest(raw=bad):
                self.route(bad)
                self.assertIsNone(store.active_route(), f"{bad!r} 被当成了一个合法路由")
                self.assertEqual(store.route_status()["state"], "route_corrupt")

    def test_path_traversal_in_the_profile_name_is_refused(self):
        """★ profile 名同时是文件名。原实现对 `../evil` **直接返回**，
        而 `codex_home() / f"{rid}.config.toml"` 会拼成 `~/.codex/../evil.config.toml`。
        cxp 那半早就校验了，Python 这半漏了。"""
        for bad in ("../evil", "a/b", "Has-Upper", "x"):
            with self.subTest(name=bad):
                self.route(json.dumps({"profile": bad}))
                self.assertIsNone(store.active_route())
                self.assertEqual(store.route_status()["state"], "route_corrupt")

    def test_a_missing_route_file_really_is_the_pool(self):
        """★ 反方向:没配过 = 账号池,这才是真正的默认。
        一个"什么都判 corrupt"的实现也能让上面两条绿。"""
        self.assertEqual(store.active_route(), store.POOL_PROFILE)
        (self.home / "rotateproxy.config.toml").write_text("x=1\n")
        self.assertEqual(store.route_status()["state"], "pool")
class TheFingerprintIsNeverMistakenForAKey(unittest.TestCase):
    """★★ 前端把 `key_fp` 回填进 key 框是最自然的写法。那串指纹**非空**、能过
    `validate()`，会被当成真 key 写进配置 ⇒ 中转站当场 401，
    而症状「key 失效」和「key 真的过期了」**一模一样**。"""

    def test_the_shape_matcher_accepts_real_fingerprints(self):
        import importlib.machinery, importlib.util
        ROOT = Path(__file__).resolve().parents[1]
        l = importlib.machinery.SourceFileLoader("relay_ctl_mod", str(ROOT / "relay-ctl"))
        m = importlib.util.module_from_spec(importlib.util.spec_from_loader(l.name, l))
        l.exec_module(m)
        for key in ("sk-73a1234567890abcdef", "sk-proj-" + "z" * 60, "abc"):
            with self.subTest(key=key):
                fp = store.fingerprint(key)
                self.assertTrue(m._looks_like_fingerprint(fp), f"认不出自己的指纹: {fp!r}")

    def test_real_keys_are_not_mistaken_for_fingerprints(self):
        """★ 反方向:真 key 绝不能被判成指纹,否则用户换 key 会静默失败。"""
        import importlib.machinery, importlib.util
        ROOT = Path(__file__).resolve().parents[1]
        l = importlib.machinery.SourceFileLoader("relay_ctl_mod2", str(ROOT / "relay-ctl"))
        m = importlib.util.module_from_spec(importlib.util.spec_from_loader(l.name, l))
        l.exec_module(m)
        for key in ("sk-73a1234567890abcdef", "sk-proj-" + "z" * 60,
                    "sk-abc (0f39111c7caf)"):
            with self.subTest(key=key):
                self.assertFalse(m._looks_like_fingerprint(key), f"真 key 被判成指纹: {key!r}")


if __name__ == "__main__":
    unittest.main()
