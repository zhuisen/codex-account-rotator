"""`agy-quota` 的**行为**闸(不是形状闸)。

守的还是那条铁律 ——「读不到」和「确实没有」绝不能返回同一个值 —— 但 agy 的假绿形态
和 grok **方向相反**,这是这个文件存在的全部理由:

    grok 怕的是假的 `used_percent: 0`   →  画出一条"这周没用过"的绿条
    agy  怕的是假的 `remaining_percent: 100` →  画出一条"额度满格"的绿条

agy 更危险,因为上游 `remainingFraction` 的**缺省值就是 1.0**:任何一处
`payload.get("remainingFraction", 1)`、任何一次把空 dict 当成功往下传,都会直接渲染成满额,
而且看上去完全正常。所以每个失败态除了断言 `quota is None`,还要加一条更硬的:
**整个响应序列化后不得出现 `remaining_percent`** —— 只要有一条假额度漏进任何嵌套层级就红。

假上游起在 127.0.0.1,用 `AGY_PIDS_OVERRIDE` / `AGY_PORTS_OVERRIDE` 跳过 `ps`/`lsof` 发现,
★ 全程**不碰真实的 agy 进程**,也不依赖本机此刻有没有 agy 在跑(否则这些断言会随机变色)。
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agy-quota"

GOOD_PAYLOAD = {
    "response": {
        "groups": [
            {
                "displayName": "Gemini Models",
                "buckets": [
                    {"bucketId": "gemini-weekly", "window": "weekly",
                     "remainingFraction": 0.9956, "resetTime": "2026-09-11T16:17:23Z"},
                    {"bucketId": "gemini-5h", "window": "5h",
                     "remainingFraction": 0.9734, "resetTime": "2026-09-04T21:17:23Z"},
                ],
            },
        ]
    }
}

# agy 在预热窗口里的真实回话(逐字来自实测,不是编的)
NOT_READY_BODY = ('{"code":"internal","message":"error getting token source: '
                  'You are not logged into Antigravity"}')


class Upstream(http.server.BaseHTTPRequestHandler):
    """可切换行为的假 agy language server。"""
    mode = "ok"

    def do_POST(self):                                   # noqa: N802 — BaseHTTPRequestHandler 的命名
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.__class__.mode == "ok":
            self._send(200, json.dumps(GOOD_PAYLOAD))
        elif self.__class__.mode == "not_ready":
            self._send(500, NOT_READY_BODY)
        elif self.__class__.mode == "rpc_error":
            self._send(503, '{"code":"unavailable"}')
        elif self.__class__.mode == "empty_groups":
            self._send(200, '{"response":{"groups":[]}}')
        elif self.__class__.mode == "no_fraction":
            # ★ 最阴的一种:结构完整、字段名都在,唯独没有那个数。
            #   天真的实现会在这里补上默认 1.0,于是"满额"。
            self._send(200, json.dumps({"response": {"groups": [
                {"displayName": "Gemini Models",
                 "buckets": [{"bucketId": "gemini-5h", "window": "5h"}]}]}}))
        elif self.__class__.mode == "garbage":
            self._send(200, "not json at all <<<")

    def _send(self, code, body):
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class AgyDegradeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), Upstream)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def run_tool(self, mode=None, pids=None, ports=None, extra=None):
        if mode:
            Upstream.mode = mode
        env = dict(os.environ)
        # 无害的安慰带:`http.client` 本就不读代理环境变量(实测三个 proxy 指黑洞仍通),
        # 留着是为了将来万一有人把抓取器换成 requests/urllib,测试环境不至于跟着黑洞。
        env["NO_PROXY"] = "127.0.0.1,localhost,::1"
        env["AGY_PIDS_OVERRIDE"] = "4242" if pids is None else pids
        env["AGY_PORTS_OVERRIDE"] = str(self.port) if ports is None else ports
        env.update(extra or {})
        proc = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         "退出码必须恒为 0,否则调用方分不清'工具坏了'和'额度读不到'")
        return json.loads(proc.stdout)

    def assert_no_fabricated_quota(self, out):
        """失败态的硬断言:任何层级都不许出现额度数字。"""
        self.assertFalse(out["available"])
        self.assertIsNone(out["quota"], "失败时 quota 必须是 None,不是 {} 也不是满额")
        self.assertIn(out["reason"], (
            "not_installed", "no_process", "not_ready", "no_ports",
            "bad_payload", "rpc_error", "network_error"))
        blob = json.dumps({k: v for k, v in out.items() if k != "last_good"})
        self.assertNotIn("remaining_percent", blob,
                         "★ 失败路径漏出了额度数字 —— 这正是'假满额'的形状")

    # ---- 成功路径:先确认基线是绿的,否则下面每一条失败断言都是假红 ----

    def test_ok_parses_real_shape(self):
        out = self.run_tool("ok")
        self.assertTrue(out["available"])
        self.assertIsNone(out["reason"])
        b = out["quota"]["groups"][0]["buckets"]
        self.assertEqual(b[0]["remaining_percent"], 99.56)
        self.assertEqual(b[1]["window"], "5h")
        self.assertIsInstance(b[0]["reset_at"], int)

    # ---- 六条降级路径 ----

    def test_not_installed_is_the_definite_negative(self):
        """本机没有 agy —— **确定的否定**,UI 隐藏是诚实的。"""
        out = self.run_tool(pids="", extra={"AGY_BIN_OVERRIDE": "0"})
        self.assertEqual(out["reason"], "not_installed")
        self.assert_no_fabricated_quota(out)

    def test_installed_but_not_running_is_not_the_same_thing(self):
        """★★ 装了但没跑 ≠ 没装。

        agy 不常驻,**没在跑才是常态**。两者若合并:按隐藏处理 ⇒ 用户永远看不到卡;
        按显示处理 ⇒ 没装的人得到一盏永远亮着的灯。所以这条闸盯的是"它俩没被合并"。
        """
        out = self.run_tool(pids="", extra={"AGY_BIN_OVERRIDE": "/usr/bin/true"})
        self.assertEqual(out["reason"], "no_process")
        self.assert_no_fabricated_quota(out)

    def test_two_kinds_of_absence_never_collapse(self):
        """同一份输入、只改'装没装',reason 必须不同 —— 直接把"别合并"写成断言。"""
        absent = self.run_tool(pids="", extra={"AGY_BIN_OVERRIDE": "0"})["reason"]
        present = self.run_tool(pids="", extra={"AGY_BIN_OVERRIDE": "/usr/bin/true"})["reason"]
        self.assertNotEqual(absent, present)

    def test_warmup_500_is_not_ready_not_unavailable(self):
        """★ 这条守的就是我当初判错的那一枪:预热期的 500 ≠ 结构性不可达。"""
        out = self.run_tool("not_ready")
        self.assertEqual(out["reason"], "not_ready")
        self.assert_no_fabricated_quota(out)

    def test_no_ports(self):
        out = self.run_tool(ports="")
        self.assertEqual(out["reason"], "no_ports")
        self.assert_no_fabricated_quota(out)

    def test_rpc_error(self):
        out = self.run_tool("rpc_error")
        self.assertEqual(out["reason"], "rpc_error")
        self.assert_no_fabricated_quota(out)

    def test_empty_groups_is_bad_payload(self):
        out = self.run_tool("empty_groups")
        self.assertEqual(out["reason"], "bad_payload")
        self.assert_no_fabricated_quota(out)

    def test_missing_fraction_never_becomes_full_quota(self):
        """★★ 本文件最重要的一条:字段缺失时**绝不**补默认 1.0。"""
        out = self.run_tool("no_fraction")
        self.assertEqual(out["reason"], "bad_payload")
        self.assert_no_fabricated_quota(out)
        self.assertNotIn("100", json.dumps(out.get("quota")))

    def test_garbage_body(self):
        out = self.run_tool("garbage")
        self.assertEqual(out["reason"], "bad_payload")
        self.assert_no_fabricated_quota(out)

    def test_dead_port_is_network_error(self):
        """端口上没人监听 —— 也不许长得像'确实没有额度'。"""
        out = self.run_tool(ports="9")     # discard,几乎不可能有人在听
        self.assertIn(out["reason"], ("network_error", "rpc_error"))
        self.assert_no_fabricated_quota(out)

    # ---- last_good 的搬运 ----

    def test_last_good_carried_but_never_promoted(self):
        """旧读数可以留着展示,但**不许**把 available 抬回 True。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            prev = Path(d) / ".agy-quota.json"
            good = self.run_tool("ok")
            prev.write_text(json.dumps(good), encoding="utf-8")

            Upstream.mode = "rpc_error"
            env = dict(os.environ)
            env["NO_PROXY"] = "127.0.0.1,localhost,::1"
            env["AGY_PIDS_OVERRIDE"] = "4242"
            env["AGY_PORTS_OVERRIDE"] = str(self.port)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--prev", str(prev)],
                env=env, capture_output=True, text=True, timeout=60)
            out = json.loads(proc.stdout)

        self.assertFalse(out["available"], "带着 last_good 也不能变成 available")
        self.assertIsNone(out["quota"])
        self.assertEqual(out["reason"], "rpc_error")
        self.assertIsNotNone(out["last_good"])
        self.assertEqual(
            out["last_good"]["quota"]["groups"][0]["buckets"][0]["remaining_percent"],
            99.56)

    def test_readonly_touches_nothing_on_disk(self):
        """★ 抓取器自己不落盘。写 sidecar 是 Rust 侧的事,这里只负责打到 stdout。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ)
            env["NO_PROXY"] = "127.0.0.1,localhost,::1"
            env["AGY_PIDS_OVERRIDE"] = "4242"
            env["AGY_PORTS_OVERRIDE"] = str(self.port)
            Upstream.mode = "ok"
            subprocess.run([sys.executable, str(SCRIPT)], env=env, cwd=d,
                           capture_output=True, text=True, timeout=60)
            self.assertEqual(list(Path(d).iterdir()), [],
                             "agy-quota 不该在工作目录留下任何文件")


if __name__ == "__main__":
    unittest.main()
