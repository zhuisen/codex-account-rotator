"""卡片动作条的 macOS 半透明磨砂材质 —— **按它盖住了什么**量对比度（真实渲染、真实像素）。

## 起因（用户 2026-09-23）

「结合 macOS 的风格，弹出的功能样式加个透明度会比较好」。动作条从 .97 近乎不透明，
改成 macOS 菜单/弹层那种半透明 + 大半径模糊 + 提饱和。

## ★★ 为什么必须量像素，不能拿色值算

本仓规矩：「半透明浮层的对比度取决于它盖住了什么，不取决于它自己的颜色」。
但**把 alpha 合成一下**也不够 —— 那个模型不计模糊：一条 5px 高的进度条经 20px 高斯模糊后
只剩约 1/10 的强度，按「整片都是那条青色」算出来的 1.92 是个毫无意义的上界。
反过来，**完全不透明的对照组也只有 3.90** —— 最差的像素 `(46,51,58)` 是按钮描边的抗锯齿，
不是背景。两种错法都会让判据指向错误的原因。所以这里：
  · 用真浏览器渲染（含 backdrop 模糊），逐张卡打开动作条，截图；
  · 只取**动作条背景**的像素（子元素外扩 3px、四边内缩 3px，排除描边与抗锯齿）；
  · 取第 1 百分位（去孤点），8 张卡里最差的那张。

## 判据与实测（2026-09-23，`scratch/measure_action_bar_material_20260923.py`）

| | 完全不透明（对照） | 选定材质 @.66 | 门槛 |
|---|---|---|---|
| 深色 · 卡同色 · 灰色图标（muted） | 4.55 | **4.08** | 3.0（非文字） |
| 浅色 · 白     · 灰色图标（muted） | 5.43 | **4.93** | 3.0（非文字） |

深色下灰色**文字**（门槛 4.5）在任何有意义的透明度下都压不住（.80 也只有 4.29），
所以动作条里唯一一段灰字「取消」改用二级文字色 `text2`（深 7.42 / 浅 7.01）。

⚠️ **第一轮浅色数字是错的**（.68 → 2.64、.80 → 3.55）：切主题用了 `localStorage.codexbar_theme`
—— 那是**菜单栏**的键，主窗口主题不持久化、只认点太阳图标 ⇒ 浅色那列量的是「白条压在深色界面上」。
数字看着合理（浅色掉得比深色多，还能编出「透出来的是深色字」的解释），所以没人怀疑前提。
现在 `test_the_theme_really_switched` 先核实卡片底色真的变白，再量。

★ 双向：既要**够透**（否则就是悄悄把用户要的效果退回去），又要**看得清**。
"""
import io
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html?nav=home"

MUTED = {"dark": (0x79, 0x83, 0x90), "light": (0x60, 0x6B, 0x77)}
TEXT2 = {"dark": (0xAA, 0xB3, 0xC0), "light": (0x4D, 0x56, 0x63)}


def _lum(c):
    f = lambda v: (v / 255) / 12.92 if v / 255 <= .03928 else (((v / 255) + .055) / 1.055) ** 2.4
    return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2])


def _cr(a, b):
    x, y = sorted([_lum(a), _lum(b)], reverse=True)
    return (x + .05) / (y + .05)


def _measure():
    """→ {theme: {"muted": 最差, "text2": 最差, "alpha": 背景 alpha, "blur": 有无模糊, "cards": n}}"""
    try:
        from playwright.sync_api import sync_playwright
        from PIL import Image
    except ImportError:
        return None
    import urllib.request
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        for theme in ("dark", "light"):
            ctx = br.new_context(viewport={"width": 1300, "height": 900}, device_scale_factor=2)
            pg = ctx.new_page()
            pg.goto(HARNESS)
            pg.wait_for_timeout(2600)
            # ★★ 主窗口的主题**不持久化**（`useState("dark")`），只能点标题栏的太阳图标。
            #   第一版写的是 `localStorage.codexbar_theme` —— 那是**菜单栏**的键，主窗口不认 ⇒
            #   「浅色」那一档量的其实是深色界面（背景 alpha 读出来是 .66 而不是 .80，
            #   text2 只有 2.11），整列数字作废。所以切完**先正面核实卡片真的变白了**再量。
            if theme == "light":
                pg.evaluate("""() => { const c=[...document.querySelectorAll('svg circle[r="4.2"]')]
                    .map(e=>e.closest('span')).find(Boolean); if (c) c.click(); }""")
                pg.wait_for_timeout(500)
            card_bg = pg.evaluate("getComputedStyle(document.querySelector('[data-aid]')).backgroundColor")
            out.setdefault("_card_bg", {})[theme] = card_bg
            n = pg.evaluate("document.querySelectorAll('[data-aid]').length")
            worst = {"muted": 99.0, "text2": 99.0}
            meta = {}
            for i in range(n):
                pg.evaluate(f"document.querySelectorAll('[data-aid]')[{i}].click()")
                pg.wait_for_timeout(450)       # 入场 160ms 放完
                geo = pg.evaluate("""() => { const b=document.querySelector('[data-actions]'); if(!b) return null;
                    const r=b.getBoundingClientRect(), cs=getComputedStyle(b);
                    return {r:[r.left,r.top,r.right,r.bottom], bg:cs.backgroundColor,
                            blur:(cs.backdropFilter||cs.webkitBackdropFilter||''),
                            kids:[...b.children].map(e=>{const q=e.getBoundingClientRect();
                                                         return [q.left,q.top,q.right,q.bottom]})} }""")
                if not geo:
                    continue
                meta = {"bg": geo["bg"], "blur": geo["blur"]}
                L, T, R, B = geo["r"]
                img = Image.open(io.BytesIO(pg.screenshot(
                    clip={"x": L, "y": T, "width": R - L, "height": B - T}))).convert("RGB")
                px = []
                for y in range(6, img.height - 6):
                    for x in range(6, img.width - 6):
                        gx, gy = L + x / 2, T + y / 2
                        if any(k[0] - 3 <= gx <= k[2] + 3 and k[1] - 3 <= gy <= k[3] + 3
                               for k in geo["kids"]):
                            continue
                        px.append(img.getpixel((x, y)))
                for key, col in (("muted", MUTED[theme]), ("text2", TEXT2[theme])):
                    s = sorted(_cr(col, c) for c in px)
                    if s:
                        worst[key] = min(worst[key], s[len(s) // 100])
                pg.evaluate(f"document.querySelectorAll('[data-aid]')[{i}].click()")
                pg.wait_for_timeout(250)
            import re
            m = re.match(r"rgba?\(([^)]*)\)", meta.get("bg", ""))
            parts = [float(v) for v in m.group(1).split(",")] if m else []
            out[theme] = {**worst, "alpha": parts[3] if len(parts) == 4 else 1.0,
                          "blur": meta.get("blur", ""), "cards": n}
            ctx.close()
        br.close()
    return out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheTranslucentBarStaysReadable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _measure()
        if cls.r is None:
            raise unittest.SkipTest("没有 playwright/PIL，或 harness 静态服务（3304）没在跑")
        cls._bg = cls.r.pop("_card_bg", {})

    def test_the_theme_really_switched(self):
        """★★★ 前提：两档真的是两个主题。第一版切主题的方法是错的，「浅色」量的是深色界面。"""
        bg = self.r.pop("_card_bg", {}) if "_card_bg" in self.r else self.__class__._bg
        self.assertIn("255, 255, 255", bg.get("light", ""), f"★★★ 浅色档的卡片不是白的：{bg}")
        self.assertNotIn("255, 255, 255", bg.get("dark", ""), f"★★ 深色档的卡片是白的：{bg}")

    def test_it_measured_something(self):
        """★★ 先证它**量到了** —— 0 张卡时下面的「最差值」恒为初值 99，白绿。"""
        for theme, d in self.r.items():
            with self.subTest(theme=theme):
                self.assertGreaterEqual(d["cards"], 3, f"★★ {theme} 只找到 {d['cards']} 张卡")
                self.assertLess(d["muted"], 99, "★★ 一个像素都没量到")

    def test_it_is_actually_translucent(self):
        """★★ 反向：必须**真的半透明且带模糊** —— 为了过对比度把它悄悄改回不透明，
        等于撤销用户要的效果，而页面一切「正常」。"""
        for theme, d in self.r.items():
            with self.subTest(theme=theme):
                self.assertLessEqual(d["alpha"], .85, f"★★ {theme} 背景 alpha={d['alpha']}，不透明了")
                self.assertIn("blur(", d["blur"], f"★★ {theme} 没有背景模糊：{d['blur']!r}")

    def test_icons_clear_the_non_text_floor(self):
        """★★★ 灰色图标描边在最差的那张卡上 ≥ 3.0（WCAG 非文字元素）。"""
        for theme, d in self.r.items():
            with self.subTest(theme=theme):
                self.assertGreaterEqual(d["muted"], 3.0,
                                        f"★★★ {theme} 灰色图标对比度 {d['muted']:.2f} < 3.0")

    def test_the_only_grey_text_uses_text2_and_clears_4_5(self):
        """★★ 动作条里唯一一段灰字「取消」必须用 `text2`，且 ≥ 4.5。

        muted 在深色透明材质下压不住 4.5（.80 也只有 4.29），所以换了一级；
        这里双向守：换回 muted 的源码要红，text2 本身在最差底色上也要过线。
        """
        for name in ("AccountCard.tsx", "AgyCard.tsx"):
            src = (ROOT / "codexbar" / "src" / "components" / name).read_text(encoding="utf-8")
            i = src.index(">取消</span>")
            with self.subTest(card=name):
                self.assertIn("color: t.text2", src[max(0, i - 160):i],
                              f"★★ {name} 的「取消」不是 text2 —— 半透明下灰字压不住 4.5")
        for theme, d in self.r.items():
            with self.subTest(theme=theme):
                self.assertGreaterEqual(d["text2"], 4.5,
                                        f"★★ {theme} text2 在最差底色上只有 {d['text2']:.2f}")

    def test_webkit_prefix_is_there_for_wkwebview(self):
        """★ CodexBar 跑在 WKWebView 里；只写标准属性在较老的 macOS 上整条被忽略，
        而 harness 用 Chrome、两种都认 —— 这个缺口在渲染闸里**看不出来**，只能静态守。"""
        src = (ROOT / "codexbar" / "src" / "components" / "CardActionBar.tsx").read_text(encoding="utf-8")
        self.assertIn("WebkitBackdropFilter:", src, "★ 少了 WebkitBackdropFilter —— 真机上可能不模糊")


if __name__ == "__main__":
    unittest.main(verbosity=2)
