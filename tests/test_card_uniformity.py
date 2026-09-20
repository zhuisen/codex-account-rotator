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

(async () => {
  try {
    measure('codex'); corner('codex');
    document.querySelector('[data-cards-grid] > div[data-aid]')
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await wait(600); measure('codex-selected');
    for (const name of ['Gemini', 'grok']) {
      const tab = tabFor(name);
      if (!tab) { out.lanes[name] = 'tab-not-found'; continue; }
      tab.click(); await wait(800); measure(name); corner(name);
    }
  } catch (e) { out.error = String(e && e.stack || e); }
  document.title = '__UNI__' + JSON.stringify(out);
})();
""".replace("__CORNER__", _CORNER)


def _run_probe():
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
                            "--window-size=1200,1000", "--virtual-time-budget=16000",
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


class TheActionRowIsOnlyReservedOnTheSelectedRow(_Probed):
    """★★★ 预留只给同排 —— 别的排留的是纯浪费（用户：底部留白多了）。"""

    def test_with_nothing_selected_every_card_is_tight(self):
        gaps = {r["gap"] for r in self.rows("codex")}
        self.assertTrue(max(gaps) <= 20,
                        f"★★ 什么都没选时卡片底部就有死空间：{sorted(gaps)}")

    def test_the_selected_row_still_reserves(self):
        """★★★ 同排**必须**留 —— 不留的话高度摊在中间，邮箱与环之间裂开一道洞。"""
        row0 = [r for r in self.rows("codex-selected") if r["row"] == 0]
        self.assertTrue(any(r["gap"] > 30 for r in row0),
                        f"★★★ 选中卡那一排没有预留，多出的高度会摊在卡片中间：{row0}")

    def test_the_other_rows_do_not(self):
        rows = self.rows("codex-selected")
        others = [r for r in rows if r["row"] != 0]
        self.assertTrue(others, "★★ 夹具只有一排 —— 这条闸需要 ≥2 排才有判别力")
        worst = max(r["gap"] for r in others)
        self.assertLessEqual(worst, 20,
                             f"★★★ 没被选中的那几排也留了位（死空间 {worst}px）—— "
                             "它们根本没被拉高，这是纯浪费")

    def test_the_other_rows_keep_their_unselected_height(self):
        """★★ 更强的说法：别的排的高度应当**一点都没变**。"""
        base = {r["h"] for r in self.rows("codex")}
        others = {r["h"] for r in self.rows("codex-selected") if r["row"] != 0}
        self.assertEqual(others, base,
                         f"★★ 选中一张卡把别的排也撑高了：{sorted(base)} → {sorted(others)}")


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

    def test_the_row_math_uses_it_too(self):
        self.assertIn("Math.floor(i / CARD_COLS)", self.code,
                      "★★ 行算式没用 CARD_COLS —— 它会与网格分叉")

    def test_reservation_is_never_lane_wide_again(self):
        """★★★ 变回 `selectedCard !== null` 一刀切就是这条 bug 本身。"""
        self.assertNotIn("reserveActions={selectedCard !== null}", self.code,
                         "★★★ 预留又变成整档一刀切了 —— 没被拉高的排会跟着空出一截")
        self.assertEqual(self.code.count("reserveActions={sameRow("), 2,
                         "★★ codex 与 Gemini 两档都要走 sameRow()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
