"""agy 降级 reason 的**两边一致性**闸(同 `test_grok_reason_copy.py` 的纪律)。

`agy-quota` 产出 reason,`codexbar/src/agy.ts` 把它翻成用户能读懂的一句话。两边各写一份闭集,
只改一边就会出现「后端返回了一个 reason,前端 switch 落到 default」—— 用户看到一句什么都没说的
兜底文案,而**页面照常渲染、控制台照常干净**,没有任何东西会红。

所以断言两个集合**相等**,且都从源文件解析,不在这里粘第三份副本
(全局规则:守卫测试的期望值必须从真源推导)。

agy 这边多守一条 grok 没有的:
  ★ 文案否认的是**「额度耗尽」**,不是 grok 那句「额度为 0」。方向相反 ——
    grok 给已用(怕假的 0% = 没用过),agy 给剩余(怕假的 100% = 满格)。
    这两句话不能互抄,抄了就等于在用户面前把方向讲反。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "agy-quota"
TS = ROOT / "codexbar" / "src" / "agy.ts"

# 这两个 reason 描述的是"本机没有 agy / agy 没在跑",不是"额度读不到",所以豁免"否认耗尽"那条。
# ★ `no_process` 在这里豁免,但它**必须**给出可执行动作(见下面那条断言)——
#   它是最常出现的一个,一句"稍后重试"会让用户永远等不到数。
NOT_A_QUOTA_FAILURE = {"not_installed", "no_process"}


def py_reasons():
    src = PY.read_text(encoding="utf-8")
    block = src.split("REASONS = (", 1)[1].split(")", 1)[0]
    return {m.group(1) for m in re.finditer(r'"([a-z_]+)"', block)}


def ts_union():
    """`export type AgyReason = | "a" | "b" …` 里的字面量。"""
    src = TS.read_text(encoding="utf-8")
    block = src.split("export type AgyReason", 1)[1].split(";", 1)[0]
    return {m.group(1) for m in re.finditer(r'"([a-z_]+)"', block)}


def ts_switch_cases():
    """`agyReasonNote` 的 switch 里真的处理了哪些 case(default 不算)。"""
    src = TS.read_text(encoding="utf-8")
    body = src.split("export function agyReasonNote", 1)[1]
    return {m.group(1) for m in re.finditer(r'case\s+"([a-z_]+)"\s*:', body)}


def ts_note_bodies():
    """→ {reason: 这条 case 的返回文案(拼接后的字面量部分)}。"""
    src = TS.read_text(encoding="utf-8")
    body = src.split("export function agyReasonNote", 1)[1].split("\n}", 1)[0]
    out, cur, buf = {}, None, []
    for line in body.splitlines():
        # ★ `default:` 必须终止收集,否则兜底文案会被并进**最后一个** case ——
        #   那条 case 就会因为借了 default 的措辞而假绿(grok 那份正是这样发现的)。
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


def ts_tones():
    """→ {reason: 该 case 实际返回的 tone}。**要处理 fall-through**。

    ★ 第一版是"从 `case "no_process"` 往后找 muted"。那是个空守卫,两个方向都会骗人:
      · `case "no_process":` 若排在 fall-through 的**上面**,它自己那段里没有 return,
        于是查不到 muted ⇒ **假红**;
      · 往后多扫几十个字符去凑,又会捡到**下一个 case** 的返回值 ⇒ **假绿**。
      所以这里改成真的把 case 攒起来、遇到 return 才一起结算。
    """
    src = TS.read_text(encoding="utf-8")
    body = src.split("export function agyReasonTone", 1)[1].split("\n}", 1)[0]
    out, pending = {}, []
    for line in body.splitlines():
        for m in re.finditer(r'case\s+"([a-z_]+)"\s*:', line):
            pending.append(m.group(1))
        r = re.search(r'return\s+"([a-z]+)"', line)
        if r:
            for reason in pending:
                out[reason] = r.group(1)
            pending = []
    return out


class AgyReasonSetsAgree(unittest.TestCase):
    def test_parsers_actually_found_something(self):
        """★ 先证明解析器没打空 —— 空集合两两相等,会让下面每条断言都假绿。"""
        self.assertGreaterEqual(len(py_reasons()), 6)
        self.assertGreaterEqual(len(ts_union()), 6)
        self.assertGreaterEqual(len(ts_switch_cases()), 6)
        self.assertGreaterEqual(len(ts_note_bodies()), 6)

    def test_python_set_equals_typescript_union(self):
        self.assertEqual(py_reasons(), ts_union(),
                         "agy-quota 的 REASONS 与 agy.ts 的 AgyReason 不一致")

    def test_every_reason_has_a_switch_case(self):
        missing = py_reasons() - ts_switch_cases()
        self.assertEqual(missing, set(),
                         "这些 reason 会落到 default 兜底文案:{}".format(sorted(missing)))

    def test_no_orphan_switch_case(self):
        extra = ts_switch_cases() - py_reasons()
        self.assertEqual(extra, set(),
                         "agy.ts 处理了后端不会产出的 reason:{}".format(sorted(extra)))

    def test_every_note_denies_exhausted_quota(self):
        """★★ 方向断言:agy 要否认的是「额度耗尽」。

        上游 `remainingFraction` 缺省 1.0,所以这条链路的假绿形态是**满格**;
        文案若照抄 grok 的「不是额度为 0」,讲的就是反方向那件事。
        """
        for reason, note in ts_note_bodies().items():
            if reason in NOT_A_QUOTA_FAILURE:
                continue
            with self.subTest(reason=reason):
                self.assertIn("不是「额度耗尽」", note,
                              "{} 的文案没有否认耗尽 —— 用户分不出真假".format(reason))

    def test_no_note_borrows_grok_wording(self):
        """反向闸:抄了 grok 那句就红。两条链路方向相反,措辞不能串。"""
        for reason, note in ts_note_bodies().items():
            with self.subTest(reason=reason):
                self.assertNotIn("额度为 0", note,
                                 "{} 抄了 grok 的措辞(agy 给的是剩余,方向相反)".format(reason))

    def test_every_note_says_something_actionable(self):
        cues = ("起一次", "跑一次", "装了", "自动重试", "过几秒", "接口可能改了")
        for reason, note in ts_note_bodies().items():
            with self.subTest(reason=reason):
                self.assertTrue(any(c in note for c in cues),
                                "{} 的文案没给下一步动作也没说会自愈:{!r}".format(reason, note[:60]))

    def test_no_process_gives_a_real_action_not_just_retry(self):
        """★ `no_process` 是最常出现的一个。它的动作必须是"去起一个 agy",

        而不是"稍后重试" —— 重试**永远**修不了"进程没在跑",那正是 erp-v3
        那条无效提示的同款形态(告诉用户做一件对该状态无效的事)。
        """
        note = ts_note_bodies().get("no_process", "")
        self.assertTrue("起一次" in note or "跑一次" in note,
                        "no_process 必须告诉用户去起 agy,而不是等它自愈")

    def test_absence_reasons_are_muted_not_warning(self):
        """agy 不常驻,"没在跑"是常态。染成警告色 = 又造一盏长亮的灯。"""
        tones = ts_tones()
        self.assertGreaterEqual(len(tones), 3, "tone 解析器打空了,下面的断言会假绿")
        for reason in ("not_installed", "no_process"):
            with self.subTest(reason=reason):
                self.assertEqual(tones.get(reason), "muted",
                                 "{} 是常态不是故障,必须 muted".format(reason))


if __name__ == "__main__":
    unittest.main()
