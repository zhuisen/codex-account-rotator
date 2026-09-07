"""设置页的数值控件:滑块(粗调) + **可直接输入**(精调)。

用户 2026-09-07:「滑块滚动不太精准能滚到想要的数值」。

## 三条会静默出错的路

**① 组件必须在模块作用域。** 原来 `NumInput` 定义在页面组件的 render 里 —— 每次渲染都是一个
**新的组件类型**,React 整个卸载重建。对滑块只是掉帧(本仓 `Seg` 那条已判过),
但对**输入框是致命的**:每敲一个字符重建一次,焦点丢失、根本打不进字。
所以"加个输入框"的第一步是先把它搬出来,不是加一个 `<input>` 了事。

**② 打字期间不能 clamp。** 边打边钳的话,想输 `25` 会在打完 `2` 的瞬间被钳到 min=5 变成 `5`,
第二个字符再也接不上。必须用**草稿态**,失焦/回车才提交并 clamp。

**③ `onKeyDown` 必须 `stopPropagation`。** 全局 ⌘1~⌘9 是切号快捷键 ——
不拦的话在框里打数字会**真的切号**(改名输入框上踩过同一个坑)。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "codexbar" / "src" / "pages" / "SettingsPage.tsx"
HARNESS = ROOT / "codexbar" / "uishot" / "make_harness.py"


def src():
    return PAGE.read_text(encoding="utf-8")


class DefinedAtModuleScope(unittest.TestCase):
    def test_not_nested_inside_the_page_component(self):
        s = src()
        i_comp = s.index("function NumInput")
        i_page = s.index("export default function SettingsPage")
        self.assertLess(i_comp, i_page,
                        "NumInput 又回到页面组件里了 —— 每敲一个字符就重建,输入框会丢焦点")

    def test_takes_theme_as_a_prop(self):
        """搬到模块作用域后拿不到闭包里的 `t`,必须显式传 —— 漏传会静默用到 undefined 的色值。"""
        s = src()
        i = s.index("function NumInput")
        self.assertIn("t: Theme", s[i:i + 400], "NumInput 没有接收主题")


class TypingIsNotFoughtByClamping(unittest.TestCase):
    def test_uses_a_draft_state(self):
        s = src()
        i = s.index("function NumInput")
        body = s[i:s.index("\n}\n", i)]
        self.assertIn("draft", body, "没有草稿态 —— 边打边 clamp 会把 `25` 在第一位就钳成 `5`")
        # ★ 判据打在 onChange 上:它只能写草稿,不能直接回写
        m = re.search(r"onChange=\{e => setDraft\(e\.target\.value\)\}", body)
        self.assertIsNotNone(m, "输入框的 onChange 直接回写了值,而不是写草稿")

    def test_commits_on_blur_and_enter(self):
        s = src()
        i = s.index("function NumInput")
        body = s[i:s.index("\n}\n", i)]
        self.assertIn("onBlur", body, "失焦不提交 —— 打完的值会丢")
        self.assertIn('"Enter"', body, "回车不提交")

    def test_commit_clamps_into_range(self):
        s = src()
        i = s.index("const commit")
        body = s[i:i + 420]
        self.assertIn("Math.min(max", body)
        self.assertIn("Math.max(min", body)

    def test_illegal_input_is_discarded_not_written(self):
        """★ 空串/非数字必须**丢弃回落**,不能写进设置 —— `Number("") === 0` 会把阈值设成 0。"""
        s = src()
        i = s.index("const commit")
        body = s[i:i + 420]
        self.assertIn("Number.isFinite", body, "没有挡住非数字 —— `Number('') === 0` 会把阈值写成 0")
        self.assertRegex(body, r"if \(!raw\.trim\(\)[^\n]*\) return;",
                         "空输入没有直接返回")


class GlobalShortcutsAreBlocked(unittest.TestCase):
    def test_keydown_stops_propagation(self):
        """★★ 全局 ⌘1~⌘9 是切号快捷键。在阈值框里打 `2` 会**真的切到 2 号账号**。"""
        s = src()
        i = s.index("function NumInput")
        body = s[i:s.index("\n}\n", i)]
        j = body.index("onKeyDown")
        self.assertIn("stopPropagation", body[j:j + 200],
                      "输入框没拦键盘事件 —— 打数字会触发全局切号快捷键")


class HarnessCanReachIt(unittest.TestCase):
    def test_auto_switch_can_be_turned_on(self):
        """★ 阈值那一行**只在「额度低自动切号」开着时渲染**。没有这个开关,
        新加的输入框在 harness 里一个像素都验不到,而截图会正常渲染、探针报干净。"""
        h = HARNESS.read_text(encoding="utf-8")
        self.assertIn("autoSwitchEnabled: p.get('autoswitch') === 'on'", h,
                      "harness 打不开自动切号 —— 阈值输入框无法被验证")


if __name__ == "__main__":
    unittest.main()
