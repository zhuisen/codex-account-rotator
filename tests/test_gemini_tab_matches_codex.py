"""Gemini 档与 Codex 档**功能对齐**（用户 2026-09-13：「gemini 的功能也没有 1:1 同步上 codex」）。

用户圈出来的是两块：**Hero 区**（当前使用中 + 建议切到）和**卡片展开的动作条**。

## ★★★ 对齐**不等于**照搬，三件东西刻意没做，每一条都有事实依据

| 没做 | 为什么 |
|---|---|
| 「探针」 | 它跑的是 `codex-rotate probe --all`，扣的是 **codex** 的额度。挂在 Gemini 档上 = 用户看着 agy 的卡按下去、花的是另一家的钱 |
| 「检查 token」 | agy 没有对等物（那是问 OpenAI 服务端 token 是否被作废） |
| 「自动切号」开关 | agy 的自动选号发生在 `bin/agy` **拉起进程之前**，不是 app 能开关的运行期行为。给一个点了没用的开关，比没有这个开关糟 |

给一个点下去没反应、或者扣错家钱的按钮，比缺一个按钮糟得多 —— 这一组闸两头都守。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
APP = SRC / "App.tsx"
CARD = SRC / "components" / "AgyCard.tsx"
ACC = SRC / "components" / "AccountCard.tsx"
RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"


def code(p):
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


def gemini_block():
    """总览里 Gemini 档那一段（含 Hero、动作条、卡片网格）。"""
    c = code(APP)
    i = c.index('{provider === "gemini" && (<>')
    return c[i:c.index('{provider === "grok" && (<>', i)]


class TheGeminiTabHasAHeroLikeCodex(unittest.TestCase):

    def test_there_is_a_hero(self):
        b = gemini_block()
        self.assertIn("当前使用中", b, "★★ Gemini 档没有 Hero 区")

    def test_the_hero_shows_both_windows(self):
        """★ 与卡片同一条纪律：槽位写死 `5h`/`周`，缺的显式画 `—`。
        "有什么画什么"会让 Hero 时有两段时有一段，而那个少没有任何地方解释。"""
        c = code(APP)
        m = re.search(r'agyHeroSlots = \[([^\]]+)\]', c)
        self.assertIsNotNone(m, "★ Hero 的槽位表不见了 —— 判据看不懂了，先修闸")
        self.assertEqual(re.findall(r'"([^"]+)"', m.group(1)), ["5h", "周"])

    def test_it_suggests_switching_to_the_best(self):
        self.assertIn("建议切到", gemini_block(), "★★ Hero 没有「建议切到」")

    def test_a_tie_goes_to_the_current_account(self):
        """★★ 打平时当前号赢。`reduce` 取第一个最大值，于是两个号都是 96% 时会推荐
        "切到另一个 96%" —— 零收益，而 agy 换号的代价是得重开一个会话。"""
        c = code(APP)
        i = c.index("const agyTop")
        seg = c[i:c.index("\n  const agyBest", i)]
        self.assertIn("x.a.sub === agyPool.liveSub", seg, "★★ 平局时会推荐一次零收益的换号")

    def test_unknown_quota_never_gets_recommended(self):
        """★★★ 读不到额度的号**不参与**排名。让"未知"冒充满额被推荐，
        是本仓在 codex 选号器上栽过的同一条（未知被当成 0% 已用 ⇒ 排最空闲）。"""
        c = code(APP)
        i = c.index("const agyRank")
        seg = c[i:c.index("const agyTop", i)]
        self.assertIn("x.pct != null", seg, "★★★ 额度未知的号会被当成候选")


class TheGeminiCardHasTheSameActionBar(unittest.TestCase):

    def test_the_card_can_be_selected(self):
        self.assertIn("isSelected", code(CARD), "★★ agy 卡不能选中 ⇒ 没有动作条")

    def test_siblings_reserve_the_same_height(self):
        """★★ 同排有别的卡展开时，本卡渲染**同一条动作条但整条隐形** ——
        不是画一个"差不多高"的占位。账号卡那边手算过一次，sweep 当场量出还差 34px。"""
        c = code(CARD)
        self.assertIn("(isSelected || reserveActions) && (", c, "★★ 没有占位 ⇒ 兄弟卡高度不齐")
        i = c.index("(isSelected || reserveActions) && (")
        seg = c[i:i + 700]
        self.assertIn('visibility: "hidden"', seg, "★ 占位没隐形")
        self.assertIn('pointerEvents: "none"', seg,
                      "★★ 隐形那份能点 —— 会出现看不见却点得到的按钮")

    def test_it_has_switch_rename_and_remove(self):
        c = code(CARD)
        for tok, why in (("onRename", "改名"), ("onRemove", "移除"), ("onSwitch", "切换")):
            with self.subTest(action=why):
                self.assertIn(tok, c, f"★★ agy 卡缺「{why}」—— 与 codex 卡不对齐")

    def test_remove_asks_twice(self):
        """★★★ 移除不可逆。把「确认删除」也压成图标等于让人凭记忆点。"""
        c = code(CARD)
        # ⚠️ 判据不能只是「源码里有 confirmDelete / 确认删除」：把三元条件改成
        #    `false ? …` 之后那两个字符串**仍然在源码里**，闸照样绿（实测）。
        #    要打在**分支条件**和**按钮做什么**上。
        self.assertIn("!confirmDelete ? (", c, "★★★ 删除按钮不再走二次确认的分支")
        self.assertIn("onClick={() => setConfirmDelete(true)}", c,
                      "★★★ 垃圾桶按钮直接删了 —— 不可逆操作一键就走")
        self.assertIn("setConfirmDelete(false); onRemove();", c,
                      "★★★ 真正的删除不是从确认态发出的")

    def test_rename_does_not_submit_on_blur(self):
        """★ 与账号卡同一条：`onBlur` 一律放弃，不静默提交。"""
        c = code(CARD)
        i = c.index("onBlur")
        self.assertIn("setEditing(null)", c[i:i + 80], "★ onBlur 静默提交了")

    def test_the_rename_box_swallows_the_shortcut_keys(self):
        """★★ 全局 ⌘1~⌘9 是切号快捷键，输入框不拦的话打数字会切号
        （账号卡那边踩过一次）。"""
        c = code(CARD)
        i = c.index("onKeyDown")
        self.assertIn("stopPropagation", c[i:i + 120], "★★ 在改名框里打数字会切号")


class TheThingsDeliberatelyLeftOut(unittest.TestCase):
    """★★★ 两头都要守：缺按钮是缺陷，**多一个扣错家钱的按钮更糟**。"""

    def test_no_probe_button_on_the_gemini_tab(self):
        b = gemini_block()
        self.assertNotIn("ProbeButton", b,
                         "★★★ 探针出现在 Gemini 档 —— 它扣的是 codex 的额度")
        self.assertNotIn("ProbeButton", code(CARD),
                         "★★★ agy 卡上有探针 —— 同上")

    def test_no_health_check_on_the_gemini_tab(self):
        self.assertNotIn('"health"', gemini_block(),
                         "★★ 「检查 token」对 agy 没有对等物 —— 点了不会有任何结果")

    def test_the_bridge_still_refuses_login(self):
        """★★★ `login` 会起一个交互式 agy，GUI 里跑必然挂死。
        放开 rename/remove **不等于**把白名单变成摆设。"""
        rs = code(RS)
        i = rs.index("async fn run_agy_rotate(")
        m = re.search(r'ALLOWED: &\[&str\] = &\[([^\]]*)\]', rs[i:i + 400])
        self.assertIsNotNone(m, "★ 白名单不见了 —— 参数直接进 argv")
        allowed = set(re.findall(r'"([a-z-]+)"', m.group(1)))
        self.assertNotIn("login", allowed, "★★★ GUI 能跑 login —— 必然挂死")
        self.assertTrue(allowed <= {"quota", "switch", "live", "rename", "remove"},
                        f"★★ 白名单里有没审过的子命令: {sorted(allowed)}")


class TheHarnessCanReachTheExpandedCard(unittest.TestCase):
    """★★★ 动作条**只在选中后出现**。没有一个能选中卡的打桩开关，
    这一整块在 harness 里一个像素都验不到，而截图会正常渲染、探针会报干净。"""

    def test_pickcard_exists(self):
        h = (ROOT / "codexbar" / "uishot" / "make_harness.py").read_text(encoding="utf-8")
        self.assertIn("p.get('pickcard')", h, "★★★ harness 选不中卡片 ⇒ 动作条验不到")
        # ★ 必须点**卡片本身**：名字那个 span 上没有 onClick，靠冒泡才到卡上。
        self.assertIn("[data-cards-grid] > div", h, "★ 点的不是卡片本体")


if __name__ == "__main__":
    unittest.main()
