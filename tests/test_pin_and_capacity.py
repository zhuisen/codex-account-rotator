"""轮换语义：**默认容量最高优先，置顶才插队**（用户 2026-09-21）。

## ★★★ 这份文件是一次**反转**的记录，别按旧版改回去

2026-09-19 用户选的是「优先级压过额度」：排序键 `(套餐档, 拖拽顺序, 已用%)`，
排第一的号一直用到 429 撞限。2026-09-21 他推翻了它：

> 「codex 账号自动轮换机制，还是默认以容量最高的优先使用，不以账号的排序。
>   并且新增一个功能，点击就是优先使用该账号，不点击就是按默认的容量最高的优先使用。」

★ 旧实现错在哪，值得记：`pick_order` 给**每一个号**都排了名 ⇒ 排序键里的「已用%」
  **永远说不上话**。新实现只有一处不同，而那是全部：**未置顶的号在第二段全部并列**
  （`_pin_rank` 对它们一律返回 `len(pinned)`），于是容量立刻接管。

## 三段排序键

    (套餐档, 置顶队列位次, 最紧窗口已用%)

- **套餐档** —— Plus 优先、Pro 保底（2026-09-07 策略 C，**本次仍不变**）；
- **置顶** —— 用户点亮的号，按点击先后排队，只在档内生效；
- **已用%** —— **默认口径**：没有任何置顶时，全池按它排 = 容量最高优先。

## 拖拽顺序去哪了

降为**纯摆放**（卡片位置 + ⌘N），键从 `pick_order` 改名 `card_order`。
一个叫「挑号顺序」却不挑号的键会骗下一个人 —— 那是本仓最反感的命名。
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
_spec = importlib.util.spec_from_file_location("px_pin", ROOT / "proxy" / "proxy.py")
PX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PX)


def slot(label, plan="plus", used=0.0):
    return {"label": label, "plan": plan,
            "quota": {"primary": {"window_minutes": 300, "used_percent": used,
                                  "resets_at": None},
                      "secondary": {}}}


def order(slots, pinned=None, **extra):
    """按**生产排序函数**排出的 label 顺序。

    ⚠️ 旧版在这里**抄过一份排序键**，于是改 `proxy.py` 的真排序行对它毫无影响
    （变异实测两条都没被抓到）。现在调的是生产里唯一那份 `_sort_avail`。
    """
    state = {"slots": slots, "pinned": pinned or [], **extra}
    return [kv[1]["label"] for kv in PX._sort_avail(list(slots.items()), state)]


class CapacityDecidesWhenNothingIsPinned(unittest.TestCase):
    """★★★ 这是**默认**口径，也是这次反转的全部意义。"""

    def test_the_emptiest_account_goes_first(self):
        slots = {"a": slot("Asen", used=90.0), "b": slot("Egan", used=10.0),
                 "c": slot("Huo", used=50.0)}
        self.assertEqual(order(slots), ["Egan", "Huo", "Asen"],
                         "★★★ 没有置顶时必须按「最紧窗口已用% 最少」排 —— 容量最高优先")

    def test_the_old_drag_order_has_no_effect_at_all(self):
        """★★★ 拖拽顺序降为纯摆放。旧装机里 `pick_order` 还躺在 state.json 里，
        它**一点都不许影响轮换** —— 否则用户会看到「我明明没置顶，它却不按容量走」。"""
        slots = {"a": slot("Asen", used=90.0), "b": slot("Egan", used=10.0)}
        self.assertEqual(order(slots, pick_order=["a", "b"]), ["Egan", "Asen"],
                         "★★★ 旧的 `pick_order` 还在影响轮换")
        self.assertEqual(order(slots, card_order=["a", "b"]), ["Egan", "Asen"],
                         "★★★ `card_order`（摆放顺序）影响了轮换")


class PinningJumpsTheQueue(unittest.TestCase):
    """★★ 「点一下就优先用它」——**即使它容量最差**。"""

    def test_a_pinned_account_wins_even_when_nearly_exhausted(self):
        slots = {"a": slot("Asen", used=100.0), "b": slot("Egan", used=0.0)}
        self.assertEqual(order(slots, ["a"])[0], "Asen",
                         "★★ 置顶没压过容量 —— 与用户 2026-09-21 的选择相反")

    def test_several_pins_are_served_in_click_order(self):
        """★ 用户选的是「可置顶多个，按点击先后排队」。"""
        slots = {"a": slot("Asen", used=1.0), "b": slot("Egan", used=2.0),
                 "c": slot("Huo", used=0.0)}
        self.assertEqual(order(slots, ["b", "a"]), ["Egan", "Asen", "Huo"],
                         "★ 置顶之间没按点击先后排")

    def test_the_unpinned_rest_still_go_by_capacity(self):
        """★★ 这一条是新旧实现的**分界线**：未置顶的全部并列 ⇒ 容量接管。
        旧实现里它们各有名次，这条会红。"""
        slots = {"p": slot("Pinned", used=99.0), "x": slot("X", used=80.0),
                 "y": slot("Y", used=5.0), "z": slot("Z", used=40.0)}
        self.assertEqual(order(slots, ["p"]), ["Pinned", "Y", "Z", "X"],
                         "★★ 未置顶的没按容量排 —— 它们必须全部并列")

    def test_a_stale_aid_in_the_pin_list_breaks_nothing(self):
        slots = {"a": slot("A", used=50.0), "b": slot("B", used=10.0)}
        self.assertEqual(order(slots, ["已删除", "a"]), ["A", "B"])


class PlanTierStillComesFirst(unittest.TestCase):
    """★ 「Plus 优先、Pro 保底」是 2026-09-07 用户自己定的，本次**明确保留**。"""

    def test_a_pinned_pro_still_loses_to_any_plus(self):
        slots = {"p": slot("Pro1", plan="pro", used=0.0),
                 "u": slot("Plus9", plan="plus", used=99.0)}
        self.assertEqual(order(slots, ["p", "u"])[0], "Plus9",
                         "★ 置顶凌驾了套餐档 —— 它只在档内生效")

    def test_capacity_never_crosses_the_tier_either(self):
        slots = {"p": slot("Pro1", plan="pro", used=0.0),
                 "u": slot("Plus9", plan="plus", used=99.0)}
        self.assertEqual(order(slots)[0], "Plus9", "★ 容量优先跨了套餐档")


class HysteresisMustNotCrossAPin(unittest.TestCase):
    """★★★ 最容易被绕过的一条：迟滞会粘住**没置顶**的号，而界面上你已经点亮了别的。

    与 2026-09-07「迟滞不得跨套餐档」、2026-09-19「迟滞不得跨优先级」同形 ——
    这是同一条不变量的第三次出现，所以它有自己的闸。
    """

    def test_the_guard_compares_the_pin_rank(self):
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        # 剥注释 —— 本仓记过：断言撞上解释这条规则的注释会假绿
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        i = code.index("PICK_HYSTERESIS > 0")
        seg = code[i:i + 900]
        self.assertIn("_pin_rank(last, s)", seg,
                      "★★★ 迟滞没比置顶 —— 会静默粘住没置顶的号")
        self.assertIn("lp == bp", seg, "★★★ 比了却没用在判断里")


class ThereIsExactlyOneSortImplementation(unittest.TestCase):
    """★★ 排序只许有**一处**实现 —— 闸调的就是它。

    2026-09-19 实测教训：排序键原来内联在 `_pick` 里，测试只好抄一份同样的 key，
    于是改真排序行对闸毫无影响（两个变异都没红）。这条断言防它再被内联回去。
    """

    def test_one_sort_and_pick_uses_it(self):
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        self.assertEqual(code.count("avail.sort(key="), 1,
                         "★★ 出现了第二份排序实现 —— 两份必然分叉")
        self.assertIn("_sort_avail(avail, s)", code, "★ _pick 没走那唯一一份排序")

    def test_the_old_pick_rank_is_really_gone(self):
        """★ 留一个同名旧函数在那儿，下一个人会以为它还在用。"""
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        self.assertNotIn("def _pick_rank", src, "★ 旧的 `_pick_rank` 还在")


class FailoverStillWorks(unittest.TestCase):
    """★ 置顶的号撞限了也要跳过 —— `ok()` 在排序**之前**过滤。"""

    def test_a_cooling_pinned_account_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "state.json"
            import time as _t
            st.write_text(json.dumps({
                "slots": {"a": dict(slot("Pinned", used=0.0), cooling_until=_t.time() + 600),
                          "b": slot("Next", used=50.0)},
                "pinned": ["a"],
            }), encoding="utf-8")
            old = PX.STATE
            PX.STATE = st
            try:
                _aid, sl, _why = PX._pick(None)
            finally:
                PX.STATE = old
            self.assertEqual(sl["label"], "Next",
                             "★ 冷却中的置顶号没被跳过 —— failover 坏了")

    def test_the_proxy_only_reads_the_pin_never_writes_it(self):
        """★★ 用户选的是「撞限后回到容量优先，**冷却结束自动变回置顶**」——
        也就是说代理**只读** `pinned`，绝不因为撞限去清掉它。

        ⚠️ 第一版这条是**写错的**：切片 `code.split("def _pin_rank")[1].split("def ")[1]`
          取到的是**下一个函数**的体，与我在文档里描述的完全不是一回事（虽然碰巧绿）。
          现在判据是可执行的一句话：**全文件不许有对 `pinned` 的写入**。
        """
        import re
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        writes = re.findall(r'\[["\']pinned["\']\]\s*=|'
                            r'__setitem__\(\s*["\']pinned["\']|'
                            r'\.pop\(\s*["\']pinned["\']', code)
        self.assertEqual(writes, [],
                         f"★★ 代理写了 `pinned` —— 置顶只许用户改，不许被撞限自动清掉：{writes}")
        self.assertIn('state.get("pinned")', code, "★ 代理根本没读 `pinned`")


class TheCliIsTheOnlyWriter(unittest.TestCase):
    """★★ 真源是 `state.json` 的 `pinned`，写入口只有 `codex-rotate pin` 一个。"""

    def _run(self, *args, store=None):
        env = dict(os.environ)
        if store:
            env["CODEX_ROTATE_STORE"] = str(store)
        return subprocess.run([sys.executable, str(ROOT / "codex-rotate"), "pin", *args],
                              capture_output=True, text=True, timeout=60, env=env)

    def _store(self, d):
        (Path(d) / "state.json").write_text(
            json.dumps({"slots": {"a": slot("A"), "b": slot("B")}}), encoding="utf-8")
        return d

    def test_an_unknown_label_is_rejected_loudly(self):
        """★ 打错一个字母就该看见 —— 静默忽略会让用户以为点亮了。"""
        with tempfile.TemporaryDirectory() as d:
            r = self._run("--add", "不存在的号", store=self._store(d))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("不认识", r.stderr)

    def test_toggle_round_trips_and_stores_aids(self):
        with tempfile.TemporaryDirectory() as d:
            self._store(d)
            self.assertEqual(self._run("--toggle", "B", store=d).returncode, 0)
            st = json.loads((Path(d) / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(st["pinned"], ["b"],
                             "★ 必须按 **aid** 存 —— label 是可改的昵称")
            self._run("--toggle", "B", store=d)
            st = json.loads((Path(d) / "state.json").read_text(encoding="utf-8"))
            self.assertNotIn("pinned", st, "★ 取消最后一个置顶要删键,不是留空列表")

    def test_clicking_an_already_pinned_account_does_not_reorder_it(self):
        """★★ 「再点一下」的预期是**取消**，不是挪到队尾。`--add` 幂等。"""
        with tempfile.TemporaryDirectory() as d:
            self._store(d)
            self._run("--add", "A", store=d)
            self._run("--add", "B", store=d)
            self._run("--add", "A", store=d)          # 重复点第一个
            st = json.loads((Path(d) / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(st["pinned"], ["a", "b"],
                             "★★ 重复 --add 改了排队位次")

    def test_the_app_is_allowed_to_call_it(self):
        """★★ 白名单漏了它的话，点「置顶」会**静默失败**（Rust 侧直接拒绝）。"""
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("ALLOWED_CMDS")
        self.assertIn('"pin"', rs[i:i + 400],
                      "★★ pin 不在 ALLOWED_CMDS 里 —— 界面点了没反应")


class TheDragHintNoLongerLies(unittest.TestCase):
    """★★ 手柄提示原来写「这个顺序就是轮换优先级」—— 反转之后它是**一句假陈述**，
    而且正好会让人以为自己在调轮换。"""

    def test_the_hint_does_not_claim_to_drive_rotation(self):
        import re
        raw = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
        code = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))
        i = code.index("按住拖动")
        hint = code[i:i + 260]
        self.assertNotIn("轮换优先级", hint, "★★ 提示还在说拖拽顺序就是轮换优先级")
        self.assertIn("不影响轮换", hint, "★ 没说清它只影响摆放")


if __name__ == "__main__":
    unittest.main(verbosity=2)
