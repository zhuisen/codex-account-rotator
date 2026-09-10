"""P2 最后一批的三条闸：agy 时间戳精确 join / 模型撞色 / 中转站计数器分家。

三条的共同点还是那一个：**症状是数字悄悄错位，而没有任何东西报错。**
"""
import collections
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from traffic import scan as S

ROOT = Path(__file__).resolve().parent.parent


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _f(no, wt):
    return _varint((no << 3) | wt)


def _kv(k, v):
    """`f20` 里的一个 kv 对：`{1: key, 2: value}`（都是 length-delimited）。"""
    inner = (_f(1, 2) + _varint(len(k)) + k) + (_f(2, 2) + _varint(len(v)) + v)
    return _f(20, 2) + _varint(len(inner)) + inner


def gen_blob(inp, cr, out, model=b"gemini-3.8-flash", last_step_index=None):
    """一条 `gen_metadata.data`：`f1 → {f4 → {f2,f3,f5}, f19, f20*}`。"""
    u = (_f(2, 0) + _varint(inp)) + (_f(3, 0) + _varint(out)) + (_f(5, 0) + _varint(cr))
    inner = _f(4, 2) + _varint(len(u)) + u
    inner += _f(19, 2) + _varint(len(model)) + model
    if last_step_index is not None:
        inner += _kv(b"request_id", b"x")           # ★ 多个 kv：真实数据就是重复字段
        inner += _kv(b"last_step_index", str(last_step_index).encode())
    return _f(1, 2) + _varint(len(inner)) + inner


def step_meta(ts):
    """`steps.metadata`：`f1 → {f1 = epoch}`。"""
    i = _f(1, 0) + _varint(ts)
    return _f(1, 2) + _varint(len(i)) + i


class TheTimestampIsJoinedNotGuessed(unittest.TestCase):
    """★★★ 时间戳靠 `last_step_index` **精确 join**，不按序数猜。

    实测 263 个库 3758 条 gen：`last_step_index + 1` 落在一个 `step_type=15` 上的
    比例是 **3758/3758 = 100%**；与序数猜测**有 164 条（4.4%）不一致** ——
    那 4.4% 拿的是别人的时间戳，足以把用量记到错的日子，而画出来完全正常。

    ⚠️ 这条结论我探错过两次，夹具因此**故意做成会让两种实现分叉的形状**：
      步骤里混入非 15 的 step，使「第 k 个 step15 的绝对下标」≠「lsi+1」。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "conv.db"

    def build(self, gens, steps):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB)")
        con.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, metadata BLOB)")
        con.executemany("INSERT INTO gen_metadata VALUES (?,?)", list(enumerate(gens)))
        con.executemany("INSERT INTO steps VALUES (?,?,?)",
                        [(i, st, m) for i, (st, m) in enumerate(steps)])
        con.commit(); con.close()

    def test_it_uses_last_step_index_not_the_ordinal(self):
        """★★ 夹具让两种实现给出**不同**的答案：

        steps = [type1, type15@1000, type1, type15@2000, type15@3000]
        两条 gen，`last_step_index` = 3 和 0 ⇒ 精确 join 取 steps[4]=3000 与 steps[1]=1000。
        序数猜测会取「第 0 个 step15」=1000 与「第 1 个」=2000 —— 两条都不同。
        """
        self.build(
            [gen_blob(5, 7, 6, last_step_index=3), gen_blob(1, 1, 1, last_step_index=0)],
            [(1, None), (15, step_meta(1_700_000_000)), (1, None),
             (15, step_meta(1_700_000_500)), (15, step_meta(1_700_001_000))])
        got = sorted(r[0] for r in S._scan_agy_db(self.db))
        self.assertEqual(got, [1_700_000_000.0, 1_700_001_000.0],
                         f"★ 时间戳还在按序数猜: {got}")

    def test_the_ordinal_guess_survives_as_a_fallback(self):
        """★ 反向闸：`last_step_index` 缺失时行为必须与改动前**逐字相同** ——
        修法不能把没有这个字段的老库变成"一条都读不出"。"""
        self.build([gen_blob(5, 7, 6)],                       # 不带 last_step_index
                   [(15, step_meta(1_700_000_000))])
        got = [r[0] for r in S._scan_agy_db(self.db)]
        self.assertEqual(got, [1_700_000_000.0], "缺 last_step_index 时兜底没生效")

    def test_a_repeated_f20_is_walked_not_indexed(self):
        """★★ `f20` 是**重复字段**，一条 gen 有多个 kv。只取 `[0]` 会拿到
        `request_id` 那一条而读不到 `last_step_index` —— 我第二次探错就是这个。
        夹具把 `request_id` 放在**前面**，专门让"只取第一个"的实现失败。"""
        self.build([gen_blob(5, 7, 6, last_step_index=2)],
                   [(1, None), (1, None), (1, None), (15, step_meta(1_700_009_000))])
        got = [r[0] for r in S._scan_agy_db(self.db)]
        self.assertEqual(got, [1_700_009_000.0],
                         "★ 没遍历重复的 f20，只看了第一个 kv")


class NoTwoModelsOfOnePlatformShareAColour(unittest.TestCase):
    """★★ 两条同色的带子在堆叠图上是一条，**不会报任何错**。

    实测：agy 用过的 7 个模型 id 全部落进散列兜底，10 色盘上**撞了 3 对**，
    而撞的恰好是最需要区分的（`gemini-3.7-flash` vs `-tiered` 等）。
    散列兜底本身没问题（同名恒同色、不含灰），问题是**同时在场**的模型一多必然撞 ——
    生日悖论，7 个进 10 色盘撞车概率接近 9 成。可枚举的模型集合就该手工登记。
    """

    TS = (ROOT / "codexbar" / "src" / "theme.ts").read_text(encoding="utf-8")

    def pairs(self):
        m = re.search(r"MODEL_COLORS[^{]*\{(.*?)\n\};", self.TS, re.S)
        self.assertIsNotNone(m, "解析不出 MODEL_COLORS —— 探针坏了")
        got = re.findall(r'"([^"]+)":\s*"(#[0-9a-fA-F]{6})"', m.group(1))
        self.assertGreater(len(got), 20, f"只解析出 {len(got)} 项 —— 探针坏了")
        return got

    @staticmethod
    def platform(n):
        return ("codex" if n.startswith("gpt-") else "claude" if n.startswith("claude-")
                else "grok" if n.startswith("grok") else "kimi" if n.startswith("kimi")
                else "agy")

    def test_no_collision_inside_a_platform(self):
        by = collections.defaultdict(lambda: collections.defaultdict(list))
        for n, c in self.pairs():
            by[self.platform(n)][c].append(n)
        bad = {}
        for pl, cs in by.items():
            # ★ 唯一允许的同色：同一个模型的 thinking 变体（它就是同一个模型）。
            d = {c: v for c, v in cs.items()
                 if len(v) > 1 and {x.replace("-thinking", "") for x in v} != {v[0].replace("-thinking", "")}}
            if d:
                bad[pl] = d
        self.assertEqual(bad, {}, f"★★ 同平台内两个模型同色，图上是一条带: {bad}")

    def test_every_agy_model_seen_on_this_machine_is_registered(self):
        """★ 判据从**真实数据**取，不手抄清单 —— 手抄的清单会恰好在它该发现的
        那次改动上保持绿色（本仓 testing-discipline 的原话）。"""
        seen = set()
        root = S.AGY_DB_ROOT
        if not root.is_dir():
            self.skipTest("本机没有 agy 会话库")
        for p in sorted(root.glob("*.db"))[:80]:
            try:
                con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2.0)
                gens = list(con.execute("SELECT data FROM gen_metadata ORDER BY idx"))
            except Exception:
                continue
            finally:
                try: con.close()
                except Exception: pass
            for (blob,) in gens:
                if not blob:
                    continue
                t = S._pb(blob)
                inner = S._pb(t[1][0]) if 1 in t else {}
                m = inner.get(19)
                if m and isinstance(m[0], (bytes, bytearray)):
                    seen.add(m[0].decode("utf-8", "replace"))
        if not seen:
            self.skipTest("本机 agy 库里没有模型 id")
        known = {n for n, _ in self.pairs()}
        self.assertEqual(seen - known, set(),
                         f"★ 这些 agy 模型没登记颜色，会落进散列兜底并可能撞色: {seen - known}")


class TheRelayLaneHasItsOwnCounters(unittest.TestCase):
    """★★ `stream_aborts` / `committed_aborts` 的**存在理由**是量化账号池那条路上的
    **双计费**（有 failover ⇒ 同一次生成可能被两个号各计一次费）。
    中转站没有 failover，一次断流的含义完全不同。混进同一个键：
    账号池的指标被稀释，中转站自己的失败率无处可查 —— 两件事都不出声。
    """

    SRC = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")

    def test_the_relay_lane_bumps_a_relay_specific_key(self):
        import ast
        tree = ast.parse(self.SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_proxy_relay")
        keys = [a.args[0].value for a in ast.walk(fn)
                if isinstance(a, ast.Call) and getattr(a.func, "id", None) == "_bump"
                and a.args and isinstance(a.args[0], ast.Constant)]
        self.assertTrue(keys, "中转站泳道一个计数器都没有 —— 失败率无处可查")
        for k in keys:
            self.assertTrue(k.startswith("relay_"),
                            f"★ 中转站泳道用了账号池的计数器 `{k}`")

    def test_the_pool_lane_keeps_its_own(self):
        """★ 反向闸：账号池那两个键必须还在 —— 不能把"分家"做成"搬走"。"""
        import ast
        tree = ast.parse(self.SRC)
        relay = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "_proxy_relay")
        relay_lines = set(range(relay.lineno, relay.end_lineno + 1))
        pool = [a.args[0].value for a in ast.walk(tree)
                if isinstance(a, ast.Call) and getattr(a.func, "id", None) == "_bump"
                and a.args and isinstance(a.args[0], ast.Constant)
                and a.lineno not in relay_lines]
        self.assertIn("stream_aborts", pool)
        self.assertIn("committed_aborts", pool)


if __name__ == "__main__":
    unittest.main()
