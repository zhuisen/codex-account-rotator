"""grok **在 UI 层**也不得混进轮换池。

Python 侧已经有一条同名的闸（`tests/test_grok_readonly.py::GrokIsNotInThePool`，守 `codex-rotate` /
`proxy.py` / `quota_daemon.py`）。这一条守的是**前端**，因为菜单栏里 grok 现在长得**和账号卡一模一样**
（用户 2026-08-24 选的：「保留现在的菜单栏样式，新增紫色的 grok」）——视觉一样，就更需要数据不一样。

会静默出错的到底是什么：`accounts` / `alive` / `aliveByLabel` 这几个数组同时驱动

  · **⌘1~⌘9 切号** —— `App.tsx` 里 `aliveByLabel[idx]` 直接 `run("switch", …)`
  · 头部计数徽章、Tab 上的「账号 N」、列表的「N 个」
  · 「探针 全池」提示里的号数（那是**计费**动作）
  · `useAutoSwitch` 的候选集

grok 一旦进了其中任何一个，⌘3 就可能"切"到一个根本切不了的东西上，计数会多 1，
探针会以为要打 4 个号——**没有一处会报错**，全是静默错值。所以视觉可以复用，数组必须分家。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
MENUBAR = SRC / "MenuBar.tsx"
APP = SRC / "App.tsx"
GROKROW = SRC / "components" / "GrokRow.tsx"

# 由账号池派生、且被索引/计数/切号消费的数组名。
POOL_ARRAYS = ("accounts", "alive", "aliveByLabel", "dead")


def strip_comments(src: str) -> str:
    """注释里正解释着这条规则，朴素匹配必被它染红（本仓库反复吃过的『grep 假阳性』）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


class GrokNeverEntersPoolArrays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mb = strip_comments(MENUBAR.read_text(encoding="utf-8"))
        cls.app = strip_comments(APP.read_text(encoding="utf-8"))

    def test_anchors_exist(self):
        """★ 先证明被测目标还在。改名之后断言会静默打空 —— 那是最坏的假绿。"""
        self.assertIn("aliveByLabel", self.app, "App.tsx 的 aliveByLabel 不见了,断言已失效")
        self.assertIn("<GrokRow", self.mb, "菜单栏没有渲染 GrokRow,这条闸在守一个不存在的东西")
        self.assertIn("useGrokQuota", self.mb)

    def test_pool_arrays_are_never_concatenated_with_grok(self):
        """池数组不得被 push / concat / 展开进 grok 数据。"""
        for src, name in ((self.mb, "MenuBar.tsx"), (self.app, "App.tsx")):
            for arr in POOL_ARRAYS:
                for pat in (rf"{arr}\s*\.\s*push\s*\(", rf"{arr}\s*\.\s*concat\s*\(",
                            rf"\[\s*\.\.\.\s*{arr}\s*,"):
                    hits = re.findall(pat, src)
                    with self.subTest(file=name, arr=arr, pat=pat):
                        self.assertEqual(hits, [],
                                         "{} 里 {} 被拼接了,grok 可能混进池数组".format(name, arr))

    def test_grok_snapshot_is_a_separate_binding(self):
        """菜单栏的 grok 数据必须来自 `useGrokQuota` 自己的返回值,不是从 accounts 里挑出来的。"""
        m = re.search(r"const\s*\{([^}]*)\}\s*=\s*useGrokQuota\(", self.mb)
        self.assertIsNotNone(m, "菜单栏没有独立调用 useGrokQuota")
        self.assertIn("snap", m.group(1))
        # 反向:不许出现"从 accounts 里找 grok"这种写法
        for pat in (r"accounts\.find\([^)]*grok", r"accounts\.filter\([^)]*grok"):
            self.assertEqual(re.findall(pat, self.mb, re.I), [],
                             "grok 是从 accounts 里挑出来的 —— 它根本不该在那里面")

    def test_grokrow_receives_snapshot_not_an_account(self):
        m = re.search(r"<GrokRow[^>]*snap=\{([^}]*)\}", self.mb)
        self.assertIsNotNone(m, "GrokRow 没有拿到 snap")
        self.assertIn("grok", m.group(1).lower())

    def test_grokrow_has_no_switch_affordance(self):
        """卡片这个形状本身在说"这是能切的号"。grok 切不了,所以**绝不能**长出切换入口。"""
        code = strip_comments(GROKROW.read_text(encoding="utf-8"))
        for bad in ("onSwitch", "mb-row-switch", '"switch"', "switching"):
            with self.subTest(token=bad):
                self.assertNotIn(bad, code,
                                 "GrokRow 出现了切换相关的 {} —— 它不在池里,切不了".format(bad))

    def test_grokrow_never_invokes_rotate_commands(self):
        code = strip_comments(GROKROW.read_text(encoding="utf-8"))
        for bad in ("run_rotate", "invoke(", "run("):
            with self.subTest(token=bad):
                self.assertNotIn(bad, code,
                                 "GrokRow 直接调了 {} —— 它只该展示,动作由调用方给".format(bad))

    def test_counts_do_not_include_grok(self):
        """头部徽章 / Tab 的「账号 N」/ 列表「N 个」全部来自池数组，不得掺 grok。"""
        for pat in (r"alive\.length\s*\+", r"counts\.\w+\s*\+\s*\(?\s*grok",
                    r"grok\w*\s*\?\s*1\s*:\s*0"):
            with self.subTest(pat=pat):
                self.assertEqual(re.findall(pat, self.mb, re.I), [],
                                 "计数里掺进了 grok:{}".format(pat))

    def test_probe_all_count_is_pool_only(self):
        """「探针 全池」是**计费**动作,它的号数多算一个就是多花一次钱。"""
        m = re.search(r"hint=\{`对 \$\{([^}]*)\}", self.mb)
        self.assertIsNotNone(m, "找不到探针提示里的号数 —— 断言可能打空了")
        self.assertNotIn("grok", m.group(1).lower())


class MenubarAlwaysNamesItsDestination(unittest.TestCase):
    """★ 菜单栏每个「打开主窗口」的入口都必须**指明去哪个版块**。

    用户 2026-08-25 报:在菜单栏点账号,进去却是用量页。根因是账号行调的是
    **不带事件**的 `openMain()` —— 主窗口就停在上次那一页,于是"去哪"由**上一次的浏览历史**
    决定,而不是由这次点了什么决定。

    ⚠️ 这个 bug 的形态值得记:它**不是每次都错**。上次停在总览时点账号是对的,
    停在用量页时才错 —— 「有时对有时错」比恒错更难被报上来,也更难复现。
    根治办法不是修那一处,是让「不指定目的地」这种写法**根本写不出来**。

    每个 `navigate-*` 事件也必须在 App.tsx 有对应监听,否则点了没反应且不报错。
    """
    DEST_EVENTS = ("navigate-overview", "navigate-traffic", "navigate-platform", "navigate-settings")

    @classmethod
    def setUpClass(cls):
        cls.mb = strip_comments(MENUBAR.read_text(encoding="utf-8"))
        cls.app = strip_comments(APP.read_text(encoding="utf-8"))

    def test_no_bare_open_main(self):
        """`openMain()` 不带参数 = 沿用上次的页面。"""
        bare = re.findall(r"openMain\(\s*\)", self.mb)
        self.assertEqual(bare, [],
                         "菜单栏有 {} 处 `openMain()` 没指定目的地 —— "
                         "落在哪一页取决于上次浏览到哪".format(len(bare)))

    def test_every_open_main_names_a_known_event(self):
        calls = re.findall(r'openMain\(\s*"([^"]+)"', self.mb)
        self.assertGreaterEqual(len(calls), 4, "抓到的入口太少 —— 断言可能打空了")
        for ev in set(calls):
            with self.subTest(event=ev):
                self.assertIn(ev, self.DEST_EVENTS, "菜单栏用了未登记的跳转事件 {}".format(ev))

    def test_every_event_has_a_listener(self):
        """★ 发了事件但主窗口没监听 = **点了没反应,而且不报错**。"""
        for ev in set(re.findall(r'openMain\(\s*"([^"]+)"', self.mb)):
            with self.subTest(event=ev):
                self.assertRegex(self.app, r'listen(?:<[^>]*>)?\(\s*"' + re.escape(ev) + r'"',
                                 "App.tsx 没有监听 {} —— 点了不会有反应".format(ev))

    def test_account_rows_go_to_overview(self):
        """账号行必须去总览,不是别的版块。"""
        rows = re.findall(r"<AccountRow[^>]*onSelect=\{([^}]*)\}", self.mb, re.S)
        self.assertGreaterEqual(len(rows), 2, "没抓到账号行(可用 + 失效两处)")
        for expr in rows:
            with self.subTest(expr=expr.strip()[:50]):
                self.assertIn("navigate-overview", expr,
                              "账号行没有去总览:{!r}".format(expr.strip()[:60]))


class GrokIsInvisibleWhenAbsent(unittest.TestCase):
    """★ **没装 grok 的机器上必须零像素。**

    用户 2026-08-24 问「其他用户没用到 grok,那个框还会出现吗」—— 会,而且当时还写着
    「本机没有 ~/.grok/auth.json」。那是一盏**永远亮着、又不需要任何动作**的灯,
    只会训练人忽略所有提示(项目已判过死刑的形态)。

    两层可见性,语义完全不同,都由 `grokQuotaVisible` 一处判定:
      ① 自动:`auth_file_missing` / `auth_file_empty` = 这台机器压根没有 grok。
         这是**确定的否定**,不是"读不到",所以隐藏不违反「读不到 ≠ 确实没有」。
      ② 手动:设置页 ›「AI 平台管理」停用 —— **复用既有开关,不新造第二套**。
    """
    def test_visibility_predicate_is_single_source(self):
        grok_ts = (SRC / "grok.ts").read_text(encoding="utf-8")
        self.assertIn("export function grokQuotaVisible", grok_ts,
                      "没有统一的可见性判据 —— 两个 surface 各写一份迟早分叉")
        for f in ("components/GrokCard.tsx", "components/GrokRow.tsx"):
            code = strip_comments((SRC / f).read_text(encoding="utf-8"))
            with self.subTest(f=f):
                self.assertIn("grokQuotaVisible(", code,
                              "{} 没走统一判据".format(f))
                self.assertIn("return null", code, "{} 不可见时没有真的返回 null".format(f))

    def test_absent_reasons_hide_the_card(self):
        """判据本身:这两个 reason 必须让它隐藏。从源解析,不在测试里粘一份副本。"""
        grok_ts = (SRC / "grok.ts").read_text(encoding="utf-8")
        i = grok_ts.index("export function grokQuotaVisible")
        body = grok_ts[i:]
        for reason in ("auth_file_missing", "auth_file_empty"):
            with self.subTest(reason=reason):
                self.assertIn(reason, body,
                              "{} 不会让 grok 卡隐藏 —— 没装 grok 的人会看到一张常驻空卡".format(reason))
        self.assertIn("disabled", body, "判据里没有『用户停用』这一层")

    def test_both_surfaces_receive_the_disabled_flag(self):
        """停用开关必须**两个 surface 都接** —— 只接一个的症状是「主窗没了、菜单栏还在」。"""
        for f, needle in (("App.tsx", "platPrefs.by?.grok?.off"),
                          ("MenuBar.tsx", "prefs.by?.grok?.off")):
            code = strip_comments((SRC / f).read_text(encoding="utf-8"))
            with self.subTest(f=f):
                self.assertIn(needle, code, "{} 没有把停用状态传下去".format(f))


if __name__ == "__main__":
    unittest.main()
