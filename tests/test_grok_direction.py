"""grok 额度的**方向**与**配色**闸（`GrokCard` 总览卡 + `GrokRow` 菜单栏行）。

起因不是预防,是复盘。这两条各自都真的犯过一次,而 tsc / cargo / 单元测试**全绿**:

  · 方向:细条填「剩余」旁边数字写「已用」——同一行两个方向,截图才看出来;
    改成三处统一「已用」后,挪到总览与账号卡(100/100/98)并排,一列数字 98·35·100
    仍然反向,用户当场指出。**自洽的单位不够,要与同屏邻居同向。**
  · 配色:用户 2026-08-24 定稿「grok 的所有颜色包括条形图和圆形图都是紫色的」。
    我先前主张"紫色只给身份、环按额度染绿琥珀",被明确否掉。

守四条:
  ① 环与条吃的是**剩余**(`rem` / `lgRem` / `shown`),不是已用。
  ② 换向**只能在 `grok.ts` 做** —— 组件里出现 `100 -` 就是把方向知识复制了一份。
  ③ 环与条的颜色走**调用方传进来的平台色**(`color`),不是 `quotaColor()`,也不是写死的 hex。
  ④ 失败态**仍走语义色** —— 那是"数据出问题了",与"额度水位"是两个轴;
     全染紫会让「读不到」和「读到了」长得一样,直接违反铁律「读不到 ≠ 确实没有」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "codexbar" / "src" / "components"
CARD = COMPONENTS / "GrokCard.tsx"
ROW = COMPONENTS / "GrokRow.tsx"
GROK_TS = ROOT / "codexbar" / "src" / "grok.ts"

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# 允许写死的颜色只有**失败/告警**语义色。额度本身的色必须来自 `color` prop。
ALLOWED_HEX = {"#E0524D", "#E0901C"}


def strip_comments(src: str) -> str:
    """注释里正解释着这些规则,朴素匹配必被它染红(本仓库反复吃过的『grep 假阳性』)。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


class GrokQuotaDirectionAndColor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {}
        for p in (CARD, ROW):
            raw = p.read_text(encoding="utf-8")
            cls.files[p.name] = (raw, strip_comments(raw))

    def test_anchors_exist(self):
        """★ 先证明被测目标还在。组件被删/改名后断言会静默打空 —— 那是最坏的假绿。"""
        self.assertTrue(CARD.exists() and ROW.exists())
        for name, (_, code) in self.files.items():
            with self.subTest(f=name):
                self.assertIn("<Ring", code, "{} 里没有环 —— 断言打空了".format(name))
                # ★ 允许降级分支覆盖(`degraded ? "#E0901C" : color`),但**平台色必须仍在表达式里** ——
                #   健康态的条永远是平台色。放松成 `background:` 就成了空守卫。
                self.assertRegex(code, r"background:\s*[^,;\n]*\bcolor\b",
                                 "{} 的条没用平台色".format(name))

    # ---- ① 方向 ------------------------------------------------------------

    def test_ring_and_bar_are_fed_remaining(self):
        """★ 占位环(`pct={0}` + track 色)要与真数据环分开判 —— 否则要么误报,
        要么为了放过它把断言放宽到"0 也算合格",那样真数据填 0 就再也拦不住了。
        判据是**颜色**:占位环用 `t.ringTrack`,真数据环用平台色 `color`。"""
        for name, (_, code) in self.files.items():
            rings = re.findall(r"<Ring\b[^>]*>", code, re.S)
            bars = re.findall(r"width:\s*`\$\{([^}]*)\}%`", code)
            with self.subTest(f=name):
                self.assertTrue(rings, "{}:没抓到 <Ring>".format(name))
                self.assertTrue(bars, "{}:没抓到细条的 width".format(name))
            for tag in rings:
                m = re.search(r"pct=\{([^}]*)\}", tag)
                self.assertIsNotNone(m, "{}:<Ring> 没有 pct".format(name))
                expr = m.group(1).strip()
                placeholder = "ringTrack" in tag and expr == "0"
                with self.subTest(f=name, expr=expr):
                    if placeholder:
                        continue          # 占位环:没有数据,画空环是对的
                    self.assertNotIn("used", expr,
                                     "{}:环填了已用,与同屏账号卡反向".format(name))
                    self.assertRegex(expr, r"[rR]em",
                                     "{}:环必须吃剩余,且变量名要带方向(裸 `pct` 不算):{!r}"
                                     .format(name, expr))
            for expr in bars:
                with self.subTest(f=name, expr=expr):
                    self.assertNotIn("used", expr,
                                     "{}:条填了已用,与同屏账号卡反向".format(name))
                    self.assertRegex(expr, r"[rR]em",
                                     "{}:条必须吃剩余,且变量名要带方向(裸 `pct` 不算):{!r}"
                                     .format(name, expr))

    # ---- ② 换向只在 grok.ts ---------------------------------------------------

    def test_no_hand_rolled_conversion(self):
        for name, (_, code) in self.files.items():
            with self.subTest(f=name):
                self.assertNotIn("100 -", code,
                                 "{}:手算了换向 —— 应走 grokRemPct / grokLastGoodRemPct".format(name))

    def test_helpers_carry_direction_in_their_names(self):
        exported = re.findall(r"export function (grok\w*)\(", GROK_TS.read_text(encoding="utf-8"))
        numeric = [n for n in exported if n.endswith("Pct")]
        self.assertTrue(numeric, "没找到返回百分比的导出函数 —— 断言可能打空了")
        for n in numeric:
            with self.subTest(name=n):
                self.assertTrue("Used" in n or "Rem" in n,
                                "{} 返回百分比却没在名字里说方向".format(n))

    # ---- ③ 配色:平台色由外部传入 ---------------------------------------------

    def test_no_quota_color_on_ring_or_bar(self):
        """`quotaColor()` 是绿/琥珀的语义色。用户定稿要全紫,所以它不该再出现在这两个组件里。"""
        for name, (_, code) in self.files.items():
            with self.subTest(f=name):
                self.assertNotIn("quotaColor", code,
                                 "{}:环/条又用回了语义色,用户定稿是恒紫".format(name))

    def test_platform_colour_is_injected_not_hardcoded(self):
        """写死 `#8b7cf6` 会让"用户在设置页给平台改色"失效(CLAUDE.md §5 的既有铁律)。"""
        for name, (_, code) in self.files.items():
            with self.subTest(f=name):
                self.assertRegex(code, r"color:\s*string",
                                 "{}:没有接收 color prop".format(name))
                found = {h.upper() for h in HEX.findall(code)}
                extra = found - {a.upper() for a in ALLOWED_HEX}
                self.assertEqual(extra, set(),
                                 "{}:写死了颜色 {} —— 额度色必须走 color prop,"
                                 "只有失败/告警语义色可以写死".format(name, sorted(extra)))

    # ---- ④ 失败态保留语义色 ---------------------------------------------------

    def test_failure_states_stay_disclosed(self):
        """「读不到」必须与「读到了」一眼可分 —— 全染紫就把这条铁律抹掉了。

        ★★ **2026-08-24 改口径**:降级**说明**从整条横幅退成一个感叹号 + 悬浮
        (用户定稿)。理由是 grok 的 token 寿命就是 6 小时,「已过期」按设计每天要弹几次
        且能自愈 —— **天天弹又自愈的横幅不是警报是噪音**,而噪音会训练人忽略真警报。

        所以这条闸守的**不再是"有没有横幅"**,而是那半不能让的:
          ① 失败态挂得上标记(`GrokStaleMark`),标记里带得到 reason 文案;
          ② **数字不假装是活的** —— 有旧读数就标「旧/上次」,没有就画 `—`,
             两条路径都**绝不出现 `0`**(`0%` 是"这周没用"的合法值)。
        """
        for name, (_, code) in self.files.items():
            with self.subTest(f=name):
                self.assertIn("<GrokStaleMark", code,
                              "{}:失败态没有任何标记 —— 那就成了静默吞掉".format(name))
                self.assertRegex(code, r"<GrokStaleMark[^>]*a=\{a\}",
                                 "{}:标记没拿到账号数据,悬浮说明会是空的".format(name))

    def test_degraded_number_never_looks_live(self):
        """★★ 这是**降级里唯一不可退让**的一条:数字绝不假装是活的。

        标记可以小到一个字符,但读数必须自己说明它是旧的 —— 否则用户看到一个正常的
        百分比,没有任何办法知道它是 3 小时前的。**省掉的是解释,不是披露。**
        """
        for name, (_, code) in self.files.items():
            with self.subTest(f=name):
                # ★ 琥珀必须**绑在降级分支上**。只查 `'"#E0901C"' in code` 会被
                #   `numColor` / `glow` 里的同一个色值满足 ⇒ 把底注那处改成 `t.muted`
                #   照样绿(变异测试第 N 次抓到同款:**同一个字面量出现在别处 ≠ 这一处还在**)。
                self.assertRegex(code, r'(degraded|stale)[^;\n]{0,48}"#E0901C"',
                                 "{}:旧读数没有强制琥珀,会和当前读数长得一样".format(name))
                # 没有旧读数时画 `—`,不画 0
                self.assertIn('"—"', code,
                              "{}:没有旧读数时没画占位符 —— 可能画成了 0".format(name))
                self.assertRegex(code, r"上次读数|的读数|暂时读不到",
                                 "{}:降级态没有一句话说明这个数是旧的".format(name))

    def test_low_quota_still_warns_somewhere(self):
        """环恒紫之后,低额度不能变成完全无声 —— 数字阈值色 + glow 是仅剩的两个报警口。

        ★ 同样断言**接线**:`const glow = …` 留着但不传给 `<Ring>`,光晕就永远不亮,
        而"glow 这个词出现过"照样成立(第一版就是这么假绿的)。"""
        for name, (_, code) in self.files.items():
            with self.subTest(f=name):
                # 两种写法都要认:JSX prop `color={numColor(x)}` 与样式对象 `color: numColor`。
                # 只认其中一种就会在另一个组件上假绿 —— 第一版正是如此。
                # 同上:降级分支可以覆盖成琥珀,但**健康态的阈值色必须仍接着** ——
                # 那是环恒紫之后仅剩的两个报警口之一。
                self.assertRegex(code, r"color[:=]\s*\{?\s*[^,;\n]*numColor",
                                 "{}:数字没有接上阈值色".format(name))
                self.assertRegex(code, r"<Ring\b[^>]*glow=\{",
                                 "{}:glow 没有传给 <Ring>,低额度时不会亮".format(name))
                self.assertIn("#E0524D", code, "{}:没有危险色阈值".format(name))


if __name__ == "__main__":
    unittest.main()
