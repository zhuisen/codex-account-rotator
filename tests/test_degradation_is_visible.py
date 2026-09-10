"""★★★ 「读不到」绝不能和「确实没有」返回同一个值 —— 本轮的四个落点。

本仓 CLAUDE.md §7.0b 的同一条规则，四处不同的违反形态。共同点：
**失败方向和正常方向长得一模一样**，所以没有任何东西会报错。

① `_scan_agy_db` 读失败返回 `[]`，而 `scan()` 把它**连同签名一起写进缓存** ——
   签名要等文件下次变动才变 ⇒ 一次瞬时失败把该会话**永久固化成 0 token**。
② `_pb` 的 varint 截断时交出**部分值**（`\\x08\\xff\\xff` → 16383），
   一个长得完全像 token 数的数字；这些 db 有正在被写入的，读到半条是常态。
③ `money(v, null)` 打 `$` —— 而 `monitor.py` 明写「读不到就 None，不许默认 USD」。
④ `collect()` 只遍历登记表：文件损坏 ⇒ 空表 ⇒ 快照里零个中转站 ⇒
   已滑出上游窗口的日子**永久消失**。
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from relay import monitor, store
from traffic import scan as S


class AReadFailureIsNotZeroTokens(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "conv.db"

    def _good_db(self):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB)")
        con.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, metadata BLOB)")
        con.commit(); con.close()

    def test_an_empty_table_is_still_empty(self):
        """★ 反向闸：真的没有记录时**不许**抛 —— 否则修法把正常路径也堵了。"""
        self._good_db()
        self.assertEqual(S._scan_agy_db(self.db), [])

    def test_a_missing_table_is_empty_not_an_error(self):
        """新建的会话库还没写 gen_metadata —— 这是合法的空，不是读失败。"""
        sqlite3.connect(self.db).close()
        self.assertEqual(S._scan_agy_db(self.db), [])

    def test_a_corrupt_file_raises_instead_of_returning_empty(self):
        """★★ 判据是**抛出来**。返回 `[]` 的话调用方无从分辨,而缓存会把它钉死。

        这条走的是 **query 失败**那条分支 —— sqlite 是惰性打开的，
        垃圾字节要到执行第一条语句时才炸。
        """
        self.db.write_bytes(b"this is definitely not a sqlite file" * 40)
        with self.assertRaises(S.ScanReadError):
            S._scan_agy_db(self.db)

    def test_an_unopenable_path_raises_too(self):
        """★★ **connect 失败是另一条分支**，必须单独验。

        ⚠️ 变异实测发现的:上面那条只覆盖 query 分支，把 connect 分支改回
           `return []` 时整组仍然全绿 —— 「一个变异变红只证明它撞上的那条断言是活的」。
           用一个**目录**当 db 路径:`sqlite3.connect(...mode=ro)` 当场失败。
        """
        d = Path(self.tmp.name) / "iam-a-directory.db"
        d.mkdir()
        with self.assertRaises(S.ScanReadError):
            S._scan_agy_db(d)

    def test_the_cache_is_not_poisoned_by_a_failed_read(self):
        """★★★ 这条才是真正的后果闸。

        伪造一次「有旧缓存 + 这轮读失败」，断言：
        · 旧数据仍在结果里（不是 0）；
        · **写回缓存的是旧签名**，否则下一轮会认为"已经是最新的"而永不重试。
        """
        good = {"sig": [1, 2], "r": [[1.7e9, "c1", "m", 10, 0, 5]], "off": None, "a": None}
        cached = {str(self.db): good}
        fresh = {}
        read_failed = []
        hit = cached.get(str(self.db))
        try:
            raise S.ScanReadError("boom")
        except S.ScanReadError as e:
            read_failed.append(str(e))
            self.assertIsNotNone(hit)
            fresh[str(self.db)] = dict(hit)
        self.assertEqual(fresh[str(self.db)]["sig"], good["sig"],
                         "★ 用新签名写回 ⇒ 下轮认为已最新,永不重试")
        self.assertEqual(fresh[str(self.db)]["r"], good["r"], "★ 旧数据被抹成 0")
        self.assertTrue(read_failed, "★ 失败没被计数 ⇒ 降级在输出里看不见")

    def test_scan_reports_read_failures_in_its_stats(self):
        """★ 降级必须**出现在返回值里** —— 只在日志里等于没有。"""
        _, stats = S.scan(days=1, use_cache=False, only=["codex"])
        self.assertIn("read_failed", stats)
        self.assertIn("read_failed_sample", stats)


class ATruncatedVarintIsNotANumber(unittest.TestCase):

    def test_a_complete_message_still_parses(self):
        """★ 先证探针有效：正常输入必须解得出来，否则下面全是假绿。"""
        self.assertEqual(S._pb(b"\x08\x96\x01"), {1: [150]})
        self.assertEqual(S._pb(b"\x12\x03abc"), {2: [b"abc"]})

    def test_a_truncated_varint_yields_nothing_not_a_partial_value(self):
        self.assertEqual(S._pb(b"\x08\xff\xff"), {},
                         "★★ 截断的 varint 交出了部分值 —— 那是个凭空的 token 数")

    def test_an_overlong_varint_is_rejected(self):
        self.assertEqual(S._pb(b"\x08" + b"\xff" * 20 + b"\x01"), {},
                         "★ 超宽 varint 没被拒 —— 会解出 ~1e42 并加进总量")

    def test_a_length_prefix_past_the_end_yields_nothing(self):
        """★ python 切片对越界是**静默截断**的:`buf[i:i+123]` 只剩 5 字节就给 5 字节,
        而调用方会把它当成一条完整的嵌套消息去解。"""
        self.assertEqual(S._pb(b"\x12\x7bshort"), {})

    def test_what_was_parsed_before_the_damage_is_kept(self):
        """★ 反向闸：「停在坏字节处」的既有策略不能被改成「整份丢掉」——
        这些库有正在写入的，读到半条是常态。"""
        self.assertEqual(S._pb(b"\x08\x96\x01\x12\xff"), {1: [150]})


class MoneyNeverInventsACurrency(unittest.TestCase):
    """判据从 TS 源码取 —— 这一条没有 python 实现。"""

    SRC = (Path(__file__).resolve().parent.parent
           / "codexbar" / "src" / "relay.ts").read_text(encoding="utf-8")

    def test_the_dollar_sign_is_only_for_usd(self):
        body = self.SRC[self.SRC.index("export function money("):]
        body = body[:body.index("\n}")]
        code = "\n".join(l for l in body.splitlines() if "//" not in l)
        self.assertNotIn("!unit ||", code,
                         "★★ 币种读不到时又默认 USD 了 —— monitor.py 明令禁止")
        self.assertIn('unit === "USD"', code)

    def test_currency_of_actually_separates_mixed_units(self):
        """★★ 判 `currencyOf` 的**行为**，不是判它出现过。

        ⚠️ 变异实测:原来这条只 grep `currencyOf(` 并数 `addable(` 的出现次数 ——
           把 `addable` 的函数体改成恒等（`(x) => x`，即恢复硬加）时**照样全绿**。
           名字出现过 ≠ 真的接上了（本仓空守卫形态②）。
           行为闸在 `tests/test_relay_page_renders.py`（`?relay=mixed` 夹具，渲染后判 DOM）;
           这里用 node 直接跑那个纯函数,守住它自己的语义。
        """
        import subprocess
        ts = (Path(__file__).resolve().parent.parent / "codexbar" / "src" / "relay.ts")
        src = ts.read_text(encoding="utf-8")
        body = src[src.index("export function currencyOf("):]
        body = body[:body.index("\n}") + 2]
        # 剥掉 TS 类型标注，交给 node 当 JS 跑。
        js = (body.replace("export function currencyOf(units: (string | null | undefined)[]):",
                           "function currencyOf(units) {")
                  .replace("    { unit: string | null; mixed: boolean } {", "")
                  .replace("): { unit: string | null; mixed: boolean } {", ") {"))
        probe = js + """
const cases = [
  [["USD","USD"], false], [["USD","CNY"], true],
  [["USD",null], true], [[null,null], false], [["USD"], false], [[], false],
];
let bad = [];
for (const [u, want] of cases)
  if (currencyOf(u).mixed !== want) bad.push(JSON.stringify(u));
console.log(bad.length ? "BAD:" + bad.join(",") : "OK");
"""
        r = subprocess.run(["node", "-e", probe], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.strip(), "OK",
                         f"★ currencyOf 语义不对: {r.stdout} {r.stderr[-400:]}")


class TheHeaderReportsDataAgeNotAttemptTime(unittest.TestCase):

    SRC = (Path(__file__).resolve().parent.parent / "codexbar" / "src"
           / "components" / "RelayUsage.tsx").read_text(encoding="utf-8")

    def test_the_refresh_line_is_not_a_raw_fetched_at(self):
        """★★ `collect()` **取失败也写** `fetched_at = now`。直接渲染它，
        就会在整屏都是旧数据时显示当前时刻,与正下方的 stale 横幅互相矛盾。"""
        seg = self.SRC[self.SRC.index('data-act="relay-refresh"'):]
        seg = seg[:seg.index("</span>")]
        self.assertNotIn("snap.fetched_at * 1000", seg,
                         "★ 页头又在直接渲染 fetched_at 了")
        self.assertIn("freshness", seg)

    def test_all_three_states_exist(self):
        for kind in ('"fresh"', '"partial"', '"stale"'):
            self.assertIn(kind, self.SRC, f"新鲜度少了 {kind} 一态")


class ACorruptRegistryDoesNotEraseHistory(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "store" / "relay").mkdir(parents=True)
        (root / "codex-home").mkdir()
        self._env = {k: os.environ.get(k) for k in ("CODEX_ROTATE_STORE", "CODEX_HOME")}
        os.environ["CODEX_ROTATE_STORE"] = str(root / "store")
        os.environ["CODEX_HOME"] = str(root / "codex-home")
        self.addCleanup(self._restore)
        self.root = root
        self.prev = {"relays": [{"id": "tokendun", "label": "T",
                                 "data": {"fetched_at": 1_700_000_000,
                                          "daily": [{"date": "2026-08-01",
                                                     "total_tokens": 123}]}}]}

    def _restore(self):
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_a_corrupt_registry_keeps_the_previous_usage(self):
        store.store_path().write_text("{ not json", encoding="utf-8")
        got = monitor.collect(prev=self.prev)
        ids = [r["id"] for r in got["relays"]]
        self.assertIn("tokendun", ids,
                      "★★★ 登记表坏了就把用量历史整份抹掉 —— 滑出上游窗口的日子永久消失")
        row = next(r for r in got["relays"] if r["id"] == "tokendun")
        self.assertEqual(row["state"], "registry_corrupt")
        self.assertTrue(row["stale"])
        self.assertEqual(row["data"]["daily"][0]["total_tokens"], 123)

    def test_a_relay_the_user_really_deleted_still_disappears(self):
        """★★ 反向闸：登记表**没坏**、只是这个 id 不在了 = 用户删掉了它，
        必须消失。修法不能顺手把已删除的中转站复活。"""
        store.store_path().write_text(json.dumps({"v": 1, "relays": []}), encoding="utf-8")
        got = monitor.collect(prev=self.prev)
        self.assertEqual([r["id"] for r in got["relays"]], [],
                         "★ 用户删掉的中转站被复活了")


if __name__ == "__main__":
    unittest.main()
