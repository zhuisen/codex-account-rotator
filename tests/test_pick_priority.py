"""手工轮换优先级（用户 2026-09-19 定：**优先级压过额度**）。

## 语义

排序键 `(套餐档, 手工优先级, 最紧窗口已用%)`。三件事按这个次序说了算：

1. **Plus 优先、Pro 保底** —— 2026-09-07 的策略 C，保留不变；
2. **手工优先级** —— 用户在总览拖出来的顺序，写进 `state.json` 的 `pick_order`；
3. 最紧窗口已用% —— 原来的档内排序，现在降到第三位。

★ 「优先级压过额度」是字面意思：排第一的号**已用 100% 仍排第一**，一直用到 429 撞限、
  冷却后才轮到第二个。用户看过三个方案后选的就是这一档，代价（不再自动摊平）已知情。

## 这几条闸守的是什么

- ★★★ **迟滞不得跨优先级。** 迟滞原来只比「档 + 已用%」，于是一个粘在**低优先级**号上的
  会话会因为「没比最省的贵多少」而一直粘着 —— 把刚设的优先级**静默绕过去**，
  而界面上顺序明明是对的、额度数字看着也合理。与 2026-09-07「迟滞不得跨套餐档」同形。
- ★★ **没排过的号追加在末尾，不丢也不饿死。** 新号、刚复活的号本来就不在顺序里；
  当成"最高优先级"会让它抢走全部流量，当成"永不使用"则是静默饿死。
- ★ **failover 不受影响** —— `ok()` 在排序**之前**过滤 dead/冷却/已试过，
  所以优先级再高的号撞限了也照样跳过。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CODEX_ROTATE_STORE", str(ROOT))
_spec = importlib.util.spec_from_file_location("px_prio", ROOT / "proxy" / "proxy.py")
PX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PX)


def slot(label, plan="plus", used=0.0):
    return {"label": label, "plan": plan,
            "quota": {"primary": {"window_minutes": 300, "used_percent": used,
                                  "resets_at": None},
                      "secondary": {}}}


def order(slots, pick_order=None):
    """按**生产排序函数**排出的 label 顺序。

    ⚠️ 第一版在这里**抄了一份排序键**，于是改 `proxy.py` 的真排序行对它毫无影响 ——
    变异实测：去掉优先级、把优先级提到套餐档之前，**两条都没被抓到**。
    现在调的是生产里唯一那份 `_sort_avail`。本仓铁律：闸的期望值要从真源推导。
    """
    state = {"slots": slots, "pick_order": pick_order or []}
    return [kv[1]["label"] for kv in PX._sort_avail(list(slots.items()), state)]


class PriorityBeatsQuota(unittest.TestCase):
    """★★ 用户选的就是这一档：排第一的号**已用 100% 仍排第一**。"""

    def test_the_first_ranked_account_wins_even_when_nearly_exhausted(self):
        slots = {"a": slot("Asen", used=100.0), "b": slot("Egan", used=0.0)}
        self.assertEqual(order(slots, ["a"])[0], "Asen",
                         "★★ 优先级没压过额度 —— 与用户 2026-09-19 的选择相反")

    def test_without_a_priority_quota_still_decides(self):
        """没排过的机器行为**零变化**（仍按最紧窗口已用% 最少）。"""
        slots = {"a": slot("Asen", used=100.0), "b": slot("Egan", used=0.0)}
        self.assertEqual(order(slots, [])[0], "Egan")

    def test_the_ranked_order_is_followed_exactly(self):
        slots = {"a": slot("A"), "b": slot("B"), "c": slot("C")}
        self.assertEqual(order(slots, ["c", "a", "b"]), ["C", "A", "B"])


class PlanTierStillComesFirst(unittest.TestCase):
    """★ 「Plus 优先、Pro 保底」是 2026-09-07 用户自己定的，本次**明确保留**。"""

    def test_a_top_ranked_pro_still_loses_to_any_plus(self):
        slots = {"p": slot("Pro1", plan="pro", used=0.0),
                 "u": slot("Plus9", plan="plus", used=99.0)}
        self.assertEqual(order(slots, ["p", "u"])[0], "Plus9",
                         "★ 优先级凌驾了套餐档 —— 用户选的是「只在档内生效」")

    def test_priority_orders_within_the_plus_tier(self):
        slots = {"x": slot("X", used=1.0), "y": slot("Y", used=2.0),
                 "p": slot("Pro1", plan="pro")}
        self.assertEqual(order(slots, ["y", "x"]), ["Y", "X", "Pro1"])


class AnUnrankedAccountIsNeitherStarvedNorPromoted(unittest.TestCase):
    """★★ 新号/刚复活的号不在顺序里 —— 追加末尾是唯一既不抢也不饿的位置。"""

    def test_it_goes_last_not_first(self):
        slots = {"a": slot("Ranked", used=99.0), "n": slot("新号", used=0.0)}
        self.assertEqual(order(slots, ["a"]), ["Ranked", "新号"])

    def test_it_is_never_dropped(self):
        slots = {"a": slot("A"), "b": slot("B"), "n": slot("新号")}
        self.assertEqual(sorted(order(slots, ["b", "a"])), ["A", "B", "新号"])

    def test_several_unranked_keep_a_stable_relative_order(self):
        slots = {"a": slot("A", used=5.0), "m": slot("M", used=1.0), "n": slot("N", used=9.0)}
        got = order(slots, ["a"])
        self.assertEqual(got[0], "A")
        self.assertEqual(got[1:], ["M", "N"], "未排序的之间仍按额度排")

    def test_a_stale_aid_in_the_order_does_not_break_anything(self):
        """删过的号还留在 `pick_order` 里，不能影响其余排序。"""
        slots = {"a": slot("A"), "b": slot("B")}
        self.assertEqual(order(slots, ["已删除", "b", "a"]), ["B", "A"])


class HysteresisMustNotCrossPriority(unittest.TestCase):
    """★★★ 最容易被绕过的一条：迟滞会粘住低优先级的号，而界面上顺序是对的。"""

    def test_the_guard_compares_rank(self):
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        # 剥注释 —— 本仓记过：断言撞上解释这条规则的注释会假绿
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        i = code.index("PICK_HYSTERESIS > 0")
        seg = code[i:i + 900]
        self.assertIn("_pick_rank(last, s)", seg,
                      "★★★ 迟滞没比优先级 —— 会静默粘住低优先级的号")
        self.assertIn("lp == bp", seg, "★★★ 比了却没用在判断里")

    def test_there_is_exactly_one_sort_implementation(self):
        """★★ 排序只许有**一处**实现 —— 闸调的就是它。

        2026-09-19 实测教训：排序键原来内联在 `_pick` 里，测试只好抄一份同样的 key，
        于是改真排序行对闸毫无影响（变异：去掉优先级、把优先级提到档之前，**两条都没红**）。
        抽成 `_sort_avail` 之后行为闸才真的守得住。这条断言防它再被内联回去。
        """
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        self.assertEqual(code.count("avail.sort(key="), 1,
                         "★★ 出现了第二份排序实现 —— 两份必然分叉")
        self.assertIn("_sort_avail(avail, s)", code, "★ _pick 没走那唯一一份排序")


class FailoverStillWorks(unittest.TestCase):
    """★ 优先级再高，撞限了也要跳过 —— `ok()` 在排序**之前**过滤。"""

    def test_a_cooling_top_priority_account_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "state.json"
            import time as _t
            st.write_text(json.dumps({
                "slots": {"a": dict(slot("Top"), cooling_until=_t.time() + 600),
                          "b": slot("Next")},
                "pick_order": ["a", "b"],
            }), encoding="utf-8")
            old = PX.STATE
            PX.STATE = st
            try:
                aid, sl, why = PX._pick(None)
            finally:
                PX.STATE = old
            self.assertEqual(sl["label"], "Next",
                             "★ 冷却中的高优先级号没被跳过 —— failover 坏了")


class TheCliIsTheOnlyWriter(unittest.TestCase):
    """★★ 真源是 `state.json`，写入口只有 `codex-rotate priority` 一个。"""

    def _run(self, *args, store=None):
        env = dict(os.environ)
        if store:
            env["CODEX_ROTATE_STORE"] = str(store)
        return subprocess.run([sys.executable, str(ROOT / "codex-rotate"), "priority", *args],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_an_unknown_label_is_rejected_loudly(self):
        """★ 打错一个字母就该看见 —— 静默忽略会让用户以为排好了。"""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state.json").write_text(
                json.dumps({"slots": {"a": slot("Real")}}), encoding="utf-8")
            r = self._run("--set", "不存在的号", store=d)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("不认识", r.stderr)

    def test_set_then_read_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state.json").write_text(
                json.dumps({"slots": {"a": slot("A"), "b": slot("B")}}), encoding="utf-8")
            self.assertEqual(self._run("--set", "B", "A", store=d).returncode, 0)
            st = json.loads((Path(d) / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(st["pick_order"], ["b", "a"],
                             "★ 必须按 **aid** 存 —— label 是可改的昵称")
            r = self._run("--json", store=d)
            self.assertEqual(json.loads(r.stdout)["ranked"], ["B", "A"])

    def test_clear_removes_the_key_entirely(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state.json").write_text(
                json.dumps({"slots": {"a": slot("A")}, "pick_order": ["a"]}), encoding="utf-8")
            self._run("--clear", store=d)
            st = json.loads((Path(d) / "state.json").read_text(encoding="utf-8"))
            self.assertNotIn("pick_order", st, "★ 清除要删键,不是写空列表(两种表示会分叉)")

    def test_the_app_is_allowed_to_call_it(self):
        """★★ 白名单漏了它的话，拖拽会**静默失败**（Rust 侧直接拒绝）。"""
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("ALLOWED_CMDS")
        self.assertIn('"priority"', rs[i:i + 400],
                      "★★ priority 不在 ALLOWED_CMDS 里 —— 界面拖了没反应")


if __name__ == "__main__":
    unittest.main(verbosity=2)
