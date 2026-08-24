"""`grok-quota` 的**行为**闸(不是形状闸)。

守的是项目铁律的可执行形式:**「读不到」和「确实没有」绝不能返回同一个值。**
grok 的额度是百分比,而 `0%` 是"这周一点没用"的**合法值** —— 一旦某个失败路径悄悄写出
`used_percent: 0`,UI 就会画一条正常的绿条,用户没有任何办法知道那是假的。所以每个失败态
都要断言 `quota is None`,再加一条更硬的:**整个 quota 序列化后不得出现 `used_percent`**。

假上游用自签 CA + `SSL_CERT_FILE` 起在 127.0.0.1(`ssl.create_default_context()` 认这个 env)。
没有它,401 / 500 / 坏 payload 就只能拿真 token 打真外网去凑,既慢又把测试绑在外网状态上。
★ 全程**不碰真实 `~/.grok`** —— `GROK_AUTH_PATH` 指向合成夹具(同 test_incremental_parse.py 的纪律)。
"""
import http.server
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "grok-quota"

GOOD_PAYLOAD = {
    "config": {
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "start": "2026-08-20T11:34:58.068526+00:00",
            "end": "2026-08-27T11:34:58.068526+00:00",
        },
        "creditUsagePercent": 35.0,
        "onDemandCap": {"val": 0},
        "onDemandUsed": {"val": 0},
        "productUsage": [
            {"product": "GrokBuild", "usagePercent": 27.0},
            {"product": "GrokAppBuilder", "usagePercent": 4.0},
            {"product": "GrokImagine", "usagePercent": 4.0},
        ],
        "prepaidBalance": {"val": 0},
    }
}


def make_cert(tmp):
    """自签一张 127.0.0.1 的证书。macOS 自带 openssl,够用。"""
    key, crt = tmp / "k.pem", tmp / "c.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(crt), "-days", "1",
         "-subj", "/CN=127.0.0.1",
         "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True)
    return key, crt


class FakeUpstream:
    """可编程的假 xAI。`self.status` / `self.body` 决定下一次响应;`self.hits` 记请求数。"""

    def __init__(self, key, crt):
        self.status = 200
        self.body = json.dumps(GOOD_PAYLOAD).encode()
        self.hits = 0
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                      # noqa: N802 — BaseHTTPRequestHandler 的约定
                outer.hits += 1
                outer.last_path = self.path
                outer.last_headers = dict(self.headers)
                self.send_response(outer.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *_a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(crt), str(key))
        self.srv.socket = ctx.wrap_socket(self.srv.socket, server_side=True)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


class GrokDegradeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.key, cls.crt = make_cert(cls.tmp)
        cls.up = FakeUpstream(cls.key, cls.crt)

    @classmethod
    def tearDownClass(cls):
        cls.up.stop()
        cls._tmp.cleanup()

    # ---- helpers ----------------------------------------------------------

    def write_auth(self, name, *, expires_in=3600, token="tok-abc", extra=None):
        p = self.tmp / name
        exp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + expires_in)) + ".000000Z"
        entry = {"key": token, "user_id": "u-1", "email": "grok@example.com", "expires_at": exp}
        if extra is not None:
            entry.update(extra)
        p.write_text(json.dumps({"https://auth.x.ai::client-1": entry}), encoding="utf-8")
        return p

    def run_tool(self, auth, *, prev=None, host=None):
        env = dict(os.environ)
        env["GROK_AUTH_PATH"] = str(auth)
        env["GROK_BILLING_HOST"] = host or "127.0.0.1:{}".format(self.up.port)
        env["SSL_CERT_FILE"] = str(self.crt)
        cmd = [sys.executable, str(SCRIPT)]
        if prev:
            cmd += ["--prev", str(prev)]
        out = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        # ★★ 退出码恒 0 是契约的一部分,不是顺带检查:非 0 会让 Rust 走 Err(String),
        #    而 Err 在前端三条路径上都被读成"没数据",等于把降级又折叠回去。
        self.assertEqual(out.returncode, 0, "exit={} stderr={}".format(out.returncode, out.stderr))
        return json.loads(out.stdout)

    def assert_degraded(self, acc, reason):
        self.assertFalse(acc["available"])
        self.assertEqual(acc["reason"], reason)
        self.assertIsNone(acc["quota"], "失败态 quota 必须是 None,绝不能是 0")
        # 更硬的一条:0% 是"这周没用"的合法值,失败态一旦长出这个字段就再也分不出真假。
        self.assertNotIn("used_percent", json.dumps(acc.get("quota") or {}))
        self.assertIn(reason, self.reasons(), "reason 必须来自闭集")

    @staticmethod
    def reasons():
        src = SCRIPT.read_text(encoding="utf-8")
        block = src.split("REASONS = (", 1)[1].split(")", 1)[0]
        return {ln.strip().strip('",') for ln in block.splitlines() if ln.strip().startswith('"')}

    # ---- 成功态 ------------------------------------------------------------

    def test_success(self):
        self.up.status, self.up.body = 200, json.dumps(GOOD_PAYLOAD).encode()
        snap = self.run_tool(self.write_auth("ok.json"))
        acc = snap["accounts"][0]
        self.assertTrue(acc["available"])
        self.assertEqual(acc["quota"]["used_percent"], 35.0)
        self.assertEqual(acc["quota"]["window_minutes"], 10080.0)
        self.assertEqual(acc["quota"]["period_type"], "USAGE_PERIOD_TYPE_WEEKLY")
        self.assertEqual(len(acc["quota"]["products"]), 3)
        # 成功时 last_good 必须为 None:当前值就是最好的值,留着只会让消费方犹豫取哪个。
        self.assertIsNone(acc["last_good"])

    def test_only_get_and_correct_path(self):
        self.up.status, self.up.body = 200, json.dumps(GOOD_PAYLOAD).encode()
        self.run_tool(self.write_auth("ok2.json"))
        self.assertEqual(self.up.last_path, "/v1/billing?format=credits")
        self.assertEqual(self.up.last_headers.get("x-xai-token-auth"), "xai-grok-cli")

    # ---- 失败态 ------------------------------------------------------------

    def test_unauthorized_401(self):
        self.up.status, self.up.body = 401, b'{"error":"Invalid or expired credentials"}'
        self.assert_degraded(self.run_tool(self.write_auth("a1.json"))["accounts"][0], "unauthorized")

    def test_unauthorized_403(self):
        self.up.status, self.up.body = 403, b'{"error":"forbidden"}'
        self.assert_degraded(self.run_tool(self.write_auth("a2.json"))["accounts"][0], "unauthorized")

    def test_http_error_500(self):
        self.up.status, self.up.body = 500, b"boom"
        self.assert_degraded(self.run_tool(self.write_auth("a3.json"))["accounts"][0], "http_error")

    def test_bad_payload_200_without_field(self):
        self.up.status, self.up.body = 200, json.dumps({"config": {"somethingElse": 1}}).encode()
        self.assert_degraded(self.run_tool(self.write_auth("a4.json"))["accounts"][0], "bad_payload")

    def test_bad_payload_not_json(self):
        self.up.status, self.up.body = 200, b"<html>nope</html>"
        self.assert_degraded(self.run_tool(self.write_auth("a5.json"))["accounts"][0], "bad_payload")

    def test_auth_file_missing(self):
        acc = self.run_tool(self.tmp / "nope.json")["accounts"][0]
        self.assert_degraded(acc, "auth_file_missing")

    def test_auth_file_unreadable(self):
        p = self.tmp / "broken.json"
        p.write_text("{not json", encoding="utf-8")
        self.assert_degraded(self.run_tool(p)["accounts"][0], "auth_file_unreadable")

    def test_auth_file_empty(self):
        p = self.tmp / "empty.json"
        p.write_text("{}", encoding="utf-8")
        self.assert_degraded(self.run_tool(p)["accounts"][0], "auth_file_empty")

    def test_network_error(self):
        acc = self.run_tool(self.write_auth("a6.json"),
                            host="127.0.0.1:1")["accounts"][0]   # 没人监听
        self.assert_degraded(acc, "network_error")
        self.assertIsNone(acc["http_status"], "请求没发出去时 http_status 必须是 None")

    def test_token_expired_short_circuits(self):
        """本地判过期必须**真的**不发请求 —— 否则那条注释就是谎话。"""
        self.up.status, self.up.body = 200, json.dumps(GOOD_PAYLOAD).encode()
        before = self.up.hits
        acc = self.run_tool(self.write_auth("exp.json", expires_in=-60))["accounts"][0]
        self.assert_degraded(acc, "token_expired")
        self.assertEqual(self.up.hits, before, "token_expired 态下假上游必须收到 0 个请求")

    # ---- last_good 转移 -----------------------------------------------------

    def test_last_good_carried_from_previous_success(self):
        auth = self.write_auth("carry.json")
        self.up.status, self.up.body = 200, json.dumps(GOOD_PAYLOAD).encode()
        first = self.run_tool(auth)
        prev = self.tmp / "prev.json"
        prev.write_text(json.dumps(first), encoding="utf-8")

        time.sleep(1.1)                                    # 让 fetched_at 必然不同
        self.up.status, self.up.body = 401, b'{"error":"x"}'
        second = self.run_tool(auth, prev=prev)
        acc = second["accounts"][0]
        self.assert_degraded(acc, "unauthorized")
        self.assertEqual(acc["last_good"]["used_percent"], 35.0)
        # ★ 必须是**上一次**的时刻,不是这次的 —— 否则"3 小时前的读数"会显示成"刚刚"。
        self.assertEqual(acc["last_good"]["fetched_at"], first["fetched_at"])
        self.assertNotEqual(acc["last_good"]["fetched_at"], second["fetched_at"])

    def test_last_good_survives_two_consecutive_failures(self):
        """连续两次失败不能把陈旧读数丢掉 —— 那正是最需要它的时候。"""
        auth = self.write_auth("carry2.json")
        self.up.status, self.up.body = 200, json.dumps(GOOD_PAYLOAD).encode()
        first = self.run_tool(auth)
        p1 = self.tmp / "p1.json"
        p1.write_text(json.dumps(first), encoding="utf-8")

        self.up.status, self.up.body = 500, b"boom"
        second = self.run_tool(auth, prev=p1)
        p2 = self.tmp / "p2.json"
        p2.write_text(json.dumps(second), encoding="utf-8")

        third = self.run_tool(auth, prev=p2)
        self.assertEqual(third["accounts"][0]["last_good"]["used_percent"], 35.0)
        self.assertEqual(third["accounts"][0]["last_good"]["fetched_at"], first["fetched_at"])

    def test_prev_unreadable_is_not_fatal(self):
        bad = self.tmp / "badprev.json"
        bad.write_text("garbage", encoding="utf-8")
        self.up.status, self.up.body = 401, b'{"error":"x"}'
        acc = self.run_tool(self.write_auth("a7.json"), prev=bad)["accounts"][0]
        self.assert_degraded(acc, "unauthorized")
        self.assertIsNone(acc["last_good"])

    # ---- 多账号 ------------------------------------------------------------

    def test_multiple_accounts_all_scanned(self):
        p = self.tmp / "multi.json"
        exp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 3600)) + ".000000Z"
        p.write_text(json.dumps({
            "https://auth.x.ai::c1": {"key": "t1", "user_id": "u1", "email": "a@example.com", "expires_at": exp},
            "https://auth.x.ai::c2": {"key": "t2", "user_id": "u2", "email": "b@example.com", "expires_at": exp},
        }), encoding="utf-8")
        self.up.status, self.up.body = 200, json.dumps(GOOD_PAYLOAD).encode()
        snap = self.run_tool(p)
        self.assertEqual(len(snap["accounts"]), 2, "多账号不能被静默丢掉")
        self.assertTrue(all(a["available"] for a in snap["accounts"]))


if __name__ == "__main__":
    unittest.main()
