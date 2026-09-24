"""日志页「代理轮换」的 Gemini 版块（用户 2026-09-24：「改成 codex 和 gemini 两个版块」）。

数据：`traffic/agy_rotation.py`（纯模块，与 `rotation.collect` 同形）。判据：
① 会话按 agy 自己日志的 `applyAuthResult` 归属，**认不出就不归属**（计数，不猜）；
② 一场会话中途身份变了要切段，不把整场记在第一个号头上；
③ 「在岗」是区间**并集**（本机常有多个 agy 同号并发，实测求和一天出 139633s）；
④ 有换号记录的是「切换」，没有的是「钥匙串被写回」（drift）—— 两者不许混；
⑤ 输出与前端 `Rotation` 接口同形（从 TS 源现解析）；按号 token 恒 0、覆盖率为 None（前端显示「—」）；
⑥ 前端：Gemini 版不把 `rot.log` 再并进运行日志（那份就是 agy.log，会每行两遍且错标 proxy）；
   IPC 只读不 emit；模块进了安装包 resources。
"""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "traffic"))
import agy_rotation as AR  # noqa: E402

NOW = time.time()


def _stamp(t):
    return time.strftime("%m%d %H:%M:%S.000000", time.localtime(t))


class Fixture:
    def __init__(self):
        self.d = Path(tempfile.mkdtemp(prefix="agyrot-"))
        self.logs = self.d / "log"
        self.logs.mkdir()
        (self.d / ".agy-pool.json").write_text(json.dumps({"accounts": {
            "s0": {"label": "A", "email": "a@x.y"}, "s1": {"label": "B", "email": "b@x.y"}}}))
        self.n = 0

    def run(self, a_h, b_h, *auths):
        """一场会话：`auths` = [(相对小时, email), …]；空 = 认不出身份。"""
        t0 = NOW + a_h * 3600
        self.n += 1
        f = self.logs / time.strftime("cli-%Y%m%d_%H%M%S.log", time.localtime(t0 + self.n))
        body = "I%s 1 x.go:1] start\n" % _stamp(t0)
        for (h, email) in auths:
            body += "I%s 2 server_oauth.go:196] applyAuthResult: email=%s, authMethod=consumer\n" % (
                _stamp(NOW + h * 3600), email)
        f.write_text(body)
        os.utime(f, (NOW + b_h * 3600, NOW + b_h * 3600))

    def switch(self, h, label):
        with open(self.d / "agy.log", "a") as fh:
            fh.write("[agy %s] auto 自动切到 [%s]（剩余 90%%，new，落点 keyring）\n"
                     % (time.strftime("%m-%d %H:%M:%S", time.localtime(NOW + h * 3600)), label))

    def collect(self, hours=24):
        return AR.collect(hours, now=NOW, log_dir=self.logs, store=self.d)


class SessionsAreAttributedByAgysOwnLog(unittest.TestCase):
    def test_an_unreadable_identity_is_counted_not_guessed(self):
        f = Fixture()
        f.run(-3, -2)
        r = f.collect()
        self.assertEqual(r["segments"], [])
        self.assertEqual(r["coverage"]["responses_unplaced"], 1, "★★ 认不出身份的会话被悄悄丢了")

    def test_an_identity_change_mid_session_splits_it(self):
        """★★ 长会话中途被钥匙串写回 → 同一份日志第二条 applyAuthResult。"""
        f = Fixture()
        f.run(-5, -1, (-5, "a@x.y"), (-3, "b@x.y"))
        segs = [(s["acc"], round((s["end"] - s["start"]) / 3600)) for s in f.collect()["segments"]]
        self.assertEqual(segs, [("A", 2), ("B", 2)])

    def test_on_duty_is_a_union_not_a_sum(self):
        """★★★ 两场同号并发会话：在岗 = 并集（2h），不是求和（3h）。"""
        f = Fixture()
        f.run(-4, -2, (-4, "a@x.y"))
        f.run(-3, -2, (-3, "a@x.y"))
        row = next(r for r in f.collect()["daily"]["rows"] if r["acc"] == "A")
        secs = sum(c["secs"] for c in row["cells"] if isinstance(c, dict))
        self.assertAlmostEqual(secs / 3600, 2, delta=0.05)


class SwitchAndDriftAreDifferentThings(unittest.TestCase):
    def test_a_logged_switch_is_a_switch(self):
        f = Fixture()
        f.run(-6, -5, (-6, "a@x.y"))
        f.switch(-4.01, "B")
        f.run(-4, -3, (-4, "b@x.y"))
        r = f.collect()
        self.assertEqual(r["segments"][1]["enter_reason"], "switch")
        self.assertFalse(any(e["reason"] == "drift" for e in r["events"]))

    def test_an_unlogged_change_is_drift(self):
        """★★ 没有换号记录却换了身份 = 某个常驻 agy 把钥匙串写回了 —— 必须单独说出来。"""
        f = Fixture()
        f.run(-6, -5, (-6, "a@x.y"))
        f.run(-4, -3, (-4, "b@x.y"))
        r = f.collect()
        self.assertEqual(r["segments"][1]["enter_reason"], "drift")
        self.assertTrue(any(e["reason"] == "drift" for e in r["events"]))


class TheOutputMatchesTheRotationInterface(unittest.TestCase):
    def test_keys_parsed_from_the_ts_source(self):
        ts = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")

        def fields(name):
            body = re.search(r"interface %s \{([\s\S]*?)\n\}" % name, ts).group(1)
            body = re.sub(r"/\*\*[\s\S]*?\*/", "", body)
            return {k for k in re.findall(r"^\s{2}(\w+):", body, re.M)}   # 只核必填键（`reason?`/`detail?` 是失败态专用）
        f = Fixture()
        f.run(-3, -1, (-3, "a@x.y"))
        r = f.collect()
        self.assertTrue(fields("Rotation") <= set(r), fields("Rotation") - set(r))
        self.assertTrue(fields("Seg0") <= set(r["segments"][0]), fields("Seg0") - set(r["segments"][0]))
        self.assertTrue(fields("Acct") - {"retired"} <= set(r["accounts"][0]))

    def test_no_per_account_tokens_are_invented(self):
        """★★ 账本不带身份 —— 按时间拼就是猜。token 恒 0、覆盖率 None，前端据此显示「—」。"""
        f = Fixture()
        f.run(-3, -1, (-3, "a@x.y"))
        r = f.collect()
        self.assertEqual({s["tokens"] for s in r["segments"]}, {0})
        self.assertIsNone(r["coverage"]["attributed_pct"])
        self.assertEqual(r["platform"], "agy")


class TheLogsPageWiring(unittest.TestCase):
    SRC = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")

    def test_the_gemini_tab_uses_its_own_ipc(self):
        self.assertIn('invoke<Rotation>("read_agy_rotation"', self.SRC)
        self.assertIn('<Seg opts={["codex", "agy"] as const}', self.SRC)

    def test_gemini_never_shows_token_numbers(self):
        self.assertIn('v={rot && !isAgy ? fmtTok(rot.kpi.tokens) : "—"}', self.SRC)
        self.assertIn('{isAgy ? "—" : fmtTok(l.tokens)}', self.SRC)

    def test_the_run_log_is_not_merged_twice(self):
        """★ Gemini 版的 rot.log 就是 agy.log 的换号行 —— 服务日志里已经整份含着。"""
        self.assertIn("const proxy = isAgy ? [] :", self.SRC)

    def test_the_ipc_is_read_only_and_the_module_ships(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("async fn read_agy_rotation")
        self.assertNotIn("emit(", rs[i:rs.index("\n}", i)])
        conf = (ROOT / "codexbar" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
        self.assertIn('"../../traffic/agy_rotation.py"', conf, "★★ 模块没进安装包 —— 装机版这一版整块读不出")


if __name__ == "__main__":
    unittest.main(verbosity=2)
