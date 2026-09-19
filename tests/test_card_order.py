"""总览卡片拖拽排序（用户 2026-09-19 要的功能）。

## 为什么这几条闸值得写

拖拽本身坏了顶多是「拖不动」，一眼能看见。真正危险的是**两个不出声的方向**：

1. **没排过的号被丢掉。** 按「只渲染 order 里有的」写，新加的号、刚复活的号就会
   **静默消失**，而用户看到的是「我加了个号，总览里没有」—— 完全指不到排序功能。
   这是本仓「读不到 ≠ 没有」在排序上的形态。
2. **`⌘N` 与角标分叉。** 左上角那个 `⌘N` 角标就是「按 ⌘N 能切到它」的承诺，而
   **角标是唯一可见的那一半**。若显示顺序被拖乱、`⌘N` 仍按 label 序，用户会照着角标按，
   然后切到**别的号**上 —— 切号是有副作用的（换的是正在计费的账号）。
   用户 2026-09-19 选的就是「⌘N 跟视觉顺序」，所以两者必须**共用同一个数组**。

## 行为闸怎么跑

`codexbar/src/cardOrder.ts` 是**零 import 的纯模块**，用
`node --experimental-strip-types` 直接跑**真文件** —— 不是对源码做文本断言，
也不是测一份抄过来的副本（本仓铁律：闸的期望值要从真源推导）。
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"
PURE = SRC / "cardOrder.ts"


def _node(expr):
    """在真的 `cardOrder.ts` 上跑一段表达式，返回 JSON 解析后的结果。"""
    script = (
        "import('file://%s').then(m => {"
        "  const id = x => x;"
        "  console.log(JSON.stringify(%s));"
        "});" % (PURE.as_posix(), expr)
    )
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip().startswith(("[", "{", '"'))]
    if not out:
        raise AssertionError(f"node 没有产出结果：\nstdout={r.stdout}\nstderr={r.stderr[-600:]}")
    return json.loads(out[-1])


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class TheOrderNeverLosesACard(unittest.TestCase):
    """★★★ 最贵的一条：没排过的号必须还在。"""

    def test_an_unknown_id_is_appended_not_dropped(self):
        got = _node("m.applyOrder(['a','b','新号'], ['b','a'], id)")
        self.assertIn("新号", got, "★★★ 没记录过的号被丢掉了 —— 用户会看到「加了号但总览没有」")
        self.assertEqual(got, ["b", "a", "新号"], "新号应追加在末尾")

    def test_several_unknown_ids_keep_their_relative_order(self):
        got = _node("m.applyOrder(['x','a','y','b'], ['b','a'], id)")
        self.assertEqual(got, ["b", "a", "x", "y"])

    def test_a_stale_id_in_the_order_is_ignored(self):
        """删过的号还留在 order 里，不能让它影响其余排序，也不能凭空造出一项。"""
        got = _node("m.applyOrder(['a','b'], ['已删除','b','a'], id)")
        self.assertEqual(got, ["b", "a"])

    def test_every_input_survives_no_matter_the_order(self):
        """不变量：输出是输入的一个排列 —— 不多不少。"""
        for order in ("[]", "['b']", "['z','y']", "['b','a','c']"):
            got = _node(f"m.applyOrder(['a','b','c'], {order}, id)")
            self.assertEqual(sorted(got), ["a", "b", "c"], f"order={order}")


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class AnUntouchedMachineBehavesExactlyAsBefore(unittest.TestCase):
    """★ 没拖过的人必须一个像素都感觉不到变化。"""

    def test_an_empty_order_returns_the_input_unchanged(self):
        self.assertEqual(_node("m.applyOrder(['a','b','c'], [], id)"), ["a", "b", "c"])

    def test_an_undefined_order_returns_the_input_unchanged(self):
        self.assertEqual(_node("m.applyOrder(['a','b','c'], undefined, id)"), ["a", "b", "c"])


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class MoveItemIsSane(unittest.TestCase):
    def test_forward_and_backward(self):
        self.assertEqual(_node("m.moveItem(['a','b','c'], 0, 2)"), ["b", "c", "a"])
        self.assertEqual(_node("m.moveItem(['a','b','c'], 2, 0)"), ["c", "a", "b"])

    def test_out_of_range_is_a_no_op(self):
        for args in ("0, 9", "-1, 0", "5, 5"):
            self.assertEqual(_node(f"m.moveItem(['a','b','c'], {args})"), ["a", "b", "c"])

    def test_it_does_not_mutate_the_input(self):
        got = _node("(() => { const a = ['a','b','c']; m.moveItem(a, 0, 2); return a; })()")
        self.assertEqual(got, ["a", "b", "c"], "★ 原地改了入参 —— React 会看不到变化")


class TheShortcutAgreesWithWhatYouSee(unittest.TestCase):
    """★★ `⌘N` 与角标必须来自**同一个数组**（用户 2026-09-19 选的那一档）。"""

    @classmethod
    def setUpClass(cls):
        raw = (SRC / "App.tsx").read_text(encoding="utf-8")
        # 剥注释 —— 本仓记过：断言撞上解释这条规则的注释会假绿/假红
        cls.code = "\n".join(
            l for l in raw.splitlines()
            if not l.strip().startswith("//") and not l.strip().startswith("*")
            and not l.strip().startswith("/*"))

    def test_the_keyboard_target_comes_from_the_ordered_list(self):
        self.assertIn("const target = orderedAlive[idx]", self.code,
                      "★★ ⌘N 还在用 label 序 —— 角标会指向别的号")
        self.assertNotIn("const target = aliveByLabel[idx]", self.code)

    def test_the_cards_render_from_the_same_list(self):
        self.assertIn("const alive = orderedAlive", self.code,
                      "★★ 卡片与 ⌘N 用了两个不同的数组")

    def test_the_badge_index_is_the_position_in_that_list(self):
        self.assertIn("const shortcutIdx = alive.findIndex", self.code,
                      "★ 角标序号不是「第几张」—— 与 ⌘N 会分叉")


class TheGeminiLaneFollowsTheSameRule(unittest.TestCase):
    """★ Gemini 档也能拖（用户 2026-09-19 勾了它），规则与 codex 档**完全一致**。

    ⚠️ **grok 档刻意不接**：它是单号只读、永远只有一张卡。给它画一个拖不出任何效果的
    手柄，就是「画一个点了没反应的东西」—— 本仓判过死刑的形态（同 `⌘N` 角标那次）。
    """

    @classmethod
    def setUpClass(cls):
        raw = (SRC / "App.tsx").read_text(encoding="utf-8")
        cls.code = "\n".join(l for l in raw.splitlines()
                              if not l.strip().startswith(("//", "*", "/*")))

    def test_gemini_cards_render_from_the_ordered_list(self):
        self.assertIn("orderedAgy.map(", self.code,
                      "★ Gemini 卡片没走排序后的列表")

    def test_the_gemini_shortcut_uses_the_same_list(self):
        self.assertIn("const a = orderedAgy[idx]", self.code,
                      "★★ Gemini 的 ⌘N 与卡片顺序分叉了 —— 角标会指向别的号")

    def test_grok_gets_no_handle(self):
        """单卡档不给手柄。判据：GrokCard 的调用点不传 `drag`。"""
        i = self.code.index("<GrokCard")
        self.assertNotIn("drag={", self.code[i:i + 700],
                         "★ grok 只有一张卡，手柄拖不出任何效果")

    def test_the_two_lanes_keep_separate_orders(self):
        """codex 与 gemini 是两组不同的卡，顺序必须各存各的。"""
        self.assertIn('setOrderFor("codex"', self.code)
        self.assertIn('setOrderFor("gemini"', self.code)


class DraggingDoesNotBreakClickToSelect(unittest.TestCase):
    """★ 卡片现在「点一下 = 选中并展开动作条」。手柄必须把两件事分开。

    ⚠️ 手柄 2026-09-19 抽成了 `components/DragHandle.tsx`（`AccountCard` 与 `AgyCard`
    都要用，同一条交互规则的两份实现必然分叉）。判据跟着搬到新家 —— **规则没变，家变了**。
    """

    @classmethod
    def setUpClass(cls):
        cls.handle = (SRC / "components" / "DragHandle.tsx").read_text(encoding="utf-8")
        cls.card = (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8")

    def test_the_handle_stops_propagation_on_mousedown(self):
        """★ 断言打在 **`onMouseDown` 这一个 handler** 上，不是「附近出现过这个词」。

        ⚠️ 第一版取 `[i-260 : i+80]` 的窗口，而手柄上还有**另一个**
        `onClick={(e) => e.stopPropagation()}` 落在同一个窗口里 —— 于是把 `onMouseDown`
        的那处整个删掉，闸**照样绿**（变异实测）。本仓空守卫形态③：同一个词、不同的用途。
        """
        self.assertIn("onMouseDown={(e) => { e.stopPropagation(); onDown(); }}", self.handle,
                      "★ 按手柄会连带触发「点一下=选中」—— onMouseDown 必须自己拦")

    def test_the_handle_also_stops_the_click(self):
        """松手时的 click 是**另一件事**，也要拦，否则点击仍会穿透成「选中」。"""
        self.assertIn("onClick={(e) => e.stopPropagation()}", self.handle)

    def test_the_card_is_only_draggable_once_the_handle_is_pressed(self):
        self.assertIn("draggable={drag?.draggable ?? false}", self.card,
                      "★ draggable 常开的话整张卡随手一拖就走 —— 选手柄就是为了避免这个")

    def test_without_the_drag_prop_no_handle_is_rendered(self):
        """不传 `drag` 的调用方（菜单栏等）行为必须零变化。"""
        self.assertIn("drag?: DragWiring", self.card, "drag 必须是可选 prop")
        self.assertIn("{drag && <DragHandle", self.card, "没有 drag 时不该渲染手柄")


class TheOrderIsBroadcastAcrossWebviews(unittest.TestCase):
    """★ 主窗与菜单栏是两个独立 webview，localStorage 改动**不互相通知**。"""

    def test_it_emits_and_listens(self):
        h = (SRC / "hooks" / "useCardOrder.ts").read_text(encoding="utf-8")
        self.assertIn('emit(EVT', h, "★ 不广播 ⇒ 两个界面排法不一致")
        self.assertIn("listen<CardOrder>(EVT", h)

    def test_it_does_not_touch_state_json(self):
        """纯展示偏好不许混进那个被五个进程同读写的文件。

        ⚠️ **必须先剥注释**：这个文件的 docstring 里正写着「故意不写进 `state.json`」，
        直接断言会撞上那句说明而假红 —— 本仓已记过五次的「空守卫形态④」，我这轮又踩一次。
        """
        raw = (SRC / "hooks" / "useCardOrder.ts").read_text(encoding="utf-8")
        code = "\n".join(l for l in raw.splitlines()
                          if not l.strip().startswith(("//", "*", "/*")))
        self.assertNotIn("run_rotate", code)
        self.assertNotIn("state.json", code)
        self.assertNotIn("invoke(", code, "★ 展示偏好不该走 IPC")


if __name__ == "__main__":
    unittest.main(verbosity=2)
