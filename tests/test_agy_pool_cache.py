"""Gemini 档必须**有缓存**：切档不许把已经验证过的当值号打回陈旧的 `live_seen`。

## 来历（2026-09-14，用户实报）

> 「gemini 没有对应的缓存，因此在总览里切换导致跳来跳去」

`useAgyPool` 是总览三档里**唯一**没有缓存语义的取数口：codex 走常驻的 `useStore`、
grok/agy 额度走带 `fetched_at` 单调采纳的 `useQuotaSidecar`，而它每次 `enabled` 翻真
都从零重来一遍，并且**先把 `liveSub` 写成池文件里的 `live_seen`**，约 200~440ms 后
才被 `agy-rotate live --json` 的现读改正。

这两个值**本来就常常不同** —— 本机 2026-09-14 实测：

    .agy-pool.json  live_seen = 100000000000000000002   (dbk)
    agy-rotate live --json → sub = 100000000000000000001 (sam), drifted: true

所以每进一次 Gemini 档，Hero 的号名 / 邮箱 / 环形百分比 / 5h·周两行**整块闪一次**，
「当前」徽章在两张卡之间跑一个来回。这就是用户说的"跳来跳去"。

## 违反的不变量

**「这次还没读到」不许覆盖「已经读到并验证过」**（`CLAUDE.md` §7.0b 的 UI 侧形态）。
`live_seen` 只是**种子**：它在我们什么都不知道时比空白强，但现读一旦回来过，
退回去就是拿一个**已知不可靠**的值覆盖一个**已知可靠**的值。

## ★ 为什么这条闸必须是时间序列，不能是终态快照

**终态永远是对的。** 错的只有中间那 200~440ms。本仓所有既有探针（overflow / 折行 /
`--dump-dom`）问的都是"最后长什么样"，它们对这类缺陷**完全沉默** ——
而沉默在报告里长得和通过一模一样。为此给 harness 加了 `trails` 探针
（按 16ms 采样几个**身份格**的文字，相邻重复折叠），判据打在序列上。

## 实测（本文件的判据全部来自这三组，不是推理）

`?nav=home&agypool=3&agydrift=1&agy_delay=100&click=Gemini,Codex,Gemini`
（夹具：`live_seen=sub0`→`qq55` 是种子，`live --json` 回 `sub1`→`Asen` 是现读真值）

| | hero 序列 | gemtab 序列 |
|---|---|---|
| 修复前（HEAD） | null → **qq55**@774 → Asen@966 → null@1078 → **qq55**@1366 → Asen@1558 | Gemini1@82 → Gemini3@**774** |
| 修复后 | null → qq55@749 → Asen@845 → null@1053 → **Asen**@1341 | Gemini1@62 → Gemini3@**82** |

两处都被钉住：
① 重进那一次不再退回 `qq55`；
② 分档条上的「Gemini N」在**用户第一次点进这一档之前**就已经是真数
   —— 池文件读是一次 `read_sidecar`（不起子进程、不联网、不消耗配额），
   所以它在挂载时就跑，而不是等进档。修复前那个 `Math.max(1, 0)` = **1**
   会一直挂到用户点进去的那一刻，然后整条 pill 重排。

## ⚠️ 档位是挑过的：`agy_delay=100`，不是随手取

`agy_delay=220` 时修复前的**第一次**访问在用户点走（1000ms）之前根本没跑完现读，
于是 `Asen` 从没出现过，「现读之后又退回种子」这个形状就构不成 —— 闸会**假绿**。
100ms 让两条 stub（各起一个 python，真机实测各约 80ms）在 300ms 的点击间隔内跑完，
这才是**只有被测那条能挡住**的那一档（CLAUDE.md §7.-1 第 ⑦ 问）。
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEXBAR = ROOT / "codexbar"
UISHOT = CODEXBAR / "uishot"
HOOK = CODEXBAR / "src" / "hooks" / "useAgyPool.ts"

BASE = "http://127.0.0.1:3304"
# ★ 见模块 docstring 最后一段：这个 100 是挑出来的判别档，改大会让闸假绿。
URL = (BASE + "/harness.html"
       "?nav=home&agypool=3&agydrift=1&agy_delay=100&click=Gemini,Codex,Gemini")

SEED = "qq55"      # 夹具里 live_seen 指向的号 —— **未验证**的那个
LIVE = "Asen"      # `live --json` 现读回来的号 —— **验证过**的那个


def _strip_comments(src):
    """注释里正解释着这条规则，朴素匹配必被它染红（本仓反复吃过的『grep 假阳性』）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _runs(trail):
    """把 `[{t,v},…]` 压成非空值的**游程**序列（连续相同折叠、null 只作分隔）。"""
    out = []
    for x in trail:
        v = x.get("v")
        if v is None:
            continue
        if not out or out[-1] != v:
            out.append(v)
    return out


class TheGeminiTabKeepsItsVerifiedCurrentAccount(unittest.TestCase):
    """行为闸：跑真实构建产物，量身份格随时间的变化。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(UISHOT))
        import sweep

        # ★★ **先把被测源码编进 harness 要加载的那份 bundle。**
        #    不编就是测旧代码 —— 本仓已经因此假绿过两次（CLAUDE.md §4），
        #    而 `sweep.probe` 只是去打静态服务，`make_harness.py` 的
        #    `_assert_fresh_bundle()` 在这条路径上**根本不会被调用**。
        #    所以这道防线必须由本测试自己建，不能指望别处。
        #    ⚠️ `vite build --outDir uishot/app` 会清空目录、连 harness.html 一起删掉，
        #       所以两步顺序固定：先 build，再 make_harness。
        for cmd in (["./node_modules/.bin/vite", "build", "--outDir", "uishot/app"],
                    [sys.executable, "uishot/make_harness.py"]):
            r = subprocess.run(cmd, cwd=str(CODEXBAR), capture_output=True,
                               text=True, timeout=600)
            if r.returncode != 0:
                raise unittest.SkipTest(
                    "构建 harness 失败（{}）：{}".format(cmd[0], (r.stderr or r.stdout)[-400:]))

        ok, how = sweep.server_alive(BASE)
        if not ok:
            # ★ skip 不是绿。memory.md §3 记着：服务没起来时这类测试是 skip，
            #   把 skip 读成通过就是把「没测」当成「测过了」。
            raise unittest.SkipTest(
                "harness 静态服务没起来（{}）—— 这条闸这一轮**没有跑**，别当成通过。"
                "起法见 CLAUDE.md §4。".format(how))

        cls.d = sweep.probe(URL, 1200)

    # ── ① 先证明探针真的打在东西上（否则下面的「没跳」是空话）──────────────

    def test_the_page_actually_rendered(self):
        self.assertIsNone(self.d.get("_fatal"), self.d.get("_fatal"))
        self.assertGreater(self.d.get("mounted", 0), 0, "整页零渲染 —— 下面全是假阴性")
        self.assertEqual(self.d.get("errors"), [], "页面报错了，探针读到的是降级态")

    def test_every_click_hit_exactly_one_element(self):
        """★ 点错位置和没点中长得一模一样 —— 命中数必须核到唯一。"""
        clicks = self.d.get("clicks") or []
        self.assertEqual(len(clicks), 3, "三次分档点击没有全部发生：{}".format(clicks))
        for c in clicks:
            self.assertIn("命中1个", c, "分档 pill 命中数不是 1：{}".format(c))

    def test_the_fixture_really_drifts(self):
        """★★ 没有这条，「没退回种子」就是空话 —— 种子和现读一样时它永远成立。"""
        runs = _runs(self.d["trails"]["hero"])
        self.assertIn(SEED, runs, "Hero 从没显示过种子号，夹具没在验这条路")
        self.assertIn(LIVE, runs, "Hero 从没显示过现读号，`live --json` 打桩可能没生效")
        self.assertNotEqual(SEED, LIVE)

    # ── ② 被报的那个缺陷本身 ─────────────────────────────────────────────

    def test_the_seed_never_comes_back_after_the_live_read(self):
        """★★★ 现读一旦回来过，界面就不许再退回未验证的 `live_seen`。

        修复前实测：`qq55 → Asen → (切走) → qq55 → Asen`，
        最后那个 `qq55` 就是用户看到的"跳"。
        """
        runs = _runs(self.d["trails"]["hero"])
        first_live = runs.index(LIVE)
        after = runs[first_live:]
        self.assertNotIn(
            SEED, after,
            "★ 现读到 {!r} 之后，Hero 又退回了未验证的 {!r} —— 这就是「跳来跳去」。\n"
            "  完整序列：{}".format(LIVE, SEED, runs))

    def test_the_tab_count_is_real_before_the_user_ever_opens_the_tab(self):
        """★★ 分档条上的「Gemini N」不能等进档才变成真数。

        判据是**自相对**的，不写死点击时刻：Hero 第一次非空 = 用户第一次进这一档，
        计数必须在那之前就已经定下来。
        """
        tabs = self.d["trails"]["gemtab"]
        heroes = [x for x in self.d["trails"]["hero"] if x.get("v") is not None]
        self.assertTrue(tabs and heroes, "身份格一个都没采到 —— 探针或 data-* 标记没了")
        entered_at = heroes[0]["t"]
        settled_at = tabs[-1]["t"]
        self.assertLess(
            settled_at, entered_at,
            "★ 「Gemini N」直到进档才变成真数（{}ms 才定下来，而进档是 {}ms）——\n"
            "  在那之前它一直显示兜底的 1，进档那一刻整条 pill 重排。\n"
            "  序列：{}".format(settled_at, entered_at,
                                [(x["t"], x["v"]) for x in tabs]))


class AFailedLiveProbeMustNotClaimThereIsNoDrift(unittest.TestCase):
    """静态闸：`live` 的 catch 里不许写 `setDrifted(false)`。

    ★ 这一条**故意是静态的**，因为它守的是一条"失败路径"：原来
    `catch { setDrifted(false) }` 把「这次没探到」折叠成「确实没漂移」，
    于是一次子进程失败就会让那条琥珀告警消失 —— 而告警消失和"问题解决了"
    在界面上是同一个样子。同 §7.0b 的老形状。
    """

    def test_anchors_exist(self):
        """★ 先证明被测目标还在。改名之后断言会静默打空，那是最坏的假绿。"""
        src = _strip_comments(HOOK.read_text(encoding="utf-8"))
        self.assertIn("setDrifted", src, "useAgyPool 里没有 setDrifted 了，这条闸在守空气")
        self.assertIn('"live", "--json"', src, "现读那条调用不见了，断言已失效")

    def test_the_catch_block_does_not_assert_no_drift(self):
        src = _strip_comments(HOOK.read_text(encoding="utf-8"))
        # 取 `live --json` 那个 try 之后的第一个 catch 块。
        i = src.index('"live", "--json"')
        j = src.index("catch", i)
        block = src[j:src.index("}", src.index("{", j))]
        self.assertNotIn(
            "setDrifted", block,
            "★ 现读失败的 catch 里又写了 setDrifted —— 那是把「没探到」说成「没漂移」。\n"
            "  catch 块：{!r}".format(block))


if __name__ == "__main__":
    unittest.main()
