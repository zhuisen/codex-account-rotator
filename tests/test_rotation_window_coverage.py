"""轮换窗口的完整性判据（用户 2026-09-21：「代理轮换的数据欠缺」）。

## 这条闸守的是什么

`tail_truncated` 的**旧**判据是 `文件大小 > TAIL_BYTES` —— 与你选的窗口毫无关系。
实测 2026-09-21：proxy.log 长到 9.1MB 之后它**恒为真**，而 7d 窗口实际只需要 1.04MB、
一条数据都没少。界面因此天天挂着「仅统计日志尾部」，**真被截断的那天反而看不出来**。

★ 这是本仓头号铁律的一个变体：**「我少读了」≠「文件很大」**。一个曾经准确的标志退化成
  恒真的噪音，而一盏长亮的灯比没有灯更糟 —— 用户学会的是忽略它。

## 三态必须分开（合并任意两个都是 bug）

| covered | truncated | 含义 | 可补救吗 |
|---|---|---|---|
| True | False | 窗口完整 | —— |
| False | True | **上限切进了窗口**，本可以多读 | 能 |
| False | False | 日志本身就没那么早 | 不能：确实没有 |

`log_begins_at` 为 `None` 时**还要再分一次**：`undated_head`（那批行本来就没时间戳，
确实没有）vs `unreadable`（打不开，没打中）。合并就是又犯一次同样的错。
"""
import importlib.util
import time
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rot_cov", ROOT / "traffic" / "rotation.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

HOUR = 3600.0


def _log(path, now, oldest_hours, lines_per_hour=1, pad=0, undated_head=0):
    """造一份合成 proxy.log：从 `oldest_hours` 小时前一直写到现在。

    `pad` 给每行塞无意义的填充，用来把文件撑到想要的字节数 —— 这样"上限切进窗口"
    这一档才测得到，而**不必**去读真实的 9MB 日志（那会让闸依赖本机状态）。
    """
    out = []
    for _ in range(undated_head):
        out.append("[proxy] → POST /responses [plus5] new prev=-")
    n = int(oldest_hours * lines_per_hour)
    for i in range(n, 0, -1):
        t = time.localtime(now - i * HOUR / lines_per_hour)
        out.append(f"[proxy {t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:"
                   f"{t.tm_min:02d}:{t.tm_sec:02d}] → POST /responses [plus5] new prev=-"
                   + ("x" * pad))
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")


class TheThreeOutcomesAreDistinguishable(unittest.TestCase):
    """★★★ 三态各是各的。任意两个被合并，下面就有一条会红。"""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = str(Path(self.d.name) / "proxy.log")
        self.now = time.time()

    def tearDown(self):
        self.d.cleanup()

    def test_a_window_inside_the_log_is_covered(self):
        _log(self.p, self.now, oldest_hours=48, lines_per_hour=20)
        _, i = R._tail_covering(self.p, self.now - 6 * HOUR, self.now)
        self.assertTrue(i["covered"], "★★★ 窗口明明在日志里，却报成没覆盖")
        self.assertFalse(i["truncated"], "★★★ 没超上限却报成截断")

    def test_a_window_older_than_the_log_is_not_truncation(self):
        """★★★ 日志本身没那么早 ⇒ `truncated` 必须是 False。

        报成截断会让人以为"调大上限就能看到"，而那段时间**根本没有记录**。
        """
        _log(self.p, self.now, oldest_hours=6, lines_per_hour=20)
        _, i = R._tail_covering(self.p, self.now - 240 * HOUR, self.now)
        self.assertFalse(i["covered"])
        self.assertFalse(i["truncated"],
                         "★★★ 把「日志没那么早」说成了「被截断」—— 两者的下一步完全不同")

    def test_the_cap_cutting_into_the_window_is_truncation(self):
        """★★ 这一档才是 `tail_truncated` 现在唯一的含义。"""
        _log(self.p, self.now, oldest_hours=200, lines_per_hour=6, pad=900)
        _, i = R._tail_covering(self.p, self.now - 190 * HOUR, self.now, cap=64 * 1024)
        self.assertTrue(i["truncated"], "★★ 上限切进了窗口却没报截断")
        self.assertFalse(i["covered"])

    def test_the_file_being_big_alone_is_not_truncation(self):
        """★★★ **这就是那个 bug 本身**：文件远大于上限，但窗口很短、数据完整。"""
        _log(self.p, self.now, oldest_hours=200, lines_per_hour=6, pad=900)
        size = Path(self.p).stat().st_size
        cap = 64 * 1024
        self.assertGreater(size, cap * 4, "夹具没撑够大 —— 这条闸此刻没有判别力")
        _, i = R._tail_covering(self.p, self.now - 2 * HOUR, self.now, cap=cap)
        self.assertTrue(i["covered"], "★★★ 短窗口的数据是全的")
        self.assertFalse(i["truncated"],
                         "★★★ 又把「文件很大」当成「被截断」了 —— 用户 2026-09-21 报的就是它")


class ItNeverReadsMoreThanItNeeds(unittest.TestCase):
    """★★ 旧实现**每次都读 6MB** 并全量正则扫一遍，不管窗口多短。"""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = str(Path(self.d.name) / "proxy.log")
        self.now = time.time()
        _log(self.p, self.now, oldest_hours=400, lines_per_hour=6, pad=900)

    def tearDown(self):
        self.d.cleanup()

    def test_a_short_window_reads_far_less_than_a_long_one(self):
        _, short = R._tail_covering(self.p, self.now - 2 * HOUR, self.now)
        _, long_ = R._tail_covering(self.p, self.now - 300 * HOUR, self.now)
        self.assertLess(short["read_bytes"], long_["read_bytes"] / 2,
                        f"★★ 短窗口没少读：{short['read_bytes']} vs {long_['read_bytes']}")

    def test_it_never_exceeds_the_cap(self):
        """★ 第一版把上限判断放在**读之后**，倍增到 8MB 时先读了 8.39MB 才发现超限。

        ⚠️ `cap` **必须大于起步块** `_TAIL_CHUNK`，否则初始那次 `min` 就已经夹到 cap、
          倍增那一行根本走不到 —— 变异实测：cap=128KB 时把倍增里的 `cap` 拿掉也不红。
          这是本仓形态⑩：判据档位挑错，被上游另一条路径兜住了。
        """
        cap = R._TAIL_CHUNK + 200 * 1024
        self.assertGreater(cap, R._TAIL_CHUNK, "cap 不大于起步块 ⇒ 这条闸没有判别力")
        self.assertGreater(Path(self.p).stat().st_size, cap * 2, "夹具没撑够大")
        _, i = R._tail_covering(self.p, self.now - 9999 * HOUR, self.now, cap=cap)
        self.assertLessEqual(i["read_bytes"], cap,
                             f"★ 读了 {i['read_bytes']} 字节，超过上限 {cap}")


class WhyThereIsNoStartTimeIsItselfTwoDifferentThings(unittest.TestCase):
    """★★ `log_begins_at is None` 必须带原因，否则它自己又把两件事合并了。"""

    def test_an_undated_head_says_so(self):
        """实测本机：proxy.log 最早那批是 `[proxy] …`，带日期的格式是后来才加的。"""
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "proxy.log")
            _log(p, time.time(), oldest_hours=4, lines_per_hour=10, undated_head=3000)
            t, why = R._log_begins_at(p, time.time())
            self.assertIsNone(t)
            self.assertEqual(why, "undated_head",
                             "★★ 把「那段行没有时间戳」说成了别的")

    def test_an_unreadable_file_is_not_the_same_thing(self):
        t, why = R._log_begins_at("/nonexistent/proxy.log", time.time())
        self.assertIsNone(t)
        self.assertEqual(why, "unreadable",
                         "★★ 「打不开」与「确实没时间戳」返回了同一个值")

    def test_a_dated_head_reports_the_real_start(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "proxy.log")
            now = time.time()
            _log(p, now, oldest_hours=30, lines_per_hour=4)
            t, why = R._log_begins_at(p, now)
            self.assertEqual(why, "ok")
            self.assertAlmostEqual(t, now - 30 * HOUR, delta=2 * HOUR)


class TheUiSaysSomethingDifferentForEachOutcome(unittest.TestCase):
    """★★ 三态共用一句话，就等于又把它们合并了 —— 只是合并在展示层。"""

    def setUp(self):
        raw = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")
        # 剥注释：本仓形态④ —— 上面那段说明里正写着这些词
        import re
        self.code = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))

    def test_the_old_always_on_sentence_is_gone(self):
        self.assertNotIn("仅统计日志尾部", self.code,
                         "★★★ 那句恒真的话又回来了 —— 它由文件大小驱动，与窗口无关")

    def test_a_complete_window_says_nothing_at_all(self):
        """★ 完整是常态，说了就是噪音。"""
        i = self.code.index("windowNote")
        seg = self.code[i:i + 1400]
        self.assertIn('if (c.window_covered) return "";', seg,
                      "★ 窗口完整时仍在说话")

    def test_each_branch_tells_the_user_what_to_do(self):
        """★ 本仓 §5d：披露要说「做什么」，不是只说「坏了」。"""
        i = self.code.index("windowNote")
        seg = self.code[i:i + 1400]
        self.assertIn("更短的窗口", seg, "★ 可补救的那一档没说怎么补救")
        self.assertIn("确实没有数据", seg, "★ 不可补救的那一档没说清是「确实没有」")
        self.assertIn("无法判断", seg, "★ 读不到时说成了「数据完整」")


class TheAttributionRatioIsExplainedByTheRightCause(unittest.TestCase):
    """★★★ 一个**正确的数字**配了一个**错误的原因**，比数字错更难发现。

    旧文案把 `501/558` 解释成「直连 codex 的请求不经过代理」—— 但直连请求**连分母都进不去**
    （分母只数走过代理的响应），所以它影响的是「合计是下界」，**与这个比例毫无关系**。

    2026-09-21 实测查清了真因：缺的 57 个 response_id 去 `~/.codex/sessions` 逐个找，
    **57/57 根本没有 usage 记录** —— 不是解析漏了、也不是窗口剪枝剪掉了，是流式中断后
    turn 没完成，codex 就不写。按账号看缺失率与 stream err 率 **r = 0.98（n=6）**。

    ★ 而按本仓计费相位，`stream err` = 已送达上游 = **已计费** ⇒ 这不是"统计不全"，
      是"这些钱看不见"。文案必须说出这一点。
    """

    def setUp(self):
        import re
        raw = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")
        self.code = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))
        i = self.code.index("const covNote")
        self.seg = self.code[i:i + 900]

    def test_the_ratio_is_no_longer_blamed_on_direct_connections(self):
        """★★★ 「直连」那句可以留，但**不许紧跟在比例后面当它的解释**。"""
        j = self.seg.index("attributed_pct")
        between = self.seg[j:j + 260]
        self.assertNotIn("直连", between,
                         "★★★ 比例又被解释成「直连不经过代理」—— 那两件事不相干")

    def test_it_names_the_real_cause(self):
        self.assertIn("流式中断", self.seg, "★★ 没说出真因（流断 ⇒ codex 不写 usage 记录）")

    def test_it_says_the_money_was_actually_spent(self):
        """★ 只说「统计不全」会被读成"无所谓"，而这部分是真花了钱的。"""
        self.assertIn("已经计费", self.seg,
                      "★ 没说明这部分已计费 —— 用户会以为只是统计口径问题")

    def test_it_does_not_overclaim_a_per_request_join(self):
        """★★ 证据是账号级相关（r=0.98），**不是逐请求对上** —— 不许写成"全部"。

        proxy.log 给 affinity 行打 `#resp_…`、给 stream err 打代理自己的请求号，
        没有任何一行把两套 id 连起来。把相关写成因果正是本仓禁止的"把推断写成实测"。
        """
        self.assertIn("多数", self.seg,
                      "★★ 把相关写成了确定 —— 逐请求的 join 还不存在")
        self.assertNotIn("全部是流式中断", self.seg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
