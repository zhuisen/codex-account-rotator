"""「AI用量信息」与「平台详情」是**同一族的两页**，交接稿 §1/§5 给的骨架必须都在。

## 由来（2026-09-13，用户实报「ai 总览的内容和位置不是 1:1」）

逐项比对交接稿 `流量总览-交接说明.md` 与实机，两处缺口：

1. **数据源副标整行不存在**（稿 §1「汇总各 CLI 本地 transcript · 不消耗额度」、
   §5「读本地 transcript · 不消耗额度」）。它不是装饰 —— `不消耗额度` 是本仓反复
   强调的披露，而"这页会不会花我的钱"正是第一次看到它时会问的。
2. **「请求数」这一格只在详情页有**（那边叫「请求轮数」），总览没有。
   而 `grandRounds` 一直在算、没人消费 —— **后端有值 ≠ 已披露**，本仓的老形态。

★ 判据两边都从源码解析，不手列：`KpiStrip` 的 `items` 里那些 `k:` 字面量。
  这两页共用 `KpiStrip` 正是因为它们此前**各写一份渲染、漂过两次**。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
PAGES = {"总览": SRC / "pages" / "TrafficPage.tsx",
         "详情": SRC / "pages" / "PlatformPage.tsx"}


def code(p):
    """剥掉 JSX 注释与行注释 —— 本仓注释密度极高，闸撞上自己的说明文字已是惯犯（形态⑫）。"""
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


def kpi_blocks(p):
    """`const kpis` 的两份骨架（`loading ? [...] : [...]`），每份是**列名按序**的列表。

    ⚠️ 三个坑，全都踩过：
      1. **必须先切到那个数组块** —— 整文件扫 `k: "…"` 会把别处的 KPI 定义也收进来。
      2. **按数组元素数，不按 `k:` 出现次数** —— `{ k: isToday ? "较昨日" : "日均" }`
         是**一格两名**，数字面量会把它算成两格（或在占位骨架里一格都算不到）。
         所以按花括号深度切元素，每个元素取它的第一个字符串字面量。
      3. 定长切片会滑进下一段，所以按 `];` 这个结构边界收尾。
    """
    body = code(p)
    start = body.index("const kpis")
    blk = body[start:body.index("\n  ];", start)]
    parts = blk.split("] : [")
    out = []
    for part in parts:
        cols, depth, buf = [], 0, ""
        for ch in part:
            if ch == "{":
                depth += 1
                if depth == 1:
                    buf = ""
                    continue
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    m = re.search(r'k:\s*(?:[^,]*?\?\s*)?"([^"]+)"', buf)
                    if m:
                        cols.append(m.group(1))
                    continue
            if depth >= 1:
                buf += ch
        out.append(cols)
    return out


class BothUsagePagesCarryTheHandoffSkeleton(unittest.TestCase):

    def test_the_loading_skeleton_carries_the_same_columns(self):
        """★★ 占位骨架的列**必须是加载完那组的子集，且一格都不能少**。

        不一致的症状是数据一到 KPI 条整条重排抖一下（`space-evenly` 会重新均分），
        而这既不报错、也不会被任何截图探针发现 —— 我这次加「请求数」时就只加了一边。

        ⚠️ 这里比的是**名字集合**不是个数：加载完那组里 `isToday ? {A} : {B}` 是
        一格两名，按个数比会永远对不上（第一版就是这么假红的）。
        """
        for name, p in PAGES.items():
            blocks = kpi_blocks(p)
            if len(blocks) < 2:
                continue
            with self.subTest(page=name):
                skel, real = set(blocks[0]), set(blocks[1])
                self.assertEqual(skel - real, set(),
                                 f"★★ {name} 占位骨架里有加载完没有的列: {skel - real}")
                # 反方向只挑必须常驻的那几格 —— `日均`/`日均费用` 在今日档会换名，不能全量比
                for k in ("总 token", "总费用"):
                    self.assertIn(k, skel, f"★★ {name} 的占位骨架缺「{k}」")
                self.assertTrue(any("请求" in k for k in skel),
                                f"★★ {name} 的占位骨架缺请求数 ⇒ 数据一到整条 KPI 会重排")

    def test_the_probe_finds_kpis_on_both(self):
        """★ 先证探针有效 —— 解析到 0 个 KPI 会让整条闸恒绿。"""
        for name, p in PAGES.items():
            with self.subTest(page=name):
                self.assertGreaterEqual(len(kpi_blocks(p)[-1]), 4,
                                        f"{name} 只解析到 {kpi_blocks(p)[-1]} —— 正则跟不上写法了")

    def test_each_page_has_a_source_subtitle(self):
        for name, p in PAGES.items():
            with self.subTest(page=name):
                body = code(p)
                self.assertIn("<PageSub", body, f"★★ {name} 没有数据源副标（稿 §1/§5）")
                # ★ 判据打在**那句披露**上，不是"有没有这个组件" —— 组件在、文案换成
                #   「数据源」三个字，用户仍然不知道这页花不花钱。
                i = body.index("<PageSub")
                self.assertIn("不消耗额度", body[i:i + 200],
                              f"★★ {name} 的副标没说「不消耗额度」")

    def test_the_request_count_is_disclosed_on_both(self):
        """★★ 两页都要有请求数这一格。稿里两页用词不同（主页「请求数」/ 详情「请求轮数」），
        所以判据是**含「请求」二字的那一格存在**，不是逐字相等。"""
        for name, p in PAGES.items():
            with self.subTest(page=name):
                hit = [k for k in kpi_blocks(p)[-1] if "请求" in k]
                self.assertTrue(hit, f"★★ {name} 的 KPI 里没有请求数: {kpi_blocks(p)[-1]}")

    def test_it_sits_right_after_the_token_total(self):
        """★ 稿 §1/§5 里它都紧跟在「合计 token」后面（第 2 列）。位置也是 1:1 的一部分 ——
        用户这次报的正是「内容**和位置**」。

        ⚠️ 判据用**相邻**而不是下标 `== 1`：今日档那两格（`较昨日`/`费用较昨日`）是三元
        分支里的**替代项**不是额外列，按下标数会把它们算进去。"""
        for name, p in PAGES.items():
            with self.subTest(page=name):
                keys = kpi_blocks(p)[-1]
                i = next(i for i, k in enumerate(keys) if k.startswith("总 token"))
                j = next(j for j, k in enumerate(keys) if "请求" in k)
                self.assertEqual(j, i + 1,
                                 f"★ {name} 的请求数没有紧跟在 token 合计后面: {keys}")

    def test_the_shared_money_columns_agree(self):
        """★ 两页共有的那几格用词必须一致，否则读者在两页之间切换时要重新认一遍。"""
        for k in ("总 token", "总费用"):
            for name, p in PAGES.items():
                with self.subTest(page=name, col=k):
                    self.assertIn(k, kpi_blocks(p)[-1], f"★ {name} 缺「{k}」")

    def test_the_rounds_field_is_actually_consumed(self):
        """★★ `grandRounds` 此前算了却没人用 —— 孤儿字段是「后端有值 ≠ 已披露」的形态。
        判据打在**消费点**上，不是"这个字段存在"。"""
        self.assertIn("view?.grandRounds", code(PAGES["总览"]),
                      "★★ grandRounds 又变回孤儿字段了")


if __name__ == "__main__":
    unittest.main()
