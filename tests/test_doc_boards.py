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

# `CLAUDE.md` 的字节阀。
#
# ★ 参照物是 **Codex 的 `project_doc_max_bytes`（131,072）**：本仓有 `AGENTS.md`，
#   Codex 平时读的是它；但 `~/.codex/config.toml` 设了
#   `project_doc_fallback_filenames = ["CLAUDE.md"]` —— `AGENTS.md` 一旦被删/改名，
#   Codex 就会去读 `CLAUDE.md` 并**静默截断**（截断的指令文件 = 失败的配置，不是"小一点"）。
#   另一半代价是 Claude 每次触碰本项目都要吃掉它。
#
# 2026-09-10 拆分：162 KB → 92 KB（§5 按内容拆成 `.claude/rules/{ui,traffic}.md`）。
# 阀留在 110 KB：在还有余量时就响，不是等撞上 131 才响。
# ⚠️ 调高它之前先问：这些内容**是不是路径相关**？是就该进 `.claude/rules/` 而不是抬阀。
CLAUDE_MAX_BYTES = 110 * 1024


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


class TheProjectDocStaysUnderCodexBudget(unittest.TestCase):
    """`CLAUDE.md` 不许长回去。

    ★ 它 gitignored（含本机事实），干净 checkout 上不存在 —— 那时**跳过并说出原因**。
    """

    def test_it_fits_with_room_to_spare(self):
        f = ROOT / "CLAUDE.md"
        if not f.exists():
            self.skipTest("CLAUDE.md 不存在（gitignored，CI 的干净 checkout 上没有）")
        n = len(f.read_bytes())
        self.assertLessEqual(
            n, CLAUDE_MAX_BYTES,
            f"★ CLAUDE.md {n/1024:.0f} KB（阀 {CLAUDE_MAX_BYTES/1024:.0f} KB，"
            f"Codex 的硬上限 128 KB）。\n"
            f"   先问**这些内容是不是路径相关**：是就搬进 `.claude/rules/<名>.md` 加 "
            f"`paths:` frontmatter，\n"
            f"   写对应文件时自动加载、平时不占上下文。抬阀是最后手段。\n"
            f"   ⚠️ 按**内容**分，不按它原来住在哪 —— 2026-09-10 差点把 `scan.py` 的口径"
            f"归进 UI 那份，\n"
            f"     那样编辑 `scan.py` 时它正好不加载。")


class TheCommittedRulesCarryNoLocalFacts(unittest.TestCase):
    """★★ `.claude/rules/*.md` **是入库的**，而 `CLAUDE.md` / `AGENTS.md` / `memory.md` 不是。

    本机先例：`skill-hub` 与 `erp-system-v3` 都提交它们的 rules —— 因为 rules 是
    **路径相关的工程规范**（共享行为），而项目 `CLAUDE.md` 在本仓还兼着本机事实与凭证细节。
    所以从 `CLAUDE.md` 往 rules 搬东西时，**边界跟着变了**：搬过去 = 公开。
    这条闸盯着那条边界，不靠"我搬的时候看过一眼"。
    """

    PATTERNS = {
        "邮箱": r"[\w.+-]+@[\w-]+\.[\w.]+",
        "account_id/UUID": r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "api key": r"\bsk-[A-Za-z0-9_-]{12,}",
        "token 赋值": r"(?i)\b(bearer|refresh_token|access_token)\b\s*[:=]\s*\S{8,}",
        "账号标签": r"\b(plus[0-9]+|Pro[0-9]+)\b",
        "绝对家目录": r"/Users/[a-z]+/",
    }

    def test_no_local_facts_leaked_into_the_committed_rules(self):
        rules = sorted((ROOT / ".claude" / "rules").glob("*.md"))
        self.assertTrue(rules, "一条 rule 都没有 —— 探针坏了，不是规则没了")
        bad = []
        for f in rules:
            t = f.read_text(encoding="utf-8")
            for name, pat in self.PATTERNS.items():
                hits = sorted(set(re.findall(pat, t)))
                if hits:
                    bad.append(f"    {f.name} · {name}: {hits[:3]}")
        self.assertEqual(bad, [],
                         "★★ 入库的 rule 里有本机事实/凭证痕迹：\n" + "\n".join(bad)
                         + "\n   → 那类内容留在 gitignored 的 `CLAUDE.md`，别跟着搬。")

    # ------------------------------------------------------------------
    # ★★★ 上面那条是**模式**闸，它按 `plus\d+|Pro\d+` 这种形状找。
    #     2026-09-16 §8 搬进 `credentials.md` 时它红了两条（`plus3/plus4`、`Pro1/plus6`），
    #     **但同一次搬运里还有两个它看不见的**：`user-b`、`user-a`
    #     —— 用户自己起的 Google 账号名，不符合任何预设形状。
    #
    #     这正是本仓那条老教训的形状：**探针看不见目标，于是"没命中"被读成"没有"。**
    #     所以补一条**从真源派生**的闸 —— 不再猜标识符长什么样，直接读本机池子里
    #     真实存在的那些名字，拿它们去 rules 里搜。全局 `testing-discipline`：
    #     「守卫测试的期望值必须从真源派生」，写死一份清单的闸会恰好在它该红的那次保持绿。
    #
    #     ⚠️ 清单本身是本机事实，所以**只能现读、绝不能写进这个文件**
    #        —— 把待查的标识符硬编码进一个入库的测试里，那个测试自己就是泄漏。
    # ------------------------------------------------------------------

    #: 太短/太通用的标识符会把正常英文词判成泄漏（`ok`、`main`、`plan`…）。
    #: 6 是实测下界：本机最短的真实标签是 4 字符，而 4~5 的英文常用词太多。
    _MIN_IDENT = 6

    @staticmethod
    def _identifiers_from(path):
        """从一份 gitignored 的池文件里现读账号标识符。文件不在就返回空集。"""
        import json
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        out = set()
        for slot in (data.get("slots") or data.get("accounts") or {}).values():
            if not isinstance(slot, dict):
                continue
            for key in ("label", "name", "email"):
                v = slot.get(key)
                if not isinstance(v, str) or not v.strip():
                    continue
                out.add(v.strip())
                if key == "email" and "@" in v:
                    out.add(v.split("@", 1)[0].strip())   # 本地部分单独也算标识符
            for old in slot.get("label_history") or []:
                if isinstance(old, str) and old.strip():
                    out.add(old.strip())
        return {s for s in out if len(s) >= TheCommittedRulesCarryNoLocalFacts._MIN_IDENT}

    def test_no_real_account_identifier_appears_in_the_committed_rules(self):
        """★★★ 本机池子里**真实存在**的账号名，一个都不许出现在入库的 rules 里。"""
        idents = (self._identifiers_from(ROOT / "state.json")
                  | self._identifiers_from(ROOT / ".agy-pool.json"))
        if not idents:
            self.skipTest("本机没有池文件（state.json / .agy-pool.json 都 gitignored，"
                          "CI 的干净 checkout 上不存在）—— 无法派生真源，跳过而不是假绿")

        rules = sorted((ROOT / ".claude" / "rules").glob("*.md"))
        self.assertTrue(rules, "一条 rule 都没有 —— 探针坏了，不是规则没了")

        # ★ 已知阳性自检：探针必须能在"确实含有标识符"的文本上响。
        #   少了这一步，一个恒不命中的探针会安静地报"干净"（本仓 2026-09-14 踩过）。
        probe = "prefix {} suffix".format(sorted(idents)[0])
        self.assertTrue(any(i in probe for i in idents),
                        "★ 探针在已知阳性上不响 —— 是探针坏了，不是 rules 干净")

        bad = []
        for f in rules:
            t = f.read_text(encoding="utf-8")
            hit = sorted(i for i in idents if i in t)
            if hit:
                bad.append("    {} · 真实账号标识符 ×{}: {}".format(f.name, len(hit), hit[:3]))
        self.assertEqual(
            bad, [],
            "★★★ 入库的 `.claude/rules/*.md` 里出现了本机池子里真实存在的账号名：\n"
            + "\n".join(bad)
            + "\n   → rules 是**入库并推到公开仓库**的，`CLAUDE.md` 不是。"
              "\n     从 `CLAUDE.md` 往 rules 搬内容时**边界跟着变了：搬过去 = 公开**。"
              "\n     改法是脱敏（`某个 Plus 号` / `A 号`），**不是**把这条闸关掉 ——"
              "\n     实测数字全部保留，只换掉指向具体某个人某个号的那几个字。")


class TheRulesUseThePathFormThatIsKnownToLoad(unittest.TestCase):
    """★ `.claude/rules/*.md` 的 `paths:` 一律写成**带通配的 glob**（`"**/name"` / `"dir/**"`）。

    ## 这是**约定**，不是已证实的语法要求 —— 区别很重要

    2026-09-16 实测：`traffic.md`（**早就存在**的规则）在打开 `traffic/rotation.py` 时
    如约注入；而同一会话里**刚建出来**的 `credentials.md` / `verification.md` /
    `rotation-lanes.md`，对任何匹配文件都没注入过一次。

    两个假说同样能解释这组观测，**当时那个会话分不开**：
      (a) 规则索引在**会话启动时枚举一次**，之后新建的文件要等下一个会话才可见；
      (b) 那几份的 `paths:` 写法本身不匹配。
    ⚠️ **(a) 单独就能解释全部观测**，而专门冲着 (b) 去的那次实验（把路径改成
    `**/LogsPage.tsx` 再打开该文件）**同样没有触发** —— 那是**反对** (b) 的证据。

    所以这条闸**不断言"没有通配就不生效"**（那是把一个未定论的推断写成实测，
    本仓明令禁止）。它只钉一件事：**统一成本机上已知能加载的那批规则用的形状**。
    代价为零，顺手排除掉一个候选原因。

    ★ 真正的判别实验写在 `CLAUDE.md` §5 —— **必须在新会话里跑**。
    """

    def test_every_path_entry_is_a_glob(self):
        rules = sorted((ROOT / ".claude" / "rules").glob("*.md"))
        self.assertTrue(rules, "一条 rule 都没有 —— 探针坏了，不是规则没了")

        bare = []
        seen_entries = 0
        for f in rules:
            parts = f.read_text(encoding="utf-8").split("---", 2)
            self.assertGreaterEqual(
                len(parts), 3,
                "★ {} 没有 frontmatter —— 没有 `paths:` 的规则**永远不会**按路径加载".format(f.name))
            for m in re.finditer(r'^\s*-\s*"([^"]+)"', parts[1], re.M):
                seen_entries += 1
                if "*" not in m.group(1):
                    bare.append("    {} · {}".format(f.name, m.group(1)))

        # ★ 已知阳性自检：解析器必须真的读出了条目。
        #   少了这一步，一个正则写错、恒 0 命中的闸会安静地报"全部合规"
        #   —— 本仓最贵的那类错（探针看不见目标 ⇒ "没命中"被读成"没有"）。
        self.assertGreater(seen_entries, 5,
                           "★ 只解析出 {} 条 paths —— 是**正则坏了**，不是规则都合规"
                           .format(seen_entries))

        self.assertEqual(
            bare, [],
            "★ 这些 `paths:` 条目没有通配符：\n" + "\n".join(bare)
            + "\n   → 统一改成 `\"**/<文件名>\"` 或 `\"<目录>/**\"`。"
              "\n     本机**已知能加载**的规则（`~/.claude/rules/*.md`）全是这个形状；"
              "\n     逐字路径**是否**生效至今未定论（见本文件类 docstring 与 `CLAUDE.md` §5）。")


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


class NoTestReadsAGitignoredDocAtImportTime(unittest.TestCase):
    """★★★ 在**导入期**读 gitignored 文件 = CI 上整个 suite 中断。

    2026-09-15 v1.6.0 那次：`test_build_number.py` 在类体里
    `(ROOT / "CLAUDE.md").read_text()`，本地 1294 条全绿，
    而 CI 的干净 checkout 上 `CLAUDE.md` 根本不存在 ⇒ `FileNotFoundError` ⇒
    pytest 算 collection error ⇒ **一条测试都没跑**，红在发版那一刻。

    ★ 这是本仓「测试环境 ≠ 镜像」的又一形态，而且比那条更隐蔽：
      不是"某条测试挂了"，是"全体没跑"，而退出码看起来就是普通的失败。
    判据：`CLAUDE.md` / `AGENTS.md` / `memory.md` 这三个 gitignored 的文件，
    在 `tests/*.py` 里**不许出现在方法体之外**的 `read_text()` 调用里。
    """

    GITIGNORED_DOCS = ("CLAUDE.md", "AGENTS.md", "memory.md")

    def test_no_module_level_read(self):
        import ast
        bad = []
        for f in sorted((ROOT / "tests").glob("test_*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "read_text"):
                    continue
                src = ast.get_source_segment(f.read_text(encoding="utf-8"), node) or ""
                if not any(d in src for d in self.GITIGNORED_DOCS):
                    continue
                # 在函数体内读是允许的（配 skipTest）；类体/模块层不行。
                inside_fn = any(
                    isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.lineno >= p.lineno and node.end_lineno <= (p.end_lineno or node.end_lineno)
                    for p in ast.walk(tree))
                if not inside_fn:
                    bad.append("{}:{}".format(f.name, node.lineno))
        self.assertEqual(bad, [],
                         "★★★ 这些地方在导入期读 gitignored 文档 —— CI 上会整个 suite 中断：\n  "
                         + "\n  ".join(bad))


if __name__ == "__main__":
    unittest.main()
