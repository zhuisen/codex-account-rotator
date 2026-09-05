"""探针必须留痕,且「能干活」与「读到额度」必须分开(2026-09-05)。

## 两个事故

### ① 探针跑完什么痕迹都不留

探针写回的 `quota` 带 `source: "probe"`,但 quotad 走 usage-api **整体替换** `slot["quota"]`
(活跃号 20s、否则 300s 一轮),于是 `state.json` 里**永远找不到一条 `source == "probe"`** ——
事后无法回答「我刚才那次探针到底跑成没有」。这与代理那批额外响应头踩的是同一个坑,
解法也一样:**独立兄弟键**,各带自己的时间戳,互不覆盖。

★ 成功、失败、跳过**都要写**。只记成功的话,「没跑过」和「跑了但失败」在 state 里
长得一模一样(都是没有这个键),又一次把「读不到」和「确实没有」折叠成同一个值。

### ② 模型答了、但响应头没带额度 ⇒ 被报成失败

`_billed_probe` 在 `pu is None and su is None` 时返回 `q=None`,**即使模型正常吐了字**。
调用方原来一律打 ✗ 且不计入可用数 —— **一个真能用的号被报成坏的,而那次计费请求已经花掉了**。
探针存在的意义是回答「这个号还能不能干活」,额度是副产品;拿副产品的缺失否定主判据,
正好把工具的目的搞反。

## 断言
① 三条路径(成功 / 失败 / 跳过死号)都写 `last_probe`;
② `completion_ok` 与 `quota_ok` 是两个独立字段,不许合并;
③ 「答了但没额度头」计入可用、且不写 quota;
④ `last_probe` 里**不存 used%**(一份事实只能有一个家)。
"""
import importlib.machinery
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CR = ROOT / "codex-rotate"


def load():
    loader = importlib.machinery.SourceFileLoader("cr_trace", str(CR))
    spec = importlib.util.spec_from_loader("cr_trace", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


class WriterWritesToTheSiblingKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def test_writes_last_probe_not_quota(self):
        """★★ 必须写兄弟键,**不能碰 `quota`** —— 碰了就会被 usage-api 抹掉。"""
        st = {"slots": {"A": {"quota": {"source": "usage-api", "primary": {"used_percent": 7.0}}}}}
        orig = self.m._mutate_state
        self.m._mutate_state = lambda f: f(st)
        try:
            self.m._write_last_probe("A", at=1, status="ok", completion_ok=True, quota_ok=True)
        finally:
            self.m._mutate_state = orig
        self.assertIn("last_probe", st["slots"]["A"])
        self.assertEqual(st["slots"]["A"]["quota"]["source"], "usage-api",
                         "探针痕迹污染了 quota —— 那正是会被 quotad 覆盖掉的地方")

    def test_unknown_slot_is_a_noop_not_a_crash(self):
        st = {"slots": {}}
        orig = self.m._mutate_state
        self.m._mutate_state = lambda f: f(st)
        try:
            self.m._write_last_probe("missing", at=1)
        finally:
            self.m._mutate_state = orig
        self.assertEqual(st["slots"], {})


class ProbeSourceCoversEveryOutcome(unittest.TestCase):
    """静态闸:三条路径都要留痕,且两个 ok 分开。"""

    def setUp(self):
        src = CR.read_text(encoding="utf-8")
        i = src.index("def cmd_probe(")
        self.body = src[i:src.index("\ndef ", i + 10)]
        self.code = re.sub(r"#[^\n]*", "", self.body)

    def test_anchor_found(self):
        """★ 先证明切到的是真函数体,否则下面都在空串上恒绿。"""
        self.assertIn("_billed_probe", self.body)
        self.assertGreater(len(self.body), 800)

    def test_every_outcome_writes_a_trace(self):
        """成功 / 失败 / 跳过 —— 至少三处调用。"""
        n = len(re.findall(r"_write_last_probe\(", self.code))
        self.assertGreaterEqual(n, 3,
                                "只有 %d 处留痕 —— 成功/失败/跳过必须都写" % n)

    def test_records_skipped_dead(self):
        self.assertIn("skipped_dead", self.code,
                      "被 --all 跳过的死号没有留痕,用户点了「全池」却不知道漏了谁")

    def test_completion_and_quota_are_separate_fields(self):
        for f in ("completion_ok", "quota_ok"):
            with self.subTest(field=f):
                self.assertIn(f, self.code, "缺字段 %s —— 两件事被合并了" % f)

    def test_answered_without_quota_headers_counts_as_usable(self):
        """★★ 事故②:有答案就该计入可用,不能因为没额度头而报失败。"""
        self.assertRegex(
            self.code, r"if not q and not completion_ok",
            "失败判据仍然只看 q —— 模型答了但没额度头时会被误报为不可用")
        self.assertIn("ok_no_quota_headers", self.code,
                      "缺少「可用但额度未读到」这个中间状态")

    def test_quota_written_only_when_present(self):
        """没有 q 时不许写 quota（否则写进去一个 None 窗口）。"""
        self.assertRegex(self.code, r"if q:\s*\n\s*_mutate_state",
                         "quota 的写入没有被 `if q` 守住")

    def test_trace_does_not_store_used_percent(self):
        """★ 一份事实一个家：used% 归 quota，事件归 last_probe。

        存进来的话 20 秒后就会和 usage-api 的读数分叉，而 UI 很容易拿事件里的陈旧数当现值。
        """
        calls = re.findall(r"_write_last_probe\((.*?)\)\n", self.code, re.S)
        self.assertTrue(calls, "没抓到任何调用 —— 断言可能打空了")
        for c in calls:
            with self.subTest(call=c[:60]):
                self.assertNotIn("used_percent", c)
                self.assertNotIn("after", c)
                self.assertNotIn("before", c)


if __name__ == "__main__":
    unittest.main()
