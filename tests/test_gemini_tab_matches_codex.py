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
    """总览里**所有** `provider === "gemini"` 的段落拼起来。

    ⚠️ 不能只取 `(<>` 那一段：**动作条与卡片网格不在同一处** ——
    动作条在顶栏右侧、网格在下面。只切一段会让「有没有探针/检查 token」
    这类断言对着半页源码判，而那种假红/假绿两个方向都出现过。
    """
    c = code(APP)
    marks = [i for i in range(len(c)) if c.startswith('{provider === "gemini" &&', i)]
    assert marks, "★ 解析不到 Gemini 档 —— 判据看不懂了，先修闸"
    out = []
    for i in marks:
        j = c.find('{provider === "', i + 10)
        out.append(c[i:j if j > 0 else len(c)])
    return "\n".join(out)


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

    def test_the_probe_is_agys_own_not_codexs(self):
        """★★★ **这条 2026-09-13 被用户推翻并改写过。**

        旧的是「Gemini 档不许有 ProbeButton」，理由是探针扣 codex 的额度。
        用户原话：「探针做，做另外的机制，扣的是 agy 的额度啊…不是照搬 codex 的方法啊」。
        现在 agy 有了自己的探针（起 `agy -p`，花 agy 自己的额度），
        旧闸锁死的是一个**已经不成立的前提**。

        改写后守的是真正的那条：**Gemini 档绝不能去跑 codex 的那条命令。**
        """
        b = gemini_block()
        self.assertIn("agyPool.probe(", b, "★★ Gemini 档没有自己的探针")
        for bad in ('"probe-all"', '["probe", "--all"]', 'run("probe'):
            with self.subTest(token=bad):
                self.assertNotIn(bad, b,
                                 f"★★★ Gemini 档跑了 codex 的 {bad} —— 扣的是另一家的额度")

    def test_the_health_check_is_agys_own_too(self):
        """★ 同理：`health` 走 `agyPool.health()`（刷 token + 打 API，零消耗），
        不是 codex 那条 `run("health", ["health"])`。"""
        b = gemini_block()
        self.assertIn("agyPool.health()", b, "★★ Gemini 档没有检查 token")
        self.assertNotIn('run("health"', b, "★★★ Gemini 档跑了 codex 的 health")

    def test_the_bridge_still_refuses_login(self):
        """★★★ `login` 会起一个交互式 agy，GUI 里跑必然挂死。
        放开 rename/remove **不等于**把白名单变成摆设。"""
        rs = code(RS)
        i = rs.index("async fn run_agy_rotate(")
        m = re.search(r'ALLOWED: &\[&str\] = &\[([^\]]*)\]', rs[i:i + 400])
        self.assertIsNotNone(m, "★ 白名单不见了 —— 参数直接进 argv")
        allowed = set(re.findall(r'"([a-z-]+)"', m.group(1)))
        self.assertNotIn("login", allowed, "★★★ GUI 能跑 login —— 必然挂死")
        self.assertTrue(allowed <= {"quota", "switch", "live", "rename", "remove",
                                    "health", "probe", "rotate", "auto-switch"},
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


class ClickingARowGoesToTheOverviewNotTheUsagePage(unittest.TestCase):
    """★★ 用户 2026-09-14：「菜单栏我不同的账号点击进去，为什么是跳转到 ai 用量那里了？」

    根因：三档的「点行」语义被做得不一致 ——
      · 账号行（codex）走 `navigate-overview`（用户 2026-08-11 从三个 demo 里选的**方案 A**：
        点行开主界面、换号走行上的「切换」）
      · agy / grok 那两档走的是 `navigate-platform` ⇒ `setPage("traffic")` ⇒ **AI 用量**的平台详情页
      · 而 agy 的**当值号**没有 `onSwitch`，点行时还会退回 `onOpen` —— 同一档内两种行为

    现在三档一致：**点行 = 弹主界面的总览，并停在这一行所属的那一档**。
    """

    MB = (ROOT / "codexbar" / "src" / "MenuBar.tsx")
    ROW = (ROOT / "codexbar" / "src" / "components" / "AgyRow.tsx")

    def test_no_row_jumps_to_the_usage_page(self):
        c = code(self.MB)
        i = c.index('<div className="mb-list">')
        seg = c[i:c.index("</div>\n      </div>", i)]
        self.assertNotIn("navigate-platform", seg,
                         "★★ 又有行点击跳到 AI 用量的平台详情页了")

    def test_every_row_carries_its_own_tab(self):
        """★ 不带档的话主窗会停在**上次那一档** —— 点 Gemini 的行落在 Codex 档上。
        「打开主窗口」和「去哪一档」是两件事，前者不该顺带决定后者。"""
        c = code(self.MB)
        for k in ('"navigate-overview", "codex"', '"navigate-overview", "gemini"',
                  '"navigate-overview", "grok"'):
            with self.subTest(tab=k):
                self.assertIn(k, c, f"★ 缺 {k}")

    def test_the_main_window_honours_the_tab(self):
        """★★ 只发不收等于没发。判据打在**监听那一侧**。"""
        c = code(APP)
        i = c.index('listen<string | undefined>("navigate-overview"')
        seg = c[i:i + 420]
        self.assertIn("setProvider(e.payload)", seg, "★★ 主窗收到了档位却不切")
        # ★ 缺省必须不动 provider —— 老的调用点（不带档）行为一个字不变
        self.assertIn('e.payload === "codex"', seg, "★ 没有校验载荷 ⇒ 脏值能改档")

    def test_clicking_an_agy_row_does_not_switch(self):
        """★★ 换号走名字旁边那个「切换」徽章，点行只开主界面 ——
        与账号行同一条语义。混着来的症状就是用户报的那个跳转。"""
        c = code(self.ROW)
        i = c.index('<div className="mb-row" onClick=')
        self.assertIn("onClick={switching ? undefined : onOpen}", c[i:i + 120],
                      "★★ 点行又变回切号了")


class TheShortcutBadgeOnlyAppearsWhereItWorks(unittest.TestCase):
    """★★ 用户 2026-09-14：「为什么 gemini 的账号排序左上角还是 CLI？」

    那个角标是「按 ⌘N 能切到它」的**承诺**。只给 codex 接线、却在别的档也画角标，
    就是画一个点了没反应的东西 —— 本仓判过死刑的形态。所以两件事必须一起做：
    **接线按档分流，角标也只在真的接了线的那一档出现。**
    """

    def test_the_keyboard_is_routed_per_tab(self):
        c = code(APP)
        i = c.index("useKeyboard(win, refresh")
        seg = c[i:c.index("\n  });", i)]
        self.assertIn('provider === "gemini"', seg, "★★ ⌘N 没有为 Gemini 档接线")
        self.assertIn("agyPool.switchTo(a.label)", seg, "★★ 接了线却没真的切号")
        self.assertIn('provider === "grok"', seg, "★ Grok 档（单号只读）没有短路")

    def test_the_badge_is_passed_only_when_wired(self):
        self.assertIn("shortcut={i < 9 ? i + 1 : undefined}", code(APP),
                      "★★ 角标没传 ⇒ 卡上还是 `CLI`")

    def test_agy_still_stays_out_of_the_pool_arrays(self):
        """★★★ 按档分流**不等于**把 agy 塞进 `alive`/`accounts` ——
        那两个数组还驱动着计数徽章、探针全池的号数、自动切号。"""
        c = code(APP)
        i = c.index("useKeyboard(win, refresh")
        seg = c[i:c.index("\n  });", i)]
        self.assertNotIn("aliveByLabel[idx].sub", seg)
        self.assertIn("agyPool.accounts[idx]", seg, "★ Gemini 档取的不是它自己那列")
