"""额度窗口判据的**三处一致性**闸。

起因:2026-08-25 用户报「Plus 的 5 小时额度回来了」。实测 `state.json` 确认 ——
plus5 的 `primary.window_minutes = 300`(5 小时)、weekly 退到了 `secondary`。

**为什么旧代码会丢掉它**:这段逻辑要挡的东西从没变过 —— Codex 仍会返回**空槽**
`{window_minutes: 0, resets_at: null}`。但 2026-07 那会儿真窗口只剩周(10080)/月(43200),
于是「够大(>=5000)」**恰好等价于**「非空」,当时就用了这个代理判据。
5h 回归后等价关系断了(`300 < 5000`)—— **一个合法窗口被当垃圾丢掉,用户看不到自己的额度。**

★ 教训不是"阈值调小点",是**别用量级去猜语义**:量级一变,判据就失效,而且失效得很安静。

**为什么必须做成闸**:同一判据有**三份副本**,跨语言没法共用:
  · `codexbar/src/helpers.ts` —— 主界面
  · `codex-rotate`            —— CLI
  · `codexbar/src-tauri/src/lib.rs` —— **托盘标题**
漏改任何一份的症状都是"有的地方看得见 5h、有的地方看不见",**没有一处会报错**。
(与仓库里 `quotaColor` / `rem_rgb` 那对同族:CLAUDE.md 明写「改阈值必须两处一起改」。)
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "codexbar" / "src" / "helpers.ts"
ROTATE = ROOT / "codex-rotate"
LIB_RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"


def strip_comments(src: str) -> str:
    """注释里正解释着这条规则(还引用了旧阈值 5000),朴素匹配必被它染红。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return re.sub(r"^\s*#[^\n]*", "", src, flags=re.M)


class WindowPredicateIsConsistent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = strip_comments(HELPERS.read_text(encoding="utf-8"))
        cls.py = strip_comments(ROTATE.read_text(encoding="utf-8"))
        cls.rs = strip_comments(LIB_RS.read_text(encoding="utf-8"))

    def test_anchors_exist(self):
        """★ 先证明三个被测目标都还在 —— 改名后断言会静默打空。"""
        self.assertIn("REAL_WINDOW_MIN", self.ts, "helpers.ts 里的判据不见了")
        self.assertIn("REAL_WINDOW_MIN", self.py, "codex-rotate 里的判据不见了")
        self.assertIn("window_minutes", self.rs, "lib.rs 托盘不再读 window_minutes?")

    def test_no_copy_still_discards_the_5h_window(self):
        """★★ 三份都不得再按量级丢窗口。5h = 300 分钟,任何 >300 的下限都会吞掉它。"""
        for name, src, pat in (
            ("helpers.ts", self.ts, r"REAL_WINDOW_MIN\s*=\s*(\d+)"),
            ("codex-rotate", self.py, r"REAL_WINDOW_MIN\s*=\s*(\d+)"),
        ):
            m = re.search(pat, src)
            with self.subTest(f=name):
                self.assertIsNotNone(m, "{}:找不到阈值".format(name))
                v = int(m.group(1))
                self.assertLessEqual(v, 300,
                                     "{} 的下限是 {},会把 5 小时窗口(300)当空槽丢掉".format(name, v))

    def test_rust_tray_does_not_discard_the_5h_window(self):
        """托盘那份是 Rust 写死的比较,不走常量 —— 单独断言。

        ★ 必须**只挑「有效性」那个比较**。第一版把所有 `wm >= N` 都收进来,于是
        标签用的 `wm >= 40000.0`(月/周分档)也被当成下限报红 —— **同一个变量的比较,
        语义完全不同**。判据:有效性那处紧跟 `used_percent` 一起决定要不要这个窗口。
        """
        m = re.search(r"let wm = [^;]*;\s*let used[^;]*;\s*match \(wm\s*([><=]+)\s*([0-9.]+)",
                      self.rs, re.S)
        self.assertIsNotNone(m, "找不到托盘的窗口有效性判断 —— 断言可能打空了")
        op, v = m.group(1), float(m.group(2))
        self.assertIn(op, (">", ">="), "有效性判断的方向反了")
        self.assertLessEqual(v, 300.0,
                             "lib.rs 托盘的下限是 {},会丢掉 5 小时窗口".format(v))

    def test_labels_cover_short_windows(self):
        """★★ 标签必须按**实际时长**分档。旧版是 `>=40000 ? 月 : 周` —— 300 分钟会被标成「周」,
        **那比不显示更糟:它把 5 小时的余量说成一周的余量。**

        三份都要有「周」那一档(10000)和更短的档(1440),否则短窗口会掉进「周」里。
        """
        for name, src in (("helpers.ts", self.ts), ("codex-rotate", self.py), ("lib.rs", self.rs)):
            with self.subTest(f=name):
                self.assertRegex(src, r"\b10000(?:\.0)?\b",
                                 "{}:标签没有「周」这一档,短窗口会被并进周".format(name))
                self.assertRegex(src, r"\b1440(?:\.0)?\b",
                                 "{}:标签没有比周更短的档 —— 5h 会被标成周".format(name))

    def test_real_state_still_parses(self):
        """★ 拿**真实 state.json** 交叉验证:5h 窗口确实在,且判据不会丢掉它。

        这条是"用真数据验"而不是"用夹具验" —— 这次的 bug 正是真数据变了才暴露的。
        没有 5h 窗口的机器上自动跳过(不制造假红)。
        """
        state = ROOT / "state.json"
        if not state.exists():
            self.skipTest("本机没有 state.json")
        d = json.loads(state.read_text(encoding="utf-8"))
        wins = []
        for s in (d.get("slots") or {}).values():
            q = s.get("quota") or {}
            for k in ("primary", "secondary"):
                wm = (q.get(k) or {}).get("window_minutes")
                if wm:
                    wins.append(wm)
        if not any(w and w < 5000 for w in wins):
            self.skipTest("本机当前没有短于 5000 分钟的窗口,无从验证")
        m = re.search(r"REAL_WINDOW_MIN\s*=\s*(\d+)", self.ts)
        short = min(w for w in wins if w < 5000)
        self.assertLessEqual(int(m.group(1)), short,
                             "真实数据里有 {} 分钟的窗口,而判据下限是 {} —— 它会被丢掉"
                             .format(short, m.group(1)))


class HeroRingLabelMatchesItsNumber(unittest.TestCase):
    """★★ hero 环的数字取 `tightest`(跨窗口最小),标签**必须取同一个窗口**的名字。

    只有一个窗口时两者永远一致,所以这个缺陷在 5h 缺席的那一年里根本不可能暴露。
    5h 回归 ⇒ Plus 号有两个窗口 ⇒ 数字可能来自周、标签却写着「5h」。
    **这是"恢复 5h"这件事本身引入的缺陷,不是老 bug。**
    """
    SURFACES = ("App.tsx", "components/AccountCard.tsx", "components/AccountRow.tsx")

    def test_no_surface_summarises_with_the_first_window(self):
        """★★ **单个汇总数字一律取「最紧」的窗口**,四个 surface 都是:
        hero 环、卡片环、菜单栏行、托盘标题。

        `windows[0]` 是 primary —— plus 号的 primary 现在是 **5h**,而真正卡住人的
        可能是周。用第一个 = **把约束藏起来**,而且它显示的还是个正常的绿数字。
        只有"有空间列清单"的地方(卡片下方的细条)才该把 `windows` 全画出来。
        """
        for rel in self.SURFACES:
            code = strip_comments((ROOT / "codexbar" / "src" / rel).read_text(encoding="utf-8"))
            with self.subTest(f=rel):
                self.assertNotRegex(code, r"windows\[0\]",
                                    "{}:还在用 windows[0] 做汇总 —— 会藏掉更紧的那个窗口".format(rel))
                self.assertRegex(code, r"tightest",
                                 "{}:没有用 tightest".format(rel))

    def test_helpers_derives_tightest_from_the_window_list(self):
        ts = strip_comments(HELPERS.read_text(encoding="utf-8"))
        self.assertIn("tightestWin", ts, "helpers 没有导出 tightestWin")
        self.assertRegex(ts, r"reduce\(\(a, b\) =>",
                         "tightest 不是从窗口列表里挑出来的,拿不到它是哪个窗口")


class WindowColourRule(unittest.TestCase):
    """★★ C′：**窗口识别色 + 低额度夺色**（用户 2026-08-26 定稿）。

    两个诉求本来打架，这条规则是它们的和解：
      · 「5h 和周的颜色不一样」→ 平时按**窗口**取色（青 / 绿）；
      · 「低额度靠条色报警」  → **跌破阈值时警告色夺回条色**。
    即 **识别是常态，报警是例外，而例外优先** —— 额度快没了的时候，
    「这是哪个窗口」远不如「这个要没了」重要。

    这条闸守两件事：
      ① 夺色**真的在**（低额度必须返回警告色，不能只按窗口分色）；
      ② 两个 surface **不许各写一份** —— 菜单栏行与总览卡都必须调同一个函数。
         本项目在 grok 那边栽过一次：同一状态两个 surface 两种画法，靠截图才发现。
    """
    SURFACES = ("components/AccountRow.tsx", "components/AccountCard.tsx")

    @classmethod
    def setUpClass(cls):
        cls.ts = strip_comments(HELPERS.read_text(encoding="utf-8"))

    def test_low_quota_takes_over_the_bar_colour(self):
        """★ 用户要求①：低额度靠条色报警。判据打在函数体上，不是"这个词出现过"。"""
        i = self.ts.index("export function winBarColor")
        body = self.ts[i:self.ts.index("\n}", i)]
        self.assertRegex(body, r'return\s*"#E0901C"',
                         "低额度不再返回琥珀 —— 条色报警没了")
        self.assertRegex(body, r'return\s*"#E0524D"',
                         "危险档不再返回红")
        # ★ 夺色必须**排在**识别色之前,否则永远轮不到
        warn = min(body.index('"#E0901C"'), body.index('"#E0524D"'))
        self.assertLess(warn, body.index("winColor("),
                        "警告色排在识别色之后 —— 那样低额度永远夺不到色")

    def test_identity_colour_survives_at_healthy_levels(self):
        """反向:别把窗口识别色整个删掉 —— 那就退回改动前了。"""
        i = self.ts.index("export function winBarColor")
        body = self.ts[i:self.ts.index("\n}", i)]
        self.assertIn("winColor(", body, "正常档不再按窗口取色,双色相没了")

    def test_both_surfaces_use_the_same_rule(self):
        for rel in self.SURFACES:
            code = strip_comments((ROOT / "codexbar" / "src" / rel).read_text(encoding="utf-8"))
            with self.subTest(f=rel):
                self.assertIn("winBarColor(", code, "{} 没走统一的配色规则".format(rel))
                self.assertNotIn("quotaColor(", code,
                                 "{} 还在直接用 quotaColor —— 与另一个 surface 会分叉".format(rel))


class NumberAndBarNeverDisagree(unittest.TestCase):
    """★★ 策略③：**百分比数字与条形共用同一套阈值**（用户 2026-08-26 定稿）。

    改动前三个 surface **各写一份，而且写的还不一样**：
      · `AccountCard` / `AccountRow` —— `pct < 50 ? 琥珀 : 次级灰`，**没有红档**；
      · `GrokCard`                   —— 三档（≤10 红 / <50 琥珀 / 否则灰）。
    症状：剩 7% 时**条是红的、账号卡的数字却是琥珀** —— 同一个状态两种说法，
    而它不报错、不折行、不溢出，任何自动化都看不见，只能靠人盯着截图。

    这条闸守三件事：
      ① 判据只有**一处**（`quotaLevel`），条色与数字色都从它取；
      ② 数字**有红档**（回到两档就等于把危险说成警告）；
      ③ 三个 surface 都调 `winNumColor`，谁也不许再手写一份。
    """
    SURFACES = ("components/AccountCard.tsx", "components/AccountRow.tsx", "components/GrokCard.tsx")

    @classmethod
    def setUpClass(cls):
        cls.ts = strip_comments(HELPERS.read_text(encoding="utf-8"))

    def test_single_threshold_predicate(self):
        """★ 条色与数字色必须**都**走 `quotaLevel` —— 两处各写一串 if 迟早分叉。"""
        self.assertIn("function quotaLevel", self.ts, "quotaLevel 不见了")
        for fn in ("winBarColor", "winNumColor"):
            i = self.ts.index("export function {}".format(fn))
            body = self.ts[i:self.ts.index("\n}", i)]
            with self.subTest(f=fn):
                self.assertIn("quotaLevel(", body,
                              "{} 没有走 quotaLevel —— 阈值又变成两份了".format(fn))

    def test_number_keeps_a_danger_level(self):
        """★★ 数字必须有红档。退回两档 = 把「危险」说成「警告」，而条还是红的。"""
        i = self.ts.index("export function winNumColor")
        body = self.ts[i:self.ts.index("\n}", i)]
        self.assertRegex(body, r'return\s*"#E0524D"', "数字没有危险档(红)")
        self.assertRegex(body, r'return\s*"#E0901C"', "数字没有警告档(琥珀)")
        self.assertIn("t.text2", body, "数字正常态不再是中性灰 —— 策略③的前半句没了")

    def test_normal_state_stays_neutral(self):
        """反向：正常态**不许**染窗口识别色（那是策略②，用户没选它）。

        判据打在函数体上：`winNumColor` 里不该出现 `winColor(`。
        """
        i = self.ts.index("export function winNumColor")
        body = self.ts[i:self.ts.index("\n}", i)]
        self.assertNotIn("winColor(", body,
                         "数字正常态跟着染窗口色了 —— 那是策略②，一屏六个彩色数字")

    def test_no_surface_hand_rolls_the_rule(self):
        for rel in self.SURFACES:
            code = strip_comments((ROOT / "codexbar" / "src" / rel).read_text(encoding="utf-8"))
            with self.subTest(f=rel):
                self.assertIn("winNumColor(", code,
                              "{}:没走统一的数字取色".format(rel))
                self.assertNotRegex(
                    code, r"pct\s*<\s*50\s*\?",
                    "{}:又手写了一份 `pct < 50 ?` 阈值 —— 这正是本闸要挡的".format(rel))


if __name__ == "__main__":
    unittest.main()
