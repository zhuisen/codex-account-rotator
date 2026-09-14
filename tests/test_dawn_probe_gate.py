"""每日清晨计费探针白跑了必须有人说（2026-09-14 体检查出）。

## 来历

今天 06:03 的 dawn-probe **5 个号全败**（全部 `SSL: UNEXPECTED_EOF_WHILE_READING`，
重试后同错），而**没有任何一处会为此变红**：

- `codex-rotate health` 只字未提；
- 设置页的 `dawnDesc` 把 `0/5 可用` 和 `4/4 可用` 画成同一行中性文字；
- `state.json` 里 `dawn_probe.note` 是 `""` —— 而那是 `done` 路径**恒写空**的，
  拿它当"没有异常"就是恒绿。

是翻 `dawnprobe.log` 才看到的。这是本仓「第二次抓到同一类 bug，交付物是一条**会变红的检查**」
的第三次，所以这一轮的交付物是这个文件。

## ★★★ 判据刻意**不是**「5h 窗口有没有锚定」

那个问题今天的答案是"锚定了"——但锚定它的是 08:45 一次**手动** `probe --all`，
不是这个定时器。拿结果当判据，会让「定时器已经连着几天白跑」永远不报，
而那正是本仓 `keepalive/refreshquota` 的 `runs = 0` 前科的形状。
**这条闸报的是运营事实：今天这次自动计费尝试，成了没有。**

## ★★ warn 与 unknown 的下一步动作**正好相反**，所以不能合并

    全部 `send err`  ⇒ 请求没完整送达 ⇒ 可证未计费 ⇒ 今天**可以**安全重跑
    含 `committed`   ⇒ 已送达可能已判决 ⇒ **绝不能**重跑，重跑 = 二次扣费

合并成一个"失败"等级，等于让用户在"可能重复扣费"上掷硬币。
"""
import importlib.machinery
import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_SRC = (ROOT / "codex-rotate").read_text(encoding="utf-8")

# ★ 按路径 import 是允许的（模块顶层只有常量），但**绝不读真实 state.json**：
#   下面每条都自带 `state=` 夹具，`dawn_probe_gate` 因此走不到 `_state()`。
CLI = importlib.machinery.SourceFileLoader("cr_gate", str(ROOT / "codex-rotate")).load_module()

TODAY = time.strftime("%Y-%m-%d")


def at(hour, minute=30):
    return time.mktime(time.strptime("{} {:02d}:{:02d}".format(TODAY, hour, minute),
                                     "%Y-%m-%d %H:%M"))


def gate(dawn, hour=12):
    return CLI.dawn_probe_gate(now=at(hour), state={"dawn_probe": dawn})


def done(ok, total=5, **extra):
    d = {"enabled": True, "date": TODAY, "state": "done", "ok": ok, "total": total}
    d.update(extra)
    return d


class TheGateStaysQuietWhenNothingWasPromised(unittest.TestCase):

    def test_disabled_is_not_a_failure(self):
        """没开就没承诺。给一个自己关掉的功能报警 = 训练用户忽略告警。"""
        self.assertEqual(gate({"enabled": False})["level"], "ok")

    def test_before_the_grace_hour_is_not_a_failure(self):
        """★ 06:00 的任务在 08:30 还没记录不算异常：Mac 多半在睡，唤醒补跑要时间。"""
        self.assertEqual(gate({"enabled": True, "date": "2026-09-01"}, hour=8)["level"], "ok")

    def test_no_plus_accounts_is_not_a_failure(self):
        """`total == 0` 是"没有可探的号"，不是"探失败了"。"""
        self.assertEqual(gate(done(0, total=0))["level"], "ok")

    def test_a_partial_success_is_not_a_failure(self):
        """★ 只要有一个号成了，窗口就被锚上了 —— 这条闸不是用来追求满分的。"""
        self.assertEqual(gate(done(4))["level"], "ok")

    def test_a_fresh_running_record_is_not_a_failure(self):
        self.assertEqual(
            gate({"enabled": True, "date": TODAY, "state": "running",
                  "at": int(at(12)) - 5, "total": 5})["level"], "ok")


class TheGateGoesRedOnTheThingsThatActuallyHappen(unittest.TestCase):

    def test_the_timer_never_fired_today(self):
        """★★★ `runs = 0` 那个前科的形态：任务装了、但根本没触发。"""
        g = gate({"enabled": True, "date": "2026-09-01"}, hour=12)
        self.assertEqual(g["level"], "warn")
        self.assertTrue(any("launchctl" in l for l in g["lines"]),
                        "★ 没给出查定时器的命令 —— 只说'坏了'不说'做什么'")

    def test_a_stale_running_record_is_flagged_as_maybe_billed(self):
        """★ 中途死了 ⇒ 日期已占、今天不会重试，而且**可能已经花过钱**。"""
        g = gate({"enabled": True, "date": TODAY, "state": "running",
                  "at": int(at(6)), "total": 5}, hour=12)
        self.assertEqual(g["level"], "unknown")
        self.assertTrue(any("别直接重跑" in l for l in g["lines"]))

    def test_todays_actual_shape_zero_of_five(self):
        """★★★ 今天这次本身：0/5。旧实现对它完全沉默。"""
        self.assertNotEqual(gate(done(0))["level"], "ok",
                            "★ 今天 0/5 被判成正常 —— 这正是要修的那个沉默")


class TheTwoFailureKindsGiveOppositeAdvice(unittest.TestCase):
    """★★ 这一组才是这条闸真正的价值：**说清下一步做什么**，而两种情况正好相反。"""

    def test_provably_unbilled_says_you_may_retry(self):
        g = gate(done(0, billing="unbilled", phases={"send_err": 5}))
        self.assertEqual(g["level"], "warn")
        joined = "\n".join(g["lines"])
        self.assertIn("--force", joined, "★ 可证未计费却没告诉用户可以重跑")
        self.assertNotIn("不要", joined, "★ 可证未计费却劝人别重跑 —— 建议给反了")

    def test_maybe_billed_says_do_not_retry(self):
        g = gate(done(0, billing="maybe", phases={"committed_err": 1, "send_err": 4}))
        self.assertEqual(g["level"], "unknown")
        joined = "\n".join(g["lines"])
        self.assertIn("不要", joined, "★ 可能已计费却没有制止重跑")

    def test_the_two_levels_are_not_the_same(self):
        """★★ 合并成一个等级 = 让用户在"可能重复扣费"上掷硬币。"""
        a = gate(done(0, billing="unbilled", phases={"send_err": 5}))["level"]
        b = gate(done(0, billing="maybe", phases={"committed_err": 1}))["level"]
        self.assertNotEqual(a, b, "★ 两种失败被折叠成同一个等级")

    def test_a_record_without_phases_refuses_to_recommend_retry(self):
        """★★★ **判不出来时按"可能已计费"处理**（旧版本写的记录就没有这个字段）。

        这是钱这一侧的 fail-safe：把"不知道"当成"安全"，代价是可能二次扣费。
        """
        g = gate(done(0))
        self.assertEqual(g["level"], "unknown")
        self.assertNotIn("可以安全重跑", "\n".join(g["lines"]))


class TheJudgementDoesNotUseALyingField(unittest.TestCase):

    def test_note_is_never_the_criterion(self):
        """★★ `note` 在 `done` 路径上**恒写 `""`**，拿它判就是恒绿。

        判据打在函数体上：`dawn_probe_gate` 不许读 `note`。
        """
        i = CLI_SRC.index("def dawn_probe_gate")
        body = CLI_SRC[i:CLI_SRC.index("\ndef proxy_env_gate", i)]
        body = re.sub(r"#[^\n]*", "", body)          # ★ 剥注释：说明里正解释着这条
        body = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
        self.assertNotIn('"note"', body, "★ 闸又去读 note 了 —— 那个字段恒空，会让它恒绿")

    def test_the_done_path_really_does_blank_the_note(self):
        """★ 证明上面那条不是空守卫：`done` 那次 `_save` 里 `note` 确实写死成空。"""
        i = CLI_SRC.index('"state": "done"')
        self.assertIn('"note": ""', CLI_SRC[i:i + 300],
                      "★ done 路径不再写空 note 了 —— 上面那条判据要重写")


class TheGateIsWiredIntoHealth(unittest.TestCase):
    """★★★ 只定义不接线等于没做 —— 本仓刚在 `read_logs` 上栽过一次同样的。"""

    def test_health_calls_it_and_prints_it(self):
        src = re.sub(r"#[^\n]*", "", CLI_SRC)
        self.assertIn("dawn_probe_gate()", src, "★ health 没调用这条闸")
        i = src.index("pgate = dawn_probe_gate()")
        seg = src[i:i + 700]
        self.assertIn('pgate["level"] != "ok"', seg, "★ 调了但没判等级")
        self.assertIn('pgate["lines"]', seg, "★ 判了但没印出来 —— 用户永远看不到")




class EveryBilledProbeRecordsWhoTriggeredIt(unittest.TestCase):
    """★★★ 「谁在自动花钱」必须有答案（2026-09-14 加）。

    当天 08:45:00–08:45:50 有一次 `probe --all`（7 个槽位被写过：5 真探 + 2 跳过
    ⇒ 5 次真实计费），而 `last_probe` 里**没有任何字段**能说出是定时器、
    界面按钮还是终端触发的。本仓最贵的问题恰好是这一个，而这条链路当时答不上来。
    """

    def test_last_probe_always_carries_a_via(self):
        i = CLI_SRC.index("def _write_last_probe")
        body = CLI_SRC[i:CLI_SRC.index("\ndef ", i + 10)]
        self.assertIn('setdefault("via"', body,
                      "★ `last_probe` 不再记来源 —— 下一次不明计费又查不出来了")

    def test_the_default_does_not_impersonate_the_terminal(self):
        """★★ 取不到时**不许**写成 `"cli"`。

        那会把「没传这个变量」和「真的是从终端跑的」折叠成同一个值 ——
        本仓反复记的那种「这一枪没打中和确实没有返回同一个值」。
        """
        i = CLI_SRC.index("def _write_last_probe")
        body = CLI_SRC[i:CLI_SRC.index("\ndef ", i + 10)]
        m = re.search(r'setdefault\("via",\s*os\.environ\.get\([^)]*\)\s*or\s*"([^"]+)"', body)
        self.assertIsNotNone(m, "★ 缺省值的写法变了，这条判据要重写")
        self.assertNotEqual(m.group(1), "cli",
                            "★ 缺省写成 `cli` = 把「没证据」伪装成「从终端跑的」")

    def test_the_dawn_path_labels_itself(self):
        i = CLI_SRC.index("def cmd_dawn_probe")
        body = CLI_SRC[i:CLI_SRC.index("cmd_probe([], aids=targets)", i)]
        self.assertIn('CODEX_ROTATE_CALLER"] = "dawn"', body,
                      "★ 定时器那条路没有自己的标记 —— 它正是最该认得出来的一条")

    def test_the_ui_bridge_labels_itself_at_the_single_entry_point(self):
        """★ 必须加在 `spawn_cmd`（所有子进程的唯一入口），不是逐个调用点 ——
        逐个加迟早漏一个，而漏掉的那条正好会伪装成"从终端跑的"。"""
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("fn spawn_cmd(")
        self.assertIn('CODEX_ROTATE_CALLER", "ui"', rs[i:i + 1400],
                      "★ Tauri 侧没在唯一入口打标记")


if __name__ == "__main__":
    unittest.main()
