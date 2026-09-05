"""`agy-quota` 的 **JSON 字段名** 必须与 `codexbar/src/agy.ts` 的接口逐字一致。

两边是我手写的两份,中间没有代码生成。写差一个字母 —— `remaining_percent` 写成
`remainingPercent`、`reset_at` 写成 `resetAt` —— 后果是:

    TS 里 `b.remaining_percent` 得到 `undefined`
      → `agyTightest` 比较 `undefined < undefined` 恒 false,reduce 返回第一个
      → 环上画出 `NaN` 或 `—`

**全程零报错、零类型错误**(JSON.parse 的结果是 `any` 断言进接口的,tsc 拦不住),
页面照常渲染。这正是本仓反复吃亏的形态,所以要有一条闸真的去比这两组名字。

★ 断言的是**真实产出**,不是我在测试里粘的一份期望副本:跑一次真脚本(打到假上游),
拿它实际吐出来的 key 去比 TS。粘副本的话,改坏脚本时副本也会跟着被改,闸就空了。
"""
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agy-quota"
TS = ROOT / "codexbar" / "src" / "agy.ts"

PAYLOAD = {
    "response": {
        "groups": [
            {
                "displayName": "Gemini Models",
                "buckets": [
                    {"bucketId": "gemini-weekly", "window": "weekly",
                     "remainingFraction": 0.9956, "resetTime": "2026-09-11T16:17:23Z"},
                ],
            },
        ]
    }
}


class Upstream(http.server.BaseHTTPRequestHandler):
    def do_POST(self):                                   # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        raw = json.dumps(PAYLOAD).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def ts_fields(interface):
    """`export interface X { a: T; b: T }` 里的字段名。

    ★ 只取**顶层**字段:嵌套的对象字面量(如 `last_good` 的内联类型)会引入它自己的字段,
    混进来会让"多余字段"那条断言假绿。用花括号深度过滤。
    """
    src = TS.read_text(encoding="utf-8")
    m = re.search(r"export interface " + interface + r"\s*\{", src)
    assert m, "找不到 interface " + interface
    i = m.end()
    depth, out, buf = 1, [], src[i:]
    line_depth = 0
    for line in buf.splitlines():
        if depth <= 0:
            break
        # 先记本行开头的深度,再按本行的括号更新 —— 否则 `x: { a: 1 }` 单行会被误判
        line_depth = depth
        stripped = line.strip()
        fm = re.match(r"([a-z_][a-zA-Z0-9_]*)\s*\??\s*:", stripped)
        if fm and line_depth == 1:
            out.append(fm.group(1))
        depth += line.count("{") - line.count("}")
    return set(out)


class AgyJsonMatchesTypeScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), Upstream)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

        env = dict(os.environ)
        env["AGY_PIDS_OVERRIDE"] = "4242"
        env["AGY_PORTS_OVERRIDE"] = str(cls.port)
        proc = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=60)
        cls.out = json.loads(proc.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_the_run_actually_produced_quota(self):
        """★ 先证明这一跑真的拿到了额度 —— 失败态的 quota 是 None,
        那样下面每条字段断言都在比空集合,会全绿。"""
        self.assertTrue(self.out["available"], "假上游没被打通,下面的断言会假绿")
        self.assertIsNotNone(self.out["quota"])

    def test_snapshot_top_level_fields_match(self):
        py = set(self.out.keys())
        ts = ts_fields("AgySnapshot")
        self.assertEqual(py, ts,
                         "顶层字段不一致\n  只在 python: {}\n  只在 ts: {}".format(
                             sorted(py - ts), sorted(ts - py)))

    def test_group_fields_match(self):
        g = self.out["quota"]["groups"][0]
        self.assertEqual(set(g.keys()), ts_fields("AgyGroup"))

    def test_bucket_fields_match(self):
        b = self.out["quota"]["groups"][0]["buckets"][0]
        py, ts = set(b.keys()), ts_fields("AgyBucket")
        self.assertEqual(py, ts,
                         "桶字段不一致(写差一个字母 = UI 永远画 — 且零报错)"
                         "\n  只在 python: {}\n  只在 ts: {}".format(
                             sorted(py - ts), sorted(ts - py)))

    def test_quota_wrapper_field_matches(self):
        self.assertEqual(set(self.out["quota"].keys()), ts_fields("AgyQuota"))

    def test_remaining_is_a_percent_not_a_fraction(self):
        """★ 上游给的是 0~1 的 fraction,我们对外是 0~100 的百分比。

        这一层换算若丢了,UI 会画出一条 **0.99% 的条** —— 看着像"快用光了",
        方向感觉还挺合理,所以肉眼极难发现。
        """
        b = self.out["quota"]["groups"][0]["buckets"][0]
        self.assertAlmostEqual(b["remaining_percent"], 99.56, places=2)
        self.assertGreater(b["remaining_percent"], 1.0,
                           "看起来还是 fraction(0~1),没换成百分比")

    def test_reset_at_is_epoch_seconds(self):
        b = self.out["quota"]["groups"][0]["buckets"][0]
        self.assertIsInstance(b["reset_at"], int)
        # 2026-09-11 那个时间戳。给个宽区间,只验它不是毫秒、不是 0、不是字符串。
        self.assertGreater(b["reset_at"], 1_700_000_000)
        self.assertLess(b["reset_at"], 2_000_000_000, "看着像毫秒时间戳")


if __name__ == "__main__":
    unittest.main()
