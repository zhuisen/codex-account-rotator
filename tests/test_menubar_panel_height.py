"""菜单栏两个 Tab 必须等高,且超出部分**滚动而不是裁切**(2026-09-06)。

## 来历

账号变多之后,账号 Tab 自然高 **731px**、今日 Tab **580px**,切 Tab 时弹窗会跳高一大截;
而 731 已经逼近旧上限 760 —— 再多一个号就顶死。用户:「菜单栏的账号太多,高度太高了,
要跟 AI 用量的高度一致」。

## 修法与两个坑

上限统一到 **580**（今日 Tab 的自然高度），账号列表内部滚动。过程中踩到两个:

① ★★ **只钳 `setSize` 是不够的。** 内容仍然 731 高、窗口 580,`.mb-root` 又是
   `overflow: hidden` ⇒ 直接**裁掉** 151px。裁切比太高更糟:下面的号看不见,
   而且**没有滚动条提示还有内容**。
② ★★ **flex 链必须一路打通。** `.mb-list` 的父节点是 `.mb-pane` 不是 `.mb-root`,
   所以只给 list 加 `flex:1` 没用 —— pane 自己不受约束、长到 656px,root 照样裁。
   实测当时 root `scrollHeight=827` vs `clientHeight=578`,而**没有任何容器在滚**。
   `min-height: 0` 每一层都不能省(flex 子项默认 `min-height:auto`,不给 0 就不会收缩)。

★ 这两个坑都**分不出来自"overflow 探针"**:裁切根本不算溢出,两种情况的 overflow 都是 0。
  所以专门加了 `scrollables` 探针量 `scrollHeight vs clientHeight`。

## 断言
① 两个 Tab 的最终 setSize 高度相等;
② 账号 Tab 里**确实有容器在滚**（不是被裁）;
③ `.mb-root` 自己不出现溢出（scrollHeight ≈ clientHeight）;
④ 高度上限只有**一个**真源（CSS 里不许再写死第二个数）。
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "codexbar" / "src" / "menubar.css"
TSX = ROOT / "codexbar" / "src" / "MenuBar.tsx"
BASE = "http://127.0.0.1:3304/harness-menubar.html?w=352&grok=ok"


def _strip_css_comments(src):
    """剥掉 CSS 注释。★ 不剥就是空守卫 —— 解释规则的注释里什么词都有。"""
    return re.sub(r"/\*.*?\*/", "", src, flags=re.S)


def probe(url):
    sys.path.insert(0, str(ROOT / "codexbar" / "uishot"))
    import sweep
    return sweep.probe(url, 500)


def final_height(d):
    hs = [json.loads(x)["value"]["Logical"]["height"] for x in (d.get("sizes") or [])]
    return hs[-1] if hs else None


class SingleSourceOfHeight(unittest.TestCase):
    """④ 静态闸:上限只有一个真源。这条不依赖 harness,CI 也能跑。"""

    def test_tsx_declares_the_limit(self):
        src = TSX.read_text(encoding="utf-8")
        m = re.search(r"const PANEL_H_MAX = (\d+);", src)
        self.assertIsNotNone(m, "找不到 PANEL_H_MAX")
        self.assertLessEqual(int(m.group(1)), 640,
                             "上限又被放大了 —— 账号一多弹窗会顶到屏幕外")

    def test_limit_is_injected_into_css_not_duplicated(self):
        """★ CSS 必须**读变量**,不能自己再写一个数。两处各写一个,改一处忘一处
        就会变回「窗口 580 而内容要 656」的裁切态。"""
        src = TSX.read_text(encoding="utf-8")
        self.assertIn("--mb-max-h", src, "上限没有注入 CSS 变量")
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("var(--mb-max-h", css, "CSS 没有消费那个变量")

    def test_flex_chain_is_complete(self):
        """★★ 坑②:`.mb-pane` 也必须在 flex 链上,否则 list 的 flex 是空转的。

        ⚠️ 第一版 `css.index(".mb-pane")` **命中的是我自己写的注释**
        (那段注释里就写着 "`.mb-pane` 而不是 `.mb-root`"),`flex:` 与 `min-height: 0`
        也都能在注释里找到 —— 删掉真声明,4 条静态断言仍然全绿(2026-09-06 评审实测)。
        现在先剥注释,再**定位真正的规则块**(`.mb-pane {`)。
        """
        css = _strip_css_comments(CSS.read_text(encoding="utf-8"))
        i = css.index(".mb-pane {")
        pane = css[i:css.index("}", i)]
        self.assertIn("flex:", pane, ".mb-pane 不在 flex 链上 —— list 的 flex:1 是空转")
        self.assertIn("min-height: 0", pane,
                      ".mb-pane 缺 min-height:0 —— flex 子项默认不收缩到内容以下")

    def test_today_pane_also_scrolls(self):
        """★★ 评审抓出的第 5 处:只给账号列表接了 flex 链,「今日」页没接 ——
        pane 收缩到 437px 而今日内容 474px,多出来的部分**压进底部操作栏**。
        重叠不算溢出,`scrollables` 是空的,连「root 不许溢出」也照常通过 —— 三个信号一起沉默。"""
        css = _strip_css_comments(CSS.read_text(encoding="utf-8"))
        i = css.index(".mb-today {")
        body = css[i:css.index("}", i)]
        self.assertIn("min-height: 0", body)
        self.assertIn("overflow-y: auto", body, "今日页不能滚 ⇒ 内容会压到底部按钮上")

    def test_height_is_fixed_not_content_driven(self):
        """★★ 评审抓出:只降上限不够,`setSize` 仍按当前页内容算 ⇒ 两页只是"恰好"相等。
        停掉一个平台后今日页就变 545px 而账号页仍顶上限。必须是固定值。"""
        src = TSX.read_text(encoding="utf-8")
        i = src.index("const apply = () => {")
        body = re.sub(r"//[^\n]*", "", src[i:src.index("if (Math.abs", i)])
        self.assertNotIn("scrollHeight", body,
                         "高度仍按内容算 —— 两页只会在夹具恰好相等时通过")
        self.assertIn("PANEL_H_MAX", body)

    def test_list_shrinks_instead_of_a_fixed_max_height(self):
        """★ 必须**先剥注释**再查。

        第一版直接对整段文本断言,结果匹配到了注释里那句解释旧值的
        `max-height: 560px` —— 「对着带注释的源码断言」是本仓记录过的空守卫形态,
        而且它是**假红**:代码明明是对的,闸却在拦解释这条规则的那句话。
        """
        css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
        i = css.index(".mb-list {")
        body = css[i:css.index("}", i)]
        self.assertIn("min-height: 0", body)
        self.assertIn("overflow-y: auto", body)
        self.assertNotRegex(body, r"max-height:\s*\d+px",
                            ".mb-list 又写死了 max-height —— 那是第二个真源")


class BothTabsRenderAtTheSameHeight(unittest.TestCase):
    """①②③ 行为闸。需要本机 harness 在跑(端口 3304);跑不到就跳过而不是假绿。"""

    @classmethod
    def setUpClass(cls):
        try:
            cls.acc = probe(BASE)
            cls.today = probe(BASE + "&tab=today")
        except Exception as e:                      # noqa: BLE001
            raise unittest.SkipTest("harness 不可达: %s" % e)
        if cls.acc.get("_fatal") or cls.today.get("_fatal"):
            raise unittest.SkipTest("harness 报错，跳过")

    def test_heights_match(self):
        a, t = final_height(self.acc), final_height(self.today)
        self.assertIsNotNone(a); self.assertIsNotNone(t)
        self.assertLessEqual(abs(a - t), 2,
                             "两个 Tab 高度不等(账号 %s vs 今日 %s) —— 切 Tab 会跳" % (a, t))

    def test_account_list_scrolls_rather_than_clips(self):
        """★★ 坑①:必须**有容器在滚**。没有就是被裁掉了 —— 而 overflow 探针对裁切是沉默的。"""
        sc = self.acc.get("scrollables") or []
        self.assertTrue(sc, "账号 Tab 里没有任何容器在滚 —— 超出的部分被裁掉了")
        self.assertTrue(any("mb-list" in str(x.get("sel")) for x in sc),
                        "滚的不是账号列表: %s" % [x.get("sel") for x in sc])

    def test_root_itself_does_not_overflow(self):
        """③ root 是 `overflow:hidden`,它一旦溢出就等于在裁。"""
        g = (self.acc.get("geom") or {}).get("mb-root") or {}
        if not g:
            self.skipTest("geom 探针不可用")
        self.assertLessEqual(g["scrollH"] - g["clientH"], 2,
                             "mb-root 溢出 %spx 且它是 overflow:hidden ⇒ 正在裁切内容"
                             % (g["scrollH"] - g["clientH"]))


if __name__ == "__main__":
    unittest.main()
