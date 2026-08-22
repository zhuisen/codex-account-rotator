"""Claude 增量解析的守卫测试。

★ 为什么必须有:增量算错**不报错**,只是数字小一点或大一点 —— 而这个项目里
  「一个看起来正常的错数字」比崩溃危险得多。整个改动敢上线的唯一理由是
  **守卫任何一道不过就退回全量,最坏等于改动前**;这个性质必须被钉住。

用合成夹具,不碰真实 `~/.claude`(那是活文件,且测试不该依赖它的内容)。
"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "traffic"))
import scan  # noqa: E402


def row_line(mid, ts="2026-08-01T00:00:00Z", i=10, cr=20, cw=0, out=5, model="claude-opus-5"):
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {
        "id": mid, "model": model,
        "usage": {"input_tokens": i, "cache_read_input_tokens": cr,
                  "cache_creation_input_tokens": cw, "output_tokens": out}}}) + "\n"


class IncrBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = pathlib.Path(self.tmp.name) / "s.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, mode="w"):
        with open(self.p, mode, encoding="utf-8") as f:
            f.write(text)
        return self.p.stat().st_size

    def entry(self):
        """整文件解析一次，造出缓存条目（含 off/anchors）。"""
        size = self.p.stat().st_size
        data = scan._scan_claude_file(self.p)
        off, anc = scan._full_off_anchors(self.p, size)
        return {"sig": [0, size], "r": data, "off": off, "a": anc}

    def incr(self, hit, size=None):
        # size 显式可传：删文件那个用例不能再 stat（异常会出在测试里，测不到被测代码）
        if size is None:
            size = self.p.stat().st_size
        return scan._incr_try(self.p, size, hit, scan._scan_claude_lines)


class TestIncrementalHappyPath(IncrBase):
    def test_append_matches_full_reparse(self):
        """★ 核心性质：增量结果必须与整文件重解析**逐键相同**。"""
        self.write(row_line("m1") + row_line("m2"))
        hit = self.entry()
        self.write(row_line("m3") + row_line("m4"), mode="a")
        got = self.incr(hit)
        self.assertIsNotNone(got, "正常追加不该退回全量")
        data, off, _ = got
        self.assertEqual(data, scan._scan_claude_file(self.p))
        self.assertEqual(off, self.p.stat().st_size)

    def test_unchanged_content_reuses_without_reparse(self):
        """长度没变 ⇒ 直接沿用旧结果（mtime 变了但内容没变是常态）。"""
        self.write(row_line("m1"))
        hit = self.entry()
        data, off, _ = self.incr(hit)
        self.assertIs(data, hit["r"], "内容没变时应原样沿用，不重新解析")
        self.assertEqual(off, hit["off"])


class TestPartialLine(IncrBase):
    def test_partial_tail_not_consumed(self):
        """★★ 半行绝不能算进 off —— 否则下次从它后面开始读，**那条记录永久丢失**。"""
        self.write(row_line("m1"))
        hit = self.entry()
        partial = row_line("m2").rstrip("\n")[:40]     # 写了一半的行，没有换行
        self.write(partial, mode="a")
        data, off, _ = self.incr(hit)
        self.assertEqual(off, hit["off"], "off 不该越过半行")
        self.assertEqual(set(data), {"m1"})

    def test_completed_line_picked_up_exactly_once(self):
        self.write(row_line("m1"))
        hit = self.entry()
        full = row_line("m2")
        self.write(full[:40], mode="a")               # 先写半行
        data, off, anc = self.incr(hit)
        hit2 = {"sig": [0, 0], "r": data, "off": off, "a": anc}
        self.write(full[40:], mode="a")               # 补完
        data2, off2, _ = self.incr(hit2)
        self.assertEqual(set(data2), {"m1", "m2"})
        self.assertEqual(data2, scan._scan_claude_file(self.p))
        self.assertEqual(off2, self.p.stat().st_size)


class TestGuardsFallBack(IncrBase):
    """拿不准必须返回 None(= 退回全量),**绝不能带着错数据往下走**。

    ⚠️ 变异测试的结论:真正起作用的是**锚点比对**那一道。把「文件变短」的检查拆掉,
      下面的截断用例照样红 —— 文件变短时 `[off-64KB, off)` 读不满,哈希必然对不上。
      所以别把「文件变短」当成一道独立保险,它是快速路径 + 防负数读。
    """

    def test_truncation_falls_back(self):
        self.write(row_line("m1") + row_line("m2") + row_line("m3"))
        hit = self.entry()
        self.write(row_line("m1"))                    # 截短
        self.assertIsNone(self.incr(hit), "文件变短必须退回全量")

    def test_head_rewrite_falls_back(self):
        self.write(row_line("m1") + row_line("m2"))
        hit = self.entry()
        # 同长度改写头部：长度、off 都没变，只有内容变了
        self.write(row_line("m9") + row_line("m2"))
        self.assertIsNone(self.incr(hit), "头部被改写必须退回全量")

    def test_consumed_region_rewrite_falls_back(self):
        """★ 最危险的一种:已消费区间被原地改写。它不改变文件长度,
        没有守卫的话增量会若无其事接着往后读,**且没有任何症状**。"""
        self.write("".join(row_line(f"m{i}") for i in range(60)))
        hit = self.entry()
        txt = self.p.read_text().splitlines(keepends=True)
        txt[30] = row_line("zz", i=999)               # 改中间一行，长度基本不变
        self.write("".join(txt))
        self.assertIsNone(self.incr(hit), "已消费区间被改写必须退回全量")

    def test_missing_offset_falls_back(self):
        """老缓存没有 off/a 字段（升级前写的）⇒ 退回全量，不能崩。"""
        self.write(row_line("m1"))
        self.assertIsNone(self.incr({"sig": [0, 1], "r": {}}))
        self.assertIsNone(self.incr({"sig": [0, 1], "r": {}, "off": 0}))

    def test_unreadable_file_falls_back(self):
        self.write(row_line("m1"))
        hit = self.entry()
        size = self.p.stat().st_size
        self.p.unlink()
        self.assertIsNone(self.incr(hit, size=size), "读不到文件要退回全量，不是抛异常")


if __name__ == "__main__":
    unittest.main()
