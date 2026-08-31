"""菜单栏宽度三处必须一致。

★ 为什么要一道闸:`MenuBar.tsx` 里原本就写着「must match inner_size / toggle_menubar in lib.rs」——
  **一条只写在注释里的规则**。这个项目的教训是「没有闸的规则迟早被违反,包括被写规则的人违反」,
  而这条一旦被违反**不会报错**,症状分两种、都很隐蔽:

    · 前端 `PANEL_W` > Rust `inner_size`  ⇒ 弹窗左右被裁掉一截
    · Rust `toggle_menubar` 的 `panel_w` 对不上 ⇒ 弹窗**不在托盘图标正下方**(居中算式用的就是它)

  两种都是"看着还行,就是有点怪",没人会想到去比三个数。

纯文本解析,不 import 任何模块、不碰凭证。
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TSX = ROOT / "codexbar" / "src" / "MenuBar.tsx"
RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"


def _one(path, pattern, what):
    """匹配必须**唯一** —— 匹配到 0 个和匹配到 2 个都会让这道闸悄悄失效
    (同「反向验证的变异点必须唯一」:打错位置和没打中长得一模一样)。"""
    hits = re.findall(pattern, path.read_text(encoding="utf-8"), re.M)
    assert len(hits) == 1, f"{path.name} 里 {what} 命中 {len(hits)} 次，应为 1"
    return float(hits[0])


class TestMenubarWidthSync(unittest.TestCase):
    def test_three_widths_agree(self):
        tsx = _one(TSX, r"^const PANEL_W = (\d+);", "PANEL_W")
        inner = _one(RS, r"\.inner_size\((\d+(?:\.\d+)?), \d+(?:\.\d+)?\)", "inner_size 宽度")
        # ★ 2026-08-31 起 toggle_menubar 里是 `352.0 * scale` —— `set_position` 收的是**物理**
        #   像素,而 352 是**逻辑**宽,不乘 scale 在 Retina 上会偏半个面板宽(既有缺陷,当时一并修)。
        #   闸守的仍是「三处逻辑宽必须一致」,所以只放宽表达式形状,不放宽数值。
        toggle = _one(RS, r"^\s*let panel_w = (\d+(?:\.\d+)?)\s*\*\s*scale;",
                      "toggle_menubar 的 panel_w(逻辑宽)")
        self.assertEqual(tsx, inner, "MenuBar.tsx 的 PANEL_W 与 lib.rs 的 inner_size 宽度不一致")
        self.assertEqual(tsx, toggle, "MenuBar.tsx 的 PANEL_W 与 toggle_menubar 的 panel_w 不一致")

    def test_width_within_measured_envelope(self):
        """★ 实测边界(2026-08-23,真快照 + 双 Tab):
             412~332  布局干净(无压扁、无溢出)
             312      开始折行(内容高不降反升 575→586)
             292      `.mb-root` 横向溢出 —— 硬墙
        下限取 332 而不是 292:留一档余量,不然加个徽章或账号名变长就当场翻车。
        """
        tsx = _one(TSX, r"^const PANEL_W = (\d+);", "PANEL_W")
        self.assertGreaterEqual(tsx, 332, "低于实测下限，账号行会开始折行/溢出")
        self.assertLessEqual(tsx, 460, "过宽，弹窗会盖住托盘附近其它图标")


if __name__ == "__main__":
    unittest.main()
