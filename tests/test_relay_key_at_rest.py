"""★★★ 中转站 api key 的**静止面**：落盘、指纹、以及"清理"时删掉了什么。

传输面在 `test_relay_key_transport.py`。这一份管三件同样不出声的事：

① **临时文件的权限窗口。** `Path.write_text` 按 umask 建文件（通常 0644），
   之后才 chmod 0600 —— 那之间这份含明文 key 的文件是全局可读的。
   原 docstring 只承诺「chmod 要在 rename 之前」，那条是对的、也做到了，
   但它挡的是 rename 之后的窗口。**一条只覆盖一半的规则读起来和覆盖全部一样。**

② **指纹是个验证预言机。** `sha256[:12]` = 48 bit，拿猜测一比就知道对不对；
   再露出首尾 10 个明文字符，一把 18 字符的 key 只剩 8 个未知位 ⇒ 离线可暴力。
   而指纹会进 0644 的快照文件、进日志、进截图。

③ **"只删我们写的"必须真的只删我们写的。** 判据是"文件里出现过托管标记"，
   而用户可能在那段前后写了自己的东西 —— 原实现命中标记就删掉**整个文件**。
"""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from relay import store

SECRET = "sk-AT-REST-DO-NOT-LEAK-0123456789abcdef"


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "codex-home").mkdir()
        self._env = {k: os.environ.get(k) for k in ("CODEX_ROTATE_STORE", "CODEX_HOME")}
        os.environ["CODEX_ROTATE_STORE"] = str(root / "store")
        os.environ["CODEX_HOME"] = str(root / "codex-home")
        self.addCleanup(self._restore)
        self.root = root

    def _restore(self):
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class TheKeyIsNeverWorldReadableEvenForAnInstant(_Tmp):

    def test_the_temp_file_is_created_0600_not_chmodded_to_it(self):
        """★★ 判据打在**创建的那一刻**，不是最终结果。

        只看最终文件权限的话，`write_text` + `chmod` 与 `os.open(mode)` **完全一样** ——
        闸换任何实现都绿，是个空守卫。所以这里在 `os.open` 上打桩，
        断言调用时就带了 0600，并且中途没有任何一刻是更宽的。
        """
        seen = []
        real_open = os.open

        def spy(path, flags, mode=0o777, **kw):
            if ".tmp" in str(path):
                seen.append((str(path), flags, mode))
            return real_open(path, flags, mode, **kw)

        os.open = spy
        try:
            store.upsert({"id": "r1", "label": "R", "base_url": "https://a.test/v1",
                          "key": SECRET})
        finally:
            os.open = real_open
        self.assertTrue(seen, "★ 没走 os.open —— 多半又退回了 write_text，权限窗口回来了")
        _, flags, mode = seen[0]
        self.assertEqual(mode & 0o777, 0o600, f"创建时的 mode 是 {oct(mode)}，不是 0600")
        self.assertTrue(flags & os.O_EXCL, "★ 没带 O_EXCL —— 会跟随残留的符号链接")

    def test_the_final_file_is_0600(self):
        store.upsert({"id": "r1", "label": "R", "base_url": "https://a.test/v1", "key": SECRET})
        m = stat.S_IMODE(store.store_path().stat().st_mode)
        self.assertEqual(m, 0o600, f"最终权限 {oct(m)}")

    def test_no_temp_file_survives(self):
        store.upsert({"id": "r1", "label": "R", "base_url": "https://a.test/v1", "key": SECRET})
        leftovers = list(store.store_path().parent.glob("*.tmp*"))
        self.assertEqual(leftovers, [], f"临时文件没清掉: {leftovers}")


class TheFingerprintIsNotAnOracle(_Tmp):

    def test_it_leaks_no_plaintext_tail(self):
        """★★ 尾巴是**多余的那一份**：哈希已经承担了"区分同前缀的两把"。
        留着它等于白送 3 个明文字符给离线暴力。"""
        fp = store.fingerprint(SECRET)
        self.assertNotIn(SECRET[-3:], fp, f"指纹里带了明文尾巴: {fp}")
        self.assertNotIn(SECRET[-1], fp.split("(")[0], f"前半段带了尾字符: {fp}")

    def test_the_prefix_shrinks_with_short_keys(self):
        """★ 短 key 上固定露 7 位等于露掉大半。"""
        # 规则:`len(head) <= max(1, min(7, len(key)//3))` —— 期望值**从规则算**，
        # 不手抄，否则改了规则要改两处、而测试会挡住的正是那次改动。
        for key in ("sk-abcdefghijkl", "sk-abcdef", "sk-a", SECRET):
            with self.subTest(key=key):
                head = store.fingerprint(key).split("…")[0]
                self.assertLessEqual(len(head), max(1, min(7, len(key) // 3)),
                                     f"{key!r} 露了 {head!r}（{len(head)}/{len(key)}）")

    def test_it_still_distinguishes_two_keys_with_the_same_prefix(self):
        """★ 反向闸：去掉尾巴不能把"区分"这个职责一起去掉。"""
        a = store.fingerprint("sk-same-prefix-AAAAAAAAAAAAAAAAAAAA")
        b = store.fingerprint("sk-same-prefix-BBBBBBBBBBBBBBBBBBBB")
        self.assertNotEqual(a, b)

    def test_it_still_looks_like_a_fingerprint_to_the_write_back_guard(self):
        """★★ `relay-ctl::_looks_like_fingerprint` 靠形状认它。形状一变、那道闸就失效，
        而失效的表现是**指纹被当成真 key 写进配置** ⇒ 中转站 401，
        症状与"key 真的过期了"一模一样。"""
        import importlib.util
        spec = importlib.util.spec_from_loader("relayctl", loader=None)
        mod = importlib.util.module_from_spec(spec)
        src = Path(__file__).resolve().parent.parent / "relay-ctl"
        # ★ `relay-ctl` 顶上用 `__file__` 拼 sys.path —— exec 进一个空 namespace 时
        #   它不存在,会 NameError。给它。
        mod.__dict__["__file__"] = str(src)
        exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), mod.__dict__)
        self.assertTrue(mod._looks_like_fingerprint(store.fingerprint(SECRET)),
                        f"新指纹形状过不了回填闸: {store.fingerprint(SECRET)}")
        self.assertFalse(mod._looks_like_fingerprint(SECRET), "真 key 被当成指纹了")


class CleanupRemovesOnlyWhatWeWrote(_Tmp):
    """★★ `remove()` 与 `relay-ctl cleanup` 用**同一个** `drop_managed_profile` ——
    这条规则以前是两份实现，所以两边同时错。"""

    def _profile(self, name, before="", after=""):
        p = store.codex_home() / f"{name}.config.toml"
        p.write_text(before + store.MARK_BEGIN + "\nmanaged = true\n" + store.MARK_END + after,
                     encoding="utf-8")
        return p

    def test_a_purely_managed_file_is_deleted(self):
        p = self._profile("solo")
        self.assertEqual(store.drop_managed_profile(p), "removed")
        self.assertFalse(p.exists())

    def test_user_content_around_our_block_is_preserved(self):
        """★★★ 这是本条的全部意义。原实现在这里 `unlink()` 整份。"""
        mine = '# 我自己写的\nmodel_reasoning_effort = "xhigh"\n'
        tail = "\n[projects]\nfoo = 1\n"
        p = self._profile("mixed", before=mine, after=tail)
        self.assertEqual(store.drop_managed_profile(p), "stripped")
        self.assertTrue(p.exists(), "★★ 文件被整个删了 —— 用户自己的配置没了")
        left = p.read_text(encoding="utf-8")
        self.assertIn('model_reasoning_effort = "xhigh"', left)
        self.assertIn("[projects]", left)
        self.assertNotIn(store.MARK_BEGIN, left, "托管区没剥干净")

    def test_a_file_we_never_wrote_is_untouched(self):
        p = store.codex_home() / "theirs.config.toml"
        p.write_text("# 完全是用户的\nx = 1\n", encoding="utf-8")
        before = p.read_text(encoding="utf-8")
        self.assertEqual(store.drop_managed_profile(p), "kept")
        self.assertEqual(p.read_text(encoding="utf-8"), before)

    def test_remove_uses_the_same_rule(self):
        """★ 走 `store.remove()` 这条路也必须保住用户内容 —— 两个调用点，一条规则。"""
        store.upsert({"id": "mixed", "label": "M", "base_url": "https://a.test/v1",
                      "key": SECRET})
        p = self._profile("mixed", before="# 用户的\ny = 2\n")
        store.remove("mixed")
        self.assertTrue(p.exists(), "★★ remove() 删掉了含用户内容的整份 profile")
        self.assertIn("y = 2", p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
