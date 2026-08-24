"""grok 降级 reason 的**两边一致性**闸。

`grok-quota` 产出 reason,`codexbar/src/grok.ts` 负责把它翻成用户能读懂的一句话。
两边各写一份闭集,只改一边就会出现「后端返回了一个 reason,前端 switch 落到 default」——
用户看到的是一句什么都没说的兜底文案,而**页面照常渲染、控制台照常干净**,没有任何东西会红。

所以断言两个集合**相等**,并且都从源文件解析,不在这里粘贴第三份副本
(全局规则:守卫测试的期望值必须从真源推导)。

顺带守住文案本身的两条硬要求 —— 它们是这次改动存在的理由:
  ① 每条降级文案必须**明说这不是「额度为 0」**。0% 是"这周一点没用"的合法值,
     用户没有第二个办法分辨真假。
  ② 至少要有下一步动作或原因,不能只是"出错了"。反例是 erp-v3 那条让用户"重试"的提示 ——
     而重试根本修不了它指的那个状态。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "grok-quota"
TS = ROOT / "codexbar" / "src" / "grok.ts"

# 这两个 reason 描述的是"本机压根没有 grok",不是"额度读不到",所以豁免 ① 。
NOT_A_QUOTA_FAILURE = {"auth_file_missing", "auth_file_empty"}


def py_reasons():
    src = PY.read_text(encoding="utf-8")
    block = src.split("REASONS = (", 1)[1].split(")", 1)[0]
    return {m.group(1) for m in re.finditer(r'"([a-z_]+)"', block)}


def ts_union():
    """`export type GrokReason = | "a" | "b" …` 里的字面量。"""
    src = TS.read_text(encoding="utf-8")
    block = src.split("export type GrokReason", 1)[1].split(";", 1)[0]
    return {m.group(1) for m in re.finditer(r'"([a-z_]+)"', block)}


def ts_switch_cases():
    """`grokReasonNote` 的 switch 里真的处理了哪些 case(default 不算)。"""
    src = TS.read_text(encoding="utf-8")
    body = src.split("export function grokReasonNote", 1)[1]
    return {m.group(1) for m in re.finditer(r'case\s+"([a-z_]+)"\s*:', body)}


def ts_note_bodies():
    """→ {reason: 这条 case 的返回文案(拼接后的字面量部分)}。"""
    src = TS.read_text(encoding="utf-8")
    body = src.split("export function grokReasonNote", 1)[1].split("\n}", 1)[0]
    out, cur, buf = {}, None, []
    for line in body.splitlines():
        # ★ `default:` 必须终止收集,否则兜底文案会被并进**最后一个** case ——
        #   那条 case 就会因为借了 default 的措辞而假绿(第一版正是这样,靠它才发现的)。
        if re.match(r"\s*default\s*:", line):
            break
        m = re.search(r'case\s+"([a-z_]+)"\s*:', line)
        if m:
            if cur:
                out[cur] = "".join(buf)
            cur, buf = m.group(1), []
            continue
        if cur and ("return" in line or line.strip().startswith("+")):
            buf.extend(re.findall(r"`([^`]*)`", line))
    if cur:
        out[cur] = "".join(buf)
    return out


class GrokReasonSetsAgree(unittest.TestCase):
    def test_parsers_actually_found_something(self):
        """★ 先证明三个解析器没打空 —— 空集合两两相等,会让下面每条断言都假绿。"""
        self.assertGreaterEqual(len(py_reasons()), 5)
        self.assertGreaterEqual(len(ts_union()), 5)
        self.assertGreaterEqual(len(ts_switch_cases()), 5)
        self.assertGreaterEqual(len(ts_note_bodies()), 5)

    def test_python_set_equals_typescript_union(self):
        self.assertEqual(py_reasons(), ts_union(),
                         "grok-quota 的 REASONS 与 grok.ts 的 GrokReason 不一致")

    def test_every_reason_has_a_switch_case(self):
        missing = py_reasons() - ts_switch_cases()
        self.assertEqual(missing, set(),
                         "这些 reason 会落到 default 兜底文案:{}".format(sorted(missing)))

    def test_no_orphan_switch_case(self):
        extra = ts_switch_cases() - py_reasons()
        self.assertEqual(extra, set(),
                         "grok.ts 处理了后端不会产出的 reason:{}".format(sorted(extra)))

    def test_every_note_denies_zero_percent(self):
        """① 每条"额度读不到"的文案都要明说这不是 0%。"""
        for reason, note in ts_note_bodies().items():
            if reason in NOT_A_QUOTA_FAILURE:
                continue
            with self.subTest(reason=reason):
                self.assertIn("不是「额度为 0」", note,
                              "{} 的文案没有否认 0% —— 用户分不出真假".format(reason))

    def test_every_note_says_something_actionable(self):
        """② 不能只说"出错了"。要么给动作(跑一次/重新登录),要么说清会自愈。"""
        cues = ("起一次", "跑一次", "重新登录", "自动重试", "下次刷新", "登录过", "没有任何账号", "接口可能改了")
        for reason, note in ts_note_bodies().items():
            with self.subTest(reason=reason):
                self.assertTrue(any(c in note for c in cues),
                                "{} 的文案没给下一步动作也没说会自愈:{!r}".format(reason, note[:60]))


if __name__ == "__main__":
    unittest.main()
