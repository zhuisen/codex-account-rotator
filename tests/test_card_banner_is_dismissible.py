"""重置卡横幅：单行、可关、关掉不丢信息（2026-09-18，用户实报）。

## 原来的形态是本仓判过死刑的那一种

用户原话：「这个提醒太过了，喧宾夺主，并且无法取消」。实测当时的形态：

  · 60px 三行横幅，挂在 **352px 宽**弹窗的顶部，挤掉小半张账号卡；
  · `CARD_WARN_DAYS = 3` ⇒ 它**连挂三天**；
  · `plat === "codex" && cardAlert &&` —— **没有任何关闭入口**；
  · 那颗大按钮「用卡: /usage」**点了并不用卡**（服务端要求当前周窗口"需要重置"才放行，
    盲发会为一个 `nothingToReset` 白烧一张），只弹个 toast 告诉你去终端敲命令。

⇒ **一盏连亮三天、关不掉、又不能真正执行的灯。** 本仓两条规矩正好都写着：
  · §5d「一天看一次的信息 ⇒ 折叠进角标，悬浮才展开」
  · 「长期亮着又灭不掉的告警，训练用户忽略告警」——比没有告警更糟。

## 现在的形态（用户 2026-09-18 从三个方案里选的 C）

  常驻那一半 = 卡上的 `CardBadge`（琥珀 + 光晕 + `×3·1张3天`，本来就有，零高度成本）；
  横幅只在这张卡**刚进入 3 天窗口**时弹一次单行，关掉后只剩角标。

★ 「怎么用卡」那句从横幅搬进了角标的悬浮说明 —— 那本来是横幅唯一独有的内容，
  不搬就等于「关掉 = 丢信息」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
MENUBAR = SRC / "MenuBar.tsx"
BADGE = SRC / "components" / "CardBadge.tsx"
HOOK = SRC / "hooks" / "useCardBannerDismiss.ts"


def _strip(src: str) -> str:
    """剥掉 JS/TS 注释 —— 本仓注释密度极高，而这条规则的说明里就写着它要找的那些词
    （「无法取消」「用卡: /usage」…）。不剥必被自己的说明判红（空守卫形态④）。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"\{/\*[\s\S]*?\*/\}", "", src)
    return re.sub(r"//[^\n]*", "", src)


class TheBannerCanBeDismissed(unittest.TestCase):
    """★★★ 主闸：告警必须**关得掉**。"""

    @classmethod
    def setUpClass(cls):
        cls.mb = _strip(MENUBAR.read_text(encoding="utf-8"))

    def test_the_hook_exists(self):
        self.assertTrue(HOOK.is_file(), "★★★ 关闭记忆的 hook 不见了")

    def test_the_banner_is_gated_on_visibility(self):
        """★★★ 渲染条件里必须有「用户关过没有」这一维。"""
        m = re.search(r"plat === \"codex\" && cardAlert && ([^\n]*)", self.mb)
        self.assertIsNotNone(m, "★ 找不到横幅的渲染条件 —— 断言可能打空了")
        self.assertIn("bannerVisible", m.group(1),
                      "★★★ 横幅没接关闭状态 —— 又变回「无法取消」")

    def test_there_is_a_close_control(self):
        self.assertIn("mb-banner-x", self.mb, "★★★ 没有关闭按钮")
        self.assertIn("bannerDismiss", self.mb, "★★★ 关闭按钮没接上 dismiss")

    def test_the_close_control_has_an_accessible_label(self):
        """★ 一个 10.5px 的 `×` 必须有可读的名字与 `title`，否则只有肉眼能发现它。"""
        i = self.mb.index("mb-banner-x")
        seg = self.mb[i:i + 320]
        self.assertIn("aria-label", seg, "★ 关闭按钮没有 aria-label")
        self.assertIn("title", seg, "★ 关闭按钮没有悬浮说明")


class DismissingOneAlertIsNotDismissingAllOfThem(unittest.TestCase):
    """★★★ **这是整件事最容易写错的地方。**

    存一个布尔「用户关过横幅」⇒ 下一张卡快到期时**也不会再提醒**，
    而那是一次全新的、真会损失东西的事件。
    「关掉这一条」和「以后都别提醒我」是两件事 ——
    合并成同一个值，就等于静默把这个功能关掉了。
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _strip(HOOK.read_text(encoding="utf-8"))

    def test_the_key_includes_the_card_identity(self):
        i = self.src.index("export function cardAlertKey")
        body = self.src[i:self.src.index("\n}", i)]
        self.assertIn("cardExp", body,
                      "★★★ 关闭记忆的键里没有卡的身份 —— 换了新卡也不会再提醒")
        self.assertIn("node", body, "★★ 键里没有账号 —— 另一个号的卡会被连坐")

    def test_a_missing_expiry_still_yields_a_key(self):
        """★★ `cardExp` 还没取到时也必须能生成键。

        返回 `null` 会让横幅**永远无法被关掉** —— 正是这次要修的那个症状本身。
        """
        i = self.src.index("export function cardAlertKey")
        body = self.src[i:self.src.index("\n}", i)]
        self.assertRegex(body, r"cardExp\s*\?\?",
                         "★★ `cardExp` 缺失时没有兜底 —— 横幅会退回「关不掉」")

    def test_it_really_behaves_that_way(self):
        """★★★ **行为闸**：把 hook 里的纯函数取出来真跑，验三件事。

        静态断言只能证明"键里提到了 cardExp"；只有真跑能证明
        **换一张卡就会重新提醒**。
        """
        src = HOOK.read_text(encoding="utf-8")
        m = re.search(r"export function cardAlertKey[\s\S]*?\n\}", src)
        self.assertIsNotNone(m, "★ 取不出 cardAlertKey —— 断言可能打空了")
        js = m.group(0)
        # TS → JS：去掉类型标注（只有这一个函数，形态固定）
        js = re.sub(r":\s*Pick<[^>]*>[^)]*", "", js)
        js = js.replace("export function", "function").replace(": string | null", "")

        import json
        import subprocess
        prog = js + """
const A = {node: "wing", cardExp: "2026-10-02"};
const A2 = {node: "wing", cardExp: "2026-10-02"};
const B = {node: "wing", cardExp: "2026-10-09"};   // 换了一张新卡
const C = {node: "Egan", cardExp: "2026-10-02"};   // 另一个号
const D = {node: "wing"};                          // 明细还没取到
console.log(JSON.stringify({
  same: cardAlertKey(A) === cardAlertKey(A2),
  newCard: cardAlertKey(A) !== cardAlertKey(B),
  otherNode: cardAlertKey(A) !== cardAlertKey(C),
  noExpiryStillKeyed: cardAlertKey(D) !== null,
  nullSafe: cardAlertKey(null) === null,
}));
"""
        r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        got = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(got["same"], "★ 同一张卡应当是同一个键")
        self.assertTrue(got["newCard"],
                        "★★★ 换了新卡键没变 —— 关过一次之后**新卡再也不提醒**")
        self.assertTrue(got["otherNode"], "★★ 另一个号的卡被连坐了")
        self.assertTrue(got["noExpiryStillKeyed"],
                        "★★ 明细没取到时生成不出键 —— 横幅会永远关不掉")
        self.assertTrue(got["nullSafe"], "★ 空输入没有返回 null")


class DismissingLosesNoInformation(unittest.TestCase):
    """★★★ 关掉横幅之后，它携带的每一条信息都必须还在别处。

    否则「可关闭」就是把信息藏起来，而不是把噪音降下去。
    """

    def test_the_how_to_use_line_moved_into_the_always_present_badge(self):
        """★★★ 「怎么用卡」原来只在横幅里。角标是常驻的，所以它是正确的归宿。"""
        badge = _strip(BADGE.read_text(encoding="utf-8"))
        self.assertIn("/usage", badge,
                      "★★★ 角标悬浮里没有用法 —— 关掉横幅就等于丢掉这条信息")
        self.assertIn("Redeem", badge, "★★ 用法没说全（缺 Redeem 那一步）")

    def test_the_how_to_use_line_only_shows_when_expiring(self):
        """★ 平时那句是噪音 —— 「披露的寿命跟着它描述的事实走」。"""
        badge = _strip(BADGE.read_text(encoding="utf-8"))
        i = badge.index("/usage")
        seg = badge[max(0, i - 400):i]
        self.assertIn("expiring", seg,
                      "★ 用法没有按「是否快到期」加条件 —— 会一直挂在悬浮里")

    def test_the_count_and_expiry_are_on_the_badge(self):
        """★ 张数与到期日也要在角标上（横幅原本也说了这两件）。"""
        badge = _strip(BADGE.read_text(encoding="utf-8"))
        self.assertIn("a.cards", badge)
        self.assertIn("cardExp", badge)


class TheBannerIsOneLineNow(unittest.TestCase):
    """★★ 「喧宾夺主」那一半：60px → 单行。"""

    @classmethod
    def setUpClass(cls):
        cls.mb = _strip(MENUBAR.read_text(encoding="utf-8"))
        cls.css = (SRC / "menubar.css").read_text(encoding="utf-8")

    def test_the_subtitle_row_is_gone(self):
        """★ 判据 2026-09-19 由**整个文件**收窄到**重置卡那一段**。

        原来断言的是 `mb-banner-sub` 不许出现在 `MenuBar.tsx` 里任何地方。那在当时是对的
        （文件里只有重置卡一条横幅），但它把「这条横幅要单行」写成了「这个文件不许有副标题」。
        同日新增的**接入闸**横幅合法地用两行（徽章一行 + 该做什么一行）——352px 下挤成一行
        会被省略号从尾部切掉动作那半，而本仓披露铁律要求告警必须说下一步。
        ⚠️ 前提被取代，不是规则被放弃：重置卡横幅**仍然**必须是单行，只是判据现在只看它。
        """
        seg = self.mb.split("cardAlert && bannerVisible", 1)
        self.assertEqual(len(seg), 2, "找不到重置卡横幅那一段 —— 判据的锚点漂了")
        block = seg[1].split("</div>\n      )}", 1)[0]
        self.assertNotIn("mb-banner-sub", block,
                         "★★ 重置卡横幅的副标题行又回来了 —— 它必须是单行")

    def test_the_fake_action_button_is_gone(self):
        """★★★ 那颗「用卡: /usage」**点了并不用卡**，只弹 toast。

        一个看起来能执行、实际只会告诉你去别处操作的大按钮，
        比没有按钮更糟 —— 它把「说明」伪装成了「动作」。
        """
        self.assertNotIn("mb-banner-hint", self.mb,
                         "★★★ 那颗假动作按钮又回来了")

    def test_the_slim_style_exists(self):
        self.assertIn(".mb-banner-slim", self.css, "★★ 单行样式不见了")
        i = self.css.index(".mb-banner-slim")
        seg = self.css[i:i + 200]
        self.assertIn("padding", seg, "★ 单行形态没收紧内边距")

    def test_the_close_target_is_bigger_than_the_glyph(self):
        """★ 10.5px 的 `×` 本身太小 —— 命中区必须靠 padding 撑大，
        否则「点不中」和「没点」长得一模一样（同 harness 那条 clicks 纪律）。"""
        i = self.css.index(".mb-banner-x")
        seg = self.css[i:i + 300]
        self.assertIn("padding", seg, "★ 关闭按钮没有额外命中区")
        self.assertIn("cursor: pointer", seg, "★ 关闭按钮没有指针光标")


if __name__ == "__main__":
    unittest.main()
