"""窄窗下**不许断字**的闸。

起因是用户 2026-08-24 的截图:窗口一窄,总览头部就散架 ——
「总览」被劈成「总 / 览」、「刷新全池」→「刷新全 / 池」、「检查 token」→「检查 / token」、
「探针 全池」→「探针 全 / 池」。根因是 `GhostButton` / `ProbeButton` 既没有 `whiteSpace: nowrap`
也没有 `flexShrink: 0`,flex 在空间不够时**压缩按钮宽度**,文字只能在按钮内部折行。

修的时候在 760px 又发现**同一个病根的第二处**:hero 那行把日期劈成
「订阅至 2026- / 09-08」「至 2026- / 09-21」。**断开的日期比断开的按钮严重得多** ——
按钮只是难看,日期会被读成另一个日期。所以这条闸同时守两处,不只补被点名的那一处。

正确的形状是**两层**,缺一层都不成立:
  ① 原子(按钮、日期段、标题)`whiteSpace: nowrap` —— 永远不在内部断开;
  ② 容器 `flexWrap: "wrap"` —— 空间不够时让**整个原子**换行。
只做 ① 会横向溢出,只做 ② 原子照样被压扁。

⚠️ 这是**形状闸**,拦得住诚实改动(有人顺手删掉 nowrap),拦不住刻意绕过
(改用别的属性名、把样式挪进 CSS 文件)。真正的判据是像素 —— 每次改这块布局仍要按
CLAUDE.md §4 跑一遍 `?nav=home` 的窄宽度截图。已实测干净的下限:**700px**。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
APP = SRC / "App.tsx"
GHOST = SRC / "components" / "GhostButton.tsx"
PROBE = SRC / "components" / "ProbeButton.tsx"


def strip_comments(src: str) -> str:
    """注释里正解释着这条规则(还引用了断字后的样子),朴素匹配必被它染红。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


class ButtonsNeverBreakMidWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ghost = strip_comments(GHOST.read_text(encoding="utf-8"))
        cls.probe = strip_comments(PROBE.read_text(encoding="utf-8"))
        cls.app = strip_comments(APP.read_text(encoding="utf-8"))

    def test_anchors_exist(self):
        """★ 先证明被测文件还是那个文件 —— 组件改名后断言会静默打空。"""
        for name, src in (("GhostButton", self.ghost), ("ProbeButton", self.probe)):
            with self.subTest(f=name):
                self.assertIn("inline-flex", src, "{}:不再是 inline-flex 按钮?".format(name))
        self.assertIn("总览", self.app)

    # ---- ① 原子不断字 --------------------------------------------------------

    @staticmethod
    def _button_style_block(src: str) -> str:
        """截出**按钮自己**的样式块(从 `display: "inline-flex"` 起 400 字符)。

        ★ 不能对整个文件断言:`GhostButton.tsx` 里 `flexShrink: 0` 出现两次,另一处是
        **加载转圈的 spinner**。对全文断言时,把按钮的那条删掉照样绿 —— 变异测试当场抓到的空守卫。
        与全局那条「同前缀 ≠ 同标识」同族:**同文件里同名属性 ≠ 同一个元素**。
        """
        i = src.index('display: "inline-flex"')
        return src[i:i + 400]

    def test_shared_buttons_declare_nowrap_and_no_shrink(self):
        for name, src in (("GhostButton", self.ghost), ("ProbeButton", self.probe)):
            block = self._button_style_block(src)
            with self.subTest(f=name):
                self.assertRegex(block, r'whiteSpace:\s*"nowrap"',
                                 "{}:按钮样式块里没有 nowrap —— 窄窗下文字会在按钮内部折行".format(name))
                self.assertRegex(block, r"flexShrink:\s*0",
                                 "{}:按钮样式块里没有 flexShrink:0 —— flex 会压缩它的宽度".format(name))

    def test_page_title_never_breaks(self):
        """「总览」被劈成「总 / 览」是用户报的第一个症状。"""
        m = re.search(r"<span style=\{\{[^}]*fontSize:\s*20[^}]*\}\}>总览</span>", self.app, re.S)
        self.assertIsNotNone(m, "找不到总览标题 —— 断言可能打空了")
        self.assertIn("nowrap", m.group(0), "总览标题没有 nowrap")

    def test_hero_date_segments_never_break(self):
        """★ 断开的日期会被读成另一个日期 —— 比断开的按钮严重得多。"""
        m = re.search(r"<span[^>]*>订阅至", self.app)
        self.assertIsNotNone(m, "找不到「订阅至」那段 —— 断言可能打空了")
        self.assertIn("nowrap", m.group(0),
                      "「订阅至 <日期>」没有 nowrap,窄窗会劈成「2026- / 09-08」")
        m2 = re.search(r"<span[^>]*>\{i > 0 &&", self.app)
        self.assertIsNotNone(m2, "找不到窗口额度那段 —— 断言可能打空了")
        self.assertIn("nowrap", m2.group(0), "「周 96% ↻6d13h」那段没有 nowrap")

    # ---- ② 容器允许整块换行 ---------------------------------------------------

    def test_header_and_hero_containers_allow_wrapping(self):
        """只做 nowrap 不做 flexWrap 会从"断字"变成"横向溢出" —— 两层缺一不可。"""
        needles = (
            (r'justifyContent:\s*"space-between",\s*\n?\s*marginBottom:\s*12,[^}]*flexWrap:\s*"wrap"',
             "总览头部容器没有 flexWrap"),
            (r'gap:\s*7,\s*alignItems:\s*"center",\s*\n?\s*flexWrap:\s*"wrap"',
             "按钮行没有 flexWrap"),
            (r'gap:\s*13,\s*marginTop:\s*8[^}]*flexWrap:\s*"wrap"',
             "hero 元信息行没有 flexWrap"),
        )
        for pat, msg in needles:
            with self.subTest(msg=msg):
                self.assertRegex(self.app, pat, msg)

    def test_narrow_threshold_and_min_width_agree(self):
        """★ 自动折叠阈值 与 窗口 `minWidth` 是**一对**,只改一个就会破。

        ★★ 2026-08-26 两处一起改了,**下限随字号走**:用户选了 D 档字号(整体 +3),
        实测卡片宽 **≥240px 才站得住**、≤235px 就页脚内折行 ⇒ 对应窗口下限整体抬高:
          · 侧栏展开 ≥960 干净(卡宽 240)、940 起破;
          · 侧栏折叠 ≥840 干净(卡宽 241)、820 起破。差 124px = 侧栏宽度差(176-52)。
        取 `NARROW_W = 960`、`minWidth = 860`(比折叠下限留 20px 余量)。

        ★ **方向**:`NARROW_W` 是"低于它就折叠"。所以窗口 ≥ `NARROW_W` 时侧栏是**开**的,
          必须 `NARROW_W >= 展开态下限` —— 否则在 [展开下限, NARROW_W) 这段里侧栏还开着、
          卡片已经挤破了。原来这里写的是 `<=`(方向反的),因为当时两个数恰好都是 860,
          错了也一直是绿的 —— **相等会让方向错误隐形**,所以现在两个数不同了才暴露。
        单独调其中一个的症状:**窗口能被拖到某个宽度,那里侧栏还没折叠、卡片已经溢出** ——
        而且不报错,只是右边少一块。
        """
        import json
        m = re.search(r"const NARROW_W = (\d+);", self.app)
        self.assertIsNotNone(m, "找不到 NARROW_W —— 自动折叠可能被删了")
        narrow = int(m.group(1))

        conf = json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json")
                          .read_text(encoding="utf-8"))
        win = conf["app"]["windows"][0]
        self.assertIn("minWidth", win,
                      "窗口没有 minWidth —— 能被拖到任意窄,就没有可以宣称干净的宽度")
        self.assertGreaterEqual(narrow, 960,
                                "NARROW_W({}) 低于展开态实测下限 960 —— 那段宽度里侧栏还开着,"
                                "而卡片已经挤破了".format(narrow))
        self.assertGreaterEqual(win["minWidth"], 840,
                                "minWidth({}) 低于折叠态实测下限 840".format(win["minWidth"]))
        self.assertLess(win["minWidth"], narrow,
                        "minWidth 应当**低于**折叠阈值,否则自动折叠永远不会触发")

    def test_auto_collapse_does_not_persist(self):
        """★ 自动折叠是**显示层覆盖**,绝不能写进偏好。

        写了的话,用户把窗口拖窄一次,「侧栏默认展开」这条设置就被永久抹掉 ——
        拿一次布局意外去改一条长期偏好。判据:那个 effect 里不得出现 `patchSettings`。
        """
        # 不用正则:这段要匹配的字面量里同时有 `\d`、`(`、`"`,写成正则会在转义上翻车
        # (第一版就翻了两次)。切片取 effect 的作用域即可,判据一样硬。
        i = self.app.find("const NARROW_W")
        self.assertNotEqual(i, -1, "找不到自动折叠的 effect —— 断言可能打空了")
        j = self.app.find('removeEventListener("resize"', i)
        self.assertNotEqual(j, -1, "自动折叠的 effect 没有解绑 resize 监听")
        block = self.app[i:j]
        self.assertNotIn("patchSettings", block,
                         "自动折叠写了偏好 —— 用户拖窄一次,「默认展开」就没了")
        self.assertIn("getSettings().navOpen", block,
                      "变宽时没有从偏好读回来,侧栏会一直停在折叠态")

    def test_scrollbars_are_themed_and_not_a_dead_rule(self):
        """★ 主窗滚动条必须有样式,且浅色主题那条**不能是死规则**。

        用户 2026-08-24 报「右侧有一条黑边」:主窗从来没给滚动条做过样式
        (`::-webkit-scrollbar` 之前只在 menubar.css 里给菜单栏列表做了一份),
        系统默认滚动条在深色底上就是一条黑带,而且**占布局宽度**,把图表右缘挤到底下。

        ⚠️ **harness 看不到这个** —— headless Chrome 默认覆盖式滚动条(不占宽),
        扫描全程报"干净"。这是继 `zoom` 之后第二次「验证环境 ≠ 运行环境」。
        所以只能用源码闸兜住。

        ★ 第二条断言防的是**死规则**:`.cb-light ::-webkit-scrollbar-thumb` 依赖根节点
        带 `cb-light`,而写完那条 CSS 时根节点上**根本没有这个 class** —— 规则永远不生效,
        浅色主题下白色拇指在白底上等于隐形,而且没有任何东西会报错。
        """
        css = (SRC / "App.css").read_text(encoding="utf-8")
        # ★ 断言的是**那条定宽规则真的在**,不是"这个词出现过"。
        #   第一版用 `assertIn("::-webkit-scrollbar", css)`,而 `-track`/`-thumb` 里都含这个子串
        #   ⇒ 把定宽那条删掉照样绿。**子串存在 ≠ 规则存在**(今天第三次同款空守卫)。
        self.assertRegex(css, r"::-webkit-scrollbar\s*\{[^}]*width",
                         "主窗没有给滚动条定宽 —— 会用系统默认,深色底上是一条黑带且占布局宽")
        self.assertRegex(css, r"::-webkit-scrollbar-track\s*\{[^}]*transparent",
                         "滚动条轨道没有置透明 —— 那条轨道就是用户看到的「黑边」")
        # ★ 必须**两个主题各有一条**。只写 `assertRegex(...thumb...)` 时,把深色那条删掉
        #   仍会被 `.cb-light` 那条匹配上 ⇒ 假绿(变异测试第三次抓到同款)。
        thumbs = re.findall(r"(^|\n)(\.cb-light\s+)?::-webkit-scrollbar-thumb\s*\{[^}]*background",
                            css)
        dark = [t for t in thumbs if not t[1]]
        light = [t for t in thumbs if t[1]]
        self.assertTrue(dark, "深色主题的滚动条拇指没有配色")
        self.assertTrue(light, "浅色主题的滚动条拇指没有配色 —— 白拇指在白底上等于隐形")
        if ".cb-light ::-webkit-scrollbar" in css:
            self.assertIn('className={theme === "light" ? "cb-light" : undefined}', self.app,
                          "写了 .cb-light 的滚动条规则,但根节点没有这个 class —— 死规则")

    def test_grid_columns_can_actually_shrink(self):
        """★★ CSS Grid 里裸 `1fr` = `minmax(auto, 1fr)`,最小值是 **min-content 不是 0**。

        后果:列**压不下去**,卡片内部那些 `minWidth:0` + 省略号**根本没机会生效**,
        只能整个网格溢出。2026-08-25 实测暴露 —— 差值角标从 `-8%` 变成 `-22%`(宽一个字符),
        860px 下网格自然宽 659 / 可用 644,右侧被裁。

        ⚠️ **真教训不是"下限要重新量"** —— 是**下限本来就不该随内容宽度浮动**。
        用 `minmax(0, 1fr)` 之后列能缩、省略号接手,布局不再受数据摆布。
        """
        self.assertNotRegex(self.app, r'gridTemplateColumns:\s*"1fr 1fr 1fr"',
                            "九宫格用了裸 1fr —— 列压不下去,内容一变宽就整体溢出")
        self.assertRegex(self.app, r"gridTemplateColumns:[^\n]*minmax\(0",
                         "九宫格没有用 minmax(0, ...) —— 列的最小值仍是 min-content")

    def test_account_name_can_never_vanish(self):
        """★★ 只给 `minWidth: 0` 会让 flex 把名字压到 **0px 直接消失**。

        2026-08-25 实测:Pro1 那行徽章最多(PRO+活+USE+当前),860px 下自然宽 122 / 可用 114,
        flex 就把唯一可缩的名字压没了 —— **认不出这是哪个号,比裁掉半个日期严重得多**。
        所以名字要有**下限**(截成 `Pro…` 也还认得出),整行允许换行让徽章掉到第二行。
        """
        # ★ 名字那个 span 在 **AccountCard.tsx**,不在 App.tsx。
        #   第一版对着 self.app 断言 ⇒ 测试恒红,而恒红的测试**任何变异都会"变红"**,
        #   变异测试的绿灯全是假的(今天第二次踩:先证明基线是绿的,再做变异)。
        card = strip_comments((SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8"))
        # ★ 锚点**不要挂在字号数值上**。原来写死 `fontSize: 13.5`,2026-08-26 把字号提取成
        #   `CARD_TYPE`(用户选了 D 档)后这条立刻打空 —— 幸好有下面那句"断言可能打空了"接住,
        #   否则它会静默变成"永远通过"。改成认**被测的那个属性本身**(渲染 `{a.node}` 的 span)。
        m = re.search(r"<span style=\{\{[^}]*\}\}>\{a\.node\}", card, re.S)
        self.assertIsNotNone(m, "找不到账号名那个 span —— 断言可能打空了")
        self.assertNotRegex(m.group(0), r"minWidth:\s*0\b",
                            "账号名 minWidth 是 0 —— flex 会把它压到消失")
        self.assertRegex(m.group(0), r"minWidth:\s*[1-9]\d",
                         "账号名没有宽度下限")

    def test_summary_yields_space_first(self):
        """窄窗下该让位的是那行摘要(下面每张卡都写着状态),不是按钮。"""
        m = re.search(r"\{summary\}", self.app)
        self.assertIsNotNone(m, "找不到 summary —— 断言可能打空了")
        block = self.app[max(0, m.start() - 400):m.start()]
        self.assertIn("textOverflow", block, "summary 没有省略号,不会优雅地让位")
        self.assertIn("minWidth: 0", block, "summary 没有 minWidth:0,flex 不会让它先缩")


class WideTableMinWidthIsDerivedNotMeasured(unittest.TestCase):
    """★★ 宽数据表的 `minWidth` 必须**由列宽算出来**，不许写一个实测常数。

    起因（2026-08-26，一轮里踩了两次同一类）：
      · `test_narrow_window_nowrap` 有条断言锚在字号字面量 `13.5` 上，字号提取成常量后当场打空；
      · `PlatformPage` 的 `TABLE_MIN = 700` 注释写着「900px 实测自然宽 698」——
        用户要求放大模型表字号、列宽全部重算后，那个 700 **立刻失真**。

    失真的症状**不是报错**：表照常渲染，只是在某个宽度下最右边一列被悄悄裁掉，
    而裁掉的正是「费用/百万」（这张表里唯一回答"钱花在哪个型号上"的列）。
    横向滚动条也不会出现 —— `minWidth` 太小时行会被约束成可用宽，内部继续溢出。

    ★ 所以判据是**结构性的**：`TABLE_MIN` 必须是一个由 `TABLE_TYPE` 各列宽相加的表达式。
      这样字号一改、列宽一改，下限自动跟上，没有"忘了同步"这一步可漏。
    """

    @classmethod
    def setUpClass(cls):
        cls.code = strip_comments((SRC / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8"))
        cls.theme = strip_comments((SRC / "theme.ts").read_text(encoding="utf-8"))

    def test_anchor_exists(self):
        self.assertIn("TABLE_MIN", self.code, "TABLE_MIN 不见了 —— 断言可能打空了")
        self.assertIn("TABLE_TYPE", self.theme, "theme 里没有 TABLE_TYPE —— 断言可能打空了")

    def test_table_min_is_not_a_hardcoded_number(self):
        m = re.search(r"const TABLE_MIN\s*=\s*([^;]+);", self.code, re.S)
        self.assertIsNotNone(m, "找不到 TABLE_MIN 的定义")
        expr = m.group(1)
        self.assertNotRegex(expr.strip(), r"^\s*\d+\s*$",
                            "TABLE_MIN 又被写成一个常数了 —— 字号/列宽一改它就失真，"
                            "而症状是最右边一列被悄悄裁掉，不报错")
        self.assertIn("TZ.", expr, "TABLE_MIN 没有从列宽标尺推导")

    def test_grid_columns_come_from_the_scale(self):
        """列宽也不许散落成字面量 —— 那样 TABLE_MIN 推导得再对也白搭。"""
        m = re.search(r"gridTemplateColumns:\s*`([^`]+)`", self.code)
        self.assertIsNotNone(m, "找不到模型表的列模板")
        tpl = m.group(1)
        self.assertGreaterEqual(tpl.count("TZ."), 8,
                                "模型表的列宽还有写死的字面量:{}".format(tpl))

    def test_table_font_sizes_come_from_the_scale(self):
        """★ 字号与列宽必须同源。只放大字号不改列宽 = 数字串位。"""
        for token in ("TZ.body", "TZ.colHead", "TZ.groupHead"):
            self.assertIn(token, self.code, "模型表的字号没有走 {}".format(token))


if __name__ == "__main__":
    unittest.main()
