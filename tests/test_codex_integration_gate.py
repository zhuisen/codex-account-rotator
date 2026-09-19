"""装机链路总闸（`codex-rotate` 的 `codex_integration_gate`）。

## 这道闸在守什么

用户 2026-09-19 报「下载了 CodexBar，敲 `codex` 没走 rotateproxy」。查下来四处缺口，
**每一处单独就足以让轮换失效，而它们全都静默**：`.dmg` 里不含 `proxy/`；`INSTALL.md`
不装 `codex` wrapper；profile 缺失时 codex **不报错**只是退回单号直连；App 又把
`health` 的 stdout 丢了。用户看到的是「一个看起来正常的空池」。

本仓铁律：同一类 bug 第二次出现，交付物必须是**一个会变红的检查**。

## 最重要的一条：`not_installed` ≠ `broken` ≠ `unknown`

三者的下一步动作完全不同（去装 / 去修 / 去查权限），合并任意两个都会把人导向错误的方向。
★ 闸的第一版**自己犯了这个错**：`_read_text_or_none` 对「文件不存在」和「读不到」都返回
`None`，而 provider 那条忘了用 `.exists()` 分开 ⇒ 一台干净的 .dmg 机器被判成 `broken`
（红：「你装了但坏了」）。实测于 2026-09-19，`ACleanMachineReadsAsNotInstalled` 守着它。
"""
import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    """`codex-rotate` 无 .py 后缀，按路径加载。顶层只有常量，无 I/O、无网络。"""
    loader = importlib.machinery.SourceFileLoader("cr_integ", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _closed_port():
    """拿一个**确定没人听**的端口：绑上再关掉，内核短时间内不会复用。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class GateCase(unittest.TestCase):
    """每个用例一套完全隔离的 CODEX_HOME / STORE。**绝不碰真的 `~/.codex` 或 state.json。**"""

    def setUp(self):
        self.mod = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.store = Path(self.tmp.name) / "store"
        self.home.mkdir(parents=True)
        self.store.mkdir(parents=True)
        # ★ 这三个是模块级常量，import 时就定死了 —— 必须改模块属性，改环境变量没用。
        self.mod.CODEX_HOME = self.home
        self.mod.STORE = self.store
        self.mod.STATE = self.store / "state.json"
        self._old_port = os.environ.get("CRP_PORT")
        os.environ["CRP_PORT"] = str(_closed_port())
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._restore_port)

    def _restore_port(self):
        if self._old_port is None:
            os.environ.pop("CRP_PORT", None)
        else:
            os.environ["CRP_PORT"] = self._old_port

    # ---- 造场景的小工具 ----
    def wire_provider(self, base=None, ws=True):
        # ★ 记住参数：`listen()` 会换端口，届时要用**同样的意图**重写这个文件，
        #   否则 base_url 还指着旧端口 —— 第一版就是这么让四个用例假红的。
        self._prov = (base, ws)
        port = os.environ["CRP_PORT"]
        body = "[model_providers.rotateproxy]\n"
        body += 'base_url = "http://%s"\n' % (base or ("127.0.0.1:" + port))
        if ws:
            body += "supports_websockets = false\n"
        (self.home / "config.toml").write_text(body, encoding="utf-8")

    def wire_profile(self):
        (self.home / "rotateproxy.config.toml").write_text(
            'model_provider = "rotateproxy"\n', encoding="utf-8")

    def wire_entry(self):
        (self.store / "proxy").mkdir(parents=True, exist_ok=True)
        (self.store / "proxy" / "cxp").write_text("#!/bin/sh\n", encoding="utf-8")

    def wire_accounts(self, n=2):
        slots = {("a%d" % i): {"label": "p%d" % i, "file": "x"} for i in range(n)}
        self.mod.STATE.write_text(json.dumps({"slots": slots, "active": None}),
                                  encoding="utf-8")

    def listen(self):
        """真开一个监听，让 `listening` 那条能变绿。用完关掉。

        ★ 换端口后必须**重写** provider 配置：base_url 里钉着端口号，不重写就还指着
          那个没人听的旧端口，于是 `provider` 变 `bad`、整个用例假红。调用顺序不该
          成为陷阱，所以由这里兜住，而不是要求每个用例记得先 `listen()`。
        """
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        # ★ backlog 要够大：闸每调一次就 connect 一次而**从不 accept**，`listen(1)` 在
        #   第二次调用就把队列占满 ⇒ connect 超时 ⇒ `listening` 假红。一个用例里
        #   「先测基线再测变异」正好要调两次，第一版就栽在这里（仪器撒谎，不是闸错）。
        srv.listen(128)
        os.environ["CRP_PORT"] = str(srv.getsockname()[1])
        self.addCleanup(srv.close)
        if getattr(self, "_prov", None) is not None:
            base, ws = self._prov
            if base is None:                    # 显式写死别处的，保持它的意图
                self.wire_provider(ws=ws)

    def state_of(self, g=None):
        return (g or self.mod.codex_integration_gate())["state"]

    def check(self, cid, g=None):
        g = g or self.mod.codex_integration_gate()
        return [c for c in g["checks"] if c["id"] == cid][0]


class ACleanMachineReadsAsNotInstalled(GateCase):
    """★★ 只下载 .dmg 的用户 = `not_installed`（中性），**不是** `broken`（红）。

    这正是闸的第一版犯的错：provider 那条把「config.toml 不存在」报成了 `unknown`，
    于是 `never` 判据（三者皆 `bad`）不成立，干净机器被喊成「接线断了，去修」。
    ⚠️ 两者的下一步完全相反 —— 一个该去**装**，一个该去**修**。
    """

    def test_a_clean_machine_is_not_installed(self):
        self.assertEqual(self.state_of(), "not_installed")

    def test_the_missing_config_is_bad_not_unknown(self):
        """把它报成 `unknown` 就会让上面那条判据失效 —— 这是那个 bug 的**根因**位置。"""
        self.assertEqual(self.check("provider")["state"], "bad")

    def test_it_says_dmg_lacks_the_proxy_half(self):
        """文案必须说**做什么**，不能只说坏了（本仓披露规范）。"""
        txt = "\n".join(self.mod.codex_integration_gate()["lines"])
        self.assertIn("只装了用量看板那一半", txt)
        # ★ 必须指向**公开的**装机指南。原来指 `SETUP.md`（仓库根的开发者文档），
        #   而下载 .dmg 的人手里根本没有仓库 —— 2026-09-19 改指 docs/INSTALL.md。
        self.assertIn("docs/INSTALL.md", txt)
        # 并且要说清楚装完之后敲什么：`codex` 走轮换、`cxd` 直连（用户 2026-09-19 定稿）。
        self.assertIn("cxd", txt)

    def test_not_installed_is_not_reported_as_ok(self):
        self.assertNotEqual(self.mod.codex_integration_gate()["level"], "ok")


class AHalfWiredMachineReadsAsBroken(GateCase):
    """装了一部分但断了 = `broken`（红）。与 `not_installed` 必须分色。"""

    def test_provider_without_profile_is_broken(self):
        self.wire_provider()
        self.assertEqual(self.state_of(), "broken")

    def test_the_broken_lines_name_each_failing_check(self):
        self.wire_provider()
        txt = "\n".join(self.mod.codex_integration_gate()["lines"])
        self.assertIn("profile overlay", txt)
        self.assertIn("入口 cxp", txt)

    def test_a_wrong_base_url_is_caught(self):
        """块在、但指向别处 —— codex 照样不报错，直接连上游。"""
        self.wire_profile()
        self.wire_entry()
        self.wire_provider(base="api.openai.com")
        self.assertEqual(self.check("provider")["state"], "bad")
        self.assertEqual(self.state_of(), "broken")


class AnUnknownNeverPassesForOk(GateCase):
    """★★ 本仓最贵的一条铁律：「读不到 ≠ 没有」，且 `unknown` 绝不折叠成 `ok`。"""

    def test_one_unreadable_file_blocks_ready(self):
        self.wire_profile()
        self.wire_entry()
        self.wire_provider()
        self.wire_accounts()
        self.listen()
        self.assertEqual(self.state_of(), "ready")      # 先确认基线是绿的
        cfg = self.home / "config.toml"
        cfg.chmod(0o000)
        self.addCleanup(lambda: cfg.chmod(0o644))
        if os.access(cfg, os.R_OK):                     # root 跑测试时读得到，跳过
            self.skipTest("以 root 运行，chmod 000 仍可读")
        g = self.mod.codex_integration_gate()
        self.assertEqual(g["state"], "unknown")
        self.assertEqual(g["level"], "unknown")
        self.assertNotEqual(g["level"], "ok")

    def test_an_unreadable_file_is_unknown_not_bad(self):
        """「存在但读不到」与「不存在」也要分开 —— 前者去查权限，后者去写配置。"""
        self.wire_profile()
        cfg = self.home / "config.toml"
        cfg.write_text("x=1\n", encoding="utf-8")
        cfg.chmod(0o000)
        self.addCleanup(lambda: cfg.chmod(0o644))
        if os.access(cfg, os.R_OK):
            self.skipTest("以 root 运行，chmod 000 仍可读")
        self.assertEqual(self.check("provider")["state"], "unknown")


class AnEmptyPoolIsAmberNotRed(GateCase):
    """接线齐全但没号 = `no_accounts`（琥珀）。

    ⚠️ 与 `broken` 混在一起，会让一个只差 `login` 的人去重装 launchd 服务。
    """

    def _fully_wired(self):
        self.wire_profile()
        self.wire_entry()
        self.wire_provider()
        self.listen()

    def test_wired_but_empty_is_no_accounts(self):
        self._fully_wired()
        self.assertEqual(self.state_of(), "no_accounts")

    def test_adding_accounts_turns_it_ready(self):
        self._fully_wired()
        self.wire_accounts()
        self.assertEqual(self.state_of(), "ready")

    def test_it_warns_against_codex_login(self):
        """★ `codex login` 会 server-side 吊销当值号（本仓死过 3 个号）。文案必须挡住。"""
        self._fully_wired()
        txt = "\n".join(self.mod.codex_integration_gate()["lines"])
        self.assertIn("codex-rotate login", txt)
        self.assertIn("不要", txt)


class TheWebsocketBypassIsCaught(GateCase):
    """WS 直连开着 = 完全绕过代理、只烧 auth.json 那一个号，而代理日志里什么都没有。"""

    def test_missing_supports_websockets_is_bad(self):
        self.wire_profile()
        self.wire_entry()
        self.wire_provider(ws=False)
        self.listen()
        self.assertEqual(self.check("ws")["state"], "bad")
        self.assertEqual(self.state_of(), "broken")

    def test_spacing_variants_still_count_as_off(self):
        """`supports_websockets=false` 与 `... = false` 是同一件事，别因空格误报。"""
        self.wire_profile()
        self.wire_entry()
        (self.home / "config.toml").write_text(
            '[model_providers.rotateproxy]\nbase_url = "http://127.0.0.1:%s"\n'
            'supports_websockets=false\n' % os.environ["CRP_PORT"], encoding="utf-8")
        self.assertEqual(self.check("ws")["state"], "ok")


class TheCliContractHolds(unittest.TestCase):
    """App 要消费 `--json`。★ 与 `health` 共用同一个真源，否则 UI 和 CLI 迟早两种答案。"""

    def test_integration_json_parses_and_has_the_ui_fields(self):
        out = subprocess.run([sys.executable, str(ROOT / "codex-rotate"),
                              "integration", "--json"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        d = json.loads(out.stdout)
        for k in ("level", "state", "checks", "lines", "port"):
            self.assertIn(k, d)
        self.assertIn(d["state"],
                      {"ready", "no_accounts", "broken", "not_installed", "unknown"})
        self.assertIn(d["level"], {"ok", "warn", "unknown"})

    def test_every_check_carries_a_state_and_a_label(self):
        out = subprocess.run([sys.executable, str(ROOT / "codex-rotate"),
                              "integration", "--json"],
                             capture_output=True, text=True, timeout=30)
        checks = json.loads(out.stdout)["checks"]
        self.assertTrue(checks, "★ 零个检查项却报了结论 —— 空扫描器假阳性")
        for c in checks:
            self.assertIn(c["state"], {"ok", "bad", "unknown"})
            self.assertTrue(c["label"])
            if c["state"] == "bad":
                self.assertTrue(c["fix"], "坏了必须给修法，不能只说坏了")

    def test_the_gate_is_wired_into_health(self):
        """闸写了没接 = 白写。这条守的是接线本身。"""
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        head = src.split("def cmd_health", 1)[1][:1600]
        self.assertIn("codex_integration_gate()", head,
                      "cmd_health 没调接入闸")
        cmds = src.split("CMDS = {", 1)[1].split("}", 1)[0]
        self.assertIn('"integration": cmd_integration', cmds,
                      "CMDS 没注册 integration 子命令")


if __name__ == "__main__":
    unittest.main(verbosity=2)
