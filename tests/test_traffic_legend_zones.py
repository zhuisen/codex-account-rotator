"""用量总览「平台图例」**主次双区**的不变量闸（用户 2026-08-26 选的 D 档）。

背景：平台数从 5 涨到 7（本机快照实测），单列图例每多一个平台就多 28px，
用户报「窗口要上下很长」。改成前 3 名完整行 + 其余紧凑格，紧凑格列数随宽度自适应。

这条闸守的**不是排版好不好看**，而是三件"坏了也不报错"的事：

  ① **没有平台会从两个区之间掉出去**。头部 `slice(0, N)` 与长尾 `slice(N)` 的 N
     **必须是同一个数**。写成 `slice(0,3)` + `slice(4)` 会静默吞掉第 4 名 ——
     页面照常渲染、总量 KPI 照常正确，只是那个平台**不见了**。
     这正是本仓库反复强调的「读不到 ≠ 确实没有」在 UI 层的形态。
  ② **两个区共用同一个分母**。占比分头各算一份的话，长尾的 % 会以自己的小计为分母，
     算出来的数**看起来完全正常**（还是 0~100 的百分比），却和头部不可比。
  ③ **长尾格保留全部交互**。完整行有 `onDrill`（点进平台详情）与 `setHoverKey`
     （悬停点亮堆叠图对应层）；长尾少接一个的症状是"这几个平台悬停没反应"，
     不抛错、只是行为悄悄少了一半。

另外守一条排版判据：紧凑区必须用 `auto-fit`，**不许写死列数** ——
用户明确要「跟着界面尺寸大小选择一行 4 个还是 3 个」，写死列数就是把一个会变的量钉进布局。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src" / "pages" / "TrafficPage.tsx"


def strip_comments(src: str) -> str:
    """注释里正解释着这些规则（还写着 `slice`、`auto-fit` 等词），朴素匹配必被它染绿。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


class LegendZonesNeverLoseAPlatform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = strip_comments(SRC.read_text(encoding="utf-8"))

    def test_anchors_exist(self):
        """★ 先证明被测目标还在 —— 改名后下面的断言会静默打空。"""
        for name in ("legendHead", "legendTail", "legendGrand"):
            self.assertIn(name, self.code, "{} 不见了 —— 断言可能打空了".format(name))

    def test_head_and_tail_split_at_the_same_index(self):
        """★★ ① 切分点必须同源。两个 slice 的下标不同 = 有平台被静默吞掉。"""
        head = re.search(r"legendHead\s*=[^;]*?\.slice\(0,\s*(\d+)\)", self.code, re.S)
        tail = re.search(r"legendTail\s*=[^;]*?\.slice\((\d+)\)", self.code, re.S)
        self.assertIsNotNone(head, "找不到头部的 slice —— 断言可能打空了")
        self.assertIsNotNone(tail, "找不到长尾的 slice —— 断言可能打空了")
        self.assertEqual(head.group(1), tail.group(1),
                         "头部取前 {} 个、长尾从第 {} 个开始 —— 中间的平台会**消失**，"
                         "而页面不会报任何错".format(head.group(1), tail.group(1)))

    def test_split_only_when_the_tail_is_worth_a_zone(self):
        """长尾只有 1 个时不该分区：读者要多认一种版式，却什么也没省。

        判据：阈值必须**严格大于**切分点（切分点 3 ⇒ 阈值 ≥4，取 5 才保证长尾 ≥2）。
        """
        m = re.search(r"twoZone\s*=\s*\([^)]*\)\s*>=\s*(\d+)", self.code)
        self.assertIsNotNone(m, "找不到分区阈值 —— 断言可能打空了")
        head = re.search(r"legendHead\s*=[^;]*?\.slice\(0,\s*(\d+)\)", self.code, re.S)
        # ★ 必须 **+2**，不是"大于"。发版前评审抓到：`assertGreater(4, 3)` 为真，
        #   于是把 `>= 5` 改成 `>= 4` 这条照样绿，而 4 个平台会渲染成
        #   3 行完整 + **1 个孤零零的紧凑格** —— 正是这条 docstring 说要挡的东西。
        #   **断言比自己的注释弱**，是本仓库的老毛病（子串存在 ≠ 规则存在的同族）。
        self.assertGreaterEqual(int(m.group(1)), int(head.group(1)) + 2,
                                "阈值 {} 不足以保证长尾 ≥2（切分点 {}）—— "
                                "会出现只有 1 个长尾的分区".format(m.group(1), head.group(1)))

    def test_both_zones_share_one_denominator(self):
        """★★ ② 两个区的占比必须用同一个分母。

        ★ 判据**只打在图例那一段**。第一版写成全文 `assertNotIn("view.grand")`，
          结果把 KPI 区里合法的 `view!.grand`（「最大占比」那一格）也判成违规 ——
          **一个会挡住正确代码的闸，比没有闸更糟**：它逼着下一个人去绕过它。
        """
        seg = self.code[self.code.index("legendHead.map"):]
        seg = seg[:seg.index("PlatformCard")]
        self.assertNotRegex(seg, r"view[!?]?\.grand",
                            "图例里又直接读 view.grand 了 —— 两个区应共用 legendGrand 这一个基准")
        # ★★ 必须**分别**锚到两个区。原来写 `seg.count("legendGrand") >= 2`，
        #    那是**子串计数**：把长尾那处改名成 `legendGrandTail`（一个很自然的名字）
        #    计数仍是 2、`view.grand` 正则也不响，而长尾的占比会按长尾小计归一化 ——
        #    两个区各自加到 100%，**数字看起来完全正常**。发版前评审抓到。
        cut = seg.index("legendTail.map")
        head_seg, tail_seg = seg[:cut], seg[cut:]
        self.assertRegex(head_seg, r"\blegendGrand\b", "头部没有用 legendGrand")
        self.assertRegex(tail_seg, r"\blegendGrand\b",
                         "长尾没有用 legendGrand —— 它会用自己的小计当分母")

    def test_tail_keeps_every_interaction_the_full_row_has(self):
        """★★ ③ 长尾格的交互必须与完整行一致。判据打在**长尾那段代码**上，不是全文。"""
        i = self.code.index("legendTail.map")
        tail_block = self.code[i:i + 2200]
        for handler in ("onDrill(", "setHoverKey("):
            self.assertIn(handler, tail_block,
                          "长尾格没有接 {} —— 这几个平台会点不动/悬停没反应".format(handler))

    def test_tail_columns_are_width_driven_not_hardcoded(self):
        """用户要求「跟着界面尺寸选一行 4 个还是 3 个」。写死列数就是把会变的量钉死。"""
        i = self.code.index("legendTail.length > 0")
        block = self.code[i:i + 700]
        self.assertNotRegex(block, r"repeat\(\s*\d+\s*,",
                            "紧凑区写死了列数 —— 窗口变宽/变窄都不会跟着变")
        # ★★ 必须是 `auto-fill`，**`auto-fit` 是错的那个**：它会把空轨塌缩，
        #    于是长尾只有 2~3 个时，剩下的 `1fr` 把每格拉到 ~630px —— 名字孤零零在最左、
        #    中间大片空白，与「紧凑区」的目标正好相反。
        #    实测（1276px 容器）：2 格 auto-fit 631px / auto-fill 309px；
        #    **4 格时两者都是 309px** —— 当前 7 个平台（长尾恒为 4）看不出差别，
        #    所以这条只能靠断言守，截图和现有夹具都证伪不了它。
        self.assertIn("auto-fill", block, "紧凑区没有用 auto-fill，列数不会随宽度变")
        self.assertNotIn("auto-fit", block,
                         "用了 auto-fit —— 长尾 2~3 个时空轨塌缩，每格被拉成 ~630px")

    def test_tail_name_has_a_width_floor(self):
        """★ 名字要有下限。没有下限时 flex 会把它压到截断成 `Anti…`/`Dee…`，
        **认不出是哪个平台，比少放一格严重得多**（2026-08-26 实测踩过一次）。"""
        i = self.code.index("legendTail.map")
        block = self.code[i:i + 2200]
        self.assertRegex(block, r"minWidth:\s*[1-9]\d",
                         "长尾的平台名没有宽度下限，会被压成省略号")


if __name__ == "__main__":
    unittest.main()
