"""总览按**供应商**分区（2026-09-13，用户：「总览版块要划分 openai 和 gemini 等」）。

## 分区不是装饰

三家的账号语义**根本不同**，摆在同一张网格里，读者会拿同一套直觉去理解它们：

    OpenAI(codex)  池 · 经本地代理**逐请求**换号 · 5h/周双窗口 · 探针要花钱
    Google(agy)    池 · **启动前**换凭证（agy 只在启动时读凭证）· 额度是随时可读的比例
    xAI(grok)      单号只读 · 周窗口

「为什么 codex 能热切而 agy 不能」这种问题，只有把它们摆在各自的标题下才不会一直被问。
所以下面既钉**有没有分区**，也钉**说明文字互不相同** —— 三段一样的说明等于没分。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
SEC = (ROOT / "codexbar" / "src" / "components" / "ProviderSection.tsx").read_text(encoding="utf-8")


class TheOverviewIsSplitByProvider(unittest.TestCase):

    TITLES = re.findall(r'<ProviderSection[^>]*?title="([^"]+)"', APP, re.S)
    NOTES = re.findall(r'note="([^"]+)"', APP)

    def test_three_provider_sections(self):
        self.assertEqual(self.TITLES, ["OpenAI", "Google", "xAI"],
                         "★ 分区标题或顺序不对（顺序 = 账号数量降序，主力池排最前）")

    def test_each_section_explains_its_own_rotation(self):
        """★★ 说明文字必须**互不相同**。三段一样的说明等于没分区 ——
        而"看起来分了"比没分更糟：它让人以为差异已经被解释过了。"""
        self.assertEqual(len(self.NOTES), 3)
        self.assertEqual(len(set(self.NOTES)), 3, "★★ 有两区的说明一字不差")

    def test_the_notes_name_the_actual_mechanism(self):
        """★ 判据打在**机制词**上，不是"有没有字"。写成「Google 的账号」这种
        同义反复也能过长度检查，但它什么都没说。"""
        joined = " ".join(self.NOTES)
        for word in ("逐请求", "启动前", "只读"):
            with self.subTest(word=word):
                self.assertIn(word, joined, f"★ 没有一段说明提到「{word}」这个关键差异")

    def test_every_section_owns_a_grid(self):
        """★ 每区各自一张 `data-cards-grid`。uishot 的对齐闸是**按排比较**的 ——
        分区之后每张网格就是自己的比较集，不会拿 grok 卡去跟 codex 卡比高度。"""
        # ⚠️ 数的是 `<div data-cards-grid` 这个**属性用法**，不是这个词 ——
        #    上面有一段注释正解释着这个属性是干什么的，`count("data-cards-grid")` 会数成 4。
        #    本轮第三次踩到同一个形状：这些文件的注释里就写着闸要找的那些词。
        self.assertEqual(APP.count("<div data-cards-grid"), 3,
                         "★ 网格数与分区数对不上 —— 对齐闸会跨区比较")

    def test_the_note_shares_the_title_row(self):
        """★ 说明与标题**同排**。总览是"一屏看全"的页面，三区各多一行说明就是多 ~60px，
        而那 60px 会把卡片挤到折叠线以下。"""
        i = SEC.index("{note}")
        self.assertIn('marginLeft: "auto"', SEC[max(0, i - 400):i],
                      "★ 说明另起了一行 —— 总览会多出约 60px")


class TheExtraCardsStillStayOutOfThePool(unittest.TestCase):
    """★★★ 分区**不能**顺手把 grok/agy 并进 `alive`。

    那个数组同时驱动 ⌘1~⌘9 切号、计数徽章、探针全池的号数、自动切号 ——
    混进去之后 ⌘4 会"切"到一个切不了的东西上，**而且不报错**。
    （既有闸在 `test_grok_not_in_pool_ui.py` / `test_agy_not_in_pool_ui.py`，
    这里只钉「分区之后仍然如此」这一点。）
    """

    def test_neither_card_is_rendered_from_alive(self):
        i = APP.index("{alive.map((a) => {")
        j = APP.index("</ProviderSection>", i)
        seg = APP[i:j]
        for tag in ("<GrokCard", "<AgyCard"):
            with self.subTest(card=tag):
                self.assertNotIn(tag, seg,
                                 f"★★★ {tag} 跑进了 alive 那张网格 —— ⌘N 会切到切不了的东西上")


if __name__ == "__main__":
    unittest.main()
