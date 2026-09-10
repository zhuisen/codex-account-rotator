"""中转站配置存储与 codex profile 渲染的闸。

## ★★ 这份测试自己的第一条不变量:绝不碰真实数据

`relay.store` 读写两个地方 —— `$CODEX_ROTATE_STORE/relay/` 和 `$CODEX_HOME/`。
两个都必须在 setUp 里指向 tmpdir,而且要**双向验证**（本仓 testing-discipline 的原话:
「一个读了 ORM 还没填的环境变量的守卫,是个看起来像保护的空操作」）:
  - 不设变量时,模块指向的是仓库根 / `~/.codex` —— 那是真数据,测试绝不许跑到那里;
  - 设了变量后,模块必须真的跟着走。
`RealDataIsNeverTouched` 两个方向都验。
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

    def relay(self, **kw):
        return {"id": "tokendun", "label": "TokenDun",
                "base_url": "https://api.example-relay.test/v1",
                "key": "sk-TESTONLY-0000000000000000000000000000", **kw}


class RealDataIsNeverTouched(_Tmp):
    """★ 两个方向都验,否则守卫可能是个空操作。"""

    def test_with_env_set_the_module_follows_it(self):
        store.upsert(self.relay())
        self.assertTrue(store.store_path().exists())
        self.assertIn(self.tmp.name, str(store.store_path()))
        self.assertIn(self.tmp.name, str(store.codex_home()))

    def test_without_env_the_module_points_at_real_paths(self):
        """不设变量时它指向真实位置 —— 正因为如此,setUp 的隔离不是可选项。"""
        os.environ.pop("CODEX_ROTATE_STORE", None)
        os.environ.pop("CODEX_HOME", None)
        self.assertNotIn(self.tmp.name, str(store.store_path()))
        self.assertEqual(store.codex_home(), Path.home() / ".codex")

    def test_the_suite_left_no_fake_relay_in_the_real_store(self):
        """★ 判据从「真实 store 不存在」改成「真实 store 里没有测试的假数据」
        （2026-09-09）:用户现在真的配了中转站,那个文件**应该**存在。
        原判据会在功能真正投入使用的那一刻变红 —— 一个「东西开始工作就报警」的闸
        只会被人关掉。要守的从来是**污染**,不是**存在**。"""
        store.upsert(self.relay(key=KeysNeverLeak.SECRET))
        os.environ.pop("CODEX_ROTATE_STORE", None)
        real = store.store_path()
        if not real.exists():
            return
        txt = real.read_text(encoding="utf-8")
        self.assertNotIn("TESTONLY", txt, f"测试的假凭证写进了真实配置: {real}")
        self.assertNotIn("example-relay.test", txt, f"测试的假 base_url 进了真实配置: {real}")


class KeysNeverLeak(_Tmp):
    SECRET = "sk-TESTONLY-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def test_redacted_output_contains_no_key_material(self):
        store.upsert(self.relay(key=self.SECRET))
        blob = json.dumps(store.redacted(), ensure_ascii=False)
        self.assertNotIn(self.SECRET, blob)
        self.assertNotIn(self.SECRET[8:24], blob, "key 中段也不许出现")
        self.assertNotIn('"key"', blob, "redacted 里不该还留着 key 字段")
        self.assertIn("key_fp", blob)

    def test_fingerprint_distinguishes_two_keys_with_the_same_prefix(self):
        """★ 只取前缀会让同一家签发的两把 key 看起来一样 —— 本机就真有两把
        都是 67 位、都以 `sk-` 开头的 key。指纹必须能区分。"""
        a = "sk-abcdef" + "1" * 40
        b = "sk-abcdef" + "2" * 40
        self.assertNotEqual(store.fingerprint(a), store.fingerprint(b))

    def test_empty_key_fingerprints_to_empty_not_to_a_hash(self):
        """空 key 给个哈希会让「没配」看起来像「配了」。"""
        self.assertEqual(store.fingerprint(""), "")


class FilePermissionsAndAtomicity(_Tmp):
    def test_store_is_0600(self):
        store.upsert(self.relay())
        mode = stat.S_IMODE(store.store_path().stat().st_mode)
        self.assertEqual(mode, 0o600, f"含 key 的文件权限是 {oct(mode)}")

    def test_no_temp_file_is_left_behind(self):
        store.upsert(self.relay())
        leftovers = list(store.store_path().parent.glob("*.tmp*"))
        self.assertEqual(leftovers, [], f"原子写留下了临时文件: {leftovers}")

    def test_route_file_is_readable_because_cxp_reads_it_every_launch(self):
        """★ 路由文件**不含密钥**,而 cxp 每次启动都要读它。给 0600 没必要,
        但更重要的是别把它和含密钥的那份混为一谈。"""
        store.set_route(store.POOL_PROFILE)
        self.assertEqual(stat.S_IMODE(store.route_path().stat().st_mode), 0o644)


class Validation(_Tmp):
    def test_reserved_ids_are_refused(self):
        """`openai` 等内置 id 不可覆盖（codex 0.154 硬报 reserved built-in provider IDs）;
        `rotateproxy` 被占用会把两条路由搅在一起。"""
        for bad in ("openai", "codex", "rotateproxy"):
            with self.subTest(id=bad):
                cfg, errs = store.upsert(self.relay(id=bad))
                self.assertIsNone(cfg)
                self.assertTrue(any("保留名" in e for e in errs), errs)

    def test_id_charset_blocks_path_traversal(self):
        """id 直接当文件名用（`~/.codex/<id>.config.toml`）。"""
        for bad in ("../evil", "a/b", "A-Upper", "x", "with space", ""):
            with self.subTest(id=bad):
                cfg, errs = store.upsert(self.relay(id=bad))
                self.assertIsNone(cfg, f"{bad!r} 不该被接受")

    def test_pasting_the_full_endpoint_is_caught(self):
        """最常见的粘贴错误:把 `…/v1/chat/completions` 当 base_url 填进来。"""
        cfg, errs = store.upsert(self.relay(base_url="https://x.test/v1/chat/completions"))
        self.assertIsNone(cfg)
        self.assertTrue(any("完整端点" in e for e in errs), errs)

    def test_non_http_scheme_is_refused(self):
        self.assertIsNone(store.upsert(self.relay(base_url="ftp://x.test/v1"))[0])

    def test_empty_key_is_refused(self):
        self.assertIsNone(store.upsert(self.relay(key="  "))[0])

    def test_a_rejected_upsert_does_not_write(self):
        """★ 校验失败还落盘 = 半个坏配置留在那里。"""
        store.upsert(self.relay())
        before = store.store_path().read_text()
        store.upsert(self.relay(id="openai"))
        self.assertEqual(store.store_path().read_text(), before)


class UsagePathIsThreeStateNotTwo(_Tmp):
    def test_a_new_relay_has_usage_path_none_not_a_default(self):
        """★★ `None`（没探测过）和 `"/usage"`（探测过就是它）**不是同一个状态**。
        预设成 `/usage` 会把「没查过」伪装成「已知」—— 而各家中转站的计费端点不一样
        （one-api/new-api 走 `/dashboard/billing/…`,本站实测 404）。"""
        store.upsert(self.relay())
        self.assertIsNone(store.get("tokendun")["usage_path"])

    def test_a_probed_path_survives_a_later_edit(self):
        store.upsert(self.relay())
        store.upsert({**store.get("tokendun"), "usage_path": "/usage"})
        store.upsert({**store.get("tokendun"), "label": "改个名"})
        self.assertEqual(store.get("tokendun")["usage_path"], "/usage")


class RemoveCleansUpEverything(_Tmp):
    """`remove` 还要**顺手清掉 2026-09-09 之前留下的每中转站一份 profile**。

    新模型下 codex 不再加载那些文件，但它们里面有明文可读的 `base_url` 与脚本路径，
    留着只会误导下一次排查。★ 只删带托管标记的 —— 没标记 = 用户或别的工具写的。
    """

    def _legacy_profile(self, rid="tokendun", managed=True):
        p = self.home / f"{rid}.config.toml"
        body = f'model_provider = "{rid}"\n'
        if managed:
            body = f"{store.MARK_BEGIN}\n{body}{store.MARK_END}\n"
        p.write_text(body)
        return p

    def test_removing_a_relay_resets_the_route_and_deletes_its_legacy_profile(self):
        store.upsert(self.relay())
        store.set_route("tokendun")
        p = self._legacy_profile()
        self.assertTrue(store.remove("tokendun"))
        self.assertEqual(store.active_route(), store.POOL_PROFILE)
        self.assertFalse(p.exists(), "遗留 profile 没被清掉")

    def test_a_hand_written_profile_is_never_deleted(self):
        """★ 没有托管标记 = 不是我们写的。静默盖掉/删掉别人的配置比不动更糟。"""
        store.upsert(self.relay())
        p = self._legacy_profile(managed=False)
        store.remove("tokendun")
        self.assertTrue(p.exists(), "删掉了一个不属于本工具的文件")

    def test_removing_something_else_does_not_touch_the_active_route(self):
        store.upsert(self.relay())
        store.upsert(self.relay(id="other", label="Other"))
        store.set_route("tokendun")
        store.remove("other")
        self.assertEqual(store.active_route(), "tokendun")

    def test_reserved_names_are_refused(self):
        """★★ `remove("rotateproxy")` 曾会删掉**账号池的** overlay 而返回 `False`
        （「没删到中转站」）—— 删了最要紧的东西却报告"什么也没删"，
        之后所有 cxp 直接 exit 78。"""
        with self.assertRaises(KeyError):
            store.remove("rotateproxy")


class CorruptStoreIsPreservedNotSilentlyDropped(_Tmp):
    def test_bad_json_is_renamed_aside_not_overwritten(self):
        """★ 「配置丢了」和「从来没配过」不能返回同一个值 —— 坏文件留档才查得清。"""
        store.upsert(self.relay())
        store.store_path().write_text("{ this is not json")
        self.assertEqual(store.load()["relays"], [])
        kept = list(store.store_path().parent.glob("*.corrupt-*"))
        self.assertEqual(len(kept), 1, "坏配置被静默丢弃了")


class RouteStatusUnderOneProviderTwoUpstreams(_Tmp):
    """★★ 2026-09-09 定稿后的路由五态。

    中转站不再有自己的 codex profile，所以 `profile_stale` 整条分支消失了。
    剩下的每一态都对应一种**「看起来正常、其实不是」**，而其中三种的共同后果是
    代理**退回账号池** —— 用户以为在按量付费，实际扣的是订阅额度。
    这三种必须彼此分开报，因为修法完全不同。
    """

    def _pool_profile(self):
        """账号池那份 profile。现在它是**唯一**需要存在的 profile。"""
        (self.home / "rotateproxy.config.toml").write_text('model_provider = "rotateproxy"\n')

    def test_pool(self):
        self._pool_profile()
        st = store.route_status()
        self.assertEqual(st["state"], "pool")

    def test_relay(self):
        self._pool_profile()
        store.upsert(self.relay())
        store.set_route("tokendun")
        st = store.route_status()
        self.assertEqual(st["state"], "relay")
        self.assertEqual(st["label"], "TokenDun")
        # ★ 只出指纹，绝不出完整 key。
        self.assertNotIn(self.relay()["key"], json.dumps(st))

    def test_missing_pool_profile_is_reported_even_when_routed_to_a_relay(self):
        """★ 中转站档也走 rotateproxy 这份 profile —— 它没了同样是静默失败。"""
        store.upsert(self.relay())
        store.set_route("tokendun")
        st = store.route_status()
        self.assertEqual(st["state"], "profile_missing")
        self.assertIn("rotateproxy.config.toml", st["path"])

    def test_orphan_says_the_pool_is_being_billed(self):
        """路由指着一个已删除的中转站 ⇒ 代理退回账号池。
        ★ 文案必须点明"实际扣的是订阅额度" —— 只说"孤儿"用户不会意识到钱走哪儿了。"""
        self._pool_profile()
        store.upsert(self.relay())
        store.set_route("tokendun")
        # 绕过 remove()（它会顺手把路由复位），直接制造不一致。
        cfg = store.load()
        cfg["relays"] = []
        store.save(cfg)
        st = store.route_status()
        self.assertEqual(st["state"], "orphan")
        self.assertIn("订阅额度", st["detail"])

    def test_disabled_relay_is_its_own_state(self):
        """★ 与 orphan 分开：修法不同（一个要重新登记，一个只要启用）。
        本仓铁律——告警要说「做什么」，那就不能把两种不同的「做什么」折叠成一句。"""
        self._pool_profile()
        store.upsert(self.relay())
        store.set_route("tokendun")
        store.patch("tokendun", enabled=False)
        st = store.route_status()
        self.assertEqual(st["state"], "relay_disabled")
        self.assertIn("订阅额度", st["detail"])

    def test_corrupt_route_is_not_silently_the_pool(self):
        self._pool_profile()
        store.route_path().parent.mkdir(parents=True, exist_ok=True)
        store.route_path().write_text("{ broken")
        self.assertEqual(store.route_status()["state"], "route_corrupt")

    def test_profile_stale_is_gone_for_good(self):
        """★ 负面结论也要钉住：这个态**不该再出现**。
        留一个永不返回的分支比删掉更糟 —— 下一个人会照着它写 UI 和文案。

        ★★ 判据走 **AST 常量**不走源码文本：第一版用 `not in inspect.getsource(...)`，
           被 `route_status` 自己**解释这一改动的 docstring** 判红。同一台机器上
           同一个下午踩了两次同形状的错（另一次在 tests/test_proxy_relay_upstream.py）。
        """
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(store.route_status)))
        fn = tree.body[0]
        body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                               and isinstance(fn.body[0].value, ast.Constant)) else fn.body
        lits = {n.value for stmt in body for n in ast.walk(stmt)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertNotIn("profile_stale", lits,
                         "route_status 仍会返回 profile_stale —— 该分支应随架构改动一起删除")
