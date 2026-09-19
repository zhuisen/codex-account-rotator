"""账号池 Connector —— 它会动用户的 `~/.codex`，所以每一条边界都要有闸。

## 为什么这些闸比一般的重

Connector 是本仓**第一个主动改用户配置文件**的东西。它碰的三样各自有前科：

  · `~/.codex/config.toml` —— 用户的 MCP / hooks / 模型偏好都在里面。本仓在中转站
    profile 上栽过一次（2026-09-10：命中托管标记就 `unlink()` 整份），所以这里的判据是
    **标记之外逐字节不变**，而且 `apply` → `remove` 往返之后必须回到**原样**。
  · `~/.local/bin` —— 用户可能自己放了同名脚本。**只覆盖 symlink，普通文件先备份**；
    `remove` 只删指向我们运行时的那些。
  · `codex login` / `codex logout` —— 会 server-side 吊销当值号（本机死过 3 个号）。
    Connector **永远不许调它们**，这条有独立的静态闸。

## 隔离

全部走 `CODEX_HOME` / `CODEXBAR_LOCAL_BIN` / `CODEXBAR_LAUNCH_AGENTS` 三个环境变量。
★ `services` 那一步会真跑 `install-launchd.sh` 并调 `launchctl` —— 测试**一律不选它**，
  只用静态闸验「失败必须如实上报」。
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import connector  # noqa: E402


USER_CONFIG = (
    "# 我自己的配置\n"
    'model = "gpt-5.6-sol"\n'
    "\n"
    "[mcp_servers.foo]\n"
    'command = "x"\n'
)


class Sandbox(unittest.TestCase):
    """一套完全隔离的 HOME 侧目录 + 一份假的安装包 `src`。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.src = d / "src"
        self.store = d / "store"
        self.home = d / "home"
        self.bin = d / "bin"
        self.agents = d / "agents"
        for p in (self.src, self.store, self.home, self.bin, self.agents):
            p.mkdir(parents=True)
        for rel in connector.RUNTIME_FILES:
            s = ROOT / rel
            if s.exists():
                (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, self.src / rel)
        self._env = {}
        for k, v in (("CODEX_HOME", self.home), ("CODEXBAR_LOCAL_BIN", self.bin),
                     ("CODEXBAR_LAUNCH_AGENTS", self.agents)):
            self._env[k] = os.environ.get(k)
            os.environ[k] = str(v)
        self.addCleanup(self._restore)
        # ★ 绝不让 plan 去问真机的 launchctl —— 那会让结果跟着**跑测试的机器**变。
        self._svc = connector._svc_loaded
        connector._svc_loaded = lambda name: False
        self.addCleanup(lambda: setattr(connector, "_svc_loaded", self._svc))

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @property
    def cfg(self):
        return self.home / "config.toml"

    def plan(self):
        return connector.plan(self.src, self.store)

    def step(self, sid, p=None):
        return [s for s in (p or self.plan())["steps"] if s["id"] == sid][0]

    def apply(self, *steps):
        return connector.apply(self.src, self.store, list(steps))


class TheUsersConfigIsNeverRewritten(Sandbox):
    """★★★ 只在托管标记之间写。标记之外**一个字节都不动**。"""

    def test_existing_content_survives_verbatim(self):
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider")
        after = self.cfg.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(USER_CONFIG.rstrip("\n")),
                        "★ 用户原有内容被改动了")
        self.assertIn("[mcp_servers.foo]", after)
        self.assertIn(connector.MARK_BEGIN, after)

    def test_apply_then_remove_round_trips_to_the_original(self):
        """★★ 往返之后必须回到原样 —— 这是「可撤销」的唯一硬判据。"""
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider", "profile")
        connector.remove(self.store)
        self.assertEqual(self.cfg.read_text(encoding="utf-8").strip(),
                         USER_CONFIG.strip(), "★★ 撤销之后没回到原样")

    def test_a_second_apply_does_not_duplicate_the_block(self):
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider")
        self.apply("runtime", "provider")
        self.assertEqual(self.cfg.read_text(encoding="utf-8").count(connector.MARK_BEGIN), 1)

    def test_a_config_we_never_touched_is_left_alone_by_remove(self):
        """没有托管标记 ⇒ 不是我们写的 ⇒ `remove` 一个字节都不许动。"""
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        connector.remove(self.store)
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), USER_CONFIG)


class AHandMadeSetupIsReportedAsExternalNotTodo(Sandbox):
    """★★ 「没装」与「你自己装的」必须分开 —— 否则会建议用户覆盖正在用的配置。

    2026-09-19 实测：第一版把作者机器上手工配的 provider/profile/wrapper 全报成 `todo`。
    """

    def test_a_handwritten_provider_reads_as_external(self):
        self.cfg.write_text(USER_CONFIG + '\n[model_providers.rotateproxy]\nbase_url = "x"\n',
                            encoding="utf-8")
        self.assertEqual(self.step("provider")["state"], "external")

    def test_an_external_setup_still_counts_as_ready(self):
        """它确实在工作 —— 只是不是我们装的。不能因此一直弹「未接入」。"""
        self.cfg.write_text(USER_CONFIG + '\n[model_providers.rotateproxy]\nbase_url = "x"\n',
                            encoding="utf-8")
        (self.home / "rotateproxy.config.toml").write_text(
            'model_provider = "rotateproxy"\n', encoding="utf-8")
        for n in connector.ENTRIES:
            (self.bin / n).write_text("#!/bin/sh\n", encoding="utf-8")
        connector._svc_loaded = lambda name: True
        self.apply("runtime")
        p = self.plan()
        self.assertTrue(p["ready"], [s["state"] for s in p["steps"]])

    def test_our_own_block_reads_as_done_not_external(self):
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider")
        self.assertEqual(self.step("provider")["state"], "done")


class TheEntriesNeverClobberUserFiles(Sandbox):
    def test_a_real_file_is_backed_up_not_overwritten(self):
        mine = self.bin / "cxp"
        mine.write_text("#!/bin/sh\necho 我自己的\n", encoding="utf-8")
        r = self.apply("runtime", "entries")
        self.assertTrue(any("备份" in n for n in r["notes"]), r["notes"])
        self.assertTrue((self.bin / "cxp.before-codexbar").exists(),
                        "★ 用户原有的文件被直接覆盖了")

    def test_remove_keeps_symlinks_that_are_not_ours(self):
        foreign = self.bin / "cxd"
        foreign.symlink_to("/usr/bin/true")
        self.apply("runtime", "entries")          # 它是 symlink ⇒ 会被替换
        # 再造一个不属于我们的
        (self.bin / "codex-rotate").unlink()
        (self.bin / "codex-rotate").symlink_to("/usr/bin/true")
        out = connector.remove(self.store)
        self.assertTrue((self.bin / "codex-rotate").is_symlink(),
                        "★ 删掉了不是我们建的 symlink")
        self.assertTrue(any("codex-rotate" in k for k in out["kept"]), out)

    def test_every_entry_target_ships_in_the_runtime(self):
        """★★ 漏一个就会建出**悬空 symlink** —— 点一下报 No such file，
        而用户完全看不出与 Connector 有关。2026-09-19 `agy-rotate` 真漏过。"""
        missing = [t for t in connector.ENTRIES.values()
                   if t not in connector.RUNTIME_FILES]
        self.assertEqual(missing, [], f"★★ 这些入口的目标不在运行时清单里：{missing}")

    def test_the_copied_runtime_has_no_dangling_entry(self):
        """行为闸：真复制一遍，逐个入口确认目标文件存在。"""
        self.apply("runtime", "entries")
        for name in connector.ENTRIES:
            link = self.bin / name
            self.assertTrue(link.is_symlink(), name)
            self.assertTrue(Path(os.readlink(link)).exists(),
                            f"★★ {name} 是悬空 symlink → {os.readlink(link)}")


class TheWrapperStepIsOptIn(Sandbox):
    """★ 装它之后裸 `codex` 的行为就变了 —— 必须是用户单独勾的一步。"""

    def test_it_is_marked_optional(self):
        self.assertTrue(self.step(connector.STEP_WRAPPER)["optional"])

    def test_no_other_step_is_optional(self):
        opt = [s["id"] for s in self.plan()["steps"] if s["optional"]]
        self.assertEqual(opt, [connector.STEP_WRAPPER])

    def test_readiness_does_not_require_it(self):
        """不装 wrapper 也算接好了（`cxp` 就能用）——否则会逼用户改 `codex`。"""
        for n in connector.ENTRIES:
            (self.bin / n).write_text("#", encoding="utf-8")
        self.cfg.write_text('[model_providers.rotateproxy]\n', encoding="utf-8")
        (self.home / "rotateproxy.config.toml").write_text("rotateproxy\n", encoding="utf-8")
        connector._svc_loaded = lambda name: True
        self.apply("runtime")
        self.assertTrue(self.plan()["ready"])

    def test_applying_entries_alone_never_touches_codex(self):
        self.apply("runtime", "entries")
        self.assertFalse((self.bin / "codex").exists(),
                         "★ 没勾 wrapper 却动了 `codex`")


class ItNeverTouchesCredentials(unittest.TestCase):
    """★★★ `codex login` / `codex logout` 会 server-side 吊销当值号。静态闸。"""

    def test_the_module_never_invokes_codex_login_or_logout(self):
        src = (ROOT / "connector.py").read_text(encoding="utf-8")
        # 剥掉注释与 docstring —— 本仓记过：断言撞上解释这条规则的注释会假红。
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                node.value = ""
        code = ast.unparse(tree)
        for bad in ('"login"', "'login'", '"logout"', "'logout'"):
            self.assertNotIn(bad, code, f"★★★ connector 里出现了 {bad}")

    def test_it_never_reads_the_auth_dir(self):
        src = (ROOT / "connector.py").read_text(encoding="utf-8")
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                node.value = ""
        self.assertNotIn("auth.json", ast.unparse(tree))


class FailuresAreReportedHonestly(Sandbox):
    def test_a_failed_service_install_is_not_swallowed(self):
        """★ 装服务失败却报 ok ⇒ 用户以为装好了，而代理根本没起。"""
        script = self.store / "runtime" / "scripts" / "install-launchd.sh"
        self.apply("runtime")
        script.write_text("#!/bin/bash\necho 故意失败 >&2\nexit 3\n", encoding="utf-8")
        r = connector.apply(self.src, self.store, ["services"])
        self.assertFalse(r["ok"])
        self.assertIn("失败", r["error"])
        self.assertNotIn("services", r["done"])

    def test_a_missing_runtime_file_blocks_instead_of_half_installing(self):
        (self.src / "proxy" / "proxy.py").unlink()
        st = self.step("runtime")
        self.assertEqual(st["state"], "blocked")
        self.assertTrue(self.plan()["blocked"])


class TheRuntimeActuallyShipsInTheInstaller(unittest.TestCase):
    """★★★ 「改了谁来读，就必须同时验谁来写。」

    Connector 读 `RUNTIME_FILES`，而**供给方**是 `tauri.conf.json` 的 `bundle.resources`。
    本机看不出分叉：`deploy.sh` 把仓库路径烧进 `CODEXBAR_STORE_DEFAULT`，于是 app 拿到的
    `script_dir()` 就是仓库本身，什么都在。**只有 CI 出的安装包会缺**，而症状是
    「点了接入，说缺运行时文件」——在开发机上永远复现不出来。
    同族前车之鉴：`CODEX_ROTATE_STORE` 那次，四个服务定义一个都没带那个变量。
    """

    def test_every_runtime_file_is_bundled(self):
        import json as _json
        cfg = _json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json")
                          .read_text(encoding="utf-8"))
        dests = set(cfg["bundle"]["resources"].values())
        missing = [rel for rel in connector.RUNTIME_FILES
                   if f"scripts/{rel}" not in dests]
        self.assertEqual(missing, [],
                         f"★★★ 这些运行时文件没进安装包，.dmg 用户点接入会失败：{missing}")

    def test_every_runtime_file_exists_in_the_repo(self):
        gone = [rel for rel in connector.RUNTIME_FILES if not (ROOT / rel).exists()]
        self.assertEqual(gone, [], f"★ 清单里的文件仓库里没有：{gone}")

    def test_the_bundled_paths_match_what_connector_looks_for(self):
        """★ 目的地必须是 `scripts/<rel>` —— `script_dir()` 就是 `Resources/scripts`，
        而 connector 按 `src / rel` 找。路径一错就是悬空。"""
        import json as _json
        cfg = _json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json")
                          .read_text(encoding="utf-8"))
        for srcp, dest in cfg["bundle"]["resources"].items():
            rel = srcp.replace("../../", "")
            if rel in connector.RUNTIME_FILES:
                self.assertEqual(dest, f"scripts/{rel}", f"{rel} 的打包目的地不对")


class TheBlockedStateIsNotApplyable(unittest.TestCase):
    """★★ 「装不了」的红条和一个能点的「接入」按钮同时出现时，用户只会信后者。

    像素验证抓到（2026-09-19）：`blocked` 下复选框仍是勾选态、按钮仍写「接入（N 项）」，
    而 `apply()` 只挡了 `chosen.length` 与 `busy`，**没挡 `blocked`** —— 按钮变灰只是样式，
    点下去照样会跑。这一类「看起来不能点、其实能点」在本仓算 bug。
    """

    def test_default_picks_are_empty_when_blocked(self):
        src = (ROOT / "codexbar" / "src" / "components" / "ConnectorPanel.tsx") \
            .read_text(encoding="utf-8")
        self.assertIn("function defaultPicks(steps: Step[], blocked: boolean)", src,
                      "defaultPicks 没有接受 blocked")
        self.assertIn("out[s.id] = !blocked &&", src,
                      "★ blocked 时仍会默认勾选")

    def test_apply_guards_on_blocked(self):
        src = (ROOT / "codexbar" / "src" / "components" / "ConnectorPanel.tsx") \
            .read_text(encoding="utf-8")
        # 只看代码，剥掉注释 —— 本仓记过：断言撞上解释这条规则的注释会假绿。
        code = "\n".join(l for l in src.splitlines()
                          if not l.strip().startswith("//") and not l.strip().startswith("*"))
        self.assertIn("plan?.blocked) return;", code,
                      "★★ apply() 没有挡住 blocked —— 按钮变灰只是样式")


class TheCliContractHolds(unittest.TestCase):
    def test_plan_json_parses_and_carries_the_ui_fields(self):
        env = dict(os.environ)
        with tempfile.TemporaryDirectory() as d:
            env["CODEX_HOME"] = str(Path(d) / "home")
            env["CODEXBAR_LOCAL_BIN"] = str(Path(d) / "bin")
            r = subprocess.run([sys.executable, str(ROOT / "connector.py"), "plan",
                                "--src", str(ROOT), "--store", str(ROOT), "--json"],
                               capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        d = json.loads(r.stdout)
        for k in ("steps", "runtime", "ready", "port"):
            self.assertIn(k, d)
        for s in d["steps"]:
            self.assertIn(s["state"], {"todo", "done", "external", "blocked"})
            self.assertTrue(s["title"] and s["why"])

    def test_apply_refuses_without_steps(self):
        r = subprocess.run([sys.executable, str(ROOT / "connector.py"), "apply",
                            "--src", str(ROOT), "--store", str(ROOT)],
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
