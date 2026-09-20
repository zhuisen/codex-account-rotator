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
        self.assertIn("if (ok && next", self.app, "★★ App 侧没有区分 commit/取消")

    def test_cards_expose_an_aid_for_hit_testing(self):
        self.assertIn("data-aid={a.aid}", self.card,
                      "★ 没有 data-aid，命中测试找不到落点")


class OtherCardsMoveOutOfTheWayWhileDragging(unittest.TestCase):
    """★★ 用户 2026-09-20 点名要的手感：「像手机拖拽应用程序图标那种，
    放在一个位置后其他卡片要后移让位置」。

    做法是拖动过程中**当场重排预览数组**（`preview`），而不是等松手才动 ——
    让位本身就是落点反馈，所以不再需要"落点描边"那套。
    """

    @classmethod
    def setUpClass(cls):
        raw = (SRC / "App.tsx").read_text(encoding="utf-8")
        cls.code = "\n".join(l for l in raw.splitlines()
                              if not l.strip().startswith(("//", "*", "/*")))

    def test_there_is_a_live_preview_order(self):
        self.assertIn("const [preview, setPreview]", self.code,
                      "★★ 没有预览顺序 —— 只能等松手才动，不是要的手感")

    def test_the_preview_is_reordered_during_move(self):
        i = self.code.index("onMove:")
        self.assertIn("moveItem(base, from, to)", self.code[i:i + 600],
                      "★★ 拖动中没有重排 —— 其余卡片不会让位")

    def test_the_rendered_order_follows_the_preview(self):
        self.assertIn("preview ? applyOrder(savedAlive, preview", self.code,
                      "★★ 渲染没跟着预览走，让位看不见")

    def test_the_dragged_card_lifts(self):
        card = (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8")
        self.assertIn("boxShadow: drag?.isDragging", card, "★ 被拖的卡片没有浮起观感")
        self.assertIn('transform: drag?.isDragging ? "scale(', card)


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
const ids = () => [...document.querySelectorAll('[data-cards-grid] > div[data-aid]')]
  .map(d => d.dataset.aid).slice(0, 6);
const cards = () => [...document.querySelectorAll('[data-cards-grid] > div[data-aid]')];
const wait = ms => new Promise(r => setTimeout(r, ms));
const pe = (type, el, x, y) => el.dispatchEvent(new PointerEvent(type, {
  bubbles: true, cancelable: true, pointerId: 1, clientX: x, clientY: y,
}));
(async () => {
  try {
    const before = ids();
    const a = cards()[0], b = cards()[2];
    const h = a.querySelector('[data-drag-handle]');
    out.handleFound = !!h;
    // setPointerCapture 在合成事件里未必可用 —— 打桩掉，不让它抛断整条链
    h.setPointerCapture = () => {}; h.releasePointerCapture = () => {};
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    pe('pointerdown', h, ra.left + 5, ra.top + 5);
    await wait(120);
    out.draggingStarted = !!document.querySelector('[data-cards-grid] > div[data-aid] [data-drag-handle]');
    pe('pointermove', h, rb.left + rb.width / 2, rb.top + rb.height / 2);
    await wait(200);
    // ★ 关键:**松手之前**顺序就该变了(实时让位)
    out.duringDrag = ids();
    out.reflowedWhileDragging = JSON.stringify(before) !== JSON.stringify(out.duringDrag);
    pe('pointerup', h, rb.left + rb.width / 2, rb.top + rb.height / 2);
    await wait(500);
    out.before = before; out.after = ids();
    out.reordered = JSON.stringify(before) !== JSON.stringify(out.after);
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

    def test_other_cards_move_out_of_the_way_before_you_let_go(self):
        """★★ 用户 2026-09-20 点名要的：「放在一个位置后其他卡片要后移让位置」。

        判据刻意打在**松手之前** —— 松手后才变的话那只是"排序生效"，不是"让位"。
        """
        self.assertIsNone(self.out.get("error"), self.out.get("error"))
        self.assertTrue(self.out.get("reflowedWhileDragging"),
                        f"★★ 拖动中其余卡片没有让位：{self.out.get('before')} "
                        f"→ {self.out.get('duringDrag')}")

    def test_the_card_actually_moves(self):
        self.assertIsNone(self.out.get("error"), self.out.get("error"))
        self.assertTrue(self.out.get("reordered"),
                        f"★★★ 拖完顺序没变：{self.out.get('before')} → {self.out.get('after')}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
