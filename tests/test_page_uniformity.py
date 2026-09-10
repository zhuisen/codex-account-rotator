"""页面统一性的闸（项目 `CLAUDE.md` §5c，用户 2026-09-09 拍板）。

## 为什么这条需要一道会红的闸

本仓的铁律之一：**一条只写在文档里的规则，迟早会被违反 —— 包括被写它的人违反。**
「平台详情」8 个平台共用一个 `PlatformPage`，读者在它们之间来回切；
每多一种只在某一页出现的版块，就多一次"这一页为什么不一样"的认知成本。

实际发生过的：agy 的详情页上挂着两块别的平台都没有的东西
（覆盖率横幅、`gemini-5h / gemini-weekly` 额度水位条），
用户第一反应是「为什么账号额度在这里显示？？」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
PLATFORM = (SRC / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8")


def _body(text):
    """剥掉注释再断言。

    ★ 本仓今天已经三次被"闸命中自己的说明文字"判红（`test_proxy_relay_upstream` /
      `test_relay_store` / `test_relay_route_copy`）。这一条的注释里正解释着
      "这里曾经有 AgyQuotaBars"，不剥注释必然假红。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


class PlatformDetailStaysUniform(unittest.TestCase):
    BODY = _body(PLATFORM)

    def test_no_platform_specific_block_is_rendered(self):
        """★★ 详情页不许出现 `pk === "<某平台>"` 这种**只给一个平台画东西**的分支。

        ⚠️ 这不是"禁止任何按平台分支" —— 取色、取价、取源标签都必须按平台。
        禁的是**渲染分支**：让某一页多出/少掉一整块内容。
        """
        hits = re.findall(r'pk\s*===\s*"(\w[\w.-]*)"\s*&&', self.BODY)
        self.assertEqual(hits, [],
                         f"★ 详情页给 {hits} 单独画了版块 —— 破坏统一性，见 CLAUDE.md §5c")

    def test_the_deleted_blocks_have_not_come_back(self):
        """★ 已删的两块（用户明确说"删掉"）不许悄悄回来。"""
        for gone, why in (("AgyQuotaBars", "账号额度不属于用量页，家在总览的额度卡"),
                          ("CoverageBanner", "覆盖率升到 ~95% 后这条横幅退化成噪音")):
            self.assertNotIn(gone, self.BODY, f"★ `{gone}` 回来了 —— {why}")

    def test_deleting_a_block_also_deletes_its_component(self):
        """★ 删版块要**连组件本体一起删**，不留骨架 ——
        留一份没人渲染的组件，下一个人会以为它还在页面上。"""
        for gone in ("function AgyQuotaBars", "function CoverageBanner"):
            self.assertNotIn(gone, PLATFORM, f"★ `{gone}` 的骨架还留着")


class CollapsingUsesCssNotConditionalRendering(unittest.TestCase):
    """★★ 悬浮折叠必须用 CSS 控制可见性。

    条件渲染会让内容**离开 DOM**，而本仓的行为闸都在 `--dump-dom` 的静态 DOM 上断言 ——
    一改就全部静默失效（"测试还在、但什么也没验"）。
    """

    CSS = (SRC / "App.css").read_text(encoding="utf-8")

    def test_the_hover_classes_exist(self):
        self.assertIn(".cb-hoverwrap", self.CSS)
        self.assertIn(".cb-hoverpop", self.CSS)
        self.assertIn(".cb-hoverwrap:hover .cb-hoverpop", self.CSS,
                      "没有 hover 规则 —— 那块内容永远看不见")

    def test_the_route_split_content_stays_in_the_dom(self):
        """★ 折叠后 `data-route-footnote` 仍要在 DOM 里（只是不可见）。
        改成 `{hover && <...>}` 会让既有的行为闸静默变空。"""
        self.assertIn("cb-hoverpop", PLATFORM, "路由分账没走 CSS 折叠")
        self.assertIn("data-route-footnote", PLATFORM)
        # ★★ 判据要认**任何**把浮层包起来的条件表达式，不只是 `hover &&`。
        #    第一版只断言 `"hover && " not in ...`，而变异 `{false && <div className=
        #    "cb-hoverpop"` **照样绿** —— 一个只挡得住自己想象中那一种写法的守卫。
        body = _body(PLATFORM)
        for bad in ("&& <div className=\"cb-hoverpop", "? <div className=\"cb-hoverpop",
                    "&& (<div className=\"cb-hoverpop"):
            self.assertNotIn(bad, body,
                             "★ 浮层被条件表达式包住了 —— 内容会离开 DOM，行为闸随之失效")
        # 反向:浮层前面那个字符必须是换行/空白，即它是**无条件**渲染的兄弟节点。
        i = body.index('className="cb-hoverpop"')
        head = body[max(0, i - 200):i]
        self.assertNotIn("&&", head.rsplit(">", 1)[-1],
                         "★ 浮层与前一个标签之间夹了条件表达式")

    def test_the_popover_does_not_swallow_clicks(self):
        """★ 浮层必须 `pointer-events: none`（本仓 UI 规范）——
        否则它会挡住底下的东西，而"点不动"最难联想到浮层。"""
        m = re.search(r"\.cb-hoverpop\s*\{[^}]*\}", self.CSS, re.S)
        self.assertIsNotNone(m)
        self.assertIn("pointer-events: none", m.group(0))


if __name__ == "__main__":
    unittest.main()
