"""agy 原生 SQLite 用量源的闸（2026-09-09 接入）。

## 这个源存在的理由，以及它推翻的那条结论

本仓曾写着「agy 什么都不落盘、交互式会话的 token 永久拿不到」，依据是
"扫遍 261 个 db，结构化 `promptTokenCount` 零命中"。**那是假阴性** ——
`gen_metadata.data` 是 protobuf wire format，**里面根本没有字段名**，
`grep promptTokenCount` 永远 0 命中。用一个看不见目标的探针得出"目标不存在"。

接上之后实测：覆盖率 **37/101 (36.6%) → 277/303 (91.4%)**，90 天合计 **9M → 317M**。

## 字段号是盲解出来的，所以必须有真数据回归

`f2/f3/f5/f9` 与 `f1.f19` 都不是从 schema 读来的，是逐条比对试出来的。
agy 换一版协议就可能挪位，而**挪位之后的症状是"数字变小"，不是报错** ——
所以这里有一条真数据 canary：本机有库时必须解得出行、且量级站得住。
"""
import inspect
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from traffic import scan  # noqa: E402


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _tag(field, wt):
    return _varint((field << 3) | wt)


def _u64(field, v):
    return _tag(field, 0) + _varint(v)


def _bytes(field, b):
    return _tag(field, 2) + _varint(len(b)) + b


def gen_blob(inp, out, cache, thinking, model):
    """造一条 `gen_metadata.data`：`f1.f4.{f2,f3,f5,f9}` + `f1.f19`。"""
    usage = _u64(2, inp) + _u64(3, out) + _u64(5, cache) + _u64(9, thinking)
    inner = _bytes(4, usage) + _bytes(19, model.encode())
    return _bytes(1, inner)


def step_meta(ts):
    """造一条 `steps.metadata`：`f1.f1` = epoch 秒。"""
    return _bytes(1, _u64(1, ts))


def make_db(path, gens, steps):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB)")
    con.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, metadata BLOB)")
    for i, g in enumerate(gens):
        con.execute("INSERT INTO gen_metadata VALUES (?,?)", (i, g))
    for i, (stype, meta) in enumerate(steps):
        con.execute("INSERT INTO steps VALUES (?,?,?)", (i, stype, meta))
    con.commit()
    con.close()


TS = 1788000000          # 2026-08-x，稳定值，不随今天变


class TheProtobufMappingIsPinned(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "abc-123.db")

    def test_the_four_fields_land_where_they_should(self):
        make_db(self.db,
                [gen_blob(inp=100, out=20, cache=900, thinking=7, model="gemini-3.8-flash")],
                [(14, None), (15, step_meta(TS)), (132, None)])
        rows = scan._scan_agy_db(self.db)
        self.assertEqual(len(rows), 1)
        ts, conv, model, i_tok, cr_tok, o_tok = rows[0]
        self.assertEqual((i_tok, cr_tok, o_tok), (100, 900, 20))
        self.assertEqual(model, "gemini-3.8-flash")
        self.assertEqual(conv, "abc-123", "会话 id 取自文件名")
        self.assertEqual(int(ts), TS)

    def test_thinking_is_a_subitem_of_output_and_is_never_added(self):
        """★★ `f9`(thinking) 是 `f3`(output) 的**子项**。

        与 wrapper 账本逐会话核对：`f3` 单独命中 63/69，而 `f3+f9` 只命中 **1/69**
        （纯属巧合）。agy 属 Claude/Kimi 族 —— **各项互不相交**，加一次就重复计。
        """
        make_db(self.db,
                [gen_blob(inp=0, out=20, cache=0, thinking=19, model="m")],
                [(15, step_meta(TS))])
        self.assertEqual(scan._scan_agy_db(self.db)[0][5], 20,
                         "★ output 里混进了 thinking —— 数字会被放大近一倍")

    def test_a_row_without_a_timestamp_is_dropped_not_stamped_with_now(self):
        """★★ 拿不到时间戳的**整条丢掉**，绝不拿文件 mtime / 当前时间顶替。

        顶替会把一整段历史压进"今天" —— 而它在图上看起来**完全正常**
        （今天一根巨柱，历史一片空白），没有任何东西会报错。
        """
        make_db(self.db,
                [gen_blob(10, 1, 1, 0, "m"), gen_blob(20, 2, 2, 0, "m")],
                [(15, step_meta(TS)), (15, None)])          # 第二条没有时间戳
        rows = scan._scan_agy_db(self.db)
        self.assertEqual(len(rows), 1, "没时间戳的那条被硬塞了一个时间")
        self.assertEqual(int(rows[0][0]), TS)

    def test_the_kth_gen_pairs_with_the_kth_type15_step(self):
        """时间戳靠**序数**配对，不是靠 `idx` 相等 —— `steps` 里还有别的类型混着。"""
        make_db(self.db,
                [gen_blob(1, 1, 1, 0, "m"), gen_blob(2, 2, 2, 0, "m")],
                [(14, step_meta(TS - 999)),        # 用户消息，不参与配对
                 (15, step_meta(TS)),
                 (132, step_meta(TS + 1)),         # 工具调用，不参与配对
                 (15, step_meta(TS + 60))])
        got = [int(r[0]) for r in scan._scan_agy_db(self.db)]
        self.assertEqual(got, [TS, TS + 60], "配对错位了 —— 时间会整体漂移")

    def test_a_corrupt_blob_does_not_lose_the_whole_file(self):
        """★ 半个会话的数字也比整份丢掉强（这些库里有正在被写入的）。"""
        make_db(self.db,
                [b"\xff\xff\xff", gen_blob(5, 6, 7, 0, "m")],
                [(15, step_meta(TS)), (15, step_meta(TS + 30))])
        rows = scan._scan_agy_db(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3:], (5, 7, 6))

    def test_an_unreadable_db_raises_instead_of_returning_empty(self):
        """★★★ 契约**反过来了**（2026-09-10）——原来这条叫
        `..._returns_empty_instead_of_raising`，**把缺陷本身写成了要求**。

        返回 `[]` 看着"稳健"，实际是本仓最贵那条规则的违反：`scan()` 会把结果
        **连同签名一起写进缓存**，而签名要等文件下次变动才变 ⇒ 一次瞬时读失败
        （sqlite 被别人锁着、2s 超时）把该会话**永久固化成 0 token**，零报错。
        「读不到」和「确实没有」必须是两个可区分的值 —— 抛出来，让缓存那层决定
        保留旧值还是这轮跳过。

        ⚠️ 一条写着"不要抛"的测试会**恰好挡住修好它的那次改动**。
           发现测试与规则冲突时，先问哪个是对的，别顺手改实现去迁就测试。
        """
        Path(self.db).write_bytes(b"not a database")
        with self.assertRaises(scan.ScanReadError):
            scan._scan_agy_db(self.db)

    def test_a_table_that_does_not_exist_yet_is_still_empty(self):
        """★ 反向闸：新建的会话库还没写 `gen_metadata` —— 那是**合法的空**，
        不能跟着一起抛，否则修法把正常路径也堵了。"""
        import sqlite3 as _s
        Path(self.db).unlink(missing_ok=True)
        _s.connect(self.db).close()
        self.assertEqual(scan._scan_agy_db(self.db), [])


class TheWalFileIsPartOfTheSignature(unittest.TestCase):
    """★★ agy 的库是 `journal_mode=wal`（实测 261/261 都有 `-wal`）。

    写入落在 WAL 上时**主库的 mtime 与 size 原地不动**。只看主库会同时犯两个错：
    被 `cut` 判成"太旧、跳过"，以及命中旧缓存。两个错的症状都是
    **数字停在旧值上、零报错** —— 本仓最难发现的那一类。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "x.db"
        self.db.write_bytes(b"main")

    def test_the_signature_changes_when_only_the_wal_changes(self):
        st = self.db.stat()
        _, sig1 = scan._agy_db_sig(self.db, st)
        (self.db.parent / "x.db-wal").write_bytes(b"wal-v1")
        _, sig2 = scan._agy_db_sig(self.db, self.db.stat())
        self.assertNotEqual(sig1, sig2, "★ 只有 -wal 变了，签名没变 ⇒ 会命中旧缓存")

    def test_the_effective_mtime_follows_the_newest_sidecar(self):
        wal = self.db.parent / "x.db-wal"
        wal.write_bytes(b"w")
        future = self.db.stat().st_mtime + 10_000
        os.utime(wal, (future, future))
        eff, _ = scan._agy_db_sig(self.db, self.db.stat())
        self.assertGreaterEqual(eff, future,
                                "★ 有效 mtime 没跟上 -wal ⇒ 活跃会话会被 cut 跳过")

    def test_a_read_only_scan_does_not_change_the_signature(self):
        """★★★ **闸缺的那一半**（2026-09-10 Fable 评审抓到）。

        原来只测了「wal 变 ⇒ 签名变」。反方向没测，于是漏掉了真正的缺陷：
        `-shm` 是 WAL 的共享内存索引，**每一个读者**（含我们自己的 `mode=ro` 连接）
        都会往里写 read-mark。把它算进签名 ⇒ 一次纯只读扫描就让签名变化 ⇒
        **261 个库的缓存永不命中**，每次全量重解析 + 重写 18.5MB 缓存，而且零报错。

        空守卫的又一种形态：**只验了一个方向**。「会变」和「该不变时不变」是两条性质。
        """
        # ★★ 判据只看**那个 suffix 元组**，不做整段源码匹配 —— 今天第四次被
        #    "闸命中自己的说明文字"判红（函数里正解释着"绝不能加 -shm"）。
        #    行为断言在下面，这条只是把结构也钉住。
        src = inspect.getsource(scan._agy_db_sig)
        m = re.search(r'for suffix in \(([^)]*)\)', src)
        self.assertIsNotNone(m, "找不到 suffix 元组 —— 判据失效了")
        self.assertNotIn("shm", m.group(1),
                         "★ `-shm` 又进签名了 —— 只读也会推它的 mtime，缓存必然永不命中")
        self.assertIn("wal", m.group(1), "★ `-wal` 掉了 —— 新写入读不进来")
        # 行为侧:造一个真 SQLite（WAL 模式），只读查询一次，签名必须不变。
        # ★ **必须让 `-wal` 常驻**：SQLite 在最后一个连接关闭时会删掉 `-wal`/`-shm`，
        #   于是下一次只读打开会把它们**创建**出来、签名当然会变一次。
        #   而真实场景里 agy 持着连接，261/261 个库的 `-wal` 都是常驻的（实测）——
        #   夹具不还原这个稳态，测的就不是要测的那件事。
        db = Path(self.tmp.name) / "wal-ro.db"
        con = sqlite3.connect(db)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (x INTEGER)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        self.addCleanup(con.close)          # 全程持有 ⇒ -wal / -shm 常驻
        before = scan._agy_db_sig(db, db.stat())[1]
        ro = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        ro.execute("SELECT * FROM t").fetchall()
        ro.close()
        self.assertEqual(before, scan._agy_db_sig(db, db.stat())[1],
                         "★ 只读查询改变了签名 —— 缓存会永不命中")

    def test_a_real_write_still_changes_the_signature(self):
        """★ 反向对照。少了这条，一个「签名恒定」的实现也能让上面那条绿 ——
        而那会让**新数据永远读不进来**，比缓存失效严重得多。"""
        db = Path(self.tmp.name) / "wal-rw.db"
        con = sqlite3.connect(db)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (x INTEGER)")
        con.commit()
        self.addCleanup(con.close)
        before = scan._agy_db_sig(db, db.stat())[1]
        con.execute("INSERT INTO t VALUES (42)")
        con.commit()
        self.assertNotEqual(before, scan._agy_db_sig(db, db.stat())[1],
                            "★ 真写入没让签名变 —— 新数据永远读不进来")

    def test_a_missing_wal_is_not_an_error(self):
        eff, sig = scan._agy_db_sig(self.db, self.db.stat())
        self.assertTrue(sig)
        self.assertGreater(eff, 0)


class TheLedgerOnlyFillsGaps(unittest.TestCase):
    """SQLite 是超集（实测账本的 69 个会话**全部**是 261 个 db 的真子集，"仅账本 0"），
    所以 db 为主。账本只补 db 已消失的会话 —— **绝不双计**。

    ★ 这个类**必须把 `AGY_ROOT` 指到 tmpdir**。第一版没指，`_agy_rows` 读到了
      本机真实账本的 69 个会话，断言 `len(out)==1` 拿到 69 —— 测试碰真实数据，
      而且那条"去重"根本没被验到（本仓 testing-discipline 的第一条）。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = scan.AGY_ROOT
        scan.AGY_ROOT = Path(self.tmp.name)
        self.addCleanup(lambda: setattr(scan, "AGY_ROOT", self._old))

    def _ledger(self, *entries):
        import json as _json
        with open(Path(self.tmp.name) / "usage.jsonl", "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(_json.dumps(e) + "\n")

    def test_a_conversation_present_in_both_is_counted_once(self):
        """★★ 共有会话必须只算一次。db 有的，账本那份一律丢掉。"""
        self._ledger(
            {"ts": TS, "conv": "conv-A", "model": "m",
             "input_tokens": 999, "cache_read_tokens": 999, "output_tokens": 999},
            {"ts": TS, "conv": "conv-GONE", "model": "m",
             "input_tokens": 7, "cache_read_tokens": 3, "output_tokens": 1},
        )
        out = scan._agy_rows([(float(TS), "conv-A", "m", 10, 5, 2)])
        self.assertEqual(len(out), 2, f"应是 db 的 1 条 + 账本独有的 1 条,得到 {out}")
        totals = sorted(r[2] for r in out)
        self.assertEqual(totals, [7, 10], "★ conv-A 被计了两次 —— 账本没按会话去重")

    def test_a_conversation_only_in_the_ledger_is_kept(self):
        """★ 反方向:agy 若清理过旧会话,账本里那几个 db 已经没有的**不能白丢**。
        少了这条,一个"账本全丢掉"的实现也能让上面那条绿。"""
        self._ledger({"ts": TS, "conv": "conv-GONE", "model": "m",
                      "input_tokens": 7, "cache_read_tokens": 3, "output_tokens": 1})
        out = scan._agy_rows([])
        self.assertEqual(len(out), 1, "账本独有的会话被丢掉了")
        self.assertEqual(out[0][2:], [7, 3, 0, 1])

    def test_rows_come_out_in_the_standard_shape(self):
        out = scan._agy_rows([(float(TS), "c", "m", 10, 5, 2)])
        self.assertEqual(out[0], [TS, "m", 10, 5, 0, 2],
                         "row 形状必须是 [ts, model, in, cache_read, cache_write, out]")


@unittest.skipUnless(scan.AGY_DB_ROOT.is_dir() and any(scan.AGY_DB_ROOT.glob("*.db")),
                     "本机没有 agy 的会话库")
class RealDataCanary(unittest.TestCase):
    """★★ 字段号是**盲解**出来的，不是从 schema 读来的。

    agy 换一版协议就可能挪位，而挪位后的症状是**数字变小**、不是报错。
    这条 canary 在真库上跑，量级塌了就红。
    """

    def test_the_local_databases_still_parse(self):
        dbs = sorted(scan.AGY_DB_ROOT.glob("*.db"))
        rows = []
        for p in dbs[-40:]:                     # 取最近 40 个，够判且够快
            rows.extend(scan._scan_agy_db(p))
        self.assertGreater(len(rows), 50,
                           f"★ 最近 40 个库只解出 {len(rows)} 条 —— 字段号可能已经漂移")
        # 每条至少有一项非零（全 0 = 解到了空处）
        self.assertTrue(any(r[3] or r[4] or r[5] for r in rows))
        # 模型名解得出来（`f1.f19`）。允许少量为空，但不能全空。
        named = sum(1 for r in rows if r[2] and r[2] != "unknown")
        self.assertGreater(named, len(rows) * 0.5,
                           "★ 一半以上的行解不出模型名 —— f19 可能挪位了")

    def test_cache_read_dominates_as_measured(self):
        """实测构成里 `cache_read` 远大于 input —— 这是这类 agent 会话的固有形状。
        反过来（input 远大于 cache_read）说明 f2/f5 认反了。"""
        rows = []
        for p in sorted(scan.AGY_DB_ROOT.glob("*.db"))[-40:]:
            rows.extend(scan._scan_agy_db(p))
        i_tot = sum(r[3] for r in rows)
        cr_tot = sum(r[4] for r in rows)
        self.assertGreater(cr_tot, i_tot,
                           f"★ cache_read({cr_tot:,}) 没有大于 input({i_tot:,}) —— f2/f5 可能认反")


if __name__ == "__main__":
    unittest.main()


class TheFrontendCopyMatchesTheBackend(unittest.TestCase):
    """★★ 换了数据源，**页面上的话必须跟着换**。

    2026-09-09 用户截图报「消耗还是 0」时，后端已经跑通（覆盖率 95.2%、317M），
    但页面顶部仍写着 `traffic/agy-ledger/usage.jsonl（wrapper 记账）` 与
    「Antigravity 自己不记录用量，只有经 wrapper 的 print 模式会被记账，交互式会话拿不到」——
    **一句关于事实的假陈述**，而且正好会让用户以为"还是没接上"。

    这是本仓「后端有字段 ≠ 已披露」的**反向形态**：后端改了，披露层还在说旧事实。
    两个方向都要有闸。
    """

    ROOT = Path(__file__).resolve().parents[1]
    SCAN = (ROOT / "traffic" / "scan.py").read_text(encoding="utf-8")
    TRAFFIC_TS = (ROOT / "codexbar" / "src" / "traffic.ts").read_text(encoding="utf-8")
    PLATFORM = (ROOT / "codexbar" / "src" / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8")

    def _sqlite_is_the_primary_source(self):
        import re as _re
        m = _re.search(r'\{"key": "agy".*?\}', self.SCAN, _re.S)
        return bool(m and "_scan_agy_db" in m.group(0))

    def test_the_source_label_names_the_real_file(self):
        """页面顶部那行"数据从哪来"必须指向真正在读的东西。"""
        if not self._sqlite_is_the_primary_source():
            self.skipTest("主源不是 SQLite，这条不适用")
        self.assertIn("conversations/*.db", self.PLATFORM,
                      "★ 源标签还写着 wrapper 账本 —— 用户会以为没接上")
        self.assertNotIn("agy-ledger/usage.jsonl（wrapper 记账）", self.PLATFORM)

    def test_the_coverage_banner_no_longer_claims_print_only(self):
        """★ 覆盖率横幅是这一页最显眼的一句话。它说"交互式会话拿不到"时，
        用户没有任何理由去怀疑那是过时的。"""
        if not self._sqlite_is_the_primary_source():
            self.skipTest("主源不是 SQLite，这条不适用")
        import re as _re
        m = _re.search(r"export function coverageNote.*?\n\}", self.TRAFFIC_TS, _re.S)
        self.assertIsNotNone(m, "找不到 coverageNote —— 判据失效了")
        body = m.group(0)
        for stale in ("交互式会话拿不到", "只有经 wrapper 的 print 模式", "自己不记录用量"):
            self.assertNotIn(stale, body, f"★ 横幅还在说「{stale}」—— 那已经不是事实了")
        self.assertIn("含交互式会话", body, "没说清楚现在覆盖到哪儿")

    def test_the_gate_would_catch_a_regression(self):
        """★ 闸自证：判据依赖 `_sqlite_is_the_primary_source()` 真的能分辨两种接法。"""
        self.assertTrue(self._sqlite_is_the_primary_source(),
                        "当前主源应是 SQLite —— 若不是，上面两条会被静默 skip")
