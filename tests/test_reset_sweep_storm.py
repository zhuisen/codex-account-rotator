"""重置驱动的全池扫描不许变成**它自己判过死刑的那个东西**（2026-09-14 实测事故）。

## 事故

`_reset_crossed` 的旧注释写着：

    ★★ 判据必须是「快照拍摄于重置之前」，不能只是「重置时刻已过」。
      后者在服务端迟迟不更新 `resets_at` 时会恒为真，把兜底节拍变成每 60s 一扫，
      在 /usage 的 bot challenge 面前就是自找 403。这样写还顺带**自我清零**：
      扫描成功后 `captured_at > resets_at`，条件自动不再成立，不需要额外记"已触发过"。

前半句对，**结论错**。`captured_at` 只在 `/usage` 回 HTTP 200 **且带 rate_limit 窗口**时才前进
（非 2xx 不替换是 v0.12.10 的刻意设计）。所以：

    扫描失败 ⇒ captured_at 原地不动 ⇒ 条件恒真 ⇒ 每 60s 再扫一次 ⇒ 更容易 403 ⇒ 继续失败

**这道守卫在 403 出现的那一刻变成了 403 的放大器** —— 正是它那段注释判过死刑的形状，
只是触发条件写反了：不是"服务端不更新 resets_at"时发生，是"**我们拿不到新读数**"时发生。

## 实测数字（判据的来源，不是背景）

`quotad.log` 没有日期，只有 `[quotad HH:MM:SS]`。按「时间倒退 = 跨日」从文件尾切出
2026-09-14 当天那一段（264 行）再逐小时统计 `window reset crossed`：

    03:00→22  04:00→44  05:00→43  06:00→43  07:00→44  08:00→32   ← 设计节拍是 12 次/小时
    09:00 之后→ 1~2 次/小时

六个小时、约 228 次多余的全池 `/usage`，**正好罩住 06:03 那次 dawn-probe 全军覆没**
（5 个号同时 `SSL: UNEXPECTED_EOF_WHILE_READING`，重试后同错）。
⚠️ 这**不构成**「限流导致 SSL EOF」的证明，只是同时同机的正向证据；
   见本文件末尾 `TheEvidenceIsNotOverstated`。

## 这条闸守什么

**不是**「扫描频率不许超过 N」——那要跑真实循环。守的是纯函数的性质：
**同一个「账号 × 窗口 × 重置时刻」只许触发一次即时扫描**，无论那次扫描成没成功。
扫失败就退回 `USAGE_SECS`(300s) 的固定节拍兜底——那正是这个特性存在之前的行为。
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "daemon" / "quota_daemon.py").read_text(encoding="utf-8")


def _load_reset_crossed():
    """★ 只把被测函数抽出来执行，**不 import 模块本体**。

    `quota_daemon.py` 在模块顶层就 `SourceFileLoader` 把整个 `codex-rotate` 载进内存
    （第 44 行），而那个模块顶层会读真实 store 的路径常量。本仓的铁律是测试
    「绝不读真实 auth/state.json」，所以这里按 AST 边界切出函数源码单独 exec。
    """
    i = SRC.index("def _reset_crossed")
    j = SRC.index("\ndef log(", i)
    ns = {}
    exec(compile(SRC[i:j], "<reset_crossed>", "exec"), ns)
    return ns["_reset_crossed"]


NOW = 1_000_000


def _state(cap, ra, aid="a1", dead=False):
    return {"slots": {aid: {"auth_dead": dead,
                            "quota": {"primary": {"resets_at": ra}, "captured_at": cap}}}}


class TheImmediateSweepFiresOncePerReset(unittest.TestCase):

    def setUp(self):
        self.rc = _load_reset_crossed()

    def test_anchor_the_function_still_takes_a_memo(self):
        """★ 先证明被测目标还在。签名退回两参数的话，下面每条都会静默失效。"""
        fn = next(n for n in ast.walk(ast.parse(SRC))
                  if isinstance(n, ast.FunctionDef) and n.name == "_reset_crossed")
        names = [a.arg for a in fn.args.args]
        self.assertEqual(names, ["state", "now", "served"],
                         "★ `_reset_crossed` 的签名变了 —— 备忘录没了，这条闸在守空气")

    def test_it_fires_when_a_window_really_crossed(self):
        """★★ 正面：没有这条，下面那些「不再触发」全可以靠"永远返回 False"作弊通过。"""
        self.assertTrue(self.rc(_state(NOW - 500, NOW - 100), NOW, {}))

    def test_a_failed_sweep_does_not_re_trigger(self):
        """★★★ 事故本身：扫描失败（`captured_at` 原地不动）不许一直触发。"""
        served = {}
        st = _state(NOW - 500, NOW - 100)
        self.assertTrue(self.rc(st, NOW, served), "第一次该触发")
        for tick in range(1, 20):
            self.assertFalse(
                self.rc(st, NOW + tick * 60, served),
                "★ 第 {} 次仍然触发 —— 扫描失败后每 60s 一扫的正反馈回来了".format(tick + 1))

    def test_a_successful_sweep_also_stops_it(self):
        """★ 成功路径（`captured_at` 前进）本来就不该再触发 —— 旧实现这一半是对的，别改坏。"""
        served = {}
        self.assertTrue(self.rc(_state(NOW - 500, NOW - 100), NOW, served))
        self.assertFalse(self.rc(_state(NOW, NOW - 100), NOW + 60, served))

    def test_the_next_real_reset_fires_again(self):
        """★★ 防"修过头"：备忘录不许把**下一个**真实重置时刻也一起吞掉。

        这条就是「良性方向」的断言 —— 只堵不放的实现同样能让上面那条绿。
        """
        served = {}
        self.assertTrue(self.rc(_state(NOW - 500, NOW - 100), NOW, served))
        self.assertFalse(self.rc(_state(NOW - 500, NOW - 100), NOW + 60, served))
        # 窗口又滚了一轮：resets_at 前进到一个新时刻
        self.assertTrue(self.rc(_state(NOW - 500, NOW + 300), NOW + 400, served),
                        "★ 新的重置时刻被备忘录吞了 —— 即时扫描这个特性等于废了")

    def test_every_crossing_account_is_recorded_in_one_pass(self):
        """★★ 不许 `return` 早退。一次全池扫描覆盖所有号；只记第一个的话，
        第二个号会在下一拍再触发一次，等于把节流**按号乘了一遍**。"""
        st = {"slots": {
            "a1": {"quota": {"primary": {"resets_at": NOW - 100}, "captured_at": NOW - 500}},
            "a2": {"quota": {"primary": {"resets_at": NOW - 90}, "captured_at": NOW - 500}},
        }}
        served = {}
        self.assertTrue(self.rc(st, NOW, served))
        self.assertEqual(len(served), 2,
                         "★ 只记了 {} 个号 —— 另一个会在下一拍再触发一次扫描".format(len(served)))
        self.assertFalse(self.rc(st, NOW + 60, served))

    def test_dead_accounts_never_trigger(self):
        """已作废的号不该把全池扫描叫起来（旧实现也有这条，守住别丢）。"""
        self.assertFalse(self.rc(_state(NOW - 500, NOW - 100, dead=True), NOW, {}))

    def test_the_memo_does_not_grow_without_bound(self):
        """★ 号被删掉之后，它的备忘要清掉 —— 常驻进程里只增不减的 dict 是慢性泄漏。"""
        served = {}
        self.assertTrue(self.rc(_state(NOW - 500, NOW - 100, aid="gone"), NOW, served))
        self.assertEqual(len(served), 1)
        self.rc({"slots": {}}, NOW + 60, served)
        self.assertEqual(served, {}, "★ 号已经不在池里了，备忘还留着")


class TheFloorIsStillThere(unittest.TestCase):
    """★ 备忘录是**第二道**闸，不是替代品。`RESET_SWEEP_MIN_GAP` 那道地板必须还在——
    备忘录管"同一个重置时刻别重复"，地板管"两个不同重置时刻挨太近"。
    """

    def test_the_min_gap_constant_survives(self):
        m = re.search(r"^RESET_SWEEP_MIN_GAP\s*=\s*(\d+)", SRC, re.M)
        self.assertIsNotNone(m, "★ 地板常量没了")
        self.assertGreaterEqual(int(m.group(1)), 60, "★ 地板被调低了")

    def test_the_caller_still_ands_both_guards(self):
        """两道闸必须**同时**在调用点上；少一道都会让另一道单独顶不住。"""
        src = re.sub(r"#[^\n]*", "", SRC)          # ★ 剥注释：注释里正解释着这条规则
        i = src.index("reset_due =")
        seg = src[i:i + 260]
        self.assertIn("RESET_SWEEP_MIN_GAP", seg, "★ 调用点丢了地板")
        self.assertIn("reset_served", seg, "★ 调用点没把备忘录传进去 —— 函数改了但没人用")


class TheEvidenceIsNotOverstated(unittest.TestCase):
    """★★ 本仓铁律：别把推断写成实测。

    「扫描风暴导致了 06:03 的 SSL EOF」**没有被证明**，只有同时同机的正向证据。
    这条闸盯着注释本身，防止下一个人（包括我）把它读成已证。
    """

    def test_the_docstring_does_not_claim_causation(self):
        i = SRC.index("def _reset_crossed")
        doc = SRC[i:SRC.index('"""', SRC.index('"""', i) + 3)]
        self.assertIn("假说", doc, "★ 注释没把 SSL 那条标成假说 —— 会被读成已证")
        for overclaim in ("因此导致", "证明了 SSL", "根因是限流"):
            self.assertNotIn(overclaim, doc, "★ 注释把假说写成了结论：{}".format(overclaim))


if __name__ == "__main__":
    unittest.main()
