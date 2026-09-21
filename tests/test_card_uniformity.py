"""三档卡片的**统一性**与底部留白（用户 2026-09-20 两条）。

## ① 右上角只许有拖拽手柄

Gemini 卡与 grok 卡的右上角原来各有一个 `↻` 手动重取，坐标写死 `top:4 right:8` ——
而 `DragHandle` 用的是**字面上同一个坐标**。于是同一个角落在三档里长出三种不同的东西，
Gemini 卡上更是两个控件直接叠在一起。用户：「卡片统一一下，gemini 和 grok 账号卡片的
右上角的刷新进行删除」。

★ 删得起的理由是**取数本来就是自动的**，不是"手动才会刷"：
  · grok —— CLI 活着时 `grok-quota-sampler` 约 15s 推一次，没在跑时 `useGrokQuota` 10min 兜底；
  · agy —— 档头有「刷新全池」，选中卡的**动作条里**仍有 ↻（与 codex 卡同排同形）。
⚠️ 代价写在这里，不装作没有：grok **失去了手动催一次的能力**，读数最坏会旧至多 10 分钟。

## ② 动作条的预留只给**同排**

同排的卡在网格里本来就等高，选中卡一展开会把同排兄弟拉高；而卡内的环垂直居中、条形区
靠 `flex:1` 吊底，所以不预留的话多出来的高度会摊在**中间**，邮箱与环之间裂开一道洞
（用户 2026-08-24 截图圈过）。预留是把那段高度按到底部去 —— **同排必须留**。

但原来写的是 `selectedCard !== null` 一刀切，别的排根本没被拉高却也各空出一截。
实测（本闸的探针，2026-09-20）：选中第 0 排一张卡时，**第 1、2 排每张多 47px、
底部死空间 13→60px** —— 就是用户说的「卡片的底部留白的地方多了」。

★ 这两条都**只能量**，不能靠读代码推：死空间是「最后一个有墨的元素底边」到卡片底边的
  距离，它由 flex 链、预留占位、padding 三者合成，任何一处改动都会改它。
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
APP = SRC / "App.tsx"
HARNESS = "http://127.0.0.1:3304"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: 卡片右上角的判定框：`DragHandle` 在 `top:4 right:8`，取 24×40 足够把它框住。
_CORNER = "r.top - cr.top < 24 && cr.right - r.right < 40"

_PROBE_JS = r"""
const out = { lanes: {}, corner: {} };
const wait = ms => new Promise(r => setTimeout(r, ms));
const grids = () => [...document.querySelectorAll('[data-cards-grid]')];

/** 每张卡：高度 + 「最后一个有墨的元素底边」到卡片底边的死空间。 */
function measure(tag) {
  const rows = [];
  for (const g of grids()) [...g.children].forEach((c, i) => {
    const cr = c.getBoundingClientRect();
    if (cr.height < 40) return;
    let maxB = cr.top;
    for (const el of c.querySelectorAll('*')) {
      const s = getComputedStyle(el);
      // 隐形的预留占位、绝对定位的角标都不算"墨"
      if (s.visibility === 'hidden' || s.display === 'none' || s.position === 'absolute') continue;
      const ink = (el.textContent || '').trim() !== ''
                  || s.backgroundColor !== 'rgba(0, 0, 0, 0)' || el.tagName === 'svg';
      if (!ink) continue;
      const r = el.getBoundingClientRect();
      if (r.height > 0 && r.bottom > maxB) maxB = r.bottom;
    }
    rows.push({ i, row: Math.floor(i / 3), h: Math.round(cr.height),
                gap: Math.round(cr.bottom - maxB) });
  });
  out.lanes[tag] = rows;
}

/** 卡片右上角有几个控件，以及它们分别是什么。 */
function corner(tag) {
  const found = [];
  for (const g of grids()) for (const c of g.children) {
    const cr = c.getBoundingClientRect();
    for (const el of c.querySelectorAll('button, [data-drag-handle], span')) {
      const txt = (el.textContent || '').trim();
      if (!txt) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (__CORNER__) found.push(txt.slice(0, 4));
    }
  }
  out.corner[tag] = found;
}

const tabFor = n => [...document.querySelectorAll('*')].filter(e =>
  e.children.length === 0 && (e.textContent || '').trim().toLowerCase() === n.toLowerCase())[0];

const cards = () => [...document.querySelectorAll('[data-cards-grid] > div[data-aid]')];
const heights = () => cards().map(c => Math.round(c.getBoundingClientRect().height));
const click = i => cards()[i].dispatchEvent(new MouseEvent('click', { bubbles: true }));

(async () => {
  try {
    measure('codex'); corner('codex');
    out.heights = { '收起': heights() };
    click(0);
    await wait(600); measure('codex-selected');
    out.heights['选中第 1 张'] = heights();
    out.actions = document.querySelectorAll('[data-actions]').length;
    // ★ 「换行」的判据是**按钮的 y 坐标出现了两种**，不是 `flexWrap` 写了什么 ——
    //   写 nowrap 却让内容溢出，同样是坏的，而只看属性看不出来。
    const bar = document.querySelector('[data-actions]');
    if (bar) { const br = bar.getBoundingClientRect(), cs = getComputedStyle(bar);
      const kids = [...bar.children].map(e => e.getBoundingClientRect());
      out.bar = { 行数: new Set(kids.map(r => Math.round(r.top))).size,
                  溢出: Math.round(Math.max(0, Math.max(...kids.map(r => r.right))
                                              - (br.right - parseFloat(cs.paddingRight)))) }; }
    const ov = document.querySelector('[data-actions]');
    if (ov) { const r = ov.getBoundingClientRect(), c = cards()[0].getBoundingClientRect();
      out.overlay = { '超出卡片底边': Math.round(r.bottom - c.bottom),
                      '动画': getComputedStyle(ov).animationName }; }
    // ★ 改选另一张：验的是"换一张展开"也不改高度，不是只验"第一次展开"
    click(3); await wait(600);
    out.heights['改选第 4 张'] = heights();
    click(3); await wait(400);          // 收起，让后面的档位测量回到干净状态
    for (const name of ['Gemini', 'grok']) {
      const tab = tabFor(name);
      if (!tab) { out.lanes[name] = 'tab-not-found'; continue; }
      tab.click(); await wait(800); measure(name); corner(name);
    }
  } catch (e) { out.error = String(e && e.stack || e); }
  document.title = '__UNI__' + JSON.stringify(out);
})();
""".replace("__CORNER__", _CORNER)


def _run_probe(width=1200):
    import urllib.request
    src = APP_DIR / "harness.html"
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / "uniprobe.html"
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>setTimeout(() => {{{_PROBE_JS}}}, 2600);</script></body>", 1),
        encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            f"--window-size={width},1000", "--virtual-time-budget=16000",
                            "--dump-dom", f"{HARNESS}/uniprobe.html?nav=home"],
                           capture_output=True, text=True, timeout=180)
        m = re.search(r"__UNI__(\{.*\})\s*</title>", r.stdout, re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        page.unlink(missing_ok=True)


class _Probed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _run_probe()
        # ★★★ **第二次量在最窄窗口**（860 是 `tauri.conf.json` 的 `minWidth`，加 20 余量）。
        #   1200 下卡片有 ~349px，动作条怎么排都放得下 ⇒ 「不换行」这条在那儿**没有判别力**
        #   （变异实测：放开 `flexWrap: wrap`、把图标钮改回不可收缩，两条都照样绿）。
        #   真正的压力在用户能拖到的最窄处。本仓形态⑩：判据档位挑错会被上游兜住。
        cls.narrow = _run_probe(880)
        if cls.r is None:
            raise unittest.SkipTest("没有 Chrome 或 harness 静态服务（3304）没在跑")
        if cls.r.get("error"):
            raise AssertionError("探针自己报错了：" + cls.r["error"])

    def rows(self, lane):
        v = self.__class__.r["lanes"].get(lane)
        self.assertIsInstance(v, list, f"★★ {lane} 档没量到（可能是档位没切过去）：{v!r}")
        self.assertTrue(v, f"★★ {lane} 档一张卡都没量到 —— 零渲染看起来和通过一模一样")
        return v


class TheTopRightCornerIsTheSameOnEveryLane(_Probed):
    """★★ 三档卡片的右上角必须长得一样：有手柄的放手柄，没有的就留空。"""

    def test_no_refresh_control_in_any_corner(self):
        for lane, found in self.r["corner"].items():
            self.assertNotIn("↻", found,
                             f"★★ {lane} 档的卡片右上角又出现了 ↻ —— 它与拖拽手柄同一个坐标")

    def test_the_probe_looked_at_cards_that_really_rendered(self):
        """★★ 先正面证明量到了卡片 —— 一张卡都没渲染时「角落里没有 ↻」恒真。"""
        for lane in ("codex", "Gemini", "grok"):
            self.rows(lane)

    def test_nothing_else_squats_on_the_drag_handle_coordinate(self):
        """★ 静态兜底：`top: 4, right: 8` 这个坐标只许 DragHandle 用。

        断言前剥掉注释 —— 本仓形态④：上面的说明文字里正写着这个坐标。
        """
        for name in ("AgyCard.tsx", "GrokCard.tsx", "AccountCard.tsx"):
            raw = (SRC / "components" / name).read_text(encoding="utf-8")
            code = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))
            self.assertNotIn("top: 4, right: 8", code,
                             f"★ {name} 又往手柄那个坐标上放了控件")


class SelectingACardNeverChangesAnyHeight(_Probed):
    """★★★ 用户 2026-09-21：「不改变高度，而是弹出功能按钮去选择那种」。

    ## 这条闸取代了整整一族「同排预留」的闸

    动作条原来是文档流里的一块，展开时把卡片撑高 ~47px。同排的卡在网格里等高，
    于是邻卡跟着长 —— 为此有过 `reserveActions` / `sameRow()` 一整套「给同排每张卡
    预留一条等高隐形占位」的逻辑，外加 4 条闸。

    **浮层把那套逻辑连根去掉**：动作条绝对定位、浮在卡片底部，卡片高度恒定。
    所以那 4 条闸一并删除 —— 留着一族守护着已不存在行为的断言，下一个人会以为
    那套逻辑还在生效（本仓记过的死代码形态：删功能就连组件本体一起删）。

    ★★ 判据是**量出来的高度**，不是"源码里有 position:absolute" ——
      高度是 padding / flex 链 / 浮层定位三者合成的，任何一处改动都会改它。
    """

    EXPECT_STATES = ("收起", "选中第 1 张", "改选第 4 张")

    def test_the_probe_measured_real_cards(self):
        """★★ 先正面证明量到了卡 —— 空列表下「高度全都相同」恒真。"""
        for k in self.EXPECT_STATES:
            with self.subTest(state=k):
                self.assertGreaterEqual(len(self.r["heights"][k]), 3,
                                        f"{k}: 没量到足够多的卡：{self.r}")

    def test_every_card_has_the_same_height_in_every_state(self):
        for k in self.EXPECT_STATES:
            hs = set(self.r["heights"][k])
            with self.subTest(state=k):
                self.assertEqual(len(hs), 1, f"★★★ {k} 时卡片高度不齐：{hs}")

    def test_selecting_does_not_change_the_height_at_all(self):
        """★★★ 这就是用户要的那句话 —— 展开动作条**不许改变任何高度**。"""
        base = self.r["heights"]["收起"]
        for k in self.EXPECT_STATES[1:]:
            with self.subTest(state=k):
                self.assertEqual(self.r["heights"][k], base,
                                 f"★★★ {k} 把高度改了：{base} → {self.r['heights'][k]}")

    def test_only_the_selected_card_has_an_action_bar(self):
        """★ 浮层不再需要"隐形占位"，所以同一时刻**只该有一条**动作条在 DOM 里。"""
        self.assertEqual(self.r["actions"], 1,
                         f"★ 动作条数量不是 1：{self.r['actions']} —— 隐形占位又回来了？")

    def test_the_overlay_sits_inside_the_card(self):
        """★ 它是**覆盖在卡片底部**，不是吊在卡外（那是 demo 里的 B 案，用户没选）。"""
        self.assertLessEqual(self.r["overlay"]["超出卡片底边"], 0,
                             "★ 浮层探出了卡片底边 —— 用户选的是 A（覆盖在卡内）")

    def test_the_action_bar_never_wraps(self):
        """★★★ 用户 2026-09-21：「我不要出现换行的。自适应不断去压缩按钮」。

        实测（修前）：1300 窗口下卡内宽 351 / 按钮需要 347 —— **只差 4px**，
        窗口再窄一点就折行，最后那个删除钮掉到第二行。而折行不只是难看：
        第二行把浮层撑高、盖掉更多卡片内容，且「最后一个按钮掉下去」看着像它坏了。

        ★★ 判据是**按钮的 y 坐标只有一种**，不是"源码里写了 nowrap" ——
          写 nowrap 却横向溢出同样是坏的，而只看属性看不出来。所以两条一起断言。
        """
        for tag, res in (("1200", self.r), ("880（最窄窗口）", self.narrow)):
            with self.subTest(width=tag):
                self.assertIsNotNone(res, f"{tag} 没量到")
                self.assertEqual(res["bar"]["行数"], 1,
                                 f"★★★ {tag} 下动作条折行了：{res['bar']}")
                self.assertEqual(res["bar"]["溢出"], 0,
                                 f"★★★ {tag} 下动作条横向溢出（比折行更糟）：{res['bar']}")

    def test_the_no_wrap_insurance_is_in_place(self):
        """★ `nowrap` + 全员可收缩是**纵深防御**，不是当前生效的东西 —— 如实说。

        ⚠️ 变异实测 2026-09-21：把 `flexWrap` 放回 `wrap`、把图标钮/探针钮改回
          不可收缩，上面那条行为闸**在 880 与 1200 两个档位都照样绿** ——
          因为 `CARD_MIN_W = 320` 之后卡内宽恒 ≥342，而按钮合计 338，**永远放得下**。

        ★ 也就是说：**真正修好这件事的是网格那一条**，`nowrap` 只是保险。
          所以这里用的是**静态断言**，并且明说它的判别力来自哪 ——
          假装上面那条行为闸覆盖了它，才是本仓最不能容忍的那种"测了个寂寞"。
        ★ 保险仍然要留：字号档位、更长的按钮文案、以后多加一个控件，
          任何一条都会让那 4px 余量消失，而那时 `nowrap` 就是最后一道。
        """
        for name in ("AccountCard.tsx", "AgyCard.tsx"):
            raw = (SRC / "components" / name).read_text(encoding="utf-8")
            code = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))
            i = code.index("data-actions")
            with self.subTest(card=name):
                self.assertIn('flexWrap: "nowrap"', code[i:i + 900],
                              f"★ {name} 的动作条允许换行了 —— 保险没了")
        icons = (SRC / "components" / "CardIcons.tsx").read_text(encoding="utf-8")
        self.assertIn("flexShrink: 1", icons,
                      "★ 图标钮压不动 —— nowrap 下只能横向溢出")

    def test_the_card_can_never_get_too_narrow_for_its_own_action_bar(self):
        """★★★ 这才是**根因的闸**：按钮再怎么压，卡片窄过某个宽度就是装不下。

        实测 2026-09-21：写死 3 列时 880 窗口把卡压到 **211px**，而 7 个控件最紧
        也要 ~234px 内宽 ⇒ 怎么排都要折行。只调按钮是治标。
        现在网格按 `CARD_MIN_W` auto-fill：宽屏仍 3 列，窄屏退到 2 列、卡片反而更宽。
        """
        app = (SRC / "App.tsx").read_text(encoding="utf-8")
        m = re.search(r"const CARD_MIN_W = (\d+);", app)
        self.assertIsNotNone(m, "★★ 找不到 CARD_MIN_W —— 列数又被写死了？")
        self.assertGreaterEqual(int(m.group(1)), 300,
                                "★★★ 卡片最小宽低于 300 —— 动作条会重新折行")
        self.assertIn("repeat(auto-fill, minmax(${CARD_MIN_W}px, 1fr))", app,
                      "★★★ 网格不是按最小宽自适应 —— 窄窗会把卡压到装不下动作条")

    def test_the_entrance_animation_is_the_repos_own(self):
        """★ 用户 2026-09-21：「弹出动态效果要好看自然贴切 codexbar 风格」。
        判据是**真的挂上了那条动画**，不是源码里写了类名。"""
        self.assertEqual(self.r["overlay"]["动画"], "cbRise",
                         "★ 入场动画没生效 —— 浮层会硬生生地出现")


class TheRowMathAndTheGridShareOneNumber(unittest.TestCase):
    """★★ 「第几排」的算式与网格列数必须是**同一个常量**。

    分成两处写的话，改了 `gridTemplateColumns` 却没改行算式，预留会静默地留到
    错误的一排上 —— 而界面看起来完全正常，只是留白位置不对。
    """

    def setUp(self):
        raw = APP.read_text(encoding="utf-8")
        self.code = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))

    def test_no_grid_hardcodes_its_column_count(self):
        self.assertNotIn('gridTemplateColumns: "repeat(3', self.code,
                         "★★ 又把列数写死了 —— 它必须来自 CARD_COLS")

    def test_every_card_grid_uses_the_shared_constant(self):
        n = self.code.count("data-cards-grid")
        self.assertEqual(self.code.count("gridTemplateColumns: CARD_GRID_COLS"), n,
                         f"★★ {n} 张卡片网格里有的没走 CARD_GRID_COLS")

    def test_the_reservation_logic_is_gone_for_good(self):
        """★★ 卡片不再长高 ⇒ 那套预留逻辑**存在的理由本身消失了**，连代码一起删。
        留一份没人调用的逻辑，下一个人会以为它还在生效（本仓记过的死代码形态）。"""
        self.assertNotIn("reserveActions", self.code,
                         "★★ `reserveActions` 又回来了 —— 卡片会重新随展开长高")
        self.assertNotIn("function sameRow", self.code,
                         "★★ `sameRow()` 还在 —— 它守的行为已经不存在了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
