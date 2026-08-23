"""中性文字色的对比度闸。

★ **为什么必须是一道闸而不是又一条注释**：这个问题此前已被就地绕过**两次** ——
  `TrafficPage`（轮数）和 `KpiStrip`（单位）各留下一句「`t.faint` 实算 2.21:1，远低于 WCAG 4.5」
  然后换了个颜色了事。第二次撞见同一类 bug，该交付的是**一个会变红的检查**。
  2026-08-23 用户直接反馈「太灰了，快看不到了」——第三次。

★ **阈值按最差底色定，不是按 appBg**。用户在 demo 里选的值在 appBg 上 4.85 看着达标，
  但在 cardBg/railBg 上只有 4.49/3.86。只验一个底色会漏掉。

纯文本解析 theme.ts，不 import 前端、不跑构建。
"""
import pathlib
import re
import unittest

THEME = (pathlib.Path(__file__).resolve().parent.parent
         / "codexbar" / "src" / "theme.ts")

# 中性**文字**色。装饰性色块（饼图「其余」轨道、进度条槽）不在此列 —— 它们不是要读的内容。
TEXT_TOKENS = ("text", "text2", "muted")
# 这些 token 会被当作文字底色用
BG_TOKENS = ("appBg", "cardBg", "chromeBg", "railBg")
MIN_RATIO = 4.5          # WCAG AA 正文


def _srgb(c):
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def luminance(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (_srgb(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def themes():
    """-> {'dark': {token: '#rrggbb'}, 'light': {...}}。只认 6 位十六进制，rgba(...) 跳过。"""
    src = THEME.read_text(encoding="utf-8")
    out = {}
    for name in ("dark", "light"):
        m = re.search(rf"\b{name}:\s*\{{(.*?)\n  \}}", src, re.S)
        assert m, f"theme.ts 里找不到 {name} 主题块"
        out[name] = dict(re.findall(r'(\w+)\s*:\s*"(#[0-9a-fA-F]{6})"', m.group(1)))
    return out


class TestThemeContrast(unittest.TestCase):
    def setUp(self):
        self.themes = themes()

    def test_neutral_text_meets_aa_on_every_background(self):
        for theme, tok in self.themes.items():
            for name in TEXT_TOKENS:
                self.assertIn(name, tok, f"{theme} 缺少中性色 {name}")
                for bg in BG_TOKENS:
                    if bg not in tok:
                        continue
                    r = contrast(tok[name], tok[bg])
                    with self.subTest(theme=theme, token=name, bg=bg):
                        self.assertGreaterEqual(
                            round(r, 2), MIN_RATIO,
                            f"{theme}.{name}({tok[name]}) 在 {bg}({tok[bg]}) 上只有 {r:.2f}:1，"
                            f"低于 {MIN_RATIO}。别为了『更克制』往回调暗——这条路已经走过一次了。")

    def test_retired_tokens_stay_retired(self):
        """`faint` / `email` 是这次合并掉的两个。

        `faint` 是对比度 2.21 的那个；`email` 按**用途**命名却占着一个**层级**，
        正是「好几种灰」的由来。任何一个复活都会让三级标尺重新变成五级。
        """
        for theme, tok in self.themes.items():
            for dead in ("faint", "email"):
                with self.subTest(theme=theme, token=dead):
                    self.assertNotIn(dead, tok,
                                     f"{theme} 里 `{dead}` 复活了——中性文字只应有三级")

    def test_scale_is_monotonic(self):
        """三级必须真的是三级：亮度严格递减（深色）/递增（浅色），否则层级名就是假的。"""
        for theme, tok in self.themes.items():
            lums = [luminance(tok[n]) for n in TEXT_TOKENS]
            ordered = sorted(lums, reverse=(theme == "dark"))
            self.assertEqual(lums, ordered,
                             f"{theme} 的 text/text2/muted 亮度不是单调的：{lums}")


if __name__ == "__main__":
    unittest.main()
