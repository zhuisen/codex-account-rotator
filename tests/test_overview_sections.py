"""总览按**供应商分档**（2026-09-13，用户给了样式：`● Codex 6 │ ● Google 1 │ +`）。

## 分档不是筛选，是因为三家的账号语义根本不同

    Codex   池 · 经本地代理**逐请求**换号 · 5h/周双窗口 · 探针**要花钱**
    Google  池 · **启动前**换凭证（agy 只在启动时读）· 额度是随时可读的比例
    xAI     单号只读 · 周窗口

## ★★★ 这一组闸真正在守的东西

分档之后，页面上原有的一切都默认变成了「**当前这一档**的信息」。而总览上大部分东西
其实是 **codex 池专属**的：Hero（当值号）、`7 nodes · 6 活` 摘要、`6/7 新鲜` 覆盖度、
失效账号折叠区、以及那一排动作按钮。

它们挂在别家的档上时**看起来毫无异样**，但说的是另一家的事。其中最危险的是
**「探针 全池」—— 它是花钱的**：用户看着 agy 的卡按下去，扣的是 codex 的额度。
所以下面逐个钉，而不是只钉「有没有分档」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
TABS = (ROOT / "codexbar" / "src" / "components" / "ProviderTabs.tsx").read_text(encoding="utf-8")


class TheOverviewIsTabbedByProvider(unittest.TestCase):

    KEYS = re.findall(r'key: "(codex|google|xai)"', APP)
    NOTES = re.findall(r'note: "([^"]+)"', APP)

    def test_three_tabs_in_pool_size_order(self):
        self.assertEqual(self.KEYS, ["codex", "google", "xai"],
                         "★ 档位或顺序不对（顺序 = 账号数量降序，主力池排最前）")

    def test_each_tab_explains_its_own_rotation(self):
        """★★ 说明必须**互不相同**。三段一样等于没分档 —— 而"看起来分了"比没分更糟：
        它让人以为差异已经被解释过了。"""
        self.assertEqual(len(self.NOTES), 3)
        self.assertEqual(len(set(self.NOTES)), 3, "★★ 有两档的说明一字不差")

    def test_the_notes_name_the_actual_mechanism(self):
        """★ 判据打在**机制词**上。写成「Google 的账号」这种同义反复也能过长度检查，
        但它什么都没说。"""
        joined = " ".join(self.NOTES)
        for word in ("逐请求", "启动前", "只读"):
            with self.subTest(word=word):
                self.assertIn(word, joined, f"★ 没有一档提到「{word}」这个关键差异")

    def test_the_count_is_what_gets_rendered(self):
        """★★ 计数是「网格里画出来几张」，不是「池里有几个」。死号在下面的折叠区里，
        算进来就会出现「Codex 7」配着 6 张卡 —— 而那个差额没有任何地方解释。"""
        self.assertIn('count: accounts.filter((a) => a.status !== "dead").length', APP,
                      "★★ Codex 的计数把死号也算进去了")

    def test_the_choice_is_remembered(self):
        """★ 这一档是"我在管哪一家账号"，不是一次性筛选 —— 切到别的页再回来不该跳回第一档。"""
        self.assertIn('localStorage.setItem("codexbar_provider"', APP)

    def test_the_identity_dot_survives_selection(self):
        """★ 选中态是青底，识别色圆点是「这一档是谁」—— 两件事。
        选中时去掉圆点，就只能靠文字猜它是哪一家。"""
        i = TABS.index("items.map((p)")
        seg = TABS[i:i + 1400]
        self.assertIn("background: p.color", seg, "★ 选中态丢了识别色圆点")


class CodexOnlyThingsStayOnTheCodexTab(unittest.TestCase):
    """★★★ 分档之后，页面上的一切默认都在说「当前这一档」。

    但总览上大半是 codex 池专属的，挂在别家档上**看起来毫无异样**却说的是另一家的事。

    ⚠️ 2026-09-13：`7 nodes · 6 活` 那行摘要已按用户要求整行删掉，所以它不在下面这张表里 ——
      留着一条指向不存在的东西的断言，比没有断言更糟：它让人以为那件事还有人守着。
    """

    #: 每条：(说明, 必须被 `provider === "codex"` 包住的那段代码的锚点)
    GUARDED = [
        ("Hero（当值号）", "{provider === \"codex\" && (() => {"),
        ("失效账号折叠区", "{provider === \"codex\" && dead.length > 0 && ("),
    ]

    def test_each_codex_only_block_is_guarded(self):
        for name, anchor in self.GUARDED:
            with self.subTest(block=name):
                self.assertIn(anchor, APP, f"★★ {name} 没有收进 Codex 档 —— 它在说另一家的事")

    def test_the_billed_probe_button_cannot_appear_on_another_tab(self):
        """★★★ 最危险的一条：「探针 全池」**是花钱的**。挂在 Google 档上，
        用户看着 agy 的卡按下去，扣的是 codex 的额度。

        判据是**那一排按钮整体**被 `provider === "codex"` 包住，
        而不是"探针那一个按钮有没有条件" —— 整排都是 codex 动作。
        """
        i = APP.index('run("refresh-all"')
        head = APP[max(0, i - 900):i]
        self.assertIn('{provider === "codex" && (', head,
                      "★★★ codex 的动作条没有按档收起 —— 花钱的探针会出现在别家档上")
        # 正面验一次这一排里确实有那个花钱的按钮，否则上面的锚点挪走了也发现不了。
        self.assertIn("探针", APP[i:i + 2200], "★ 探针按钮不在这一排里了 —— 判据失准，先修闸")

    def test_the_freshness_line_is_guarded(self):
        """★ `6/7 新鲜` 数的是 codex 池的快照覆盖度。

        ⚠️ 锚点不能是「新鲜」两个字 —— 上面几百行的注释里就有「新鲜度 10min」这类说法，
        `index()` 命中的是那些，闸恒红。取渲染那一行独有的模板串。"""
        i = APP.index("`最近刷新 ${fmtAgo(lastRefreshAt)}")
        self.assertIn('{provider === "codex" && (', APP[max(0, i - 1500):i],
                      "★ 新鲜度行没有按档收起")


class TheExtraCardsStillStayOutOfThePool(unittest.TestCase):
    """★★★ 分档**不能**顺手把 grok/agy 并进 `alive`。

    那个数组同时驱动 ⌘1~⌘9 切号、计数徽章、探针全池的号数、自动切号 ——
    混进去之后 ⌘4 会"切"到一个切不了的东西上，**而且不报错**。
    """

    def test_neither_card_is_rendered_from_alive(self):
        i = APP.index("{alive.map((a) => {")
        j = APP.index('{provider === "google"', i)
        seg = APP[i:j]
        for tag in ("<GrokCard", "<AgyCard"):
            with self.subTest(card=tag):
                self.assertNotIn(tag, seg,
                                 f"★★★ {tag} 跑进了 alive 那张网格 —— ⌘N 会切到切不了的东西上")

    def test_every_tab_owns_its_grid(self):
        """★ 每档各自一张 `data-cards-grid`。uishot 的对齐闸按排比较 ——
        分档之后它只在同一档内比，不会拿 grok 卡去跟 codex 卡比高度。
        ⚠️ 数的是 `<div data-cards-grid` 这个**属性用法**，不是这个词：
           上面有注释正解释着这个属性是干什么的。"""
        self.assertEqual(APP.count("<div data-cards-grid"), 3)


if __name__ == "__main__":
    unittest.main()
