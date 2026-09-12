"""★★★ 四方评审（2026-09-07）里三条**活的**发现，2026-09-12 修。

为什么现在才修、以及为什么必须修：判断依据不是板子的年龄，是**这些路径还活不活**。
实测 `state.json` 的 `dawn_probe` = `{"enabled": true, "date": "2026-09-12",
"state": "done", "ok": 4, "total": 4}` —— 那个**唯一自动花钱**的定时器当天刚跑过，
给 4 个号各发了一次真计费请求；`.quota-anchors.json` 84 KB，三个进程在写。
所以这三条不是陈年欠账，是每天都在触发的路径。

三条的共同点还是那一个：**症状是钱或数据悄悄少了一点，而没有任何东西报错。**
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROTATE = ROOT / "codex-rotate"
ANCHORS = ROOT / "traffic" / "quota_anchors.py"


def _fn(name):
    src = ROTATE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n, src
    raise AssertionError(f"找不到 {name} —— 探针坏了")


class TheBillingPhasesAreSeparated(unittest.TestCase):
    """★★★ `SendFailed`（可证明没送达）才可重试；`UpstreamCommitted`（已送达）绝不。

    原来 `request()` / `getresponse()` / `read()` 在**同一个 try** 里，全塌成
    `req err`，而调用方对 `req err` 会重试 —— 于是「读流超时」变成**再发一次计费请求**。
    那段重试的注释自己写着「没有产生任何服务端判决」，**前提是假的**：
    `getresponse()`/`read()` 的失败发生在请求已送达、甚至已 200 之后。
    注释把不变量说对了，代码没实现它。这是本仓 §8「计费相位分界」的直接违反。
    """

    def test_request_and_response_are_in_different_try_blocks(self):
        """★★ 判据按 **handler 返回什么** 认相位，不按"哪个 try 里有什么"。

        ⚠️ 第一版遍历所有 `Try` 并要求「含 request 的 try 不许含 getresponse」——
           但**外层那个 `try/finally: conn.close()` 包着两个内层 try**，
           于是它的 body 里两个相位都有，闸当场假红，而代码是对的。
           嵌套让"哪个 try"变得没有意义；能唯一标识相位的是它**失败时说什么**。
        """
        fn, src = _fn("_billed_probe")
        send_try = commit_try = None
        for t in ast.walk(fn):
            if not isinstance(t, ast.Try):
                continue
            hs = "\n".join(ast.get_source_segment(src, h) or "" for h in t.handlers)
            body = "\n".join(ast.get_source_segment(src, st) or "" for st in t.body)
            if "send err" in hs:
                send_try = body
            if "committed err" in hs:
                commit_try = body
        self.assertIsNotNone(send_try, "找不到「没送达」那一相 —— 探针坏了")
        self.assertIsNotNone(commit_try, "找不到「已送达」那一相 —— 探针坏了")
        # ★★★ 核心不变量：判成「没送达、可重试」的那一段里，**不许有任何已送达的动作**。
        for forbidden in ("getresponse(", ".read("):
            self.assertNotIn(forbidden, send_try,
                             f"★★★ `{forbidden}` 落在「没送达」那一相里 —— "
                             "读流超时会被当成没送达而**重发一次计费请求**")
        self.assertIn("conn.request(", send_try)
        self.assertIn("getresponse(", commit_try)

    def test_the_two_phases_return_different_prefixes(self):
        fn, src = _fn("_billed_probe")
        seg = ast.get_source_segment(src, fn)
        self.assertIn("send err", seg, "没有「没送达」这一态")
        self.assertIn("committed err", seg, "没有「已送达、可能已计费」这一态")

    def test_the_retry_only_fires_on_the_not_delivered_phase(self):
        """★★ 这条才是真正花钱的那一半。只分了相位而调用方照旧重试，等于没改。"""
        fn, src = _fn("cmd_probe")
        seg = ast.get_source_segment(src, fn)
        code = "\n".join(l for l in seg.splitlines() if not l.strip().startswith("#"))
        self.assertIn('msg.startswith("send err")', code,
                      "★★★ 重试判据不是 `send err` —— 已计费的失败会被重发")
        self.assertNotIn('startswith("req err")', code)
        self.assertNotIn('startswith("committed', code,
                         "★★★ 竟然对「已送达」重试 —— 那会真的多扣一次")


class TheDawnProbeAlwaysReleasesItsClaim(unittest.TestCase):
    """★★ 认领了今天就必须在**任何**退出路径上把结果写回。

    原来 `cmd_probe()` 抛异常就走不到 `_save(state="done")`，`state` 永久钉在
    `"running"` + 今天的日期，而 `_claim` 的判据是「date == today 即已认领」⇒
    **当天余下时间任何重试都被跳过**，日志上却显示「已被另一个进程认领(防双重计费)」。
    """

    def test_an_exception_is_recorded_not_swallowed_and_not_left_running(self):
        fn, src = _fn("cmd_dawn_probe")
        seg = ast.get_source_segment(src, fn)
        tries = [t for t in ast.walk(fn) if isinstance(t, ast.Try)
                 and "cmd_probe(" in "\n".join(
                     ast.get_source_segment(src, st) or "" for st in t.body)]
        self.assertTrue(tries, "★★ `cmd_probe()` 不在任何 try 里 —— 抛了就永久占住今天")
        handlers = "\n".join(ast.get_source_segment(src, h) or ""
                             for t in tries for h in t.handlers)
        self.assertIn('"failed"', handlers,
                      "★ 异常路径没有写回结果 —— state 会停在 running")
        self.assertIn("raise", handlers,
                      "★ 异常被吞了 —— 定时器会以为自己成功了")

    def test_failed_still_blocks_a_rerun_today(self):
        """★★★ 释放成 `failed` 而不是抹掉：**「跑过但崩了」与「没跑过」不是一回事** ——
        前者可能已经花过钱，抹掉会让重跑变成二次计费。
        `failed` 仍然带今天的日期，所以仍然挡住重跑。

        ⚠️ **这条闸自己踩过一次锚点不唯一**（2026-09-12）。原来是
        `seg.index('"failed"')` 取**第一个**匹配再看前后 400 字符 —— 那天给
        `--force` 加了一句 `if claimed["state"] == "failed"` 的提示文案，它排在
        真正的 `_save(...)` 之前，窗口整个偏到新代码上，闸**假红**。
        `tools/mutate.py` 第①条要求「锚点匹配数 == 1」，而它出现在闸自己身上。
        现在按 AST 找 **except 处理器里的那个 `_save` 调用**，再核它的字典字面量：
        位置无关、文案无关，只要那次写回真的带着今天的日期就绿。"""
        fn, src = _fn("cmd_dawn_probe")
        saves = [n for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
                 for n in ast.walk(h)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_save"]
        self.assertEqual(len(saves), 1,
                         "★ 异常路径里的 `_save` 调用不是恰好 1 个 —— 探针失准，先修闸")
        d = saves[0].args[0]
        self.assertIsInstance(d, ast.Dict, "★ `_save` 的实参不是字面量字典 —— 这条闸看不进去了")
        kv = {k.value: v for k, v in zip(d.keys, d.values)
              if isinstance(k, ast.Constant)}
        self.assertEqual(getattr(kv.get("state"), "value", None), "failed",
                         "★ 异常路径没把 state 写成 failed")
        self.assertEqual(getattr(kv.get("date"), "id", None), "today",
                         "★ failed 那条没带今天的日期 ⇒ 不再挡重跑 ⇒ 可能二次计费")


class TheAnchorLedgerSurvivesConcurrentWriters(unittest.TestCase):
    """★★ `note()` 的 load→record→save 必须整段持锁。

    `save()` 是原子的（tmp + rename），文件**从不会坏** —— 正因如此这个 bug 不出声。
    坏的是**更新丢失**：A 读 → B 读 → A 写 → B 写，A 那次观测没了。
    而这本账判的是「窗口锚定没锚定」，丢观测**直接改判**。
    """

    def test_the_read_modify_write_is_inside_the_lock(self):
        src = ANCHORS.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "note")
        withs = [w for w in ast.walk(fn) if isinstance(w, ast.With)]
        self.assertTrue(withs, "★★ `note()` 里没有任何 `with` —— RMW 无保护")
        inside = "\n".join(ast.get_source_segment(src, st) or ""
                           for w in withs for st in w.body)
        for must in ("load(", "record(", "save("):
            self.assertIn(must, inside,
                          f"★★ `{must}` 在锁外 —— 只锁 save 没用，"
                          "竞态发生在「读到旧值」那一刻")

    def test_two_processes_do_not_lose_each_others_anchors(self):
        """★★★ 行为闸：两个进程各写 N 次，账本里必须**两边都在**。

        这是唯一能证明锁真的起作用的判据 —— 源码里有个 `with` 证明不了它锁住了什么。
        """
        with tempfile.TemporaryDirectory() as d:
            led = os.path.join(d, "anchors.json")
            prog = f'''
import sys, time
sys.path.insert(0, {str(ROOT / "traffic")!r})
import quota_anchors as qa
src = sys.argv[1]
for i in range(40):
    qa.note(src, "k%d" % i, 1700000000 + i * 60, float(i), now=1700000000 + i,
            path={led!r})
'''
            ps = [subprocess.Popen([sys.executable, "-c", prog, s],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                  for s in ("A", "B")]
            for p in ps:
                _, err = p.communicate(timeout=180)
                self.assertEqual(p.returncode, 0, err.decode()[-500:])
            data = json.loads(Path(led).read_text(encoding="utf-8"))
            srcs = data.get("sources") or {}
            self.assertIn("A", srcs, "★★★ A 的观测全丢了 —— 更新丢失")
            self.assertIn("B", srcs, "★★★ B 的观测全丢了 —— 更新丢失")
            for s in ("A", "B"):
                self.assertGreaterEqual(
                    len(srcs[s]), 30,
                    f"★★ {s} 只剩 {len(srcs[s])}/40 条 —— 锁没挡住互相覆盖")


if __name__ == "__main__":
    unittest.main()


def _load_rotate():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("codex_rotate", str(ROTATE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TheProbeRecordsTheWindowItJustStarted(unittest.TestCase):
    """★★★ 四方评审 #2 的修法②（2026-09-12）。

    计费探针**就是**那个把 5h 窗口锚定的动作。原来它把这个事实丢掉，
    让判定再花 **897–1197 秒**从时间序列里推导一遍同一件事，而那十几分钟里
    UI 对着刚花钱启动的窗口显示「窗口未启动」。

    ⚠️ 这组闸盯的是**两个方向**：
      · 记了没有（正向）——「没记」的症状是十几分钟的谎话；
      · **证不到就不许开口**（反向）—— 这条更要紧。`anchored` 会让 UI 画出一个
        言之凿凿的倒计时；在没证到请求真被计量时说它，就是把假钟说成真钟。
    """

    def test_the_call_passes_the_real_answered_flag_not_a_constant(self):
        """★★ 守卫必须是**变量**。写死 `True`（或整个省掉这个参数）时，
        代码照样跑、测试照样绿，而断言的门槛被悄悄拆掉了 —— 本仓 §7 的空心闸形态。"""
        fn, src = _fn("cmd_probe")
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "_mark_billed_anchor"]
        self.assertEqual(len(calls), 1,
                         "★★★ `cmd_probe` 没有(或重复)调用 `_mark_billed_anchor` —— "
                         "探针启动了窗口却不记账，UI 会说它没启动")
        args = calls[0].args
        self.assertEqual(len(args), 3, "★ 实参个数变了 —— 判据看不懂了，先修闸")
        self.assertIsInstance(args[2], ast.Name,
                              "★★★ 第三个实参不是变量 ⇒ 守卫被写死 ⇒ "
                              "证不到也会开口说 anchored")
        self.assertEqual(args[2].id, "completion_ok",
                         "★★ 守卫必须是「模型真的答了」那个量，别换成别的")

    def test_it_refuses_to_mark_when_the_model_never_answered(self):
        """★★★ 反向闸。`q` 为真**目前**蕴含「答了」，但那是 `_billed_probe`
        **内部**的不变量 —— 它一改，这里就会在证不了计量的情况下断言 anchored，
        且没有任何症状。所以守卫要显式，闸也要显式。"""
        mod = _load_rotate()
        q = {"primary": {"used_percent": 0, "window_minutes": 300,
                         "resets_at": int(time.time()) + 18000},
             "secondary": {"used_percent": None, "window_minutes": None, "resets_at": None},
             "captured_at": time.time(), "source": "probe"}
        self.assertIsNone(mod._mark_billed_anchor("aid-x", q, False),
                          "★★★ 模型没吐字也标了 —— 证不到就不该开口")

    def test_it_marks_the_reset_from_the_billed_response(self):
        """★★ 正向 + **身份正确**。标的必须是计费响应头里那个 reset ——
        探针**前**那次免费 GET 的 reset 可能还是闲置期的浮动假值，
        拿它来标就是把另一个窗口标成了已锚定。"""
        mod = _load_rotate()
        d = tempfile.mkdtemp(prefix="billed-anchor-")
        ledger = str(Path(d, "ledger.json"))
        old = os.environ.get("CODEXBAR_QUOTA_ANCHORS")
        os.environ["CODEXBAR_QUOTA_ANCHORS"] = ledger   # ★ 绝不碰真实账本
        try:
            now = time.time()
            R = int(now) + 18000
            q = {"primary": {"used_percent": 0, "window_minutes": 300, "resets_at": R},
                 "secondary": {"used_percent": None, "window_minutes": None,
                               "resets_at": None},
                 "captured_at": now, "source": "probe"}
            out = mod._mark_billed_anchor("aid-x", q, True)
            self.assertIsNotNone(out, "★ 成功的探针没写出锚点判定")
            self.assertEqual(out["300"]["state"], "anchored")
            self.assertTrue(out["300"]["billed"])
            self.assertEqual(out["300"]["reset"], R,
                             "★★ 判定没自带它所描述的那个 reset —— "
                             "前端会拿它去解释另一个窗口的倒计时")
            saved = json.loads(Path(ledger).read_text(encoding="utf-8"))
            row = saved["sources"]["codex"]["aid-x/300"][0]
            self.assertEqual(int(row["reset"]), R)
            self.assertGreater(row.get("billed_at", 0), 0)
        finally:
            if old is None:
                os.environ.pop("CODEXBAR_QUOTA_ANCHORS", None)
            else:
                os.environ["CODEXBAR_QUOTA_ANCHORS"] = old

    def test_a_window_too_short_to_be_real_is_not_marked(self):
        """★ 沿用 `_win_real` 那条既有过滤。上游偶尔回一个 0 分钟的占位窗口，
        给它标锚定等于给一个不存在的窗口发证。"""
        mod = _load_rotate()
        q = {"primary": {"used_percent": 0, "window_minutes": 0,
                         "resets_at": int(time.time()) + 60},
             "secondary": {"used_percent": None, "window_minutes": None, "resets_at": None},
             "captured_at": time.time(), "source": "probe"}
        self.assertIsNone(mod._mark_billed_anchor("aid-x", q, True))
