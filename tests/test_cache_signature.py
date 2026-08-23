"""缓存签名必须能分辨「同一秒内、长度不变」的改写。

★ 这类失效**没有任何症状**：缓存原样沿用旧解析结果，页面上的数字只是悄悄停在旧值。
  没有报错、没有告警，只有「怎么好像没更新」。所以必须有一道会红的闸。

★ 断言锚在**生产实现** `scan._sig` 上，不是复制一份算法 ——
  同一天刚栽过：另一个测试自己抄了边界计算，改坏 `scan.py` 它照样绿。
"""
import json
import pathlib
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "traffic"))
import scan  # noqa: E402


def _row(mid, out):
    return json.dumps({
        "type": "assistant", "timestamp": "2026-08-20T00:00:00Z",
        "message": {"id": mid, "model": "claude-opus-5", "usage": {
            "input_tokens": 10, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0, "output_tokens": out}}}) + "\n"


class TestCacheSignature(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = pathlib.Path(self.tmp.name) / "s.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_second_same_size_rewrite_is_detected(self):
        """★ 核心用例：**等长 + 同一秒**改写，签名必须变。

        实测两次写入可以只相隔 0.09ms，而 `int(st_mtime)` 在整整一秒内都是同一个值。
        """
        a, b = _row("m1", 111), _row("m1", 222)
        self.assertEqual(len(a), len(b), "夹具本身必须等长，否则测的是 size 不是 mtime")
        self.p.write_text(a)
        s1 = scan._sig(self.p.stat())
        self.p.write_text(b)
        s2 = scan._sig(self.p.stat())
        self.assertEqual(int(s1[0] // 1_000_000_000), int(s2[0] // 1_000_000_000),
                         "两次写入应落在同一秒内，否则这个用例没打中要害")
        self.assertNotEqual(s1, s2,
                            "同一秒内的等长改写没被签名分辨出来 —— 缓存会沿用旧解析结果，"
                            "而且没有任何症状")
        # 解析结果确实不同 ⇒ 误判为「未变动」会让页面数字停在旧值
        self.assertEqual(list(scan._scan_claude_file(self.p).values())[0][5], 222)

    def test_unchanged_file_keeps_same_signature(self):
        """反向：没动过的文件签名必须稳定，否则每次扫描都全量重解析。"""
        self.p.write_text(_row("m1", 111))
        s1 = scan._sig(self.p.stat())
        time.sleep(0.01)
        self.assertEqual(s1, scan._sig(self.p.stat()))

    def test_signature_uses_nanoseconds(self):
        """把实现钉在 `st_mtime_ns` 上 —— 秒级字段是这个 bug 的来源。"""
        self.p.write_text(_row("m1", 111))
        st = self.p.stat()
        self.assertEqual(scan._sig(st), [st.st_mtime_ns, st.st_size])
        self.assertNotEqual(scan._sig(st), [int(st.st_mtime), st.st_size],
                            "签名退回秒级了 —— 同秒等长改写会被漏掉")


if __name__ == "__main__":
    unittest.main()
