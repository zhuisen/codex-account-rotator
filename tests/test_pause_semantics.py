"""「禁用 = 暂停使用、不可调用」的闸（用户 2026-09-09 提出的语义扩大）。

## 改之前是什么样

`rotate_off` 只挡住 `proxy.py::_pick` 一条路。于是存在一个自相矛盾的状态：
号在 UI 上写着"已禁用"，却仍然会被

  · `cmd_switch` 切成 active ⇒ **裸 `\\codex` / `cx` 从此全走它**
  · `_pick_next` / `_pick_best` 挑中
  · `cmd_probe` / `cmd_dawn_probe` 发**计费**请求（后者是全仓唯一自动花钱的东西）

而其中最隐蔽的是：**暂停的号如果正好是 `active`，`auth.json` 里就是它** ——
标志说停了，号还在被调用，且没有任何症状。这正是本仓最忌讳的「写入侧标志撒谎」。

## 这份测试守的两类东西

① **每一条会发出业务请求、或会让这个号成为 active 的路径，都必须过闸。**
   逐个点名，不用"抽查一两个"—— 漏掉的那条恰恰是下次出事的那条。
② **故意保留的例外必须被钉住**：`refresh` / keepalive **不受暂停约束**。
   OAuth 刷新打的是 `auth.openai.com/oauth/token`，不计费、不占额度，只是让号别死掉。
   停掉续期，暂停就变成慢性死亡（token 过期 → 恢复时号已废）。
   这条看起来矛盾，所以更需要一条测试说明它是**故意**的，而不是漏掉的。
"""
import re
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("cr_pause", str(ROOT / "codex-rotate"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
CR = importlib.util.module_from_spec(_spec)
_loader.exec_module(CR)


def slot(label, plan="plus", used=10.0, **kw):
    d = {"label": label, "plan": plan, "file": f"{label}.json",
         "quota": {"primary": {"window_minutes": 300, "used_percent": used, "resets_at": None},
                   "secondary": {}}}
    d.update(kw)
    return d


class ThePredicateDefaultsToUsable(unittest.TestCase):
    """★★ 缺省必须等于「可用」。存量号和 autosync 新入池的号槽位里都**没有**这个键；
    读成"暂停"会让它们静默退出可用池，症状是"代理只用那两三个号"、零报错。"""

    def test_a_slot_without_the_key_is_not_paused(self):
        self.assertFalse(CR.paused({"label": "x"}))

    def test_only_a_truthy_value_pauses(self):
        self.assertTrue(CR.paused({"rotate_off": True}))
        self.assertFalse(CR.paused({"rotate_off": False}))
        self.assertFalse(CR.paused({"rotate_off": None}))


class EverySelectionPathIsGated(unittest.TestCase):
    """① 逐个点名。抽查会漏掉下次出事的那条。"""

    def _state(self, **over):
        s = {"active": "a1", "slots": {
            "a1": slot("plusA"), "a2": slot("plusB", used=5.0), "a3": slot("plusC", used=1.0)}}
        for aid, patch in over.items():
            s["slots"][aid].update(patch)
        return s

    def test_pick_next_skips_a_paused_account(self):
        """★ `_pick_next` 交出的是 **live auth**。挑中暂停号 = 让裸 codex 开始用它。"""
        s = self._state(a2={"rotate_off": True})
        self.assertEqual(CR._pick_next(s), "a3")

    def test_pick_best_skips_a_paused_account(self):
        """a3 剩余最多(used 1%)，但它被暂停了 ⇒ 应挑 a2。"""
        s = self._state(a3={"rotate_off": True})
        self.assertEqual(CR._pick_best(s), "a2")

    def test_pick_best_returns_none_when_everything_left_is_paused(self):
        """★ 全被暂停时**不猜、不动** —— 返回 None，调用方保持当前号。"""
        s = self._state(a1={"rotate_off": True}, a2={"rotate_off": True},
                        a3={"rotate_off": True})
        self.assertIsNone(CR._pick_best(s))

    def test_dawn_targets_skips_a_paused_account(self):
        """★★ 后果最实的一条:dawn-probe 是**全仓唯一自动花钱**的东西。
        给一个用户已停用的号发计费请求,钱花了、目的没达到、且用户不知情。"""
        s = self._state(a2={"rotate_off": True})
        self.assertEqual(sorted(CR._dawn_targets(s)), ["a1", "a3"])

    def test_dawn_targets_is_empty_when_all_plus_are_paused(self):
        s = self._state(a1={"rotate_off": True}, a2={"rotate_off": True},
                        a3={"rotate_off": True})
        self.assertEqual(CR._dawn_targets(s), [])


class RefreshIsDeliberatelyNotGated(unittest.TestCase):
    """② 故意保留的例外。没有这条测试，下一个人会"顺手补上"这个闸，
    而那会让暂停变成慢性死亡（token 过期 → 恢复时号已废）。"""

    def test_the_predicate_docstring_states_the_exception(self):
        """闸的理由必须写在代码里，否则它只是个看起来不一致的地方。"""
        doc = CR.paused.__doc__ or ""
        self.assertIn("refresh", doc)
        self.assertIn("oauth/token", doc)

    def test_refresh_code_path_does_not_consult_the_predicate(self):
        """★ 判据是**源码里那段函数**，不是我在这里抄一份清单。
        `cmd_refresh` / `cmd_refresh_all` / `cmd_keepalive` 都不该出现 `paused(`。"""
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        for fn in ("cmd_refresh", "cmd_refresh_all", "cmd_keepalive"):
            start = src.index(f"\ndef {fn}(")
            end = src.find("\ndef ", start + 1)
            body = src[start:end if end > 0 else len(src)]
            body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
            self.assertNotIn("paused(", body,
                             f"{fn} 里加了暂停闸 —— 那会让暂停的号 token 过期后无法恢复")


class _Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cbx_pause_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        os.makedirs(os.path.join(self.dir, "auth"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "codex-home"), exist_ok=True)
        self.state = os.path.join(self.dir, "state.json")
        self.write_state({"active": "a1", "slots": {
            "a1": {"label": "plusA", "plan": "plus", "file": "a1.json"},
            "a2": {"label": "plusB", "plan": "plus", "file": "a2.json"},
        }})
        for n, aid in (("a1.json", "a1"), ("a2.json", "a2")):
            self.write_auth(n, aid)

    def write_state(self, d):
        with open(self.state, "w", encoding="utf-8") as fh:
            json.dump(d, fh)

    def write_auth(self, name, aid):
        with open(os.path.join(self.dir, "auth", name), "w", encoding="utf-8") as fh:
            json.dump({"tokens": {"access_token": "TESTONLY-" + aid, "account_id": aid}}, fh)

    def cli(self, *args):
        # ★★ **两个变量都要设。** `STORE` 决定 state.json / auth/ 的位置,
        #    而 `LIVE = CODEX_HOME / "auth.json"` 走的是**另一个**。
        #    2026-09-09 我只设了前者 ⇒ 假凭证被写进真实 `~/.codex/auth.json`,
        #    launchd 的 autosync 当场把它当新账号加进真实账号池(详见 conftest.py)。
        env = dict(os.environ, CODEX_ROTATE_STORE=self.dir,
                   CODEX_HOME=os.path.join(self.dir, "codex-home"))
        return subprocess.run([sys.executable, str(ROOT / "codex-rotate"), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def state_now(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)

    def live(self):
        p = Path(self.dir) / "codex-home" / "auth.json"
        return json.loads(p.read_text()) if p.exists() else None


class PausingTheActiveAccountHandsOverTheLiveAuth(_Cli):
    """★★★ 这次改动的核心。改之前:标志写"已暂停"而 `auth.json` 里还是它 ——
    裸 `\\codex` / `cx` 照样在用,没有任何症状。"""

    def test_the_live_credential_moves_to_another_account(self):
        r = self.cli("rotate", "plusA", "--off")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.state_now()
        self.assertTrue(st["slots"]["a1"]["rotate_off"])
        self.assertEqual(st["active"], "a2", "暂停了当值号却没交接 —— auth.json 里还是它")
        self.assertEqual(self.live()["tokens"]["account_id"], "a2")
        self.assertIn("已把当值交给", r.stdout)

    def test_it_refuses_when_nobody_can_take_over(self):
        """★ 挑不到接手号就**拒绝暂停**,而不是"停了但不切" —— 后者让标志说谎。"""
        self.write_state({"active": "a1", "slots": {
            "a1": {"label": "plusA", "plan": "plus", "file": "a1.json"},
            "a2": {"label": "plusB", "plan": "plus", "file": "a2.json",
                   "auth_dead": True},
        }})
        r = self.cli("rotate", "plusA", "--off")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("rotate_off", self.state_now()["slots"]["a1"],
                         "拒绝了却还是写下了暂停标志")

    def test_a_broken_handover_credential_aborts_the_whole_pause(self):
        """★★ 接手号的 auth 文件缺失/损坏时,**什么都不许写**。
        若吞掉异常继续存 state,结果正是这次改动要消灭的那个状态。
        （这条是被原有 fixture 的红灯逼出来的:它当时没有凭证文件。）"""
        os.remove(os.path.join(self.dir, "auth", "a2.json"))
        r = self.cli("rotate", "plusA", "--off")
        self.assertNotEqual(r.returncode, 0)
        st = self.state_now()
        self.assertNotIn("rotate_off", st["slots"]["a1"], "交接失败却写下了暂停标志")
        self.assertEqual(st["active"], "a1")

    def test_pausing_a_non_active_account_does_not_move_the_credential(self):
        r = self.cli("rotate", "plusB", "--off")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_now()["active"], "a1")
        self.assertIsNone(self.live(), "不该动 live auth")


class PausedAccountsCannotBeCalled(_Cli):
    def test_switch_refuses_a_paused_target(self):
        """★ 切号 = 把它写进 live auth ⇒ 裸 codex 从此全走它。"""
        self.cli("rotate", "plusB", "--off")
        r = self.cli("switch", "plusB")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("暂停", r.stdout + r.stderr)
        self.assertEqual(self.state_now()["active"], "a1")

    def test_probe_refuses_a_paused_target(self):
        """★ probe 花**真钱**。对已暂停的号照做,等于"已禁用"当场失效。"""
        self.cli("rotate", "plusB", "--off")
        r = self.cli("probe", "plusB")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("暂停", r.stdout + r.stderr)

    def test_the_refusal_names_the_command_that_undoes_it(self):
        """拒绝时要告诉用户下一步敲什么 —— 本仓铁律:告警文案要说做什么。"""
        self.cli("rotate", "plusB", "--off")
        out = self.cli("switch", "plusB").stdout + self.cli("switch", "plusB").stderr
        self.assertIn("--on", out)


class SkipTracesAreDistinguishable(unittest.TestCase):
    """★ 「没探过」「因失效跳过」「因暂停跳过」是三件事,状态码必须不同 ——
    死号要去修 token,暂停号只需要用户决定要不要恢复,**动作不同**。"""

    def test_the_source_uses_a_distinct_status_for_paused(self):
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        self.assertIn('status="skipped_paused"', src)
        self.assertIn('status="skipped_dead"', src)


class TheLastUsableAccountIsStillProtected(_Cli):
    def test_cannot_pause_them_all(self):
        self.assertEqual(self.cli("rotate", "plusA", "--off").returncode, 0)
        r = self.cli("rotate", "plusB", "--off")
        self.assertNotEqual(r.returncode, 0, "把最后一个可用号也暂停了 —— codex 会整个不可用")

    def test_status_flags_a_paused_account_that_is_still_active(self):
        """★ 正常路径下不可能出现（暂停会先交接）。手改 state.json 绕过 CLI 时会出现 ——
        那是必须当场看见的不一致,不能只显示"已暂停"。"""
        self.write_state({"active": "a1", "slots": {
            "a1": {"label": "plusA", "plan": "plus", "file": "a1.json", "rotate_off": True},
            "a2": {"label": "plusB", "plan": "plus", "file": "a2.json"},
        }})
        out = self.cli("rotate", "--status").stdout
        self.assertIn("仍是 active", out)


if __name__ == "__main__":
    unittest.main()


class TheUiNeverProposesAPausedAccount(unittest.TestCase):
    """★★ 用户 2026-09-10：「我选了禁止轮换，还是会切换到对应的号上」。

    实测链路：`cmd_switch` **确实拒绝**了（暂停号不许成为当值号）。真正坏的是前端 ——

      ① `useAutoSwitch` 挑目标时只看额度 `tightest`，**没过滤 `rotates`**，
         于是每隔一轮就挑中被暂停的号；
      ② 它把 `notify("已切到 X")` 和 `run(...)` 并排写，**无条件发**成功通知。
         CLI 拒绝了，用户照样收到系统通知说切过去了。

    「它说切了、其实没切」是这条链路最不该出现的谎，而系统通知比 toast 更难撤回。
    """

    ROOT = Path(__file__).resolve().parents[1]
    HOOK = (ROOT / "codexbar" / "src" / "hooks" / "useAutoSwitch.ts").read_text(encoding="utf-8")
    STORE = (ROOT / "codexbar" / "src" / "hooks" / "useStore.ts").read_text(encoding="utf-8")

    def _body(self, text):
        """剥注释再断言 —— 本仓已多次被"闸命中自己的说明文字"判红。"""
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return re.sub(r"^\s*//.*$", "", text, flags=re.M)

    def test_the_candidate_loop_skips_paused_accounts(self):
        body = self._body(self.HOOK)
        self.assertIn("if (!a.rotates) continue;", body,
                      "★ 自动切号没排除被暂停的号 —— 会反复挑中它、被 CLI 拒、再挑中")

    def test_the_success_notification_waits_for_the_result(self):
        """★ `notify` 必须在 `run(...)` 的结果分支里，不能与它并排。"""
        body = self._body(self.HOOK)
        self.assertNotIn('run("auto-switch"', body.split(".then(")[0].split("notify(")[0][:0] or "\x00")
        # 判据:notify 出现在 `.then(` 之后
        i_run, i_then, i_notify = body.find("run(\"auto-switch\""), body.find(".then("), body.find("notify(\"自动切号\"")
        self.assertGreater(i_then, i_run, "run 之后没有 .then —— 通知没等结果")
        self.assertGreater(i_notify, i_then, "★ notify 在结果之前发出 —— CLI 拒绝了也会说「已切到」")
        self.assertIn("if (ok)", body, "没有按成功与否分支")

    def test_run_reports_whether_it_actually_succeeded(self):
        """★ 上游能力:`run` 必须返回布尔。它以前吞掉异常、返回 undefined，
        调用方**无从判断** CLI 拒绝没拒绝 —— 上面那条谎的根子在这里。"""
        body = self._body(self.STORE)
        self.assertIn("let ok = false;", body)
        self.assertIn("ok = true;", body)
        self.assertIn("return ok;", body)

    def test_the_cli_still_refuses_as_the_last_line_of_defence(self):
        """★ 前端过滤是**体验**，CLI 拒绝才是**保证**。两道都要在 ——
        前端可以被绕过（命令行、另一个 webview、旧 bundle）。"""
        cli = (self.ROOT / "codex-rotate").read_text(encoding="utf-8")
        body = cli[cli.index("def cmd_switch"):cli.index("def cmd_switch") + 2000]
        self.assertIn("paused(", body, "cmd_switch 不再检查暂停状态")
        self.assertIn("拒绝", body)
