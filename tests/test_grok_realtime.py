"""grok 额度的实时链路 —— 对照 agy Phase 5（`tests/test_agy_realtime.py`）。

改之前：CodexBar 每 10 分钟、且只在有人看着总览/菜单栏时才 GET 一次账单。
grok CLI 用着的时候数字冻着，菜单栏标题里也没有 grok。

改成什么样：
  ① **单一抓取者**：`grok-quota-sampler` 在 grok 进程活着时 subprocess `grok-quota`，
     同一份响应写账本 + sidecar。
  ② **推送不轮询**：Rust 1s 循环看 sidecar mtime 变化就 `emit("grok-quota-updated")`，
     前端监听后只读 sidecar，不发 RPC。
  ③ **app 补拉采样器**：没有 grok wrapper，CodexBar 每 60s 在锁不存在时拉起。
  ④ **绝不刷 refresh_token / 不自己打开 auth.json**。

账单接口只回整数百分比，所以「实时」= 整数跳变后约 15s 内进 UI，不是更细的曲线。
"""
import ast
import importlib.machinery
import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLER = (ROOT / "grok-quota-sampler").read_text(encoding="utf-8")
LIB_RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
HOOK = (ROOT / "codexbar" / "src" / "hooks" / "useQuotaSidecar.ts").read_text(encoding="utf-8")
GROK_HOOK = (ROOT / "codexbar" / "src" / "hooks" / "useGrokQuota.ts").read_text(encoding="utf-8")
EVENT = "grok-quota-updated"


def json_loads_conf():
    import json
    p = ROOT / "codexbar" / "src-tauri" / "tauri.conf.json"
    return json.loads(p.read_text(encoding="utf-8"))


def load_sampler():
    """文件没有 `.py` 后缀，`spec_from_file_location` 给不出 loader。每次新名字，避免
    上一次 import 时的 `CODEX_ROTATE_STORE` 被缓存进模块级 `_STORE`。"""
    name = "grok_qs_%s" % os.urandom(4).hex()
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "grok-quota-sampler"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def rs_no_comments():
    return "\n".join(l for l in LIB_RS.splitlines() if not l.lstrip().startswith("//"))


class TheSamplerIsTheSingleFetcherAndWriter(unittest.TestCase):
    def test_the_sampler_writes_the_sidecar(self):
        self.assertIn("SIDECAR", SAMPLER)
        self.assertIn(".grok-quota.json", SAMPLER)

    def test_it_writes_atomically(self):
        body = SAMPLER[SAMPLER.index("def _write_sidecar("):]
        self.assertIn("os.replace(", body, "不是原子写")
        self.assertIn(".tmp", body)

    def test_it_carries_prev_so_last_good_survives_across_restarts(self):
        body = SAMPLER[SAMPLER.index("def fetch("):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn('"--prev"', body)

    def test_a_sidecar_write_failure_does_not_kill_the_ledger(self):
        body = SAMPLER[SAMPLER.index("def _write_sidecar("):]
        self.assertIn("except OSError", body)

    def test_it_reuses_grok_quota_instead_of_reimplementing_https(self):
        """抄一份账单客户端 = 过期短路 / 降级契约 / 路径迟早漂移。"""
        self.assertIn('FETCHER = ROOT / "grok-quota"', SAMPLER)
        self.assertNotIn("HTTPSConnection", SAMPLER)


class TheSamplerDoesNotTouchCredentials(unittest.TestCase):
    """★★ 比「注释里写了别刷 token」硬：AST 里不能出现 refresh_token / 打开 auth.json。"""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SAMPLER)
        cls.docstrings = {id(n.value) for n in ast.walk(cls.tree)
                          if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                          and isinstance(n.value.value, str)}

    def code_strings(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in self.docstrings:
                yield node.value

    def test_no_refresh_token_in_code(self):
        hits = [s for s in self.code_strings() if "refresh_token" in s]
        self.assertEqual(hits, [], hits)

    def test_does_not_open_auth_json(self):
        hits = [s for s in self.code_strings() if "auth.json" in s]
        self.assertEqual(hits, [], "采样器自己打开了 auth.json：{}".format(hits))

    def test_does_not_issue_http_itself(self):
        self.assertNotIn("HTTPSConnection", SAMPLER)
        verbs = {"POST", "PUT", "PATCH", "DELETE"}
        hits = [s for s in self.code_strings() if s in verbs]
        self.assertEqual(hits, [], hits)


class TheUiIsPushedNotPolled(unittest.TestCase):
    def test_rust_emits_when_the_sidecar_changes(self):
        rs = rs_no_comments()
        self.assertIn(f'emit("{EVENT}"', rs)
        self.assertIn("grok_seen", rs, "没有比较 mtime，会每秒都发")

    def test_it_does_not_fire_on_the_first_observation(self):
        rs = rs_no_comments()
        i = rs.index(f'emit("{EVENT}"')
        window = rs[max(0, i - 400):i]
        self.assertIn("grok_seen.is_some()", window, "首次观测就发了")

    def test_the_hook_accepts_a_push_channel(self):
        self.assertIn("updateEvent", HOOK)

    def test_the_push_handler_reads_the_sidecar_and_never_runs_the_fetcher(self):
        i = HOOK.index("if (!updateEvent) return;")
        body = HOOK[i:i + 800]
        self.assertIn("invoke<string | null>(readCmd)", body)
        self.assertNotIn("runCmd", body, "推送处理里调了 runCmd —— 白发一次 RPC")

    def test_the_push_is_not_gated_by_enabled(self):
        i = HOOK.index("if (!updateEvent) return;")
        body = HOOK[i:i + 800]
        self.assertNotIn("if (!enabled)", body)

    def test_grok_actually_subscribes(self):
        self.assertIn(f'updateEvent: "{EVENT}"', GROK_HOOK)


class TheAppBackfillsTheSampler(unittest.TestCase):
    def test_the_timer_spawns_the_sampler(self):
        rs = rs_no_comments()
        self.assertIn("grok-quota-sampler", rs)

    def test_it_only_spawns_when_the_lock_is_absent(self):
        rs = rs_no_comments()
        i = rs.index("grok-quota-sampler")
        window = rs[max(0, i - 800):i]
        self.assertIn("grok-quota-ledger", window)
        self.assertIn(".sampler.lock", window)
        self.assertIn("!std::path::Path::new(&lock).exists()", window)

    def test_it_uses_its_own_counter_not_the_reset_one(self):
        """复用 `since_tick` 会在 state.json 一变时被清零 ⇒ 每秒拉一次。"""
        rs = rs_no_comments()
        i = rs.index("grok-quota-sampler")
        window = rs[max(0, i - 1600):i]
        self.assertIn("sampler_tick % 60", window)
        self.assertNotIn("since_tick % 60", window)


class TheSamplerHonoursTheStore(unittest.TestCase):
    def test_source_parses(self):
        ast.parse(SAMPLER)

    def test_ledger_follows_codex_rotate_store(self):
        import importlib.util
        old = os.environ.get("CODEX_ROTATE_STORE")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CODEX_ROTATE_STORE"] = tmp
            try:
                m = load_sampler()
                self.assertEqual(Path(m.LEDGER_DIR).resolve(),
                                 (Path(tmp) / "traffic" / "grok-quota-ledger").resolve())
                self.assertEqual(Path(m.SIDECAR).resolve(),
                                 (Path(tmp) / ".grok-quota.json").resolve())
            finally:
                if old is None:
                    os.environ.pop("CODEX_ROTATE_STORE", None)
                else:
                    os.environ["CODEX_ROTATE_STORE"] = old

    def test_it_is_bundled(self):
        res = json_loads_conf()["bundle"]["resources"]
        names = {Path(v).name for v in res.values()} if isinstance(res, dict) \
            else {Path(k).name for k in res}
        self.assertIn("grok-quota-sampler", names,
                      "采样器没进 tauri.conf.json resources —— 装机版采不到")

    def test_poll_is_not_agy_fast(self):
        """agy 2s 是 loopback；把那个数抄过来 = 对非公开账单接口每 2s 打一次。"""
        m = re.search(r'GROK_SAMPLER_POLL",\s*"(\d+)"', SAMPLER)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 10)


class FlattenDirectionIsUsedNotRemaining(unittest.TestCase):
    """grok 接口给已用。flatten 若悄悄换成剩余，锚点账本和 UI 换向会各错一次。"""

    def test_flatten_keeps_used(self):
        m = load_sampler()
        snap = {
            "accounts": [{
                "available": True,
                "quota": {
                    "used_percent": 20.0,
                    "period_end": 100,
                    "window_minutes": 10080.0,
                    "products": [{"product": "GrokBuild", "used_percent": 2.0}],
                },
            }]
        }
        flat = m.flatten(snap)
        self.assertEqual(flat["used"], 20.0)
        self.assertEqual(flat["reset"], 100)
        self.assertEqual(flat["products"], (("GrokBuild", 2.0),))

    def test_unavailable_is_none_not_zero(self):
        m = load_sampler()
        self.assertIsNone(m.flatten({"accounts": [{"available": False, "quota": None}]}))
        self.assertIsNone(m.flatten(None))


class EarlyExitDoesNotLeaveALock(unittest.TestCase):
    """★★ 评审：先 take_lock 再 grok_alive 早退，会留下 Rust 认的 stale lock，
    补拉永久停摆。闸必须是行为，不是源码里「先 alive」几个字。"""

    def test_absent_grok_leaves_no_lock(self):
        import os
        m = load_sampler()
        old_alive = m.grok_alive
        with tempfile.TemporaryDirectory() as tmp:
            m.LEDGER_DIR = Path(tmp)
            m.grok_alive = lambda: False
            try:
                self.assertEqual(m.main(), 0)
                self.assertFalse((Path(tmp) / m.LOCK).exists(),
                                 "grok 没在跑时留下了 .sampler.lock —— App 补拉会被永久挡住")
            finally:
                m.grok_alive = old_alive


class ProcessMatchIsExact(unittest.TestCase):
    def test_does_not_use_pgrep_f(self):
        tree = ast.parse(SAMPLER)
        docs = {id(n.value) for n in ast.walk(tree)
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)}
        hits = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docs and "pgrep" in n.value]
        self.assertEqual(hits, [], hits)

    def test_matches_grok_comm_not_this_script(self):
        body = SAMPLER[SAMPLER.index("def grok_alive("):]
        self.assertIn('== "grok"', body)
        self.assertIn('endswith("/grok")', body)


class TheTrayTitleStaysCodexOnly(unittest.TestCase):
    """★★ **托盘标题不带 grok 的 `Gxx%`** —— 用户 2026-09-13 明确要求去掉。

    这条**取代了**原来的 `TrayShowsGrokWhenAvailable`（断言标题里必须有 `grok_tray_tag`）。
    旧闸守的是一个已被用户否掉的形态，留着它等于把那个形态锁死 ——
    本仓同一天已经因为「闸锁的是错误前提」改写过两条。

    ★ grok 周额度的其余部分**照旧**：`grok-quota-sampler` 在 grok 活着时每 ~15s
      只读打一次账单接口，菜单栏点开有紫色 grok 行。去掉的只是**标题上那一截**。
    """

    def test_no_grok_tag_in_the_tray_title(self):
        rs = rs_no_comments()
        for bad in ("grok_tray_tag", "with_grok"):
            with self.subTest(token=bad):
                self.assertNotIn(bad, rs, f"★★ 托盘标题又带上 grok 的 {bad} 了")

    def test_the_title_builder_itself_never_mentions_grok(self):
        """★ 判据打在 `format_tray_title` 这个**函数体**上，不是整份源码 ——
        整份源码里到处都有 grok（sidecar、命令、锁），那些都该在。"""
        rs = rs_no_comments()
        i = rs.index("fn format_tray_title()")
        # ⚠️ 收尾用**下一个函数**，不用那条 `// ---- …` 分隔注释 ——
        #    `rs_no_comments()` 正好把注释剥掉了，拿它当锚点会 `ValueError`（实测）。
        seg = rs[i:rs.index("fn toggle_menubar(", i)]
        self.assertNotIn("grok", seg.lower(), "★★ 标题构造里还在读 grok")

    def test_the_purple_grok_row_is_still_there(self):
        """★★ 反方向：去掉的只是标题上那一截。**菜单栏里那行紫色 grok 必须还在** ——
        不验这一条的话，把整条 grok 通路删掉也能让上面两条变绿。"""
        mb = (ROOT / "codexbar" / "src" / "MenuBar.tsx").read_text(encoding="utf-8")
        self.assertIn("<GrokRow", mb, "★★ 连 grok 行都没了 —— 删过头了")


if __name__ == "__main__":
    unittest.main()
