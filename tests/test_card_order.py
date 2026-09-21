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
import re
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

    def test_the_two_lanes_store_their_order_in_different_places(self):
        """★★★ 两档的顺序**含义不同，家也不同**（2026-09-19 用户定）。

        · **codex** —— 顺序**就是轮换优先级**，决定钱花在哪个号上 ⇒ 真源必须是
          `state.json`（代理在 app 没开时也要读它），写入走 `codex-rotate priority --set`。
          放 localStorage 会分叉成「界面上排第一、代理却在用别的号」。
        · **gemini** —— agy 是启动前换凭证，没有逐请求的挑号器 ⇒ 顺序纯属摆放，
          留在 localStorage 即可。
        """
        self.assertIn('"priority", "--set"', self.code,
                      "★★★ codex 档没把顺序写进 state.json —— 拖了不影响轮换")
        self.assertIn('applyOrder(aliveByLabel, state.pick_order', self.code,
                      "★★★ codex 档没从 state.json 读顺序 —— 会与代理分叉")
        self.assertIn('setOrderFor("gemini"', self.code,
                      "★ gemini 档仍该留在 localStorage")
        self.assertNotIn('setOrderFor("codex"', self.code,
                         "★★ codex 档不该再写 localStorage —— 那会变成第二个真源")


class DraggingDoesNotBreakClickToSelect(unittest.TestCase):
    """★ 卡片「点一下 = 选中并展开动作条」。手柄必须把两件事分开。"""

    @classmethod
    def setUpClass(cls):
        cls.handle = (SRC / "components" / "DragHandle.tsx").read_text(encoding="utf-8")
        cls.card = (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8")

    def test_pointer_down_stops_propagation(self):
        self.assertIn("onPointerDown={(e) => {\n        e.stopPropagation();", self.handle,
                      "★ 按手柄会连带触发「点一下=选中」")

    def test_the_click_is_stopped_too(self):
        """松手时的 click 是**另一件事**，也要拦。"""
        self.assertIn("onClick={(e) => e.stopPropagation()}", self.handle)

    def test_without_the_drag_prop_no_handle_is_rendered(self):
        self.assertIn("drag?: DragWiring", self.card, "drag 必须是可选 prop")
        self.assertIn("{drag && <DragHandle", self.card, "没有 drag 时不该渲染手柄")


class ItUsesPointerEventsNotHtml5Dnd(unittest.TestCase):
    """★★★ **前提已被取代两次，这是定稿**（2026-09-20）。

    HTML5 drag-and-drop 在这个 app 里**不可用**：Tauri 窗口的 `dragDropEnabled` 默认为
    `true`，它的**原生拖放处理器会吞掉 webview 里的拖拽事件** —— `drop` 根本到不了页面。
    而 harness 跑在 Chrome、没有那层拦截，所以端到端闸一路绿、真机从第一步就不成立
    （用户连报两次「能拖拽，但是改变不了卡片的位置」）。

    ⚠️ 在此之前我还修过两条**真实但不是拦路的** WebKit 要求（`setData`、异步 `draggable`）。
       **「找到一个真原因」不等于「找到那个原因」。**

    pointer 事件不依赖任何 DnD 语义，也做得到用户要的**实时让位**。
    """

    @classmethod
    def setUpClass(cls):
        cls.handle = (SRC / "components" / "DragHandle.tsx").read_text(encoding="utf-8")
        cls.app = (SRC / "App.tsx").read_text(encoding="utf-8")
        cls.card = (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8")

    @staticmethod
    def _code(txt):
        """剥掉注释 —— 这两个文件的注释里正解释着「为什么不用 HTML5 DnD」，
        直接断言会撞上那段说明而假红。本仓空守卫形态④，本轮已踩第三次。"""
        return "\n".join(l for l in txt.splitlines()
                          if not l.strip().startswith(("//", "*", "/*", "{/*")))

    def test_no_html5_dnd_anywhere_in_the_drag_path(self):
        h, cd = self._code(self.handle), self._code(self.card)
        for name in ("onDragStart", "onDragOver", "onDrop", "dataTransfer", "draggable"):
            self.assertNotIn(name, h, f"★★★ 手柄又回到 HTML5 DnD 了（{name}）")
            self.assertNotIn(name, cd, f"★★★ 卡片又挂上 HTML5 DnD 了（{name}）")

    def test_it_captures_the_pointer(self):
        """★ 不捕获的话鼠标一离开这 12px 就断线 —— 而拖拽本来就是要离开它。"""
        self.assertIn("setPointerCapture", self.handle,
                      "★ 没捕获指针 —— 拖出手柄范围就断")

    def test_cancel_abandons_instead_of_committing(self):
        """★★ Esc / 系统打断必须**放弃**排序 —— codex 档的顺序就是计费顺序。"""
        self.assertIn("onPointerCancel", self.handle)
        self.assertIn("onEnd(false)", self.handle, "★★ 取消被当成了落点")
        hook = (SRC / "hooks" / "useCardDrag.ts").read_text(encoding="utf-8")
        self.assertIn("if (!ok || !changed)", hook,
                      "★★ hook 侧没有区分 commit/取消")
        self.assertIn("escRef.current = () => finish(false)", hook,
                      "★★ Esc 没接通 —— 自定义 pointer 拖拽不会自动收到 pointercancel")

    def test_cards_expose_an_aid_for_hit_testing(self):
        self.assertIn("data-aid={a.aid}", self.card,
                      "★ 没有 data-aid，命中测试找不到落点")


class TheDragIsSmooth(unittest.TestCase):
    """★★★ 手感层的结构不变量（第四版，2026-09-20）。

    前三版反复出问题的根子是**同一个**：拖动中让 React 重排 DOM，于是 React、
    我写的内联样式、和动画三方踩同一批节点。这一版把那个交叉点拆掉 ——
    **拖拽全程 DOM 顺序不变**，所以下面几条大多是在守「别再把它加回去」。
    """

    @classmethod
    def setUpClass(cls):
        raw = (SRC / "hooks" / "useCardDrag.ts").read_text(encoding="utf-8")
        cls.code = "\n".join(l for l in raw.splitlines()
                              if not l.strip().startswith(("//", "*", "/*")))
        cls.card = (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8")

    def test_the_dom_order_is_not_touched_during_the_drag(self):
        """★★★ 这一版的核心。`preview` 只在**提交**时才置非空。"""
        i = self.code.index("onMove: (x, y) => {")
        seg = self.code[i:self.code.index("onEnd: finish", i)]
        self.assertNotIn("setPreview", seg,
                         "★★★ 拖动中又去重排 DOM 了 —— 那正是「卡片停在半空」的根因")

    def test_positions_are_expressed_as_transforms(self):
        i = self.code.index("const layout =")
        seg = self.code[i:i + 1100]
        self.assertIn("style.transform =", seg, "★ 位置不是用 transform 表达的")
        self.assertNotIn("getBoundingClientRect", seg,
                         "★★★ layout 里读了 DOM —— 纯写样式才不会形成反馈回路")

    def test_the_follow_formula_is_the_simple_one(self):
        """★★ DOM 不动 ⇒ 不需要补偿。照搬旧补偿会偏出一整格（实测 623px）。"""
        self.assertIn("const tx = px - s.p0x;", self.code,
                      "★★ 跟手算式不对 —— 这一版应当就是 Pt − P0")

    def test_hit_testing_uses_the_slots_measured_at_press_time(self):
        """★★★ 命中只许吃按下时量的固定槽位，绝不读实时矩形（会形成反馈回路）。

        2026-09-20：命中测试搬进 `cardOrder.ts::reorderByHit`（纯函数，可直接跑），
        所以这条闸跟着搬 —— hook 这边只验**喂给它的是冻结的 `s.slots`**，
        落点判定本身的行为闸在 `TheHitTestIsIdempotent`。
        """
        i = self.code.index("onMove: (x, y) => {")
        seg = self.code[i:self.code.index("onEnd: finish", i)]
        self.assertIn("reorderByHit(s.ids, s.aid, s.slots, cx, cy)", seg,
                      "★★★ 命中没用按下时量的固定槽位")
        self.assertIn("const cx = s.c0x + (x - s.p0x);", seg,
                      "★★★ 命中又按指针判了 —— 手柄在右上角，指针比卡片超前大半格")
        self.assertNotIn("getBoundingClientRect", seg,
                         "★★★ 命中读了实时矩形 —— 会形成反馈回路")
        pure = PURE.read_text(encoding="utf-8")
        self.assertNotIn("getBoundingClientRect", pure,
                         "★★★ 纯函数里读了 DOM —— 它必须保持可直接跑")

    def test_transform_is_owned_by_the_hook_alone(self):
        """★★★ React 与 hook 都写 `transform` 时，重渲染会**抹掉**位移。"""
        self.assertNotIn("transform: drag?", self.card,
                         "★★★ React 又在写 transform")

    def test_transform_is_not_in_the_css_transition_of_the_card(self):
        """★★★ 留着它，「清空后立刻量位置」会量到过渡中间值（实测 1437 vs 685）。"""
        i = self.card.index("transition: \"background")
        self.assertNotIn("transform", self.card[i:i + 160],
                         "★★★ transform 回到了卡片的 CSS transition 里")

    def test_the_shift_animation_is_a_css_transition(self):
        self.assertIn("transform ${FLIP_MS}ms ${EASING}", self.code,
                      "★ 让位没有过渡 —— 会变成瞬移")

    def test_styles_are_cleaned_up_on_every_exit_path(self):
        """★★ 残留的内联 transform 正是用户截图里那个坏状态。"""
        self.assertIn("window.setTimeout(clearStyles", self.code, "★ 取消路径没清样式")
        self.assertIn("needsClear.current = true;", self.code, "★ 提交路径没清样式")

    def test_the_drag_state_lives_in_refs(self):
        self.assertIn("useRef<Session | null>(null)", self.code,
                      "★ 逐帧变化的量放进了 React state")

    def test_a_tiny_jitter_does_not_start_a_drag(self):
        self.assertIn("START_SLOP", self.code, "★ 手抖会把一次点击变成排序")

    def test_no_third_party_drag_library(self):
        pkg = (SRC.parent / "package.json").read_text(encoding="utf-8")
        for lib in ("dnd-kit", "react-beautiful-dnd", "framer-motion", "react-dnd", "sortablejs"):
            self.assertNotIn(lib, pkg, f"★ 引入了 {lib}")


class TheSaveHandoffDoesNotFlashBack(unittest.TestCase):
    """★★ codex 档落盘要等一次 IPC + 刷新。期间若清掉 preview，显示会**闪回旧序**。

    2026-09-20 由 codex 评审指出（读代码确认存在窗口，是否肉眼可见取决于延迟）。
    """

    def test_preview_is_cleared_only_after_the_commit_settles(self):
        raw = (SRC / "hooks" / "useCardDrag.ts").read_text(encoding="utf-8")
        code = "\n".join(l for l in raw.splitlines()
                          if not l.strip().startswith(("//", "*", "/*")))
        # ⚠️ 第四版不再需要「等落盘再清 preview」：拖拽期间 `preview` 恒为 null，
        #   提交时一次性置成新顺序，之后**不再清回 null** —— 结构上就不存在闪回窗口。
        i = code.index("const finish = (ok: boolean)")
        seg = code[i:code.index("return {", i)]
        self.assertIn("setPreview(next);", seg, "★★ 提交没落到 preview")
        self.assertNotIn("setPreview(null)", seg,
                         "★★ 提交后又把 preview 清回 null —— 会闪回旧序")


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


HARNESS = "http://127.0.0.1:3304"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: 在真页面上跑一次完整拖拽，回报三件事。
#: ★★ 这是**之前缺的那一环**：`applyOrder`/`moveItem` 有行为闸、接线有静态闸，
#:    而「真拖一次到底有没有生效」从没跑过 —— 用户 2026-09-20 报的就是这个缺口
#:    （能拖，但位置不变）。
_PROBE_JS = r"""
const out = {};
const cards = () => [...document.querySelectorAll('[data-cards-grid] > div[data-aid]')];
const ids = () => cards().map(d => d.dataset.aid);
const wait = ms => new Promise(r => setTimeout(r, ms));
const pe = (t, el, x, y) => el.dispatchEvent(new PointerEvent(t, {
  bubbles:true, cancelable:true, pointerId:1, isPrimary:true, button:0, buttons:1,
  clientX:x, clientY:y }));
(async () => {
  try {
    const before = ids();
    const a = cards()[0], b = cards()[2];
    const h = a.querySelector('[data-drag-handle]');
    out.handleFound = !!h;
    h.setPointerCapture = () => {}; h.releasePointerCapture = () => {};
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    const px = rb.left + rb.width / 2, py = rb.top + rb.height / 2;

    pe('pointerdown', h, ra.left + 5, ra.top + 5);
    await wait(80);
    pe('pointermove', h, px, py);
    await wait(180);

    // ★ 跟手：指针必须落在被拖卡片的**视觉矩形**内，偏移≈抓取点 (5,5)
    const vr = a.getBoundingClientRect();
    out.follows = px >= vr.left && px <= vr.right && py >= vr.top && py <= vr.bottom;
    out.grabGap = [Math.round(px - vr.left), Math.round(py - vr.top)];

    // ★ 让位：**DOM 顺序不变**（这一版刻意如此），靠 transform 表达 ——
    //   所以判据是「有非拖动卡片带上了非零位移」，不是「DOM 顺序变了」。
    out.domOrderDuringDrag = ids();
    out.shifted = cards().filter(c => c !== a && /translate3d\(-?\d/.test(c.style.transform || ''))
                         .map(c => c.style.transform);
    // 让位必须是**动画**：非拖动卡片要有 transform 过渡
    out.transitions = cards().filter(c => c !== a)
      .map(c => c.style.transition).filter(t => /transform/.test(t || ''));

    pe('pointerup', h, px, py);
    await wait(700);
    out.after = ids();
    out.before = before;
    out.reordered = JSON.stringify(before) !== JSON.stringify(out.after);
    // ★★ 无残留：所有卡片必须精确落回网格，且没有内联 transform
    out.leftover = cards().map(c => c.style.transform).filter(t => t && t !== 'none');
    const rects = cards().map(c => { const r = c.getBoundingClientRect();
                                     return [Math.round(r.left), Math.round(r.top)]; });
    out.cards = rects.length;
    out.cols = [...new Set(rects.map(r => r[0]))].sort((x, y) => x - y);
    out.rows = [...new Set(rects.map(r => r[1]))].sort((x, y) => x - y);
  } catch (e) { out.error = String(e); }
  document.title = '__DRAG__' + JSON.stringify(out);
})();
"""


def _run_drag_probe():
    """生成探针页、跑一次 headless、把结果取回来。拿不到环境就返回 None（调用方 skip）。"""
    import re as _re
    import urllib.request
    src = APP_DIR / "harness.html"
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / "dragprobe.html"
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>setTimeout(() => {{{_PROBE_JS}}}, 2600);</script></body>", 1),
        encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            "--window-size=1000,900", "--virtual-time-budget=11000",
                            "--dump-dom", f"{HARNESS}/dragprobe.html?nav=home"],
                           capture_output=True, text=True, timeout=120)
        m = _re.search(r"__DRAG__(\{.*\})\s*</title>", r.stdout, _re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        page.unlink(missing_ok=True)


class DraggingOneCardActuallyMovesIt(unittest.TestCase):
    """★★★ 端到端：真派发一次拖拽，看卡片顺序有没有变。

    用户 2026-09-20 报「能拖拽，但是改变不了卡片的位置」。当时**所有闸都是绿的** ——
    因为它们只测了纯函数与接线文本，**没有一条真的拖过一次**。

    真因是两条 **WebKit 特有**的要求，Chrome 都宽容，所以更难发现：

      ① `dragstart` 必须往 `dataTransfer` 写点东西，否则拖拽数据仓为空、
         **WebKit 根本不派发 `drop`**；
      ② `draggable` 必须在 `mousedown` **之前**就为真 —— WebKit 在按下那一刻判定，
         而原来的写法是「按下手柄 → `setState` 打开卡片的 `draggable`」，React 追不上。

    ⚠️ **这条闸跑在 Chrome，不是 WKWebView**（TCC 挡着抓屏，本仓结构性缺口）。
       所以它能守住「逻辑链通不通」与上面两条硬要求，**不能**替代真机点一次。
    """

    @classmethod
    def setUpClass(cls):
        cls.out = _run_drag_probe()
        if cls.out is None:
            raise unittest.SkipTest(
                "需要 Chrome + 跑着的 harness（127.0.0.1:3304）。"
                "★ skip 不是绿 —— 要验这条请先 `python3 codexbar/uishot/make_harness.py` 并起静态服务")

    def test_the_probe_found_a_handle(self):
        self.assertTrue(self.out.get("handleFound"), f"卡片上没有手柄：{self.out}")

    def test_the_dragged_card_follows_the_pointer(self):
        """★★★ 跟手的**真不变量**：指针落在被拖卡片的视觉矩形内，偏移≈抓取点。

        ⚠️ 只断言 `transform` 字符串非空证不了这个 —— 实测踩过：transform 明明有
        `translate3d(-608px…)`，而卡片离指针 604px（补偿算反了）。
        """
        self.assertIsNone(self.out.get("error"), self.out.get("error"))
        self.assertTrue(self.out.get("follows"),
                        f"★★★ 不跟手：指针相对卡片左上角 {self.out.get('grabGap')}，抓取点是 (5,5)")
        gx, gy = self.out.get("grabGap") or (999, 999)
        self.assertLess(abs(gx - 5), 8, "★★ 横向跟手偏差过大（布局基准补偿？）")
        self.assertLess(abs(gy - 5), 8, "★★ 纵向跟手偏差过大")

    def test_other_cards_shift_out_of_the_way_before_you_let_go(self):
        """★★ 用户要的「其他卡片后移让位置」。

        ⚠️ **判据 2026-09-20 改过**：这一版拖拽期间 **DOM 顺序刻意不变**
        （前三版让 React 边拖边重排，结果是卡片停在半空的那个 bug）。
        让位现在用 `transform` 表达，所以断言改成「有非拖动卡片带上了非零位移」。
        """
        self.assertIsNone(self.out.get("error"), self.out.get("error"))
        self.assertEqual(self.out.get("domOrderDuringDrag"), self.out.get("before"),
                         "★★ 拖拽期间 DOM 顺序变了 —— 那正是「卡片停在半空」的根因")
        self.assertTrue(self.out.get("shifted"),
                        "★★ 没有任何卡片让位 —— 拖到别人身上时它该移开")

    def test_the_shift_is_animated_not_instant(self):
        """★ 让位必须是**滑动**不是瞬移 —— 非拖动卡片要挂上 transform 过渡。"""
        self.assertTrue(self.out.get("transitions"),
                        "★ 让位是瞬移：非拖动卡片没有 transform 过渡")

    def test_the_card_actually_moves(self):
        self.assertIsNone(self.out.get("error"), self.out.get("error"))
        self.assertTrue(self.out.get("reordered"),
                        f"★★★ 拖完顺序没变：{self.out.get('before')} → {self.out.get('after')}")

    def test_no_card_is_left_stranded_off_the_grid(self):
        """★★★ 用户 2026-09-20 截图里的 bug：拖完之后卡片停在半空、互相重叠。

        实测那一版：有卡片落在 `(517, 313)`，而网格列在 72/379/687。
        判据是**全部卡片必须落回同一套列/行坐标**，且没有内联 transform 残留。
        """
        self.assertEqual(self.out.get("leftover"), [],
                         f"★★★ 拖完还有残留的内联 transform：{self.out.get('leftover')}")
        cols, rows = self.out.get("cols") or [], self.out.get("rows") or []
        # ⚠️ 2026-09-21 起网格是 `repeat(auto-fill, minmax(320px,1fr))` —— 列数随窗口变，
        #   **不再恒为 3**。判据跟着改成「落回**一套整齐的**列/行坐标」：
        #   坏状态的特征不是"超过 3 列"，是**每张卡各有一个 x**（实测那次 517 vs 72/379/687）。
        #   用「不同坐标数 < 卡片数」表达，与列数无关。
        n = self.out.get("cards")
        self.assertIsNotNone(n, "★★ 探针没报卡片数 —— 判据会退化成「列数 < 列数」")
        self.assertGreater(n, 2, f"★★ 没量到足够多的卡：{self.out}")
        # ★ 坏状态的特征是**每张卡各有一个 x**（实测那次 517 vs 网格列 72/379/687），
        #   而不是"超过 3 列" —— 网格 2026-09-21 起是 auto-fill，列数随窗口变。
        self.assertLess(len(cols), n, f"★★★ 每张卡各占一个 x —— 没落回网格列：{cols}")
        self.assertLess(len(rows), n, f"★★★ 每张卡各占一个 y —— 没落回网格行：{rows}")


_THRESHOLD_JS = r"""
const out = {};
const wait = ms => new Promise(r => setTimeout(r, ms));
const cards = () => [...document.querySelectorAll('[data-cards-grid] > div[data-aid]')];
const pe = (t, el, x, y) => el.dispatchEvent(new PointerEvent(t, {
  bubbles: true, cancelable: true, pointerId: 1, isPrimary: true,
  button: 0, buttons: 1, clientX: x, clientY: y }));

/** 把 0 号卡沿 x 正方向拖 `dx`，返回「有没有别的卡让位」。 */
async function travel(dx) {
  const cs = cards();
  const a = cs[0];
  const h = a.querySelector('[data-drag-handle]');
  h.setPointerCapture = () => {}; h.releasePointerCapture = () => {};
  const r = h.getBoundingClientRect();
  const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
  pe('pointerdown', h, x0, y0);
  await wait(30);
  pe('pointermove', h, x0 + dx, y0);          // 一步到位：不靠中途帧
  await wait(30);
  const moved = cards().some(c => c !== a && (c.style.transform || '') !== '');
  pe('pointerup', h, x0, y0);                  // 回到原点 ⇒ 不提交
  await wait(400);                             // 等 clearStyles(FLIP_MS + 40)
  return moved;
}

(async () => {
  try {
    const cs = cards();
    const r0 = cs[0].getBoundingClientRect(), r1 = cs[1].getBoundingClientRect();
    const pitch = r1.left - r0.left;           // 一列的步距 = 卡宽 + 间距
    out.pitch = Math.round(pitch);
    out.at30 = await travel(pitch * 0.30);     // 卡片才走了 30% ⇒ 不该让位
    out.at80 = await travel(pitch * 0.80);     // 走过 80% ⇒ 必须让位
  } catch (e) { out.error = String(e && e.stack || e); }
  document.title = '__TH__' + JSON.stringify(out);
})();
"""


def _run_threshold_probe():
    """量「让位从卡片走到百分之几开始触发」。拿不到环境返回 None（调用方 skip）。"""
    import re as _re
    import urllib.request
    src = APP_DIR / "harness.html"
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / "threshprobe.html"
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>setTimeout(() => {{{_THRESHOLD_JS}}}, 2600);</script></body>", 1),
        encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            "--window-size=1000,900", "--virtual-time-budget=13000",
                            "--dump-dom", f"{HARNESS}/threshprobe.html?nav=home"],
                           capture_output=True, text=True, timeout=120)
        m = _re.search(r"__TH__(\{.*\})\s*</title>", r.stdout, _re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        page.unlink(missing_ok=True)


class OthersMakeWayWhenTheCardIsHalfwayOver(unittest.TestCase):
    """★★★ 让位的触发点要跟着**卡片**走，不跟着指针走。

    用户 2026-09-20 截图报：「卡片去到第二个位置的一半了，第二个卡片仍然占着位置不动」。
    真因是命中测试吃的是**指针坐标**，而手柄在卡片右上角 —— 指针天然比卡片超前大半格。
    同一个错误有两个方向，取决于你从哪儿抓的：从右上角抓，指针早早越界，卡片只挪一点
    邻居就让位；反过来从左边抓，卡片过半了指针还在原格，邻居纹丝不动。用户看到的是后者。

    ★ 判据用**列步距的百分比**，不用绝对像素 —— 窗口宽度一变，绝对值就失效了。
      30% / 80% 这两档分别落在「中心跨格」阈值（≈52%）的两侧，而按指针判时
      触发点只有 ≈8%，所以 30% 那一档正是唯一能把两种实现分开的输入。
    """

    @classmethod
    def setUpClass(cls):
        cls.r = _run_threshold_probe()
        if cls.r is None:
            raise unittest.SkipTest("没有 Chrome 或 harness 静态服务（3304）没在跑")
        if cls.r.get("error"):
            raise AssertionError("探针自己报错了：" + cls.r["error"])

    def test_the_probe_actually_measured_a_real_grid(self):
        """★★ 先正面证明量到了东西 —— 零渲染的页面看起来和「通过」一模一样。"""
        self.assertGreater(self.r.get("pitch") or 0, 100,
                           f"★★ 没量到真实网格步距：{self.r}")

    def test_nothing_moves_while_the_card_is_only_30_percent_across(self):
        self.assertFalse(self.r["at30"],
                         "★★★ 卡片才走 30% 邻居就让位了 —— 命中又按指针判了")

    def test_the_neighbour_makes_way_once_the_card_is_80_percent_across(self):
        self.assertTrue(self.r["at80"],
                        "★★★ 卡片都走了 80%，邻居还杵着不动 —— 用户 2026-09-20 报的正是这个")


#: 3×1 的槽位，列在 x=[0,100] / [110,210] / [220,320]，行 y=[0,100]。
_SLOTS = ("[{left:0,top:0,right:100,bottom:100},"
          "{left:110,top:0,right:210,bottom:100},"
          "{left:220,top:0,right:320,bottom:100}]")


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class TheHitTestIsIdempotent(unittest.TestCase):
    """★★★ 指针不动 ⇒ 顺序不许变。四轮「不流畅」的真正根因。

    2026-09-20 实测：命中测试原来拿**按下时冻结的槽位身份**去 `ids.indexOf(...)` 求落点，
    而 `ids` 每帧在变 —— 操作因此不幂等。harness 同坐标连发 8 次 `pointermove`，
    布局在两个状态间反复横跳，170ms 的让位过渡每 ~8ms 被重启、**永远播不完**。

    这条闸守两件事，缺一不可：
      ① 同一坐标重复调用**只生效一次**；
      ② 最终结果**与调用次数的奇偶无关** —— 旧实现下落盘顺序取决于 pointermove 的次数，
         这是它唯一一个能被外部观测到的症状，也是最容易被漏掉的那一半。
    """

    def _repeat(self, n, x=250, y=50, ids="['a','b','c']", aid="'a'"):
        return _node(
            "(() => { let ids = %s;"
            "  for (let i = 0; i < %d; i++) ids = m.reorderByHit(ids, %s, %s, %d, %d);"
            "  return ids; })()" % (ids, n, aid, _SLOTS, x, y))

    def test_repeating_the_same_move_changes_the_order_exactly_once(self):
        steps = _node(
            "(() => { let ids = ['a','b','c']; const seen = [];"
            "  for (let i = 0; i < 8; i++) {"
            "    ids = m.reorderByHit(ids, 'a', %s, 250, 50); seen.push(ids.join('')); }"
            "  return seen; })()" % _SLOTS)
        self.assertEqual(
            sorted(set(steps)), ["bca"],
            "★★★ 指针停在同一点，顺序却在变 —— 让位过渡会被每帧重启、永远播不完。"
            f"实际逐次结果：{steps}")

    def test_the_result_does_not_depend_on_how_many_moves_arrived(self):
        """★★ 旧实现下这是对外可见的症状：落盘顺序取决于 pointermove 次数的奇偶。"""
        got = {n: self._repeat(n) for n in range(1, 10)}
        self.assertEqual(
            list({tuple(v) for v in got.values()}), [("b", "c", "a")],
            f"★★ 结果随 move 次数变化 —— 拖同一个位置，快慢不同会存出不同顺序：{got}")

    def test_a_pointer_in_empty_space_leaves_the_order_alone(self):
        """★ 落在网格空白处是「没命中」，不是「回到第 0 位」。

        ⚠️ 必须拖**不在第 0 位**的那张（这里是 `c`）。第一版拖的是 `a`，而
        「没命中 ⇒ 落点 0」这个变异对一张本来就在第 0 位的卡是空操作 —— 变异实测不红，
        夹具自己把被测行为遮住了。本仓形态⑩：判据档位要挑只有被测那条能挡住的输入。
        """
        for x, y, where in ((105, 50, "列间隙"), (250, 400, "网格下方")):
            self.assertEqual(self._repeat(3, x=x, y=y, aid="'c'"), ["a", "b", "c"],
                             f"★ {where}的坐标把卡片挪走了")

    def test_dragging_back_onto_its_own_slot_returns_it(self):
        """★ 不跳过自己的槽位 —— 指针挪回原处，卡片要正确地回去。"""
        self.assertEqual(
            _node("(() => { let ids = ['a','b','c'];"
                  "  ids = m.reorderByHit(ids, 'a', %s, 250, 50);"
                  "  ids = m.reorderByHit(ids, 'a', %s, 50, 50);"
                  "  return ids; })()" % (_SLOTS, _SLOTS)),
            ["a", "b", "c"], "★ 拖回原位没有还原")

    def test_a_no_op_returns_the_very_same_array(self):
        """★ 幂等要做到**引用不变**，调用方才能便宜地跳过后续工作。"""
        # ⚠️ 包成数组是因为 `_node` 只收 `[`/`{`/`"` 开头的行 —— 裸 `true` 会被过滤掉，
        #   表现为「node 没有产出结果」。别改成裸布尔。
        self.assertEqual(_node(
            "(() => { const a = m.reorderByHit(['a','b','c'], 'a', %s, 250, 50);"
            "  return [m.reorderByHit(a, 'a', %s, 250, 50) === a]; })()" % (_SLOTS, _SLOTS)),
            [True], "★ 空操作仍然新建了数组")

    def test_an_unknown_card_is_not_silently_moved(self):
        self.assertEqual(self._repeat(2, aid="'不存在'"), ["a", "b", "c"])

    def test_the_hook_actually_routes_through_it(self):
        """★★ 纯函数再对，hook 不调它也等于没改。

        断言打在**代码形态**上并先剥注释 —— 本仓形态⑫：注释里正解释着这条规则，
        拿关键词去 `assertIn` 永远匹配得到。
        """
        src = (SRC / "hooks" / "useCardDrag.ts").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith(("*", "/*", "//")))
        self.assertIn("reorderByHit(s.ids, s.aid, s.slots, cx, cy)", code,
                      "★★ onMove 没走那唯一一份命中测试")
        self.assertNotIn("s.ids.indexOf(over)", code,
                         "★★★ 又按「槽位原住户」求落点了 —— 那是不幂等的写法")


if __name__ == "__main__":
    unittest.main(verbosity=2)
