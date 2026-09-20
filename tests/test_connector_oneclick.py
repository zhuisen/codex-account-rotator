"""一键接入 + 「排第一但不参与轮换」的角标（用户 2026-09-21 两条）。

## ① 一键接入

用户：「接入内容太复杂了，有没有一键无脑的操作？」在这之前六步连同长解释一起摊开，
读起来像要做六个决定 —— 而其中**五步根本没得选**（不装就是不能用），只有
「让裸 `codex` 也走轮换」是真的取舍。

用户在三个方案里选的是**两个按钮并排**：主按钮做必需的 5 步，次按钮连那一步一起做。
★ 关键是**没有把可选步偷偷塞进一键**：那一步会接管 `codex` 命令，替用户做这个决定
  等于把"无脑"变成"不知情"。

## ② `⊘` 角标：排第一但根本不参与

拖拽顺序在界面上叫「轮换优先级」，但 `rotate_off` 是**另一个开关**，而 `ok()` 在排序
**之前**就把它滤掉了。实测 2026-09-21 本机：用户优先级 #1/#2/#3（5530 / mou / qq55）
**三个全是 rotate_off**，界面上却看着是最优先的 —— 实际在跑的是 #6。
「排第一但不参与」在旧界面上一个像素都看不出来。

★ 这是本仓那条「后端有字段 ≠ 已披露」的反向形态：字段在、开关在、动作条里也画着，
  但它**只在展开某一张卡时才看得到**，而用户判断优先级是在**总览一眼扫**的时候。
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
PANEL = SRC / "components" / "ConnectorPanel.tsx"
CARD = SRC / "components" / "AccountCard.tsx"
HARNESS = "http://127.0.0.1:3304"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _code(p):
    """剥掉注释 —— 本仓形态④：注释里正解释着这条规则，拿关键词断言永远匹配得到。"""
    s = p.read_text(encoding="utf-8")
    return re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s))


def _dump(query):
    import urllib.request
    if not Path(CHROME).exists() or not (APP_DIR / "harness.html").exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                        "--window-size=1200,1400", "--virtual-time-budget=8000",
                        "--dump-dom", f"{HARNESS}/harness.html?{query}"],
                       capture_output=True, text=True, timeout=180)
    return r.stdout


class TheOneClickDoesNotHideTheDecision(unittest.TestCase):
    """★★★ 一键只做没得选的那几步；接管 `codex` 永远是**另一个按钮**。"""

    def setUp(self):
        self.code = _code(PANEL)

    def test_the_primary_button_excludes_the_optional_step(self):
        self.assertIn("runApply(todoIds(false)", self.code,
                      "★★★ 一键把可选步也做了 —— 那是替用户决定要不要接管 `codex`")

    def test_the_second_button_is_the_one_that_includes_it(self):
        self.assertIn("runApply(todoIds(true)", self.code,
                      "★★ 没有「连 codex 一起接管」那个入口")

    def test_it_only_ever_applies_steps_that_are_todo(self):
        """★ `done` / `external` 不许重跑 —— `external` 是用户自己装的，契约是不碰。"""
        m = re.search(r"todoIds\s*=\s*\([^)]*\)\s*=>[\s\S]{0,260}?;", self.code)
        self.assertIsNotNone(m, "找不到 todoIds 的定义")
        self.assertIn('s.state === "todo"', m.group(0),
                      "★★ 一键会把 external（用户自己装的）也覆盖掉")

    def test_blocked_is_still_guarded_inside_the_shared_path(self):
        """★★ 三个入口共用一条 `runApply` —— 守卫必须在**那条路径上**，不在按钮样式上。"""
        self.assertIn("plan?.blocked) return;", self.code,
                      "★★ runApply 没挡 blocked —— 按钮变灰只是样式，点下去照样跑")
        self.assertEqual(self.code.count("await invoke<string>(\"connector_apply\""), 1,
                         "★★ 出现了第二条 apply 路径 —— 守卫必然漏掉其中一条")

    def test_the_detail_list_collapses_with_css_not_conditional_rendering(self):
        """★★★ 条件渲染会让明细离开 DOM，本仓接入面板的闸全在静态 DOM 上断言（§5c）。"""
        self.assertIn('data-connector-steps style={{ display: advanced ? "block" : "none" }}',
                      self.code, "★★★ 明细用了条件渲染 —— 现有的接入闸会静默全失效")

    def test_the_cost_of_the_second_button_is_written_on_screen(self):
        """★ 代价不许只写进 `title` —— 只写进悬浮等于没写（本仓 §5d）。"""
        i = self.code.index("连 codex 一起接管")
        self.assertIn("cxd", self.code[i:i + 700],
                      "★ 没在按钮旁边写明 `cxd` 仍是直连入口")


class TheOneClickRendersInEveryState(unittest.TestCase):
    """★★ 四种接入状态下按钮的出现/消失都要对 —— 静态断言看不出这个。"""

    EXPECT = {
        # conn 夹具        一键接入  连codex接管  装不了红条
        "fresh":   (True,  True,  False),   # 什么都没装
        "mixed":   (True,  False, False),   # wrapper 已装 ⇒ 第二个按钮没有意义
        "ready":   (False, False, False),   # 全装好 ⇒ 一个按钮都不该有
        "blocked": (False, False, True),    # 缺运行时 ⇒ 只许有红条
    }

    @classmethod
    def setUpClass(cls):
        cls.dom = {}
        for c in cls.EXPECT:
            d = _dump(f"nav=settings&conn={c}")
            if d is None:
                raise unittest.SkipTest("没有 Chrome 或 harness 静态服务（3304）没在跑")
            cls.dom[c] = d

    def test_the_panel_actually_rendered(self):
        """★★ 先正面证明面板在 —— 零渲染时「按钮不存在」恒真，看起来和通过一样。"""
        for c, d in self.dom.items():
            with self.subTest(conn=c):
                self.assertIn("账号池接入（Connector）", d, f"conn={c} 面板根本没渲染")

    def test_each_state_shows_exactly_the_right_buttons(self):
        for c, (one, all_, blocked) in self.EXPECT.items():
            d = self.dom[c]
            with self.subTest(conn=c):
                self.assertEqual("一键接入" in d, one, f"conn={c} 的「一键接入」出现与否不对")
                self.assertEqual("连 codex 一起接管" in d, all_,
                                 f"conn={c} 的「连 codex 一起接管」出现与否不对")
                self.assertEqual("这份安装缺少运行时文件" in d, blocked,
                                 f"conn={c} 的「装不了」红条不对")

    def test_the_advanced_list_is_present_but_hidden_everywhere(self):
        """★ 明细**始终在 DOM 里**（闸要看它），但默认不可见。"""
        for c, d in self.dom.items():
            with self.subTest(conn=c):
                self.assertIn("data-connector-steps", d, f"conn={c} 明细区不在 DOM 里")
                m = re.search(r'data-connector-steps[^>]*style="([^"]*)"', d)
                self.assertIsNotNone(m, f"conn={c} 抓不到明细区的 style")
                self.assertIn("display: none", m.group(1),
                              f"conn={c} 明细区默认就是展开的 —— 又变回六步摊开")


class AnAccountOutOfRotationSaysSoOnTheOverview(unittest.TestCase):
    """★★★ 「排第一但不参与」必须在总览一眼可见，不能只在展开的动作条里。"""

    def test_the_badge_is_driven_by_rotates_not_by_something_else(self):
        code = _code(CARD)
        self.assertIn("{!a.rotates && (", code,
                      "★★★ 角标不是由 `rotates` 驱动的 —— 它会和真实状态分叉")
        self.assertIn("data-rotate-off", code, "★ 角标没有可供闸定位的标记")

    def test_it_is_amber_not_red(self):
        """★ 主动停用 ≠ 坏了。红留给凭证失效，混用会让两种状态读不出区别。"""
        code = _code(CARD)
        i = code.index("data-rotate-off")
        self.assertIn("#E0901C", code[i:i + 220],
                      "★ 停轮换的角标用了非琥珀色 —— 与「凭证失效」撞色")

    def test_it_really_renders_on_the_overview(self):
        """★★ 行为闸：夹具里有 rotate_off 的号，总览上就必须有对应数量的角标。

        ⚠️ 判据是**两个数相等**，不是「>0」：只断言有一个，漏掉其余的号照样绿。
        """
        d = _dump("nav=home")
        if d is None:
            self.skipTest("没有 Chrome 或 harness 静态服务（3304）没在跑")
        self.assertIn('data-aid', d, "★★ 总览一张卡都没渲染")
        # ★ 期望值从**页面真正用的那份夹具**推导（内联在 harness.html 里），不另抄一份、
        #   也不去读真实 state.json。`"rotate_off": true` 是 JSON 夹具里的形态；
        #   agy 那份是 JS 表达式（`rotate_off: (...)`），冒号后无空格，天然不会误匹配。
        fixture = (APP_DIR / "harness.html").read_text(encoding="utf-8")
        want = len(re.findall(r'"rotate_off"\s*:\s*true', fixture))
        self.assertGreater(want, 0,
                           "★★ 夹具里一个停轮换的号都没有 —— 这条闸此刻没有判别力")
        self.assertEqual(d.count("data-rotate-off"), want,
                         f"★★ 夹具里有 {want} 个停轮换的号，总览上画了 "
                         f"{d.count('data-rotate-off')} 个")


if __name__ == "__main__":
    unittest.main(verbosity=2)
