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


_built = []


def _probe(url):
    """构建一次 harness（多个类共用），再取探针。

    ★★ **先把被测源码编进 harness 要加载的那份 bundle。**
       不编就是测旧代码 —— 本仓已经因此假绿过两次（CLAUDE.md §4），
       而 `sweep.probe` 只是去打静态服务，`make_harness.py` 的
       `_assert_fresh_bundle()` 在这条路径上**根本不会被调用**。
    ⚠️ `vite build --outDir uishot/app` 会清空目录、连 harness.html 一起删掉，
       所以两步顺序固定：先 build，再 make_harness。

    ★★★ **`import sweep` 必须排在产物就位之后。** `uishot/sweep.py` 在**模块层**就
       `clickable_account()` → 读 `app/harness.html`，产物不在时 **import 本身**抛
       `FileNotFoundError` —— 那是 error 不是 skip，而 CI 的干净 checkout 上没有
       node_modules / Chrome，必然走到这一条。v1.6.0 那次 CI 的 8 个 error 就是它。
    ★ 缺任何一环都 **skip 并说明"这一轮没跑"** —— skip 不是绿（memory.md §3）。
    """
    harness = CODEXBAR / "uishot" / "app" / "harness.html"
    if not _built:
        for cmd in (["./node_modules/.bin/vite", "build", "--outDir", "uishot/app"],
                    [sys.executable, "uishot/make_harness.py"]):
            try:
                r = subprocess.run(cmd, cwd=str(CODEXBAR), capture_output=True,
                                   text=True, timeout=600)
            except OSError as e:          # node_modules 不在时连可执行文件都找不到
                raise unittest.SkipTest("构建 harness 跑不起来（{}）：{}".format(cmd[0], e))
            if r.returncode != 0:
                raise unittest.SkipTest(
                    "构建 harness 失败（{}）：{}".format(cmd[0], (r.stderr or r.stdout)[-400:]))
        _built.append(True)
    if not harness.exists():
        raise unittest.SkipTest(
            "harness 产物不存在（CI 的干净 checkout 上没有 node_modules / Chrome）"
            " —— 这条闸这一轮**没有跑**，别当成通过")

    sys.path.insert(0, str(UISHOT))
    import sweep                                   # ← 只有产物就位之后才 import

    ok, how = sweep.server_alive(BASE)
    if not ok:
        raise unittest.SkipTest(
            "harness 静态服务没起来（{}）—— 这条闸这一轮**没有跑**，别当成通过。"
            "起法见 CLAUDE.md §4。".format(how))
    return sweep.probe(url, 1200)


class TheGeminiTabKeepsItsVerifiedCurrentAccount(unittest.TestCase):
    """行为闸：跑真实构建产物，量身份格随时间的变化。"""

    @classmethod
    def setUpClass(cls):
        cls.d = _probe(URL)

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


# ★ 兄弟 webview 广播的那个号（夹具里 `sub2` = Huo）。与 SEED/LIVE 都不同，
#   所以"收敛到它"不可能被前两者蒙对。
SIBLING = "Huo"
SIBLING_URL = (BASE + "/harness.html"
               "?nav=home&agypool=3&agydrift=1&agy_delay=100&click=Gemini"
               "&agylive=sub2&agylive_at=1500")


class TheTwoWebviewsAgreeOnWhoIsCurrent(unittest.TestCase):
    """★★★ 主窗与菜单栏不许对「当前号」给出两个答案（2026-09-14 用户实报）。

    ## 现场

    同一张截图里：菜单栏说当前是 `sam`、主窗总览说当前是 `dbk`。
    实测 `agy-rotate live --json` 回的是 `sam` ⇒ **菜单栏对、总览错**，
    总览停在池文件里陈旧的 `live_seen`。

    ## 根因：两个 webview，各探各的，而钥匙串正被人抢

    `useAgyPool` 在 `App.tsx` 和 `MenuBar.tsx` **各挂一份**，`enabled` 条件还不一样
    （主窗要"总览 + Gemini 档"，菜单栏要"账号 Tab + Gemini 芯片"）。于是两边在
    **不同时刻**各跑一次 `agy-rotate live --json` —— 而本机有 4 个常驻 agy 进程
    在抢同一个钥匙串槽（实测最久的 6 天 23 小时，`drifted: true`）。
    两次探测落在不同时刻，本来就会得到不同的号。

    ★★ **而 B45 加的 `verified` 位让这件事从瞬态变成永久**：在那之前两边每次进档
      都会重读、有机会收敛；之后各自锁死在自己那次探测上。
      所以跨 webview 广播不是锦上添花，是 `verified` 的**必要配套** ——
      这条闸守的正是那个配套。

    ## ⚠️ harness 只渲染一个 webview，所以能验的是"收到兄弟广播会不会收敛"

    真正的双 webview 分歧结构上模拟不出来。`?agylive=<sub>` 直接投递一条
    另一个 webview 会发的事件，验的是修法本身。**这个局限必须写出来**，
    否则下一个人会以为"两个 webview 一致"已经被自动化覆盖了。
    """

    @classmethod
    def setUpClass(cls):
        cls.d = _probe(SIBLING_URL)

    def test_the_broadcast_actually_fired(self):
        """★ 先证明事件真的投递了。没投递的话，「收敛了」就是空话。"""
        self.assertIsNone(self.d.get("_fatal"), self.d.get("_fatal"))
        self.assertEqual(self.d.get("errors"), [])
        self.assertTrue(any("agylive" in c for c in (self.d.get("clicks") or [])),
                        "★ 广播没发出去 —— 下面那条断言测的是空气")

    def test_it_converges_onto_the_sibling_reading(self):
        """★★★ 收到兄弟 webview 的现读结果后，必须改过来。"""
        runs = _runs(self.d["trails"]["hero"])
        self.assertTrue(runs, "Hero 一次都没渲染")
        self.assertEqual(
            runs[-1], SIBLING,
            "★ 没有收敛到兄弟 webview 报的当值号 {!r} —— 两个 webview 会各说各的。\n"
            "  完整序列：{}".format(SIBLING, runs))

    def test_it_had_its_own_answer_first(self):
        """★★ 防"作弊通过"：如果本 webview 压根没探出过自己的答案，
        那"收敛"只是"从来没有过第二个答案"，这条闸就没在验合流。"""
        runs = _runs(self.d["trails"]["hero"])
        self.assertIn(LIVE, runs,
                      "★ 本 webview 自己的现读结果 {!r} 从没出现过 —— 没有分歧可收敛".format(LIVE))
        self.assertLess(runs.index(LIVE), runs.index(SIBLING),
                        "★ 顺序不对：应当先有自己的答案，再被兄弟的更新覆盖")


class TheHookBroadcastsAndListens(unittest.TestCase):
    """静态闸：`useAgyPool` 必须**同时**发和收，且收的那一侧不受 `enabled` 约束。"""

    @classmethod
    def setUpClass(cls):
        cls.src = _strip_comments(HOOK.read_text(encoding="utf-8"))

    def test_it_emits_and_listens_on_the_same_event(self):
        self.assertIn("emit(LIVE_EVT", self.src, "★ 探到结果不广播 —— 兄弟 webview 永远不知道")
        self.assertIn("listen<LivePayload>(LIVE_EVT", self.src, "★ 只发不收，照样各说各的")

    def test_adoption_is_monotonic(self):
        """★ 按时间戳单调采纳（同 `useQuotaSidecar.adopt`）。

        没有这条：① 自己 emit 又被自己收到会反复写 state；
        ② 一条**更旧**的在途结果会覆盖更新的答案 —— 而那看起来就像"又跳回去了"。
        """
        self.assertIn("p.at > probedAt.current", self.src,
                      "★ 采纳没有比时间戳 —— 旧结果会覆盖新结果")

    def test_the_listener_is_not_gated_by_enabled(self):
        """★★ 收听**不受 `enabled` 约束**：那是别人已经取好的数据，收下零成本。

        受约束的话就退回「只有正在看这一档时才收敛」—— 而用户报的正是
        "菜单栏在看、总览没在看，于是两边不一样"。
        """
        i = self.src.index("listen<LivePayload>(LIVE_EVT")
        # 往回找到这个 effect 的起点，确认它的依赖数组是空的、且没有 enabled 守卫
        head = self.src.rindex("useEffect(", 0, i)
        body = self.src[head:self.src.index("}, [", i)]
        self.assertNotIn("if (!enabled)", body, "★ 收听被 enabled 挡住了")
        self.assertNotIn("enabled &&", body, "★ 收听被 enabled 挡住了")


class TheCloudQuotaRefreshesItself(unittest.TestCase):
    """★★★ 云端每账号额度必须**自动保鲜**（用户 2026-09-16：「刷新情况太慢了，
    都要我手动去刷新，额度才更新上去」）。

    ## 真因不是阈值，是这条链路上根本没有自动刷新

    2026-09-16 实测本机：三个号的 `quota_at` 全停在 **18.2 小时前**，而同机
    `.agy-quota.json`（本机 RPC，有采样器）是 **0.4 分钟前** —— 一冷一热。
    `agy-rotate quota` 此前的**唯一**调用方是 ↻ 按钮：挂载只 `readPool()` 读盘，
    `probeLive()` 只查身份不查额度。
    ★ 本仓 §7.1：症状是「要等很久才更新」时**先问信息是不是被丢掉了**，别先调阈值。
      这里丢掉的不是信息，是整条触发路径。
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _strip_comments(HOOK.read_text(encoding="utf-8"))

    def test_there_is_an_automatic_trigger_at_all(self):
        """★★★ 主闸：必须存在**不靠用户点击**的取数路径。"""
        self.assertIn("setInterval(", self.src,
                      "★★★ 没有心跳 —— 额度又只能靠手点 ↻ 才更新")
        self.assertIn("refreshQuotaIfStale", self.src,
                      "★★★ 没有「过期才取」这条路径")

    def test_the_manual_and_automatic_paths_share_one_implementation(self):
        """★ 手动 ↻ 与自动保鲜走**同一个** `runQuota` ——
        各写一份的话，迟早只有一条带上了 `running` 守卫或广播。"""
        self.assertIn("const runQuota", self.src)
        self.assertIn("runQuota(false)", self.src, "★ 手动那条没走共用实现")
        self.assertIn("runQuota(true)", self.src, "★ 自动那条没走共用实现")

    def test_the_heartbeat_respects_the_user_switch_and_visibility(self):
        """★ 设置页「后台自动刷新」关掉时，后台心跳必须闭嘴；窗口藏起来时零开销。
        ★ 两者都**每 tick 现读** —— 两个 webview 的 localStorage 不互通。"""
        i = self.src.index("setInterval(")
        body = self.src[i:i + 400]
        self.assertIn("autoRefreshEnabled()", body, "★ 心跳没看那个开关")
        self.assertIn('visibilityState === "visible"', body, "★ 没人看时还在跑")

    # ------------------------------------------------------------------
    # ★★★ 下面这条是这次改动里**唯一能自我锁死**的地方，单独给一条闸。
    # ------------------------------------------------------------------

    def test_freshness_is_judged_by_did_we_try_not_by_did_it_succeed(self):
        """★★★ 判据必须是池级的 `quota_ran_at`（**尝试过没有**），
        绝不能是各号的 `quota_at`（**取成没有**）。

        `cmd_quota` 的失败分支 `continue` 掉了、**不写 `quota_at`** ⇒ 一个坏掉的号会让
        「最旧的读数过期了吗」**永远为真** ⇒ 30s 心跳变成每 30s 起一次 18.6s 的子进程
        猛打云端。与 B46 的 `_reset_crossed` **同一个形状**：拿「成功的副作用」当
        「尝试过」的判据，失败时条件自我锁死成放大器，**而且没有任何症状**。
        """
        i = self.src.index("const refreshQuotaIfStale")
        body = self.src[i:self.src.index("}, [", i)]
        self.assertIn("quotaRanAt.current", body,
                      "★★★ 保鲜判据没用「尝试过」的时刻")
        self.assertNotIn("quota_at", body,
                         "★★★ 保鲜判据用了各号的 `quota_at` —— 一个坏号就把它变成 403 放大器")

    def test_the_cli_records_the_attempt_even_when_it_fails(self):
        """★★★ 上一条的另一半：CLI 必须**成败都写** `quota_ran_at`。

        只在成功时写 = 那个字段与 `quota_at` 等价 = 放大器原样还在，
        而闸却因为"前端读的是新字段"而变绿。**两侧都要验，缺一侧等于没验。**
        """
        cli = (ROOT / "agy-rotate").read_text(encoding="utf-8")
        i = cli.index("def cmd_quota")
        body = cli[i:cli.index("\ndef ", i + 10)]
        self.assertIn('pool["quota_ran_at"]', body, "★★★ CLI 没记录「尝试过」")
        # ★ 判据：赋值必须在**逐号循环之外**（循环里 `continue` 会跳过它）。
        #   用缩进判层级 —— 顶层语句是 4 空格，循环体内是 8+。
        line = next(l for l in body.splitlines() if 'pool["quota_ran_at"]' in l)
        self.assertEqual(len(line) - len(line.lstrip()), 4,
                         "★★★ `quota_ran_at` 写在循环体里 —— 失败的号会 `continue` 跳过它")

    def test_a_finished_run_tells_the_other_webview_to_read_not_refetch(self):
        """★ 取完广播，兄弟 webview **读盘**（~1ms）而不是也起一个 18.6s 的子进程。"""
        self.assertIn("emit(POOL_EVT", self.src, "★ 取完不广播 —— 两个 webview 各跑各的")
        self.assertIn("listen(POOL_EVT", self.src, "★ 只发不收")

    def test_the_automatic_run_does_not_spin_the_button(self):
        """★ 后台保鲜**不点亮转圈**（每 10 分钟整排卡转一次，用户会以为自己碰了什么）；
        但**失败仍然照常写 `err`** —— 静默的是"忙"，不是"坏了"。"""
        i = self.src.index("const runQuota")
        body = self.src[i:self.src.index("}, [read]", i)]
        self.assertIn("if (!silent) setBusy(true)", body, "★ 自动那次也在转圈")
        self.assertIn("setErr(", body, "★ 失败被一起静音了 —— 那是把坏了藏起来")


class TheGeminiCardMatchesTheAccountCardLayout(unittest.TestCase):
    """★★ 总览 Gemini 卡的两个文字槽与账号卡**同位同义**（用户 2026-09-16 点名整改一致性：
    「gemini model 最紧应该是放账号信息的，目前账号信息应该是放到期日期的」）。

        槽位            账号卡(codex)        Gemini 卡(agy)
        ────────────────────────────────────────────────
        名字下方        邮箱                 邮箱          ← 本轮改
        分隔线下(页脚)  `到期 YYYY-MM-DD`    `重置 MM-DD HH:MM`  ← 本轮改

    ## ⚠️ 页脚**刻意不写「到期」**，这不是偷懒

    agy **没有订阅到期日这个数据**。三个独立探针一致（2026-09-16，带正向对照 ——
    同样写法在 codex 侧找到了 `sub_until`/`sub_checked`）：
      · 凭证文件只有 `token.expiry`（access_token 的 ~6h 有效期）；
      · `id_token` 是纯 Google OIDC，无任何 plan/tier/subscription 声明；
      · agy 二进制里没有 subscription/license 类端点。
    把 6 小时的 token 有效期或额度重置日说成「到期」，就是本仓那条
    **「把 5 小时的余量说成一周的余量」** —— 比不显示更糟。
    """

    CARD = (Path(__file__).resolve().parents[1] / "codexbar" / "src"
            / "components" / "AgyCard.tsx")

    @classmethod
    def setUpClass(cls):
        cls.src = _strip_comments(cls.CARD.read_text(encoding="utf-8"))

    def test_the_subtitle_slot_holds_the_account_email(self):
        """★ 名字下方那一格 = 账号信息。"""
        i = self.src.index("fontSize: Z.email")
        body = self.src[i:i + 320]
        self.assertIn("email", body, "★ 副标题槽没放账号信息")

    def test_the_subtitle_no_longer_holds_the_tightest_group(self):
        """★★ 「X 最紧」必须从副标题槽**消失**。

        它原来占着账号信息那一格，理由是「agy 的响应里没有身份信息」——
        那说的是**本机 loopback RPC**，而 2026-09-15(B53) 起额度改走云端按账号读，
        每个号都带 `email`。**旧理由已过期**（§6：披露的寿命跟着它描述的事实走）。
        """
        i = self.src.index("fontSize: Z.email")
        self.assertNotIn("最紧", self.src[i:i + 320],
                         "★★ 副标题槽里还留着「最紧」—— 账号信息被挤掉了")

    def test_the_tightest_group_is_kept_in_a_title_not_deleted(self):
        """★ 但它**没有被删掉**，只是移进 `title`（§6：不要顺手简化掉已有功能）。

        环上那个数字是 4 个桶里最紧的一个；不说来自哪组，用户无从知道是
        Gemini 还是 Claude/GPT 见底。
        """
        self.assertIn("tight.group", self.src, "★ 「哪一组最紧」被整个删掉了")

    def test_the_footer_shows_a_reset_date_with_an_absolute_format(self):
        """★ 页脚放最紧那个窗口的重置时刻，**绝对写法**。

        与行上的 `↻2h`（相对）**互补不重复**：那里答"还有多久"，这里答"具体哪天" ——
        周窗口只看 `↻3d` 说不出是哪一天。
        """
        self.assertIn("fmtResetDate", self.src, "★ 页脚没用绝对日期")
        i = self.src.index("fontSize: Z.exp")
        # 页脚那一段：往前找到它所在的 <span>
        head = self.src.rindex("<span", 0, i)
        body = self.src[head:i + 300]
        self.assertIn("重置", body, "★ 页脚没写「重置」标签")

    def test_the_footer_never_claims_a_subscription_expiry(self):
        """★★★ 页脚**不许**出现「到期」—— agy 没有这个数据，写了就是编造。

        ⚠️ **判据只能打在真正渲染出来的那几个字上。**
        第一版把窗口开成「`<span` 起 + 400 字符」，于是扫进了 `title` 里那句
        **免责说明**「⚠️ 这不是订阅到期日」—— 当场假红。
        本仓空守卫形态⑫（断言撞上解释这条规则的文字），2026-09-13 一轮里踩过五次；
        这次是第六次，而**一条会假红的闸，用户学会的是忽略它**。
        所以窗口收敛到 `}}>` 与 `</span>` 之间的 children 表达式 —— `title` 与注释都在窗口外。
        """
        i = self.src.index("fontSize: Z.exp")
        # children 从这个 span 的 style 属性收尾（`}}>`）开始，到 `</span>` 结束。
        start = self.src.index("}}>", i) + 3
        body = self.src[start:self.src.index("</span>", start)]
        # ★ 已知阳性自检：窗口必须真的框住了渲染文案，否则"没扫到"会被读成"没写"。
        self.assertIn("重置", body, "★ 窗口没框住页脚文案 —— 是切片坏了，不是文案对了")
        self.assertNotIn("到期", body,
                         "★★★ 页脚写了「到期」—— agy 无订阅期数据，那是一句编造")

    def test_the_rotation_pool_fact_found_a_new_home(self):
        """★ 「在/不在轮换池」原来住在页脚的兜底文案里，改版后没别处可去
        （动作条里的轮换图标只在卡被选中时可见）—— 必须并进 `title`。
        **搬走一句真话之前要先给它找到家。**
        """
        self.assertIn("在轮换池", self.src, "★ 「在/不在轮换池」被顺手弄丢了")
