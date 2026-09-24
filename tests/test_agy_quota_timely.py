"""Gemini（agy）额度要**及时** —— 2026-09-23 用户：「gemini 的额度刷新不及时」。

## 真因（两件叠在一起）

① 本机实时读数自 09-22 22:32 起一直 `HTTP 401`：agy 1.2.x 的本机额度接口要一个它内部生成的
   CSRF token（实测：不带 ⇒ `missing CSRF token`；用 `ANTIGRAVITY_CSRF_TOKEN` 自设 ⇒
   `invalid CSRF token`；日志 / 进程环境 / presence 目录里都没有）。于是云端成了唯一来源。
② 云端每账号额度只在 **Gemini 档开着** 时才前进 ⇒ 每次打开先看到上次打开时的旧数，
   再等一次逐号串行的抓取（实测 8.4s / 3 个号）。

## 判据

· 后台保鲜：**恰好一个** webview（菜单栏）开，且不看 `enabled`、不看可见性。
· 各号并行：N 个号的总耗时 ≈ 最慢那个，不是之和；且结果不串号。
· 采样器：确认「要 CSRF」之后一小时内**起手就退**（app 每 60s 会把它补拉起来 ——
  只在循环里 break 等于每分钟重生一次）。退出必须排在 `take_lock` 之前（不许留陈锁）。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"


def _strip_ts(src):
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(?<![:/])//[^\n]*", "", src)


class TheCloudQuotaIsKeptFreshInTheBackground(unittest.TestCase):
    def test_exactly_one_webview_drives_it(self):
        """★★ 两个 webview 都开会在同一个 10 分钟边界上各起一次子进程。"""
        hits = []
        for p in SRC.rglob("*.tsx"):
            code = _strip_ts(p.read_text(encoding="utf-8"))
            if "useAgyPool(" in code and "background: true" in code:
                hits.append(p.name)
        self.assertEqual(hits, ["MenuBar.tsx"],
                         "★★ 后台保鲜必须恰好由菜单栏（开机即建、从不卸载）驱动")

    def test_the_background_effect_ignores_tab_and_visibility(self):
        """★★★ 主闸：后台那条**不许**再被 `enabled` 或可见性挡住 —— 窗口藏着恰恰是最需要它的时候。
        但仍受设置页「后台自动刷新」开关约束。"""
        src = _strip_ts((SRC / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8"))
        i = src.index("if (!background) return;")
        body = src[i:src.index("}, [background", i)]
        self.assertIn("refreshQuotaIfStale()", body)
        self.assertIn("autoRefreshEnabled()", body, "★ 关掉「后台自动刷新」后它还在跑")
        self.assertNotIn("visibilityState", body, "★★★ 又被可见性挡住了 —— 藏着时永不前进")
        self.assertNotRegex(body, r"\benabled\b", "★★★ 又被 Gemini 档挡住了")


def _load_cli():
    loader = importlib.machinery.SourceFileLoader("agy_rotate_timely", str(ROOT / "agy-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TheAccountsAreFetchedInParallel(unittest.TestCase):
    """行为闸：真调 `cmd_quota`，但**所有碰盘 / 碰网 / 碰钥匙串的地方都打桩**。"""

    N, DELAY = 4, 0.4

    def setUp(self):
        self.cli = _load_cli()
        subs = [f"sub{i}" for i in range(self.N)]
        self.pool = {"accounts": {s: {"label": f"L{s}"} for s in subs}}
        saved = []
        delay = self.DELAY

        def fetch_quota(token):
            time.sleep(delay)                       # 模拟网络等待
            return [{"who": token}], ""             # 带上 token ⇒ 能验「没串号」

        fake = types.SimpleNamespace(
            load=lambda: self.pool,
            fetch_quota=fetch_quota,
            quota_by_group=lambda g: {"gemini": {"remaining": 1, "reset": None, "who": g[0]["who"]}},
            save=lambda p: saved.append(True),
            _lock=lambda path: open(os.devnull),    # 上下文管理器即可
            POOL=None,
        )
        self.cli.P = fake
        self.cli._refresh_one = lambda sub, a, pool: ({"token": {"access_token": "tok-" + sub}}, "")
        self.cli._mark_live = lambda pool: None
        self.cli._log = lambda msg: None
        self.saved = saved

    def run_quota(self):
        buf = io.StringIO()
        t0 = time.monotonic()
        with redirect_stdout(buf):
            self.cli.cmd_quota(["--json"])
        return time.monotonic() - t0, json.loads(buf.getvalue())

    def test_total_time_is_the_slowest_not_the_sum(self):
        """★★★ 串行 = N×DELAY（1.6s），并行 ≈ DELAY。阈值取两者中点，不靠运气。"""
        took, _ = self.run_quota()
        self.assertLess(took, self.N * self.DELAY * 0.6,
                        f"★★★ {self.N} 个号用了 {took:.2f}s —— 还是逐号串行")

    def test_no_account_gets_another_accounts_reading(self):
        """★★★ 并行最怕串号：A 的额度写进 B 的卡。"""
        self.run_quota()
        for sub, a in self.pool["accounts"].items():
            with self.subTest(sub=sub):
                self.assertEqual(a["quota"]["gemini"]["who"], "tok-" + sub)

    def test_the_pool_is_saved_once(self):
        """落盘仍只有一次（持锁）—— 并行不改变落盘的形状。"""
        self.run_quota()
        self.assertEqual(len(self.saved), 1)
        self.assertIn("quota_ran_at", self.pool)


class TheSamplerBacksOffWhenCsrfIsRequired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = os.environ.get("CODEX_ROTATE_STORE")
        os.environ["CODEX_ROTATE_STORE"] = self.tmp.name
        try:
            spec = importlib.util.spec_from_file_location(
                "agy_sampler_timely", ROOT / "traffic" / "agy_quota_sampler.py")
            self.m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.m)
        finally:
            if old is None:
                os.environ.pop("CODEX_ROTATE_STORE", None)
            else:
                os.environ["CODEX_ROTATE_STORE"] = old
        self.assertEqual(Path(self.m.SIDECAR).parent, Path(self.tmp.name),
                         "★★ sidecar 没指到临时目录 —— 下面会读写真文件")

    def put(self, reason, age):
        Path(self.m.SIDECAR).write_text(json.dumps(
            {"reason": reason, "fetched_at": time.time() - age}), encoding="utf-8")

    def test_a_fresh_csrf_verdict_backs_off(self):
        self.put("csrf_required", 60)
        self.assertTrue(self.m._csrf_backoff())

    def test_it_retries_after_an_hour(self):
        """★ 每小时仍真试一次 —— 哪天 agy 放开接口，最多一小时后自己恢复。"""
        self.put("csrf_required", 2 * 3600)
        self.assertFalse(self.m._csrf_backoff())

    def test_other_reasons_and_missing_files_do_not_back_off(self):
        """★★ 「没读到」不许变成「不用采」。"""
        self.put("rpc_error", 60)
        self.assertFalse(self.m._csrf_backoff())
        Path(self.m.SIDECAR).unlink()
        self.assertFalse(self.m._csrf_backoff())

    def test_the_backoff_exits_before_taking_the_lock(self):
        """★★★ 早退排在 `take_lock` 之前 —— 反过来会留陈锁，app 从此再也不会补拉采样器。"""
        src = (ROOT / "traffic" / "agy_quota_sampler.py").read_text(encoding="utf-8")
        body = src[src.index("def main():"):]
        self.assertLess(body.index("if _csrf_backoff():"), body.index("take_lock("))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheQuotaSummaryGoesToTheHostAgyActuallyUses(unittest.TestCase):
    """★★★ agy 1.2.x 的后端是 `daily-cloudcode-pa`（2026-09-24 实测，CHANGELOG B69）。

    打 `cloudcode-pa` 同样回 200、形状完全相同，只是**四桶恒 1.0、reset 恒 now+窗口**——
    打错 host 没有任何报错，只有一个恒满的假读数（用户：「5h 配额都没减少，数据不合理」）。
    行为闸：真调 `fetch_quota`，只把 HTTPSConnection 换成记录 host 的假连接。
    """

    def test_fetch_quota_talks_to_the_daily_backend(self):
        sys.path.insert(0, str(ROOT))
        from agy import pool as P
        seen = []

        class FakeConn:
            def __init__(self, host, *a, **k):
                seen.append(host)

            def request(self, *a, **k):
                pass

            def getresponse(self):
                return types.SimpleNamespace(status=200, read=lambda: json.dumps(
                    {"groups": [{"displayName": "Gemini Models", "buckets": [
                        {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.7,
                         "resetTime": "2026-09-23T21:32:22Z"}]}]}).encode())

            def close(self):
                pass

        orig = P.HTTPSConnection
        P.HTTPSConnection = FakeConn
        try:
            groups, err = P.fetch_quota("tok")
        finally:
            P.HTTPSConnection = orig
        self.assertEqual(seen, ["daily-cloudcode-pa.googleapis.com"],
                         "★★★ 额度摘要没打 agy 1.2 的真后端 —— 会读到一个恒满的空账本")
        self.assertFalse(err)
