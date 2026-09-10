"""agy 额度的**实时**链路（2026-09-09，Phase 5）。

## 改之前是什么样

两个独立的轮询者打同一个 RPC：
  · 采样器每 60s（写 `samples.jsonl`）
  · app 的 `run_agy_quota` 另有一套 60s 合并 + 2min 保鲜 + 30s tick（写 `.agy-quota.json`）
而 **app 那条只在有人看着那一页时才前进** —— 用户切走再回来，最坏等 2.5 分钟。
两个 webview 也各看各的。

## 改成什么样（"逻辑同 codex"）

codex 那条链路是 **proxy 逐请求写 → quotad 定时/跨重置触发 → UI 靠 `state-changed` 推送**。
映射到 agy：
  ① **单一抓取者、单一写者**：采样器是唯一调 RPC 的人，同一份响应**同时**写账本和 sidecar；
  ② **推送不轮询**：Rust 的 1s 循环看 sidecar mtime 变化就 `emit("agy-quota-updated")`，
     前端监听后**只读 sidecar，不发 RPC**；
  ③ **跨重置立刻取**：窗口重置是这四个数唯一会跳变的时刻；
  ④ **app 补拉采样器**：采样器原本只由 `bin/agy` wrapper 拉起，从 IDE / VS Code 起的 agy
     没有 wrapper ⇒ 没有采样器 ⇒ 额度永远停在上一次读数，而 UI 看不出这一点。

## ★★ 一条被实测推翻的说法

用户提出「agy 原生把 token 写进 SQLite 的 `gen_metadata` protobuf，scan.py 已在解析」。
**实测推翻**：
  · `scan.py` 根本不读 agy 的 SQLite（源定义是 `glob: usage.jsonl`，全文无 `sqlite3`）；
  · 扫遍 **261 个** `conversations/*.db` 的所有表，结构化的 `promptTokenCount` 只有 **3 个**，
    全部来自**同一个文件**，而那是一段**会话正文里的 markdown 代码块**
    （更早的会话里我自己粘的 `usageMetadata` 示例）。
所以采样器 docstring 里那句「agy 不在任何地方落 token 计数」**是对的**，
Phase 5 只能做「额度%」的实时化，做不成「token 的实时化」。
"""
import ast
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLER = (ROOT / "traffic" / "agy_quota_sampler.py").read_text(encoding="utf-8")
LIB_RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
HOOK = (ROOT / "codexbar" / "src" / "hooks" / "useQuotaSidecar.ts").read_text(encoding="utf-8")
AGY_HOOK = (ROOT / "codexbar" / "src" / "hooks" / "useAgyQuota.ts").read_text(encoding="utf-8")
EVENT = "agy-quota-updated"


def rs_no_comments():
    return "\n".join(l for l in LIB_RS.splitlines() if not l.lstrip().startswith("//"))


class TheSamplerIsTheSingleFetcherAndWriter(unittest.TestCase):
    """★★ 两个轮询者打同一个 RPC 是纯浪费，而且它们互相看不见对方的新鲜度。"""

    def test_the_sampler_writes_the_sidecar(self):
        self.assertIn("SIDECAR", SAMPLER)
        self.assertIn(".agy-quota.json", SAMPLER)

    def test_it_writes_atomically(self):
        """★ 直接覆写会让正在读的 webview 拿到半截 JSON —— 而解析失败在 UI 上
        表现为"额度读不到"，与真的读不到同形。
        （写盘搬进了 `_write_sidecar`，判据跟着搬 —— 断言留在旧函数上会恒绿。）"""
        body = SAMPLER[SAMPLER.index("def _write_sidecar("):]
        self.assertIn("os.replace(", body, "不是原子写")
        self.assertIn(".tmp", body)

    def test_it_carries_prev_so_last_good_survives_across_restarts(self):
        """★ 不传 `--prev` 每次都是冷启动，降级时那份"陈旧但真实"的读数会丢 ——
        而「读不到」与「没有」必须可区分。"""
        body = SAMPLER[SAMPLER.index("def fetch("):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn('"--prev"', body)

    def test_a_sidecar_write_failure_does_not_kill_the_ledger(self):
        """★ sidecar 是**附带**职责。写不了它不该让采样器丢掉主职责（账本）。"""
        body = SAMPLER[SAMPLER.index("def _write_sidecar("):]
        self.assertIn("except OSError", body)


class TheUiIsPushedNotPolled(unittest.TestCase):
    def test_rust_emits_when_the_sidecar_changes(self):
        rs = rs_no_comments()
        self.assertIn(f'emit("{EVENT}"', rs)
        self.assertIn("agy_seen", rs, "没有比较 mtime，会每秒都发")

    def test_it_does_not_fire_on_the_first_observation(self):
        """★ 冷启动时前端本来就会自己读一次，再发一条是重复 —— 而重复推送会让
        "刚启动"和"刚更新"在日志里长得一样。"""
        rs = rs_no_comments()
        i = rs.index(f'emit("{EVENT}"')
        window = rs[max(0, i - 400):i]
        self.assertIn("agy_seen.is_some()", window, "首次观测就发了")

    def test_the_hook_accepts_a_push_channel(self):
        self.assertIn("updateEvent", HOOK)
        self.assertIn('from "@tauri-apps/api/event"', HOOK)

    def test_the_push_handler_reads_the_sidecar_and_never_runs_the_fetcher(self):
        """★★ 数据已经被采样器取好了。推送里再发一次 RPC，等于把"省下一次外部调用"
        这件事本身抵消掉 —— 而那正是整个 Phase 5 的目的。"""
        i = HOOK.index("if (!updateEvent) return;")
        body = HOOK[i:i + 800]
        self.assertIn("invoke<string | null>(readCmd)", body)
        self.assertNotIn("runCmd", body, "推送处理里调了 runCmd —— 白发一次 RPC")

    def test_the_push_is_not_gated_by_enabled(self):
        """★★ 受 `enabled` 约束就退回"只在有人看这一页时才前进"—— 那正是要修的东西。
        收下一条别人已经取好的数据没有成本。"""
        i = HOOK.index("if (!updateEvent) return;")
        body = HOOK[i:i + 800]
        self.assertNotIn("if (!enabled)", body)

    def test_agy_actually_subscribes(self):
        """★ hook 支持了不等于有人用。判据是 `useAgyQuota` 真的传了事件名。"""
        self.assertIn(f'updateEvent: "{EVENT}"', AGY_HOOK)


class TheResetPointIsNotMissed(unittest.TestCase):
    """★ 窗口重置是这四个数**唯一会跳变**的时刻。按 60s 节拍撞上去，用户最坏看到
    一个落后一分钟的"还剩 3%"，而真实值已经回到 100%。"""

    def test_the_loop_reacts_to_crossing_the_nearest_reset(self):
        body = SAMPLER[SAMPLER.index("def main("):]
        body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        self.assertIn("crossed", body)
        self.assertIn("last_write < nxt", body, "没有比较上次写入与重置点，条件不会自清零")

    def test_the_source_parses(self):
        ast.parse(SAMPLER)


class TheAppBackfillsTheSampler(unittest.TestCase):
    """★★ 采样器原本**只由 `bin/agy` wrapper 拉起**。从 IDE / VS Code / 绝对路径起的 agy
    没有 wrapper ⇒ 没有采样器 ⇒ 额度永远停在上一次读数，
    而 UI 只知道"数据旧了"，看不出"根本没人在采"。
    与 dawn-probe 的「launchd + app 内补跑」是同一条双路径设计。"""

    def test_the_timer_spawns_the_sampler(self):
        rs = rs_no_comments()
        self.assertIn("agy_quota_sampler.py", rs)

    def test_it_only_spawns_when_the_lock_is_absent(self):
        """★ 采样器自己有单实例锁；不看锁就拉，每分钟白起一个 python 再立刻退出。"""
        rs = rs_no_comments()
        i = rs.index("agy_quota_sampler.py")
        window = rs[max(0, i - 600):i]
        self.assertIn(".sampler.lock", window)
        self.assertIn("!std::path::Path::new(&lock).exists()", window)

    def test_it_uses_its_own_counter_not_the_reset_one(self):
        """★★ `since_tick` 会被 `changed` 分支清零。拿它做 `% 60`：state.json 一变就清零
        ⇒ 判据几乎恒为 0 ⇒ **每秒**拉一次采样器。
        这类"复用一个会被别人重置的计数器"的错**不会报错**，只会让频率悄悄错一个数量级。
        我第一版就是这么写的。"""
        rs = rs_no_comments()
        i = rs.index("agy_quota_sampler.py")
        window = rs[max(0, i - 800):i]
        self.assertIn("sampler_tick % 60", window)
        self.assertNotIn("since_tick % 60", window, "用了会被清零的那个计数器")


class AgyDoesPersistTokensAndScanIsWiredToIt(unittest.TestCase):
    """★★★ **这条结论我写反过一次，留档：不要再用文本搜索去判二进制。**

    我原来写的是「agy 不在任何地方落 token 计数」，依据是"扫遍 261 个 db，
    结构化 `promptTokenCount` 只有 3 个"。**那是假阴性** ——
    `gen_metadata.data` 是 **protobuf wire format**，里面**根本没有字段名**，
    `grep promptTokenCount` 永远 0 命中。同族的坑本仓记过两次（grep 假阳性），
    这次是**反方向**：用一个看不见目标的探针得出"目标不存在"。

    Fable 复核盲解了 wire format，我**独立复现**并逐条比对了 69 个 conv：

        gen_metadata.data → f1.f4.{f2,f3,f5,f9}
          f5 = cache_read_tokens   69/69 逐字相等
          f9 = thinking_tokens     69/69 逐字相等
          f2 = input_tokens        63/69
          f3 = output_tokens       63/69
        f1.f19 = 模型名（`gemini-3.8-flash`，861/862 行有）

    **含义**：`CLAUDE.md` 里「agy 交互式会话的 token 永久拿不到」被推翻。
    另有 **192 个不在账本里的 db、约 2.59 亿 token**（即 `coverage` 报的 84% 缺口），
    而且是**可追溯的**（db 从 2026-07-13 起）。接一个 `_scan_agy_sqlite` 源就能把
    agy 覆盖率从 15.9% 做到 ~100%，且**不依赖 wrapper**。

    ⚠️ 尚未接入（Phase 5 只做了额度%的实时化）。**未定的量**：`f1`/`f6`/`f10` 语义、
    6 个 conv 的 ≤104 残差、行是 turn 进行中落还是结束落、58 天以上会不会被清理、
    `f19` 没有 `(High)` 档位后缀（接 `rates.ts` 前要定 tier 映射）。

    所以这条测试守的是**「还没接」这个事实**，不是「本地没有」那个错结论 ——
    后者会把一个 2.59 亿 token 的数据源锁在门外。
    """

    SCAN = (ROOT / "traffic" / "scan.py").read_text(encoding="utf-8")

    def test_scan_is_wired_to_the_sqlite_source(self):
        """★ 这条原来写的是"**还没**接入"，故意设计成接入那天变红 —— 它尽职了
        （2026-09-09 接入时红了一次）。现在反过来钉住"**必须保持接入**"：
        悄悄退回只读 wrapper 账本，覆盖率会从 ~91% 掉回 ~16%，
        而症状只是**数字变小**，没有任何东西会报错。"""
        m = re.search(r'\{"key": "agy".*?\}', self.SCAN, re.S)
        self.assertIsNotNone(m)
        src = m.group(0)
        self.assertIn("_scan_agy_db", src, "★ agy 主源被退回账本了 —— 覆盖率会掉回 ~16%")
        self.assertIn("AGY_DB_ROOT", src)
        self.assertIn("_agy_db_sig", src, "★ 少了 WAL 签名钩子 —— 数字会静默停在旧值")

    def test_the_field_map_is_recorded_where_it_will_be_found(self):
        """★ 盲解出来的字段号是这条路的**全部资产**。写在只有测试才读的地方不够 ——
        采样器 docstring 里那句错的结论必须当场纠正，否则下一个人照着它再查一遍。"""
        self.assertIn("gen_metadata", SAMPLER,
                      "采样器 docstring 里那句「不在任何地方落 token 计数」还没纠正")

    def test_the_decode_still_matches_the_ledger(self):
        """★★ **真数据回归**。字段号是盲解推断的 —— 它随时可能因为 agy 换版本而失效，
        而失效的表现是"数字对不上"，不是"报错"。这条把它变成会红的。
        （只比 `cache_read`/`thinking` 两个 69/69 的；另两个有 6 个 conv 的小残差未解释。）"""
        import glob
        import sqlite3
        led_path = ROOT / "traffic" / "agy-ledger" / "usage.jsonl"
        if not led_path.exists():
            self.skipTest("本机没有 agy 账本")
        led = {}
        for line in led_path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("conv"):
                led[d["conv"]] = d
        if not led:
            self.skipTest("账本为空")
        matched = checked = 0
        for path in glob.glob(str(Path.home() / ".gemini/antigravity-cli/conversations/*.db")):
            conv = Path(path).stem
            if conv not in led:
                continue
            agg = {5: 0, 9: 0}
            try:
                c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
                for (blob,) in c.execute("SELECT data FROM gen_metadata ORDER BY idx"):
                    if not blob:
                        continue
                    for f1 in _pb(blob).get(1, []):
                        if not isinstance(f1, (bytes, bytearray)):
                            continue
                        for f4 in _pb(f1).get(4, []):
                            if not isinstance(f4, (bytes, bytearray)):
                                continue
                            u = _pb(f4)
                            for k in agg:
                                if k in u and isinstance(u[k][0], int):
                                    agg[k] += u[k][0]
                c.close()
            except sqlite3.Error:
                continue
            checked += 1
            if (agg[5] == led[conv].get("cache_read_tokens", 0)
                    and agg[9] == led[conv].get("thinking_tokens", 0)):
                matched += 1
        if checked == 0:
            self.skipTest("没有能对上的 conv")
        self.assertEqual(matched, checked,
                         f"protobuf 字段号可能变了: {matched}/{checked} 对得上")


def _pb(b):
    """极简 protobuf 解码 → {field: [值]}。值是 int 或 bytes。"""
    out, i, n = {}, 0, len(b)
    while i < n:
        k = 0; s = 0
        while i < n:
            c = b[i]; i += 1; k |= (c & 0x7F) << s; s += 7
            if not c & 0x80:
                break
        f, wt = k >> 3, k & 7
        if wt == 0:
            v = 0; s = 0
            while i < n:
                c = b[i]; i += 1; v |= (c & 0x7F) << s; s += 7
                if not c & 0x80:
                    break
        elif wt == 2:
            ln = 0; s = 0
            while i < n:
                c = b[i]; i += 1; ln |= (c & 0x7F) << s; s += 7
                if not c & 0x80:
                    break
            v = b[i:i + ln]; i += ln
        elif wt == 5:
            v = b[i:i + 4]; i += 4
        elif wt == 1:
            v = b[i:i + 8]; i += 8
        else:
            break
        out.setdefault(f, []).append(v)
    return out


class TheSamplerDoesNotSpinWhenAgyIsAbsent(unittest.TestCase):
    """★★★ 我在 Phase 5 里亲手造过一个**永续空转**：

    agy 没在跑（含没装 agy 的下游用户）时 → app 每 60s 补拉采样器 →
    它进 90s 的 2 秒快轮询 → **每次失败的 fetch 照样写 sidecar** → mtime 变 →
    Rust 广播 → 两个 webview 各读一次 → 180s 空闲退出删锁 → ≤60s 后再被拉起。
    **每 ~4.5 分钟约 40 次 python 起停 + 40 次写 + 40 次广播，永远。**
    本仓量过「没人看时零开销」，这条会把它作废。

    两道都要在：起手探活直接退出；以及写 sidecar 前比内容（剔掉每次都变的
    `fetched_at`/`pid`，否则等于没比）。
    """

    def test_it_exits_immediately_and_writes_nothing(self):
        import importlib.util
        import tempfile
        tmp = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("AGY_QUOTA_LEDGER_DIR", "CODEX_ROTATE_STORE")}
        os.environ["AGY_QUOTA_LEDGER_DIR"] = tmp
        os.environ["CODEX_ROTATE_STORE"] = tmp
        try:
            spec = importlib.util.spec_from_file_location(
                "smp_probe", ROOT / "traffic" / "agy_quota_sampler.py")
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            m.SIDECAR = Path(tmp) / ".agy-quota.json"
            m.agy_alive = lambda: False
            t0 = time.time()
            rc = m.main()
            self.assertEqual(rc, 0)
            self.assertLess(time.time() - t0, 3, "没在跑还赖了几秒 —— 会被每分钟拉起一次")
            self.assertFalse(m.SIDECAR.exists(), "写了 sidecar ⇒ 触发广播 ⇒ 空转回路")
            self.assertFalse((Path(tmp) / "samples.jsonl").exists())
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_sidecar_write_compares_content_not_just_writes(self):
        body = SAMPLER[SAMPLER.index("def _write_sidecar("):]
        body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
        self.assertIn("_last_sidecar", body)
        self.assertIn('"fetched_at"', body,
                      "比内容时没剔掉每次都变的 fetched_at —— 等于没比")


class ThePushActuallyMovesTheNumberOnScreen(unittest.TestCase):
    """★★★ 行为闸。上面全是结构断言 —— 它们证明不了「推送到达后用户看到的数变了」，
    而那正是 Phase 5 的**全部**产品价值。

    夹具设计：`?agypush=<rem>` 让**推送到达之后**的 `read_agy_quota` 返回一份
    `fetched_at` 更新、水位不同的快照。基线（不带该参数）必须看不到那个数 ——
    否则这条测试在"夹具本来就是新值"上恒绿，等于没测。
    """

    BASE = "http://127.0.0.1:3304"
    CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    NEEDLE = "42.5"

    @classmethod
    def dom(cls, qs):
        import subprocess as sp
        r = sp.run([cls.CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                    "--window-size=1200,900", "--virtual-time-budget=6000", "--dump-dom",
                    f"{cls.BASE}/harness.html?{qs}"],
                   capture_output=True, text=True, timeout=120)
        return r.stdout, re.sub(r"<script\b[^>]*>.*?</script>", "", r.stdout,
                                flags=re.S | re.I)

    @classmethod
    def setUpClass(cls):
        if not Path(cls.CHROME).exists():
            raise unittest.SkipTest("没有 Chrome")
        try:
            raw, cls.baseline = cls.dom("nav=home&rail=open&agy=ok")
        except Exception as e:                      # noqa: BLE001
            raise unittest.SkipTest("harness 不可达: %s" % e)
        if 'class="neterror"' in raw or "<title>__PROBE__" not in raw:
            raise unittest.SkipTest("harness 静态服务没在跑（3304）")
        if "Antigravity" not in cls.baseline and "agy" not in cls.baseline.lower():
            raise AssertionError("harness 可达但 agy 卡没渲染 —— 渲染缺陷，不许跳过")

    def test_the_baseline_does_not_already_show_the_pushed_value(self):
        """★ 没有这一半，"夹具本来就是新值"的实现也会绿。"""
        self.assertNotIn(self.NEEDLE, self.baseline,
                         "基线里就有推送值 —— 这条测试没有判别力")

    def test_the_number_changes_after_the_push_arrives(self):
        _raw, d = self.dom(f"nav=home&rail=open&agy=ok&agypush={self.NEEDLE}")
        self.assertIn(self.NEEDLE, d,
                      "推送到达了，但 UI 上的数没动 —— 监听没接上，或没重读 sidecar")

if __name__ == "__main__":
    unittest.main()
