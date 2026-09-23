"""`GET /models` 向上游要 gzip、本机解压后交给客户端（行为闸，真起代理 + 假上游）。

## 起因（2026-09-23）

codex 0.156.0 的空闲会话每 270s 后台刷新模型列表，预算 5 秒（59 个超时样本全落在 5.00–5.05s）。
它请求 `/models` **不带 Accept-Encoding**（假上游抓包实测 10/10），于是代理的 http.client 替它发
`identity`，上游回 **522 KB** 明文；同一份 gzip 只有 **103 KB**。上游首字节就要 ~2s，剩下的时间里
传 522 KB 常常传不完 ⇒ codex 挂断 ⇒ 代理记「断流」—— 当天一个闲置窗口刷出 80 个。

## 判据（每条都有自己的方向）

① 上游收到的是 `Accept-Encoding: gzip`；客户端拿到**逐字节相同**的明文、**没有** Content-Encoding。
② 线上字节确实变少（这才是修复的意义，不是"加了个头"）。
③ **SSE 的 POST 不碰**：不要 gzip、不缓冲。
④ 客户端自己要了 gzip ⇒ 原样透传（再解一次就是解两遍）。
⑤ 上游不理 gzip、回明文 ⇒ 照常转发，不崩。
⑥ 上游给了坏的 gzip ⇒ 干净的 502（还没发响应头，GET 不计费，让客户端重试），不是半截响应。
"""
import gzip
import http.client
import http.server
import importlib.util
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

#: 形状接近真实模型列表的明文（真实 ~522 KB）：重复度高 ⇒ gzip 压得很狠。
MODELS = json.dumps({"models": [{"slug": f"gpt-x-{i}", "base_instructions": "You are Codex. " * 200}
                                for i in range(40)]}).encode()


class Upstream(http.server.BaseHTTPRequestHandler):
    mode = "normal"          # normal | ignore_gzip | corrupt
    seen = []                # [(method, path, accept-encoding)]
    wire_bytes = []

    def do_GET(self):
        ae = self.headers.get("Accept-Encoding")
        Upstream.seen.append(("GET", self.path, ae))
        body, enc = MODELS, None
        if Upstream.mode == "corrupt":
            body, enc = b"\x1f\x8b\x08\x00not really gzip", "gzip"
        elif ae and "gzip" in ae.lower() and Upstream.mode != "ignore_gzip":
            body, enc = gzip.compress(MODELS), "gzip"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if enc:
            self.send_header("Content-Encoding", enc)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        Upstream.wire_bytes.append(len(body))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        Upstream.seen.append(("POST", self.path, self.headers.get("Accept-Encoding")))
        body = b"data: {\"type\":\"response.output_text.delta\"}\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class ModelsListComesThroughGzip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("proxy_models_gzip", ROOT / "proxy" / "proxy.py")
        px = importlib.util.module_from_spec(spec)
        sys.modules["proxy_models_gzip"] = px
        spec.loader.exec_module(px)

        cls.up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        up_port = cls.up.server_address[1]

        class H(px.Handler):
            """只走 `_open` → `_finish` 这一段：挑号/额度/粘性不是这条闸要测的。
            `aid=None` ⇒ `_finish` 不记额度（不会碰任何 state.json）。"""
            def _go(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                conn, resp = self._open(body, "tok", None, "t", "test", None, "0abc12")
                try:
                    self._finish(conn, resp, None, "t")
                finally:
                    conn.close()
            do_GET = do_POST = _go

            def log_message(self, *a):
                pass

        # 代理对上游恒用 HTTPS；测试里换成直连假上游的明文 HTTP（只在本类生命周期内）。
        cls._patch = mock.patch.object(
            px.http.client, "HTTPSConnection",
            lambda host, port, context=None, timeout=None: http.client.HTTPConnection(
                "127.0.0.1", up_port, timeout=timeout))
        cls._patch.start()
        cls._devnull = open("/dev/null", "w")
        cls._err = mock.patch.object(px.sys, "stderr", new=cls._devnull)
        cls._err.start()             # `_plog` 写 stderr —— 测试里静音，绝不写真 proxy.log
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for s in (cls.srv, cls.up):
            s.shutdown()
            s.server_close()
        cls._patch.stop()
        cls._err.stop()
        cls._devnull.close()

    def setUp(self):
        Upstream.mode = "normal"
        Upstream.seen = []
        Upstream.wire_bytes = []

    def ask(self, method="GET", path="/models?client_version=0.156.0", headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def test_the_client_gets_plain_bytes_and_upstream_was_asked_for_gzip(self):
        """★★★ ①：上游要的是 gzip，客户端拿到的是逐字节相同的明文。"""
        r, data = self.ask()
        self.assertEqual(r.status, 200)
        self.assertEqual(data, MODELS, "★★★ 客户端拿到的不是原样明文")
        self.assertIsNone(r.getheader("Content-Encoding"), "★★ 明文还挂着 Content-Encoding —— 客户端会再解一次")
        self.assertEqual(Upstream.seen[-1][2], "gzip", "★★★ 上游没被要求 gzip —— 修复没生效")

    def test_fewer_bytes_cross_the_upstream_wire(self):
        """★★ ②：意义在线上字节。只断言"加了头"会放过「要了但没省下来」。"""
        self.ask()
        self.assertLess(Upstream.wire_bytes[-1] * 3, len(MODELS),
                        f"★★ 上游线上 {Upstream.wire_bytes[-1]} B，明文 {len(MODELS)} B —— 没省下来")

    def test_sse_posts_are_left_alone(self):
        """★★★ ③：POST 不要 gzip —— SSE 必须边到边转，整包缓冲会把流式输出憋成一次性吐出。"""
        r, _ = self.ask("POST", "/responses", {"Content-Type": "application/json"}, b"{}")
        self.assertEqual(r.status, 200)
        self.assertEqual(Upstream.seen[-1][:1], ("POST",))
        self.assertNotEqual(Upstream.seen[-1][2], "gzip", "★★★ POST 也被要了 gzip")

    def test_a_client_that_asked_for_gzip_gets_it_untouched(self):
        """★ ④：客户端自己要了 gzip ⇒ 原样透传，不替它解。"""
        r, data = self.ask(headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        self.assertEqual(gzip.decompress(data), MODELS)

    def test_upstream_ignoring_gzip_is_relayed_as_is(self):
        """⑤：上游不理 gzip、回明文 ⇒ 照常转发。"""
        Upstream.mode = "ignore_gzip"
        r, data = self.ask()
        self.assertEqual((r.status, data), (200, MODELS))

    def test_a_corrupt_gzip_body_becomes_a_clean_502(self):
        """★★ ⑥：还没发响应头 ⇒ 回干净的 502（GET 免费、客户端会重试），不是 200 + 半截。"""
        Upstream.mode = "corrupt"
        r, _ = self.ask()
        self.assertEqual(r.status, 502)

    def test_only_the_models_path_is_touched(self):
        """其它 GET 不动 —— 只改量过的那一个端点。"""
        self.ask(path="/usage")
        self.assertNotEqual(Upstream.seen[-1][2], "gzip")


if __name__ == "__main__":
    unittest.main(verbosity=2)
