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
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
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


class ADeployBuiltAppOnACloneUsesTheRepoInPlace(Sandbox):
    """★★ 用户 2026-09-19 报：「我没得勾选啊，只能勾选准备运行时」。

    根因：`_runtime_dir` 原来比的是 `src == store`。而 `deploy.sh` 构建出来的 App 里
    `script_dir()` 是 **bundle 的 Resources**、`data_dir()` 是构建期烧进去的**仓库路径**
    —— **两者从来不相等**。于是一台 clone 装机的机器被判成「安装包装机」，
    Connector 建议把运行时复制到 `<仓库>/runtime`，而仓库本身就是运行时。
    其余五步本来就装好了（done/external、不可勾），于是界面上只剩这一步多余的复制可勾。

    ★ 正确判据不是「src 与 store 是不是同一个目录」，而是
      **「store 里已经有一份能用的运行时没有」**。
    """

    def test_a_repo_store_is_used_in_place_even_when_src_differs(self):
        # store 里放一份完整运行时（模拟仓库），src 是另一个目录（模拟 bundle）
        for rel in connector.RUNTIME_FILES:
            dst = self.store / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("x", encoding="utf-8")
        p = connector.plan(self.src, self.store)
        self.assertEqual(Path(p["runtime"]), self.store.resolve(),   # macOS /var→/private/var
                         "★★ store 本身就是运行时，却还要往 store/runtime 复制一份")
        self.assertTrue(p["inplace"], "inplace 应表示「不需要复制」")
        self.assertEqual(self.step("runtime", p)["state"], "done",
                         "★ 原地可用却报 todo —— 用户会看到一个多余的、唯一可勾的步骤")

    def test_a_bare_store_still_copies(self):
        """反向：store 里没有运行时（`.dmg` 装机）时必须仍然复制。"""
        p = connector.plan(self.src, self.store)
        self.assertEqual(Path(p["runtime"]), (self.store / "runtime").resolve())
        self.assertFalse(p["inplace"])
        self.assertEqual(self.step("runtime", p)["state"], "todo")


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
        # ★ 「在工作」的手工配置要带 WS 关闭 —— 不带的那种见 `AHandMadeProviderWithoutWsIsNotDone`。
        self.cfg.write_text(USER_CONFIG + '\n[model_providers.rotateproxy]\nbase_url = "x"\n'
                            'supports_websockets = false\n', encoding="utf-8")
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



#: v1.0.0~v1.6.1 `docs/INSTALL.md` 原样给的 provider 块 —— **没有** `supports_websockets`。
#: 照它手工接入的用户就是 2026-09-23 那批「发版后还是被横幅报 WS 没关」的人。
OLD_INSTALL_BLOCK = (
    "[model_providers.rotateproxy]\n"
    'name = "codex-rotate proxy"\n'
    'base_url = "http://127.0.0.1:8011"\n'
    'wire_api = "responses"\n'
    "\n"
    "[model_providers.rotateproxy.auth]\n"
    'command = "/path/to/codex-account-rotator/proxy/auth-token"\n'
)


class AHandMadeProviderWithoutWsIsNotDone(Sandbox):
    """★★ `external`（你自己写的）≠「它在正确地工作」。

    2026-09-23：Connector 只看有没有 `[model_providers.rotateproxy]` 标题，照旧文档配的
    用户被报「已接入」，而横幅同时在喊 WS 没关 —— 两处说法打架，一键接入无事可做。
    """

    def setUp(self):
        super().setUp()
        self.text = USER_CONFIG + "\n" + OLD_INSTALL_BLOCK
        self.cfg.write_text(self.text, encoding="utf-8")

    def test_the_old_install_block_gets_a_ws_step_that_is_todo(self):
        self.assertEqual(self.step("provider")["state"], "external")
        self.assertEqual(self.step("ws")["state"], "todo")

    def test_it_is_not_ready_until_fixed(self):
        (self.home / "rotateproxy.config.toml").write_text(
            'model_provider = "rotateproxy"\n', encoding="utf-8")
        for n in connector.ENTRIES:
            (self.bin / n).write_text("#!/bin/sh\n", encoding="utf-8")
        connector._svc_loaded = lambda name: True
        self.apply("runtime")
        self.assertFalse(self.plan()["ready"])
        self.apply("ws")
        self.assertTrue(self.plan()["ready"])

    def test_the_fix_adds_exactly_one_line_inside_the_table(self):
        """★★★ 只加一行，且加在**主表**里（不是 `.auth` 子表、不是文件末尾）；其余字节不变。"""
        self.apply("ws")
        after = self.cfg.read_text(encoding="utf-8")
        a, b = self.text.splitlines(keepends=True), after.splitlines(keepends=True)
        self.assertEqual(len(b), len(a) + 1)
        i = b.index("supports_websockets = false\n")
        self.assertEqual(b[i - 1].strip(), "[model_providers.rotateproxy]")
        self.assertEqual(b[:i] + b[i + 1:], a, "★★★ 那一行之外有字节被改了")

    def test_an_explicit_true_is_flipped_not_duplicated(self):
        self.cfg.write_text(self.text.replace('wire_api = "responses"\n',
                                              'wire_api = "responses"\nsupports_websockets = true\n'),
                            encoding="utf-8")
        self.apply("ws")
        after = self.cfg.read_text(encoding="utf-8")
        self.assertEqual(after.count("supports_websockets"), 1)
        self.assertIn("supports_websockets = false", after)

    def test_it_is_idempotent(self):
        self.apply("ws")
        once = self.cfg.read_text(encoding="utf-8")
        self.apply("ws")
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), once)
        self.assertEqual(self.step("ws")["state"], "done")

    def test_the_profiles_own_table_is_fixed_too(self):
        """profile overlay 里也可能有一张同名表（本机就有）—— 它覆盖 base，漏了它等于没修。"""
        prof = self.home / "rotateproxy.config.toml"
        prof.write_text('model_provider = "rotateproxy"\n\n' + OLD_INSTALL_BLOCK, encoding="utf-8")
        self.apply("ws")
        self.assertIn("supports_websockets = false", prof.read_text(encoding="utf-8"))
        self.assertEqual(connector.ws_gaps(), [])

    def test_our_managed_block_never_grows_a_ws_step(self):
        """托管块本来就带这一行 —— 不该多出一步让人以为还缺什么。"""
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider", "profile")
        self.assertEqual([s for s in self.plan()["steps"] if s["id"] == "ws"], [])

    def test_the_connector_and_the_gate_agree(self):
        """★★★ 不变量：Connector 说「好了」⇔ 接入闸的 WS 项说 ok。两处各判一次、必须同一个答案。"""
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("cr_ws_agree", str(ROOT / "codex-rotate"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        mod.CODEX_HOME = self.home
        (self.home / "rotateproxy.config.toml").write_text(
            'model_provider = "rotateproxy"\n', encoding="utf-8")

        def gate_ws():
            return [c for c in mod.codex_integration_gate()["checks"] if c["id"] == "ws"][0]["state"]

        self.assertEqual((self.step("ws")["state"], gate_ws()), ("todo", "bad"))
        self.apply("ws")
        self.assertEqual((self.step("ws")["state"], gate_ws()), ("done", "ok"))


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

    def test_remove_keeps_a_foreign_symlink_that_merely_points_inside_our_store(self):
        """★★ 2026-09-26：`remove()` 用 `str(store) in tgt`（子串）判「是不是我们建的」，
        而 `plan()` 用精确比较 —— 同一条规则两处实现，边界输入上不一致。
        用户自己建的入口只要**指向仓库/运行时里的任何路径**（哪怕是另一个文件）就被当成我们的删掉。
        判据必须与 `apply()` 建的目标**逐字节相同**。"""
        self.apply("runtime", "entries")
        runtime = connector._runtime_dir(self.src, self.store)
        # 用户自建：指向 store 内、但不是我们会建的那个目标
        (self.bin / "cxp").unlink()
        (self.bin / "cxp").symlink_to(self.store / "my-notes" / "cxp")
        (self.bin / "cxd").unlink()
        (self.bin / "cxd").symlink_to(str(runtime / "proxy" / "cxd") + ".bak")
        out = connector.remove(self.store)
        self.assertTrue((self.bin / "cxp").is_symlink(), "★★ 删掉了用户自建、只是指向 store 内的 cxp")
        self.assertTrue((self.bin / "cxd").is_symlink(), "★★ 删掉了用户自建、目标名带前缀相同的 cxd")
        self.assertTrue(any("cxp" in k for k in out["kept"]) and any("cxd" in k for k in out["kept"]), out)
        # 反向对照：我们自己建的仍然要撤掉，否则「什么都不删」也能过
        self.assertFalse((self.bin / "agy-rotate").exists() or (self.bin / "agy-rotate").is_symlink(),
                         "★ 我们自己建的入口没被撤销")

    def test_remove_still_undoes_our_own_entries_in_a_clone_install(self):
        """★ 反向对照（收紧成精确比较后最容易漏的方向）：clone 装机时 store 自己就是运行时，
        链接指向 `<store>/proxy/cxp` 而不是 `<store>/runtime/proxy/cxp`。判据用错就会**一个都撤不掉**。"""
        for rel in connector.RUNTIME_FILES:
            if (self.src / rel).exists():
                (self.store / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.src / rel, self.store / rel)
        self.assertTrue(connector._has_runtime(self.store), "夹具没有搭成 clone 装机")
        self.apply("runtime", "entries")
        self.assertTrue((self.bin / "cxp").is_symlink())
        self.assertEqual(os.readlink(self.bin / "cxp"), str(self.store.resolve() / "proxy" / "cxp"))
        connector.remove(self.store)
        for n in connector.ENTRIES:
            self.assertFalse((self.bin / n).is_symlink(), f"★★ clone 装机下 {n} 没被撤销")

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
        self.cfg.write_text('[model_providers.rotateproxy]\nsupports_websockets = false\n',
                            encoding="utf-8")
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
