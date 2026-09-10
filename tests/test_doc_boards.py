"""★★★ 两份会无限长的文档，各给一条闸。

## 为什么是闸而不是一条规则

`memory.md` 的**第一行**就写着「只写进行时 · 软上限 ~60 行」。
2026-09-10 实测：**522 行**，8.7 倍，里面塞满了已发布批次。
本仓自己记过的那条正好命中：**「一条没有闸的规则会被违反，包括被写它的人违反」**。
所以这里不再重申规则，只让它红。

## 两份文件的处置**故意不同**

- `memory.md` = 现况板 → **压**。已发布的条目搬去 CHANGELOG，板上留指针。
  它的价值在于"下一个会话读它就知道现在在干什么"，长了就没人读完，等于没有。
- `CHANGELOG.md` = 历史 → **不压，到点分卷**。它是唯一记着"当时实测数字"的地方
  （B36 那次靠一条 `git log -S` 就看出某条注释是三个月前的权衡、其数据早已过期）。
  摘要会把不可再生的那部分磨掉，所以只准整段搬去 `docs/CHANGELOG-archive-*.md`。

## ⚠️ `memory.md` 是 gitignored

干净 checkout（CI）上它不存在 —— 那一档必须 `skipTest` 并**说出原因**，
不能静默通过（静默通过与"检查过了没问题"在报告里长得一模一样）。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "memory.md"
CHANGELOG = ROOT / "CHANGELOG.md"

# 现况板的行数阀。
#
# ★★ **它是一条「增长」闸，不是「理想长度」闸。** 定阀那天（2026-09-10）先做了一次
#    真实搬运：522 → 237 行，把已发布的批次搬进 CHANGELOG、把「弃案与负面结论」
#    整段（**逐字，不摘要**）搬进 CHANGELOG。剩下的 ~230 行**逐节核过，全是真开着的**
#    （14 条未修的评审发现、未复现的容量问题、已发版但验证仍有缺口的一长串…）。
#
#    所以阀**不是** 60（它自称的那个数），也不是 150 —— 那两个数今天都要求删掉真条目，
#    而一条天天红、只能靠删真东西才能变绿的闸，用户学会的是关掉它。
#    阀定在诚实残量之上留一点余量：**它在下一次臃肿时响，不在今天响。**
#
# ⚠️ **要调高这个数，必须在同一个 commit 里先搬走点什么，并说明搬去了哪。**
#    单独调高它 = 把闸拆了还留个壳。
BOARD_MAX_LINES = 245

# 章节标题里出现这些 = 这件事**已经结束了**，属于 CHANGELOG 不属于现况板。
DONE_MARKERS = ("已完成", "已部署", "已发版", "✅", "已修", "已清空", "已上线")
# 这些是**决策/状态**标记，不是"活干完了"，留在板上是对的。
#
# ⚠️ 第一版只列了「未…」几个词，于是把 `1c. 已发版、**待真机回归**` 与
#    `1a. 已发版**但验证仍有缺口**` 判成了该搬 —— 两条都还开着，那是**假红**。
#    标题里同时出现"发了"和"但还没…"是这个板子上最常见的形状，判据必须看后半句。
#    一条会假红的闸，用户学会的是忽略它。
NOT_DONE = ("未修", "未做", "未验", "未定", "未复现", "未拍板",
            "待", "缺口", "仍有", "仍在", "没有办法")

# CHANGELOG 分卷阀。今天 2455 行 —— 阀设在这之上，它是**绊线**不是当下的活。
CHANGELOG_MAX_LINES = 3000


def _sections(text):
    """-> [(行号, 标题)]，只取 `##` / `###`。"""
    return [(i + 1, ln.strip())
            for i, ln in enumerate(text.splitlines())
            if ln.startswith("## ") or ln.startswith("### ")]


class TheBoardStaysABoard(unittest.TestCase):
    """`memory.md` 只写**进行时**。"""

    def setUp(self):
        if not BOARD.exists():
            # ★ 说出原因。`memory.md` 是 gitignored（它含跨会话 WIP 与本机事实），
            #   所以干净 checkout 上没有它 —— 那不是"检查通过"。
            self.skipTest("memory.md 不存在（它 gitignored，CI 的干净 checkout 上没有）"
                          " —— 这条闸只在真正有板子的机器上有意义")
        self.text = BOARD.read_text(encoding="utf-8")

    def test_the_board_is_short_enough_that_someone_reads_it(self):
        n = len(self.text.splitlines())
        self.assertLessEqual(
            n, BOARD_MAX_LINES,
            f"★★ memory.md 有 {n} 行（阀 {BOARD_MAX_LINES}）。\n"
            f"   它的价值是「下一个会话读它就知道现在在干什么」—— 长了没人读完 = 等于没有。\n"
            f"   办法不是删，是**搬**：已发布的整段挪进 CHANGELOG，板上留一行指针。\n"
            f"   下面那条测试会点名哪几节该搬。")

    def test_no_finished_work_is_still_sitting_on_the_board(self):
        """★★ 判据打在**章节标题**上，不是全文搜关键词 ——
        正文里出现「已修」通常是在描述某个历史事实，那不是这条闸要管的。"""
        stale = []
        for lineno, title in _sections(self.text):
            if any(nd in title for nd in NOT_DONE):
                continue                       # 「全部未修」这类，留着是对的
            if "未发版批次" in title:
                continue                       # 这一节的职责**就是**登记已修未发的
                                               # （docs-sync：fixed-but-unreleased 归这里）
            if any(dm in title for dm in DONE_MARKERS):
                stale.append(f"    第 {lineno} 行 · {title[:70]}")
        self.assertEqual(
            stale, [],
            "★★ 这几节的标题说这件事已经结束了，但它们还在**现况板**上：\n"
            + "\n".join(stale)
            + "\n   → 整段搬进 CHANGELOG（历史归那里），板上留一行指针；"
              "\n     durable 的规则/口径搬进 CLAUDE.md。"
              "\n   ⚠️ 搬之前先确认它**独有的知识**有别的家 —— "
              "删掉一条同时记着某个未解安全问题的 TODO 是净损失。")


class TheChangelogIsSplitNotSummarised(unittest.TestCase):
    """`CHANGELOG.md` **不压缩**，到点分卷。"""

    TEXT = CHANGELOG.read_text(encoding="utf-8")

    def test_it_is_short_enough_to_open(self):
        n = len(self.TEXT.splitlines())
        self.assertLessEqual(
            n, CHANGELOG_MAX_LINES,
            f"★ CHANGELOG.md 有 {n} 行（阀 {CHANGELOG_MAX_LINES}）——**该分卷了**。\n"
            f"   做法：把旧的**整段**移到 `docs/CHANGELOG-archive-<年份>H<半年>.md`，\n"
            f"   主文件留最近两个大版本 + 一行归档索引。\n"
            f"   ⚠️ **一个字都不许改写成摘要。** 这里唯一不可再生的是「当时的实测数字」——\n"
            f"     B36 就是靠一条 `git log -S` 看出某条注释是三个月前的权衡、数据早已过期。\n"
            f"     摘要会把它磨掉，而分卷不会（同一个 git 仓，`git log -S` 照样搜得到）。")

    def test_archives_are_indexed_from_the_main_file(self):
        """★ 分卷之后，主文件必须**指得到**归档 —— 否则它就是丢了。
        今天没有归档卷，这条自然通过；它是给分卷那天准备的。"""
        archives = sorted((ROOT / "docs").glob("CHANGELOG-archive-*.md"))
        for a in archives:
            self.assertIn(a.name, self.TEXT,
                          f"★ 归档卷 {a.name} 没有被主 CHANGELOG 索引到 —— 等于丢了")


if __name__ == "__main__":
    unittest.main()
