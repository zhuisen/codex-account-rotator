"""每日清晨探针的护栏(2026-09-06,用户要求「早上 6 点给 Plus 号探针，让 5h 额度走动」)。

## 它要解决什么

Codex 的 5h 窗口**用过才锚定**：一次没用过时服务端每轮都回「此刻 + 整窗」，
`resets_at` 跟着 now 滑动，倒计时永远停在 ~4h55m，那 5 小时额度**等于没在走**。
发一次真实请求即可锚定。

## 为什么这份测试必须存在

★★ **这是本仓唯一一个会自动花钱的东西。** 此前 `cmd_probe` 的 docstring 明写
「没有接进 quotad、没有接进 CodexBar 按钮、也没有任何定时器会调它」——
因为项目当初正是被**自动计费探测每天烧掉 17-18%** 才把它废掉的。
现在重新引入自动计费，三条护栏一条都不能松，而且每条都要有闸：

  ① **当天幂等且先占天**。launchd 06:00 与 app 内补跑**两条路都会调它**
     （用户选的「两条都要」，因为本项目的日历定时有静默不运行的前科）。
     标记必须写在**发请求之前** —— 写在之后的话，两个进程在那段窗口里
     看到的都是昨天的日期 ⇒ **双重计费**。
  ② **默认关闭**。仓库已公开，默认开启的自动计费定时器会在别人机器上悄悄花钱。
  ③ **按 `plan` 判 Plus，不按 label**。label 只是昵称，而**老号从 Plus 升 Pro 时
     label 一个字都不会变** —— 按名字挑号会在升级那天开始给没有 5h 窗口的 Pro 号
     花钱，钱花了目的一点没达到，且没有任何症状。

## ★ 这份测试绝不碰真实 state.json / 不发任何请求

全部在临时 store 上跑（`CODEX_ROTATE_STORE`），且只走**不发请求**的分支
（未启用 / 已跑过 / 被别人占天 / 没有 Plus 号）。
唯一进到"探测阶段"的用例用的是**必然失败的假凭证**，验的是「几个进程进到那一步」，
不是探测本身。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / "codex-rotate")
INSTALLER = ROOT / "scripts" / "install-launchd.sh"


def run(store, *args, **kw):
    env = dict(os.environ, CODEX_ROTATE_STORE=store)
    env.pop("CODEXBAR_QUOTA_ANCHORS", None) if kw.pop("no_anchor_iso", False) else None
    return subprocess.run([sys.executable, CLI, "dawn-probe", *args],
                          env=env, capture_output=True, text=True, timeout=120)


def store_with(slots, dawn=None):
    d = tempfile.mkdtemp(prefix="dawn-test-")
    st = {"slots": slots, "active": next(iter(slots), None)}
    if dawn is not None:
        st["dawn_probe"] = dawn
    Path(d, "state.json").write_text(json.dumps(st), encoding="utf-8")
    Path(d, "auth").mkdir(exist_ok=True)
    return d


def slot(label, plan, dead=False):
    return {"label": label, "plan": plan, "file": f"{label}.json",
            **({"auth_dead": True} if dead else {})}


PLUS_POOL = {"user-a": slot("plusA", "plus"), "user-b": slot("plusB", "plus"),
             "user-c": slot("proC", "pro"), "user-d": slot("plusD", "plus", dead=True)}


class DefaultsToOff(unittest.TestCase):
    """★★ 护栏②:默认关闭。仓库公开,默认开启的自动计费器会在别人机器上悄悄花钱。"""

    def test_fresh_store_does_not_run(self):
        d = store_with(PLUS_POOL)
        p = run(d, )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("未启用", p.stdout)
        # ★ 关键:**没有写任何运行记录** —— 空转就该是真的什么都没做
        st = json.loads(Path(d, "state.json").read_text(encoding="utf-8"))
        self.assertIsNone((st.get("dawn_probe") or {}).get("date"))

    def test_status_reports_disabled(self):
        p = run(store_with(PLUS_POOL), "--status")
        self.assertEqual(json.loads(p.stdout)["enabled"], False)


class PlanFilter(unittest.TestCase):
    """★★ 护栏③:按 `plan` 判 Plus。"""

    def test_only_plus_and_only_alive(self):
        p = run(store_with(PLUS_POOL), "--status")
        got = set(json.loads(p.stdout)["targets_today"])
        self.assertEqual(got, {"plusA", "plusB"},
                         "Pro 号或失效号混进了计费名单: %s" % sorted(got))

    def test_plan_is_read_from_plan_not_label(self):
        """★★ **老号从 Plus 升 Pro 时 label 一个字都不变。**
        所以一个 label 叫 `plusOld`、plan 已是 `pro` 的号**必须**被排除 ——
        按名字挑会在升级那天开始给没有 5h 窗口的号花钱,且毫无症状。"""
        d = store_with({"user-x": slot("plusOld", "pro")})
        self.assertEqual(json.loads(run(d, "--status").stdout)["targets_today"], [])

    def test_plan_type_from_quota_is_a_fallback(self):
        d = store_with({"user-y": {"label": "n1", "file": "n1.json",
                                   "quota": {"plan_type": "plus"}}})
        self.assertEqual(json.loads(run(d, "--status").stdout)["targets_today"], ["n1"])


class DayIdempotence(unittest.TestCase):
    """★★ 护栏①。"""

    def test_already_ran_today_is_a_noop(self):
        import datetime
        today = datetime.date.today().isoformat()
        d = store_with(PLUS_POOL, dawn={"enabled": True, "date": today, "ok": 2, "total": 2})
        p = run(d)
        self.assertIn("已跑过", p.stdout)
        self.assertNotIn("每日清晨探针 ·", p.stdout, "已跑过却仍进入了探测阶段 = 双重计费")

    def test_concurrent_runs_only_one_reaches_the_billing_stage(self):
        """★★ **这条是整份测试的守门员。**

        三个进程同时跑。若「今天跑过」的标记写在探测**之后**，它们会同时看到昨天的日期、
        同时进入探测 ⇒ 三倍计费。判据直接钉死:**恰好 1 个**打印出探测抬头。
        """
        d = store_with(PLUS_POOL, dawn={"enabled": True})
        env = dict(os.environ, CODEX_ROTATE_STORE=d)
        ps = [subprocess.Popen([sys.executable, CLI, "dawn-probe"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
              for _ in range(3)]
        outs = [p.communicate(timeout=180)[0] for p in ps]
        entered = sum(1 for o in outs if "每日清晨探针 ·" in o)
        self.assertEqual(entered, 1,
                         "%d 个进程进入了计费阶段（必须恰好 1）:\n%s"
                         % (entered, "\n---\n".join(outs)))

    def test_claim_is_written_before_probing(self):
        """★ 判据打在**源码顺序**上:占天的 `_mutate_state` 必须出现在 `cmd_probe(` 之前。
        行为测试只能证明「这次没并发出问题」，顺序才是它成立的原因。

        ⚠️ 原来硬编的是 `cmd_probe(labels)`。2026-09-12 把程序内调用改成
        `cmd_probe([], aids=targets)`（让身份走 aid、不经过 argv）之后这条闸
        `ValueError: substring not found` —— 它盯的是**实参长什么样**，而它要守的
        是**两个调用谁先谁后**。现在按 AST 比行号，实参怎么写都与它无关。"""
        import ast as _ast
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        fn = next(n for n in _ast.walk(_ast.parse(src))
                  if isinstance(n, _ast.FunctionDef) and n.name == "cmd_dawn_probe")
        calls = {}
        for n in _ast.walk(fn):
            if not isinstance(n, _ast.Call):
                continue
            name = getattr(n.func, "id", "")
            if name == "_mutate_state" and any(getattr(a, "id", "") == "_claim" for a in n.args):
                calls.setdefault("claim", n.lineno)
            elif name == "cmd_probe":
                calls.setdefault("probe", n.lineno)
        self.assertIn("claim", calls, "★ 找不到占天的 `_mutate_state(_claim)` —— 探针失准")
        self.assertIn("probe", calls, "★ 找不到 `cmd_probe(...)` 调用 —— 探针失准")
        self.assertLess(calls["claim"], calls["probe"],
                        "占天写在探测之后 —— 并发窗口里会双重计费")


class LeavesATrace(unittest.TestCase):
    """★★ 护栏③':每次运行落痕。`runs = 0、从未运行过` 正是本项目
    keepalive/refreshquota 的真实结局,而那件事没有任何一处会报红。"""

    def test_no_plus_accounts_still_records_the_run(self):
        d = store_with({"user-c": slot("proC", "pro")}, dawn={"enabled": True})
        p = run(d)
        self.assertIn("没有可探的 Plus 号", p.stdout)
        rec = json.loads(Path(d, "state.json").read_text(encoding="utf-8"))["dawn_probe"]
        self.assertTrue(rec.get("date"),
                        "「跑了但没号可探」没有落痕 —— 明天会和「压根没跑」长得一模一样")

    def test_enable_disable_round_trip(self):
        d = store_with(PLUS_POOL)
        run(d, "--enable")
        self.assertTrue(json.loads(run(d, "--status").stdout)["enabled"])
        run(d, "--disable")
        self.assertFalse(json.loads(run(d, "--status").stdout)["enabled"])


class WiredIntoTheSystem(unittest.TestCase):
    def test_launchd_job_is_installed_at_six(self):
        src = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("emit dawnprobe", src)
        i = src.index("emit dawnprobe")
        seg = src[i:i + 400]
        self.assertIn("StartCalendarInterval", seg)
        self.assertRegex(seg, r"<key>Hour</key><integer>6</integer>")
        self.assertIn("dawn-probe", seg)

    def test_installer_verifies_the_new_job(self):
        """★ 装完要能在末尾那份清单里看到它,否则「装了没装上」看不出来。"""
        self.assertIn("dawnprobe", INSTALLER.read_text(encoding="utf-8").split("==> loaded")[-1])

    def test_app_can_invoke_it(self):
        """app 内补跑靠 `run_rotate`,命令必须在白名单里,否则补跑那条路径是死的。"""
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("const ALLOWED_CMDS")
        self.assertIn('"dawn-probe"', rs[i:i + 500])

    def test_ui_surfaces_the_last_run(self):
        """★★ 「上次运行」必须显示在设置页 —— 它是「定时到底跑没跑」的唯一可见证据。
        本项目的日历定时被外力改写丢过 StartCalendarInterval,runs = 0、从未运行过,
        而没有任何一处会为此报红。"""
        ts = (ROOT / "codexbar" / "src" / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")
        self.assertIn("dawnDesc", ts)
        i = ts.index("function dawnDesc")
        body = ts[i:ts.index("\n}", i)]
        self.assertIn("上次运行", body, "没有显示上次运行时刻 —— 静默不跑就看不出来")
        self.assertIn("d.at", body)

    def test_ui_reads_state_not_localstorage(self):
        """★★ 开关的真源必须是 `state.json`:launchd 在 app 没开时也要读它。
        存进 localStorage 就是两个真源,迟早分叉成「界面说开着、定时器不认」。"""
        ts = (ROOT / "codexbar" / "src" / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")
        i = ts.index("const toggleDawn")
        self.assertIn("run_rotate", ts[i:i + 400], "开关走了 localStorage 而不是 CLI")


if __name__ == "__main__":
    unittest.main()


class ForceDoesNotJoinARunInFlight(unittest.TestCase):
    """★★★ 四方评审 #1（2026-09-07，claude+agy+grok 三家找到）：
    `--force` 原来是 `if claimed["n"] and not force:` —— 一律放行。

    `--force` 的**本意**是「今天跑过了，我想再跑一次」。可同一行也会在
    **另一个进程正跑到一半**时放行 ⇒ 两个进程同时给全池发计费请求 ⇒
    **整池双重计费**。它恰好违反这个工具自己写着的那句：
    「在"少跑一次"和"可能多花一次钱"之间，一律选前者」。

    ⚠️ 但 `running` 不能无条件当"有人在跑"：进程被 `kill -9` 时连 `failed` 都写不下，
    `running` 会永远钉在那里，`--force` 连**恢复**都做不到。所以判据是
    **`running` 且未陈旧**，不是 `running`。下面四条把这个边界的两侧都钉住 ——
    只测拒绝那一侧的话，一个"永远拒绝"的实现也能全绿。
    """

    def _dawn(self, state, age_sec):
        import time as _t
        return {"enabled": True, "date": __import__("datetime").date.today().isoformat(),
                "at": int(_t.time()) - age_sec, "state": state, "ok": None, "total": 1}

    ONE_PLUS = {"user-a": slot("plusA", "plus")}

    def test_force_refuses_while_another_run_is_in_flight(self):
        """★★ 这是全仓唯一一处**拒绝用户明确指令**的地方。
        代价不对称：拒绝 = 少跑一次；放行 = 整池多扣一次。"""
        d = store_with(self.ONE_PLUS, dawn=self._dawn("running", 30))
        p = run(d, "--force")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("每日清晨探针 ·", p.stdout,
                         "★★★ `--force` 在别人正跑时放行了 ⇒ 整池双重计费")
        self.assertIn("`--force` 也不放行", p.stdout,
                      "★ 拒绝了但没说是 force 也拦 —— 用户会以为 force 没生效再敲一遍")

    def test_force_can_still_take_over_a_stale_running(self):
        """★★ 反向闸。`kill -9` 留下的 `running` 必须能被接管，
        否则这个开关从"防重复计费"变成"永久卡死"，而用户手上没有别的办法。"""
        d = store_with(self.ONE_PLUS, dawn=self._dawn("running", 7200))
        p = run(d, "--force")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("每日清晨探针 ·", p.stdout,
                      "★ 陈旧的 running 挡住了 --force —— 进程被 -9 之后就再也跑不了了")
        self.assertIn("接管一条陈旧的 running", p.stdout,
                      "★ 接管了但没说 —— 那次**可能已经花过钱**，用户有权知道")

    def test_force_still_reruns_a_finished_day(self):
        """★ `--force` 的本职工作不能被这次修复顺手废掉。"""
        d = store_with(self.ONE_PLUS, dawn=self._dawn("done", 30))
        p = run(d, "--force")
        self.assertIn("每日清晨探针 ·", p.stdout, "★ `--force` 连正常重跑都做不到了")

    def test_without_force_every_state_still_blocks(self):
        """★ 不带 `--force` 时三种状态都挡 —— 这条本来就成立，钉住它防回归。"""
        for st in ("running", "done", "failed"):
            with self.subTest(state=st):
                p = run(store_with(self.ONE_PLUS, dawn=self._dawn(st, 30)))
                self.assertNotIn("每日清晨探针 ·", p.stdout,
                                 f"★ state={st} 时不带 force 也跑了 ⇒ 可能二次计费")


class TheProgramInternalCallDoesNotGoThroughArgv(unittest.TestCase):
    """★★★ 四方评审 #4（2026-09-07）：`cmd_dawn_probe` 原来把每个号的 **label**
    拼进 `args` 交给 `cmd_probe` 按 argv 解析，而 **label 是用户可以随便起的字符串**
    （`cmd_add` 里 `label = args[0] if args else None`，零校验）。三种后果：

      · label 叫 `--all`    ⇒ `take_all` 为真 ⇒ **给整个池子计费**，
                              包括每日探针刻意排除的 Pro 号；
      · label 叫 `--model`  ⇒ **吞掉它后面那个 label**，那个号这天漏探且无人知晓；
      · 两个号重名          ⇒ `_resolve_slot` 只认一个 ⇒ 另一个被**重复计费**。

    ★ 修法**不是拉黑这几个字符串** —— 那只堵住今天想得到的那几个。
    是让程序内调用**根本不经过 argv**：身份是 `aid`，由我们生成、不可被起名。
    所以下面第一条闸打在**结构**上（有没有走 aid 这条路），
    第二条才用 `--all` 这个具体 label 做行为验证 —— 它是**症状**不是判据。

    ⚠️ 本机今天一个都触发不到（labels 全是 `plusN`/`ProN`，无重名、无 `--` 开头），
    所以这**不是**已发生的事故，是一条只要有人起个怪名字就会当场花钱的路径。
    """

    def test_dawn_probe_passes_aids_not_label_strings(self):
        import ast as _ast
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        fn = next(n for n in _ast.walk(_ast.parse(src))
                  if isinstance(n, _ast.FunctionDef) and n.name == "cmd_dawn_probe")
        calls = [n for n in _ast.walk(fn) if isinstance(n, _ast.Call)
                 and getattr(n.func, "id", "") == "cmd_probe"]
        self.assertEqual(len(calls), 1, "★ `cmd_probe` 的调用不是恰好 1 处 —— 探针失准")
        c = calls[0]
        kw = {k.arg for k in c.keywords}
        self.assertIn("aids", kw,
                      "★★★ 没走 `aids=` ⇒ 又回到按 argv 解析 label ⇒ 怪名字能烧全池")
        self.assertEqual(len(c.args), 1, "★ 位置参数不止一个 —— 判据看不懂了，先修闸")
        self.assertIsInstance(c.args[0], _ast.List, "★ 第一个实参不是字面量列表")
        self.assertEqual(c.args[0].elts, [],
                         "★★ argv 那条路又被塞了东西 —— 必须是空列表，解析路径整条不走")

    def test_a_slot_labelled_dash_dash_all_does_not_bill_the_whole_pool(self):
        """★★ 行为验证。池子：两个 Plus（其中一个 label 就叫 `--all`）+ 一个 Pro。
        每日探针的名单是那两个 Plus；Pro 号**绝不该**被碰到。"""
        pool = {"user-a": slot("plusA", "plus"),
                "user-b": slot("--all", "plus"),
                "user-c": slot("proC", "pro")}
        d = store_with(pool, dawn={"enabled": True})
        p = run(d, "--force")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("计费探测 ·", p.stdout, "★ 没进到探测阶段，这条闸什么都没验到")
        import re as _re
        m = _re.search(r"· (\d+) 个号", p.stdout)
        self.assertIsNotNone(m, "★ 读不到号数 —— 输出格式变了，先修闸")
        self.assertEqual(int(m.group(1)), 2,
                         "★★★ 一个叫 `--all` 的 label 把 take_all 打开了 ⇒ 整池计费\n" + p.stdout)
        self.assertNotIn("proC", p.stdout,
                         "★★★ Pro 号进了计费名单 —— 每日探针刻意排除它（它没有 5h 窗口）")
