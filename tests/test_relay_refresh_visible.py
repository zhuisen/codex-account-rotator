"""中转站「刷新余额」必须**看得见、点得中**（用户 2026-09-21：「没看到刷新，或者刷新不显眼」）。

## 量出来的问题

第一版只在余额旁放了一个裸 `↻` 字形。实测（harness，`?relay=stale`）：

| | 尺寸 | 对比度 | 边框 | 底色 |
|---|---|---|---|---|
| 余额旁的 ↻ | **6 × 14 px** | 5.88 ✓ | 无 | 无 |
| 页头「刷新余额」 | **87 × 32 px** | —— | 有 | 有 |

★ **对比度从来不是问题**（5.88 达标）。问题是它**不像个控件、也几乎点不中** ——
  一个 6px 宽的字形坐在一行本来就发灰的小字里，读起来是标点不是按钮。
  这是本仓「把操作放在眼睛已经在的地方」的另一面：**放对了地方还不够，
  它得长得像个能点的东西**。

## 为什么用 GhostButton 而不是自己画一个

全 app 只该有一种「刷新」长相。总览的「刷新全池」就是 `GhostButton` + `IcRefresh`，
中转站页照用同一对 —— 用户不需要为第二个刷新再认一种结构。
★ 图标因此从 `App.tsx` 的模块局部搬进 `components/CardIcons.tsx`：两处各写一份 SVG
  必然漂移且**不报错**（这个文件头上记的就是这条，已漂过两次）。
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
PAGE = SRC / "pages" / "RelayPage.tsx"
APP = SRC / "App.tsx"
ICONS = SRC / "components" / "CardIcons.tsx"
HARNESS = "http://127.0.0.1:3304"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

_MEASURE = r"""
const out = {};
const b = document.querySelector('[data-act="relay-refresh-header"] > *');
if (b) { const r = b.getBoundingClientRect(), s = getComputedStyle(b);
  out.header = { w: Math.round(r.width), h: Math.round(r.height),
                 bordered: s.borderStyle !== 'none' && s.borderTopWidth !== '0px' }; }
const s2 = document.querySelector('[data-act="relay-balance-refresh"]');
if (s2) { const r = s2.getBoundingClientRect(); out.inline = { w: Math.round(r.width), h: Math.round(r.height) }; }
out.svgs = document.querySelectorAll('[data-act="relay-refresh-header"] svg').length;
document.title = '__RF__' + JSON.stringify(out);
"""


def _measure(query):
    import json
    import urllib.request
    src = APP_DIR / "harness.html"
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / "rfprobe.html"
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>setTimeout(() => {{{_MEASURE}}}, 2600);</script></body>", 1),
        encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            "--window-size=1300,900", "--virtual-time-budget=9000",
                            "--dump-dom", f"{HARNESS}/rfprobe.html?{query}"],
                           capture_output=True, text=True, timeout=180)
        m = re.search(r"__RF__(\{.*?\})\s*</title>", r.stdout, re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        page.unlink(missing_ok=True)


def _code(p):
    s = p.read_text(encoding="utf-8")
    return re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s))


class ThereIsARefreshWhereTheEyeLooksFirst(unittest.TestCase):
    def setUp(self):
        self.code = _code(PAGE)

    def test_the_page_header_has_one(self):
        self.assertIn('data-act="relay-refresh-header"', self.code,
                      "★★ 页头没有刷新按钮 —— 找刷新时眼睛先去的就是页头")

    def test_it_uses_the_same_button_as_the_pools_refresh(self):
        """★ 全 app 只该有一种「刷新」长相。总览是 `GhostButton` + `IcRefresh`。"""
        self.assertIn("<GhostButton", self.code, "★ 没用 GhostButton —— 又发明了一种按钮")
        self.assertIn("<IcRefresh", self.code, "★ 没用共享的刷新图标")

    def test_the_icon_is_shared_not_copied(self):
        """★★ 两处各写一份 SVG 必然漂移且**不报错**（CardIcons 文件头记的就是这条）。"""
        self.assertIn("export const IcRefresh", _code(ICONS),
                      "★★ 刷新图标没搬进共享模块")
        app = _code(APP)
        self.assertIn('import { IcRefresh } from "./components/CardIcons"', app,
                      "★★ App.tsx 还在用自己那份 —— 两份 SVG 会漂")
        self.assertNotIn('const IconRefresh = ({ spin }', app,
                         "★★ App.tsx 里的那份副本又回来了")

    def test_the_busy_state_is_wired(self):
        """★ 没有转圈的话，点下去 2.3s 内没有任何反馈，用户会连点。"""
        self.assertIn("loading={usageBusy}", self.code, "★ 按钮没有进行态")
        self.assertIn("spin={usageBusy}", self.code, "★ 图标不转 —— 看不出在跑")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class ItIsBigEnoughToBeSeenAndHit(unittest.TestCase):
    """★★★ **这条只能量，不能读源码推** —— 尺寸是字号/内边距/图标三者合成的。"""

    @classmethod
    def setUpClass(cls):
        cls.m = _measure("nav=relay&relay=stale")
        if cls.m is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_the_header_button_really_rendered(self):
        """★★ 先正面证明它在 —— 没渲染时下面的尺寸断言会 KeyError 而不是假绿。"""
        self.assertIn("header", self.m, f"★★ 页头按钮没渲染：{self.m}")

    def test_it_is_a_real_click_target(self):
        h = self.m["header"]
        self.assertGreaterEqual(h["h"], 24,
                                f"★★★ 高 {h['h']}px —— 可点目标通常要 ≥24px")
        self.assertGreaterEqual(h["w"], 60,
                                f"★★★ 宽 {h['w']}px —— 带文字的按钮不该这么窄")

    def test_it_looks_like_a_control(self):
        self.assertTrue(self.m["header"]["bordered"],
                        "★★ 没有边框 —— 那正是第一版失败的原因：读起来是文字不是按钮")

    def test_it_is_far_bigger_than_the_inline_glyph_it_replaces(self):
        """★ 把「改进了多少」钉成一个数，而不是一句「更显眼了」。"""
        h, s = self.m["header"], self.m.get("inline")
        self.assertIsNotNone(s, "余额旁那个小 ↻ 不见了 —— 它是就近入口，应当保留")
        self.assertGreater(h["w"] * h["h"], s["w"] * s["h"] * 10,
                           f"★ 页头按钮 {h['w']}×{h['h']} vs 余额旁 {s['w']}×{s['h']}"
                           " —— 没有拉开量级，等于没解决「不显眼」")


if __name__ == "__main__":
    unittest.main(verbosity=2)
