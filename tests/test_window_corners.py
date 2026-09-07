"""窗口圆角:透明窗口 + **原生**裁剪(用户 2026-09-07/09-08 两轮反馈)。

## 一条链上有五个环,断任何一个都看不出圆角,而且**四个环断掉时不报错**

| 环 | 断掉的症状 |
|---|---|
| `tauri.conf.json` 的 `windows[].transparent` | 窗口不透明 ⇒ 半径外一圈被底色填成**四个黑角** |
| `app.macOSPrivateApi` | `transparent` 被**静默忽略**,build 不报任何错 |
| `Cargo.toml` 的 `macos-private-api` feature | `cargo check` **直接失败**,但报错文案是「features does not match the allowlist」,与窗口/透明毫无字面关系 |
| `body { background: transparent }` | body 盖住根节点圆角外那一圈,黑角原样回来 —— 而配置确实生效了 |
| `round_corners()`(AppKit) | 圆是圆了但**边缘发毛**:webview 的 CSS 裁剪没有抗锯齿,直接压在桌面上 |

## ★★ macOS 上前端不许再用 `borderRadius` 裁根节点

用户 2026-09-08 的原话是「不够圆,并露桌面但边缘发毛」——「露桌面」证明 transparent 已生效,
「发毛」是 CSS 裁剪的锯齿。**先被 CSS 切一刀(带锯齿)再被原生切一刀,锯齿仍在**,
所以 macOS 那支必须归零。Windows 没有等价 API,仍走 CSS。

★ `cornerCurve = continuous` 才是苹果那种圆角(squircle)。同样半径下,圆弧角比连续曲率角
显得方 —— 用户说的「不够圆」多半是曲率不是半径,所以两者一起改。
"""
import json
import re
import unittest
from pathlib import Path


def strip_line_comments(src, marker):
    """剥掉注释再匹配。★ 本文件的注释里逐条写着这些常量名（`macos-private-api`、
    `"continuous"`），对着原文匹配会**恒绿** —— 变异测试当场抓到两条（形态④）。"""
    return "\n".join(l.split(marker)[0] for l in src.splitlines())

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "codexbar" / "src-tauri" / "tauri.conf.json"
CARGO = ROOT / "codexbar" / "src-tauri" / "Cargo.toml"
LIB = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"
APP_CSS = ROOT / "codexbar" / "src" / "App.css"
APP_TSX = ROOT / "codexbar" / "src" / "App.tsx"


class TransparencyChainIsComplete(unittest.TestCase):
    def test_window_is_transparent(self):
        c = json.loads(CONF.read_text(encoding="utf-8"))
        self.assertTrue(c["app"]["windows"][0].get("transparent"),
                        "主窗不透明 ⇒ 圆角外一圈会被窗口底色填成黑角")

    def test_macos_private_api_is_on(self):
        """★ 少了它 `transparent` 被**静默忽略** —— build 一声不吭。"""
        c = json.loads(CONF.read_text(encoding="utf-8"))
        self.assertTrue(c["app"].get("macOSPrivateApi"),
                        "macOSPrivateApi 没开 —— transparent 会被静默忽略")

    def test_cargo_feature_matches_the_config(self):
        """★ 两处必须同时有。少了它 `cargo check` 直接失败,但报错与窗口无关、容易查偏。"""
        bare = strip_line_comments(CARGO.read_text(encoding="utf-8"), "#")
        self.assertIn("macos-private-api", bare,
                      "Cargo 缺 macos-private-api feature —— 与 tauri.conf 的 macOSPrivateApi 配套")

    def test_body_does_not_paint_over_the_corners(self):
        css = APP_CSS.read_text(encoding="utf-8")
        m = re.search(r"^body\s*\{([^}]*)\}", css, re.M)
        self.assertIsNotNone(m, "找不到 body 规则")
        self.assertIn("background: transparent", m.group(1),
                      "body 刷了不透明底色 —— 它会盖住圆角外那一圈,黑角原样回来")

    def test_menubar_window_is_transparent_too(self):
        self.assertIn("transparent(true)", LIB.read_text(encoding="utf-8"),
                      "菜单栏弹窗没设透明 —— 它的 16px 圆角会变成四个黑角")


class CornersAreCutNatively(unittest.TestCase):
    def test_native_helper_exists_and_uses_continuous_curve(self):
        rs = LIB.read_text(encoding="utf-8")
        self.assertIn("fn round_corners(", rs, "没有原生圆角函数 —— CSS 裁剪会发毛")
        i = rs.index("fn round_corners(")
        body = strip_line_comments(rs[i:rs.index("\n}\n", i)], "//")
        self.assertIn("setCornerRadius", body)
        self.assertIn('"continuous"', body,
                      "没有用连续曲率 —— 那是苹果圆角的形状,同半径下圆弧角显得更方")
        self.assertIn("setMasksToBounds", body, "没有开裁剪,设了半径也不生效")
        # ★ 透明窗口的投影按 alpha 形状算,不通知就会留一圈方形残影
        self.assertIn("invalidateShadow", body, "改完没有重算投影 —— 会留方形阴影残影")

    def test_both_windows_call_it(self):
        rs = LIB.read_text(encoding="utf-8")
        self.assertEqual(rs.count("round_corners(&"), 2,
                         "主窗与菜单栏必须都调 —— 只接一个的症状是「一个圆一个毛」")

    def test_macos_does_not_also_clip_in_css(self):
        """★★ 先被 CSS 切一刀(带锯齿)再被原生切一刀,**锯齿仍在**。所以 macOS 那支必须归零。
        Windows 没有等价 API,仍走 CSS —— 判据是这个三元表达式本身。"""
        tsx = APP_TSX.read_text(encoding="utf-8")
        m = re.search(r"borderRadius:\s*([^,]+),", tsx)
        self.assertIsNotNone(m, "根节点找不到 borderRadius")
        expr = m.group(1)
        self.assertIn("winUI", expr,
                      "根节点在 macOS 上仍用 CSS 裁剪 —— 边缘会发毛(用户 2026-09-08 实证)")
        self.assertRegex(expr, r":\s*0\b", "macOS 那一支不是 0")


if __name__ == "__main__":
    unittest.main()
