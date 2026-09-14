"""菜单栏 v4 的**平台 logo 芯片行**（交接稿 `菜单栏v4-交接说明.md`，1:1 复刻）。

v4 把 v3 那条闲置的「可用账号」标题行换成了芯片行：每档一个 logo + 账号数，
列表、主 Tab 计数、右侧平台名、底部操作栏全部跟着它变。

## ★★★ 这一组闸真正在守的东西

分档之后，**底部那三个按钮说的是哪一家**成了一个会花钱的问题：

    「探针」跑的是 `codex-rotate probe --all` —— 它扣的是 **codex** 的额度。
    挂在 Gemini / Grok 档上 = 用户看着那一档的卡按下去、花的是另一家的钱。

同族的还有「刷新全池」：写死成 codex 的话，站在 Gemini 档按下去刷的是另一家，
而 toast 还说「已刷新全池」—— 按钮说的和做的不是一件事。

⚠️ **与稿的一处刻意偏离**：稿 §5 把 Grok 也算进「刷新全池｜检查 token｜探针」那一组，
   那假设 grok 有自己的账号池与探针。本机事实是 grok **单号只读**、探针属于 codex，
   所以 Grok 档也不给这两个按钮。稿与实测事实冲突时以事实为准（本仓既有纪律）。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
MB = SRC / "MenuBar.tsx"
CHIPS = SRC / "components" / "PlatformChips.tsx"
PLAT = SRC / "platforms.ts"
CSS = SRC / "menubar.css"


def code(p):
    """剥注释 —— 本仓注释密度极高，闸撞上自己的说明文字已是惯犯（空守卫形态⑫）。"""
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


class TheChipRowReplacedTheIdleTitleRow(unittest.TestCase):

    def test_the_old_title_row_is_gone(self):
        """★ 删版块要连组件本体一起删（§5c）。留一个没人渲染的 `mb-list-header`，
        下一个人会以为它还在页面上。"""
        self.assertNotIn("mb-list-header", code(MB), "★ v3 的「可用账号」标题行还在")
        self.assertNotIn(".mb-list-header", CSS.read_text(encoding="utf-8"),
                         "★ 样式还留着 —— 骨架没清干净")

    def test_the_chip_row_is_rendered(self):
        self.assertIn("<PlatformChips", code(MB), "★★ 芯片行没渲染")

    def test_one_mask_image_covers_both_states(self):
        """★★ 稿 §2：同一张白 glyph + 透明底的蒙版图，靠 `mask-image` 上色覆盖选中/未选中。
        备两套彩色图的话，下次调品牌色会漏掉其中一套，而那**不会报任何错**。"""
        c = code(CHIPS)
        self.assertIn("WebkitMaskImage", c, "★★ 没用蒙版 —— 多半是备了两套图")
        self.assertIn("maskImage", c)
        # 正面：蒙版自己那一段里必须按选中态取色。
        # ⚠️ 判据**必须切到 `mb-chip-mask` 那个元素**：`on_ ? t.appBg : p.color` 在
        #   外层 `.mb-chip-logo` 上也有一份，整文件断言时把蒙版那处删掉照样绿（实测）。
        i = c.index('className="mb-chip-mask"')
        seg = c[i:c.index("/>", i)]
        self.assertIn("on_ ? t.appBg : p.color", seg, "★ 蒙版没跟着选中态变色")

    def test_the_assets_are_bundled_not_fetched(self):
        """★★ 稿 §9.2：资产必须内置。运行时远程加载 = 离线就没有 logo，
        而这个 app 的全部卖点就是本机可用。"""
        c = code(CHIPS)
        self.assertNotIn("http", c, "★★ 有远程地址 —— 离线就没 logo")
        for f in ("logo-openai.png", "logo-grok.png"):
            with self.subTest(asset=f):
                self.assertTrue((SRC / "assets" / f).exists(), f"★★ 缺资产 {f}")

    def test_the_dead_dot_only_lights_when_there_are_dead_accounts(self):
        """★ 常亮的灯会被学会忽略 —— 本仓判过死刑的形态。"""
        self.assertIn("p.hasDead &&", code(CHIPS), "★ 死号红点不是按条件出现的")

    def test_the_right_hand_text_names_the_platform(self):
        """★ 稿 §2：右侧小字回显当前平台名，**只有 logo 时用来防认错**。"""
        self.assertIn("platformOf(plat).label", code(MB), "★ 右侧没有回显平台名")


class TheFooterCannotSpendAnotherPlatformsQuota(unittest.TestCase):
    """★★★ 这一组是整份改动里唯一会花钱的地方。"""

    def test_the_probe_button_is_gated(self):
        c = code(MB)
        self.assertIn("{codexActions && <ProbeButton", c,
                      "★★★ 探针没有按档收起 —— 它扣的是 codex 的额度")

    def test_only_codex_gets_the_codex_only_actions(self):
        """★ 判据从**真源**解析，不手列：只有 codex 那条 `codexActions: true`。"""
        pairs = re.findall(r'key: "([a-z]+)".*?codexActions: (true|false)', code(PLAT), re.S)
        self.assertTrue(pairs, "★ 解析不到 codexActions —— 正则失准，先修闸")
        on = [k for k, v in pairs if v == "true"]
        self.assertEqual(on, ["codex"], f"★★★ 这些档也拿到了 codex 专属动作: {on}")

    def test_refresh_follows_the_current_platform(self):
        """★★ 「刷新全池」写死成 codex 的话，站在 Gemini 档按下去刷的是另一家，
        而 toast 还说「已刷新全池」—— 按钮说的和做的不是一件事。"""
        c = code(MB)
        i = c.index("const refreshPool")
        seg = c[i:c.index("\n  const actions", i)]
        for k in ('plat === "gemini"', 'plat === "grok"'):
            with self.subTest(branch=k):
                self.assertIn(k, seg, f"★★ 刷新没有为 {k} 分支 —— 它在刷另一家")
        self.assertIn("agyPool.refresh()", seg)
        self.assertIn("refreshGrok()", seg)

    def test_the_reset_card_banner_stays_on_codex(self):
        """★ 重置卡是 codex 专属的东西，挂在别家档上说的是另一家的事。"""
        self.assertIn('{plat === "codex" && cardAlert && (', code(MB),
                      "★ 重置卡横幅没有按档收起")


class EachPlatformShowsItsOwnAccounts(unittest.TestCase):

    def test_each_list_is_gated_by_platform(self):
        c = code(MB)
        for k in ('{plat === "codex" && alive.map', '{plat === "gemini" && (agyPool.accounts.length',
                  '{plat === "grok" && ('):
            with self.subTest(branch=k):
                self.assertIn(k, c, f"★★ 列表没有按档分: 缺 {k}")

    # ⚠️ 「Tab 上的数字 = 当前平台账号数」那条（稿 §1）**已被用户 2026-09-14 否掉**，
    #    判据搬到 `TheTabCountsEveryPlatform`：每一档的数字芯片行上已经有了，
    #    Tab 上再重复一遍只是把同一个数说两遍。留一条锁死旧前提的闸比没有闸更糟。

    def test_gemini_can_switch_like_codex(self):
        """★★ 用户 2026-09-13 明确**淘汰**了稿里「只读·点卡不切号」那个方式：
        「可以切号的，按照目前 codex 的方式」。"""
        c = code(MB)
        i = c.index('{plat === "gemini" &&')
        seg = c[i:c.index('{plat === "grok"', i)]
        self.assertIn("agyPool.switchTo(a.label)", seg, "★★ Gemini 档又变回只读了")
        self.assertIn("下次启动 agy 生效", seg,
                      "★ 没说清代价 —— 用户会以为点一下就把正在跑的会话切走了")


class TheHarnessCanReachEveryTab(unittest.TestCase):
    """★★★ 芯片只有 logo 没有文字，harness 的 `click=` 那条路**匹配不到它** ——
    不给一个打桩开关，gemini / grok 两档一个像素都验不到，而截图会正常渲染、
    探针会报干净（本仓记过的同族假阴性）。"""

    def test_the_platform_tab_can_be_stubbed(self):
        h = (ROOT / "codexbar" / "uishot" / "make_harness.py").read_text(encoding="utf-8")
        self.assertIn("codexbar_mb_plat", h, "★★★ harness 没法选中 gemini/grok 档")
        self.assertIn("p.get('mbplat')", h)


if __name__ == "__main__":
    unittest.main()


class TheTabCountsEveryPlatform(unittest.TestCase):
    """★★ 用户 2026-09-14：「账号 6 应该要改为账号 9」。

    ⚠️ **这条与 v4 稿 §1 相反**，是用户当面否掉的：稿里写「`账号` 后的数字 =
    当前平台账号数」，而**每一档各自的数字芯片行上已经有了**（`6 / 2 / 1`）——
    Tab 上再重复一遍只是把同一个数说两遍；而"我一共有几个号"在别处一个地方都看不到。
    """

    def test_the_tab_sums_the_chips(self):
        c = code(MB)
        self.assertIn("chips.reduce((n, c) => n + c.count, 0)", c,
                      "★★ Tab 上又只数当前这一档了")

    def test_it_is_not_the_per_tab_count(self):
        """★ 反方向：别退回 `platCount`。"""
        self.assertNotIn("String(platCount)", code(MB))


# ⚠️ 「菜单栏至少装得下 4 个账号」那一组 2026-09-14 由用户**撤回**（「这个需求不要了」）。
#    连同 `MIN_ROWS` / 行高测量 / 地板持久化一并回退，面板高度仍然只由今日页决定。
