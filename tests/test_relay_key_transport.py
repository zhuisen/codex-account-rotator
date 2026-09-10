"""★★★ 中转站 api key 的**传输面**闸：它绝不能离开我们打算给它的那个对端。

这个 key 是**按量扣钱的凭证**（本站实测一句 trivial prompt $0.0863）。
和账号池的 OAuth token 不一样，它泄漏了没有"轮换掉"这种补救 —— 只能换 key，
而在换掉之前每一秒都在替别人付钱。

## 两条路，都是"看起来一切正常"的那类失败

① **跨源重定向。** `urllib` 默认跟随重定向，而 `HTTPRedirectHandler.redirect_request`
   只剥掉**内容类头**（Content-Length / Content-Type）—— `Authorization` 原样带过去。
   对端回一句 `302 Location: https://别人家/`，我们就主动把 key 送上门，
   而调用方只看到一个正常的 200。不需要对端有恶意：一个被接管的域名就够了。

② **远端明文 http。** `store.validate` 原本只校验"是不是 http(s) 开头"，
   远端 `http://` 一路放行；而 `proxy.py::_relay_upstream()` 那侧一直要求 https。
   同一条规则三处实现，宽的那处说了算。

两条闸都**起一个真的 HTTP 服务**来测，不 mock urllib —— 要测的正是 urllib
自己的默认行为，把它 mock 掉就等于把被测对象换成了我的假设。
"""
import http.server
import json
import socket
import threading
import unittest

from relay import monitor, store


class _Handler(http.server.BaseHTTPRequestHandler):
    """`/redirect` → 302 到另一个 origin；`/landing` 把收到的 header 记下来。"""

    def do_GET(self):                                  # noqa: N802
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", self.server.target)
            self.end_headers()
            return
        # 落地页：**如实记下**有没有收到 Authorization。
        self.server.seen.append(self.headers.get("Authorization"))
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):                          # 别把测试日志刷满
        pass


def _serve():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    srv.seen, srv.target = [], ""
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class RelayKeyTransport(unittest.TestCase):
    SECRET = "sk-test-DO-NOT-LEAK-0123456789"

    @classmethod
    def setUpClass(cls):
        cls.a, cls.b = _serve(), _serve()          # 两个不同端口 ⇒ 两个不同 origin
        cls.a.target = f"http://127.0.0.1:{cls.b.server_port}/landing"

    @classmethod
    def tearDownClass(cls):
        for s in (cls.a, cls.b):
            s.shutdown(); s.server_close()

    def setUp(self):
        self.a.seen.clear(); self.b.seen.clear()

    def base(self, srv):
        return f"http://127.0.0.1:{srv.server_port}"

    # ── ① 跨源重定向 ───────────────────────────────────────────────────────
    def test_a_cross_origin_redirect_never_carries_the_key(self):
        """★ 判据是**第二个服务收没收到 key**，不是我们的返回值长什么样。

        只断言"返回了错误"会被一个"跟过去了但恰好报错"的实现骗过 —— key 已经发出去了。
        """
        st, detail = monitor._get(self.base(self.a), "/redirect", self.SECRET)
        self.assertEqual(self.b.seen, [],
                         f"★★ key 被带到了第二个 origin: {self.b.seen}")
        # 且必须**说出原因**。静默返回一个空结果会伪装成"对端没数据"。
        self.assertIn("跨源", str(detail))
        self.assertNotIn(self.SECRET, str(detail), "错误详情里不许回显 key")
        self.assertIsNotNone(st)

    def test_a_same_origin_redirect_still_works(self):
        """反向闸：同源跳转必须照常跟过去，否则"修法"退化成禁用重定向。

        路径级跳转（`/usage` → `/api/usage`）是真实存在的，一刀切禁掉会把
        一整类正常中转站判死。
        """
        self.a.target = "/landing"                 # 同源相对跳转
        try:
            st, body = monitor._get(self.base(self.a), "/redirect", self.SECRET)
            self.assertEqual(st, 200, f"同源跳转被误杀: {body}")
            self.assertEqual(self.a.seen, [f"Bearer {self.SECRET}"])
        finally:
            self.a.target = f"http://127.0.0.1:{self.b.server_port}/landing"

    def test_the_redirect_guard_counts_the_port(self):
        """★ 同源判据必须带端口。两个服务同为 `127.0.0.1`，只比 hostname 会放过去。

        这条正是上面那个夹具的存在理由 —— 它俩 host 相同、端口不同。
        """
        self.assertNotEqual(monitor._origin(self.base(self.a) + "/x"),
                            monitor._origin(self.base(self.b) + "/x"))

    # ── ② 远端明文 http ────────────────────────────────────────────────────
    def test_plain_http_to_a_remote_host_is_refused_before_sending(self):
        st, detail = monitor._get("http://relay.example.com", "/usage", self.SECRET)
        self.assertIsNone(st)
        self.assertIn("明文", detail)
        self.assertNotIn(self.SECRET, detail)

    def test_plain_http_to_loopback_is_still_allowed(self):
        """反向闸：自建 one-api 跑在 `http://127.0.0.1:3000` 是正常用法。
        流量不出网卡，禁掉它是把一条安全规则变成一次功能回归。"""
        self.assertTrue(monitor._key_is_safe_to_send("http://127.0.0.1:3000/usage"))
        self.assertTrue(monitor._key_is_safe_to_send("http://[::1]:3000/usage"))
        self.assertTrue(monitor._key_is_safe_to_send("https://relay.example.com/usage"))
        self.assertFalse(monitor._key_is_safe_to_send("http://relay.example.com/usage"))

    def test_config_validation_rejects_remote_plain_http(self):
        """★ 同一条规则在**配置时**也要挡 —— 否则用户加号时一切正常，
        直到某次刷新才在日志角落里看到一句拒绝。"""
        row = {"id": "r1", "base_url": "http://relay.example.com/v1", "key": "k"}
        self.assertTrue([e for e in store.validate(row) if "明文" in e],
                        f"远端明文 http 被配置校验放行了: {store.validate(row)}")
        for good in ("https://relay.example.com/v1", "http://127.0.0.1:3000/v1",
                     "http://[::1]:3000/v1"):
            self.assertEqual([e for e in store.validate({**row, "base_url": good})
                              if "明文" in e], [], f"误杀: {good}")


if __name__ == "__main__":
    unittest.main()
