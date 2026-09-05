"""agy **在 UI 层**也不得混进轮换池,外加两条 agy 独有的可见性铁律。

第一部分与 `test_grok_not_in_pool_ui.py` 同构,理由也一样:菜单栏里 agy 长得**和账号卡一样**,
视觉一样就更需要数据不一样。`accounts` / `alive` / `aliveByLabel` 同时驱动 ⌘1~⌘9 切号、
计数徽章、探针全池的号数(**计费**动作)、自动切号 —— agy 混进任何一个,⌘3 就可能"切"到一个
根本切不了的东西上,而**没有一处会报错**。

第二部分是 grok 那边不存在的问题,也是这个文件真正的重点:

  ★★ **`not_installed` 要藏,`no_process` 必须显示。**

  agy 与 grok 的关键差别是**它不常驻**:grok 装了就有 `~/.grok/auth.json`,而 agy 的额度
  只在进程活着时可读,所以"没在跑"是**常态**。两者若被合并成一个"没有":
    · 都按隐藏处理 ⇒ 装了 agy 的人**几乎永远看不到卡**(平时 agy 就没在跑);
    · 都按显示处理 ⇒ 没装的人得到一盏永远亮着、又无从消除的灯(本仓判过死刑的形态)。
  这条闸就是把"它俩没被合并"写成断言。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
MENUBAR = SRC / "MenuBar.tsx"
APP = SRC / "App.tsx"
AGYROW = SRC / "components" / "AgyRow.tsx"
AGYCARD = SRC / "components" / "AgyCard.tsx"
AGY_TS = SRC / "agy.ts"

POOL_ARRAYS = ("accounts", "alive", "aliveByLabel", "dead")


def strip_comments(src: str) -> str:
    """注释里正解释着这条规则,朴素匹配必被它染红(本仓反复吃过的『grep 假阳性』)。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


class AgyNeverEntersPoolArrays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mb = strip_comments(MENUBAR.read_text(encoding="utf-8"))
        cls.app = strip_comments(APP.read_text(encoding="utf-8"))

    def test_anchors_exist(self):
        """★ 先证明被测目标还在。改名之后断言会静默打空 —— 那是最坏的假绿。"""
        self.assertIn("aliveByLabel", self.app, "App.tsx 的 aliveByLabel 不见了,断言已失效")
        self.assertIn("<AgyRow", self.mb, "菜单栏没有渲染 AgyRow,这条闸在守一个不存在的东西")
        self.assertIn("<AgyCard", self.app, "总览没有渲染 AgyCard")
        self.assertIn("useAgyQuota", self.mb)

    def test_agy_snapshot_is_a_separate_binding(self):
        """菜单栏的 agy 数据必须来自 `useAgyQuota` 自己的返回值,不是从 accounts 里挑出来的。"""
        m = re.search(r"const\s*\{([^}]*)\}\s*=\s*useAgyQuota\(", self.mb)
        self.assertIsNotNone(m, "菜单栏没有独立调用 useAgyQuota")
        self.assertIn("snap", m.group(1))
        for pat in (r"accounts\.find\([^)]*agy", r"accounts\.filter\([^)]*agy"):
            self.assertEqual(re.findall(pat, self.mb, re.I), [],
                             "agy 是从 accounts 里挑出来的 —— 它根本不该在那里面")

    def test_agyrow_has_no_switch_affordance(self):
        """卡片这个形状本身在说"这是能切的号"。agy 切不了,所以绝不能长出切换入口。"""
        code = strip_comments(AGYROW.read_text(encoding="utf-8"))
        for bad in ("onSwitch", "mb-row-switch", '"switch"', "switching"):
            with self.subTest(token=bad):
                self.assertNotIn(bad, code,
                                 "AgyRow 出现了切换相关的 {} —— 它不在池里".format(bad))

    def test_agy_components_never_invoke_commands(self):
        for f in (AGYROW, AGYCARD):
            code = strip_comments(f.read_text(encoding="utf-8"))
            for bad in ("run_rotate", "invoke(", "run("):
                with self.subTest(f=f.name, token=bad):
                    self.assertNotIn(bad, code,
                                     "{} 直接调了 {} —— 它只该展示".format(f.name, bad))

    def test_counts_do_not_include_agy(self):
        for pat in (r"counts\.\w+\s*\+\s*\(?\s*agy", r"agy\w*\s*\?\s*1\s*:\s*0"):
            with self.subTest(pat=pat):
                self.assertEqual(re.findall(pat, self.mb, re.I), [],
                                 "计数里掺进了 agy:{}".format(pat))

    def test_agyrow_names_its_destination(self):
        """菜单栏点 agy 必须指明去哪个版块 —— 裸 `openMain()` 会落在"上次那一页"。

        (用户 2026-08-25 报过这个 bug 的账号行版本:它**不是每次都错**,
        上次停在总览时点是对的,停在用量页才错 —— 比恒错更难报也更难复现。)
        """
        m = re.search(r"<AgyRow[^>]*onOpen=\{([^}]*(?:\}[^}]*)*?)\}\s*/>", self.mb, re.S)
        self.assertIsNotNone(m, "AgyRow 没有 onOpen —— 点了不会有反应")
        self.assertIn("navigate-platform", m.group(1),
                      "AgyRow 的 onOpen 没指定目的地")


class AgyVisibilityDistinguishesTwoKindsOfAbsence(unittest.TestCase):
    """★★ 这个文件的重点:两种"没有"绝不能合并。见模块头注释。"""

    @classmethod
    def setUpClass(cls):
        cls.ts = AGY_TS.read_text(encoding="utf-8")
        i = cls.ts.index("export function agyQuotaVisible")
        cls.body = cls.ts[i:]

    def test_visibility_predicate_is_single_source(self):
        self.assertIn("export function agyQuotaVisible", self.ts,
                      "没有统一的可见性判据 —— 两个 surface 各写一份迟早分叉")
        for f in ("components/AgyCard.tsx", "components/AgyRow.tsx"):
            code = strip_comments((SRC / f).read_text(encoding="utf-8"))
            with self.subTest(f=f):
                self.assertIn("agyQuotaVisible(", code, "{} 没走统一判据".format(f))
                self.assertIn("return null", code, "{} 不可见时没有真的返回 null".format(f))

    def test_not_installed_hides_the_card(self):
        """没装 agy = **确定的否定**,隐藏是诚实的。"""
        self.assertIn("not_installed", self.body,
                      "not_installed 不会让 agy 卡隐藏 —— 没装的人会看到一张常驻空卡")

    def test_no_process_does_NOT_hide_the_card(self):
        """★★ 反向断言,本文件最重要的一条。

        agy 不常驻,"没在跑"是常态。把它一起藏掉 ⇒ 用户**几乎永远看不到** agy 的额度,
        而此时卡上本可以显示 `last_good`(关于一份真实额度的真实数字)。
        """
        self.assertNotIn("no_process", self.body,
                         "agyQuotaVisible 把 no_process 也藏了 —— agy 平时就没在跑,"
                         "这等于永久隐藏。它该显示上次读数。")

    def test_the_two_absences_are_distinct_in_the_type(self):
        union = self.ts.split("export type AgyReason", 1)[1].split(";", 1)[0]
        for r in ("not_installed", "no_process"):
            with self.subTest(reason=r):
                self.assertIn(r, union, "AgyReason 缺了 {}".format(r))

    def test_both_surfaces_receive_the_disabled_flag(self):
        """停用开关必须**两个 surface 都接** —— 只接一个的症状是「主窗没了、菜单栏还在」。"""
        for f, needle in (("App.tsx", "platPrefs.by?.agy?.off"),
                          ("MenuBar.tsx", "prefs.by?.agy?.off")):
            code = strip_comments((SRC / f).read_text(encoding="utf-8"))
            with self.subTest(f=f):
                self.assertIn(needle, code, "{} 没有把停用状态传下去".format(f))


class AgyNeverFabricatesFullQuota(unittest.TestCase):
    """★ 上游 `remainingFraction` 缺省是 1.0,所以这条链路的假绿形态是**满格**。

    UI 层守住两件事:失败时画 `—` 而不是数字;取数一律走 `agy.ts` 的具名函数,
    不在组件里直接摸 `remaining_percent` 的默认值。
    """
    def test_components_render_dash_when_no_data(self):
        """无数据时画 `—`,不画数字。

        ★ 两个组件写法不同但都对:AgyCard 是字符串字面量 `"—"`,AgyRow 是 JSX 文本 `>—<`。
        第一版断言只认前者,于是把一个正确的实现判成了红 —— 断言窄于规则,红得没有意义。
        所以这里只查**渲染代码里有没有这个字符**(注释已剥掉,免得被说明文字里的破折号蒙混)。
        """
        for f in (AGYCARD, AGYROW):
            code = strip_comments(f.read_text(encoding="utf-8"))
            with self.subTest(f=f.name):
                self.assertIn("—", code,
                              "{} 没有 — 的兜底,无数据时可能画出一个数字".format(f.name))

    def test_no_default_of_one_hundred(self):
        """不许出现 `?? 100` / `|| 100` 这种把缺失补成满格的写法。"""
        for f in (AGYCARD, AGYROW, AGY_TS):
            code = strip_comments(f.read_text(encoding="utf-8"))
            for pat in (r"\?\?\s*100\b", r"\|\|\s*100\b", r"\?\?\s*1\.0\b"):
                with self.subTest(f=f.name, pat=pat):
                    self.assertEqual(re.findall(pat, code), [],
                                     "{} 把缺失的额度补成了满格".format(f.name))

    def test_direction_helpers_are_used_not_hand_rolled(self):
        """agy 原生给**剩余**,grok 给**已用**。组件里出现 `100 - ` 就是在手搓换向。"""
        for f in (AGYCARD, AGYROW):
            code = strip_comments(f.read_text(encoding="utf-8"))
            with self.subTest(f=f.name):
                self.assertEqual(re.findall(r"100\s*-\s*\w", code), [],
                                 "{} 里手搓了方向换算 —— agy 本来就是剩余,"
                                 "这个减法要么多余要么反了".format(f.name))


if __name__ == "__main__":
    unittest.main()
