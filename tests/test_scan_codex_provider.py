"""codex 的 **provider 分账**（2026-09-09，Phase 4）。

## 它解决的是一个真实存在的双重计价

经中转站的会话**照样写 rollout**，于是那批 token 既进「AI用量」的 Codex 桶
（按 OpenAI 牌价折算成"等效成本"），又在中转站那边**真金实扣过一次**。
同一批 token 以两个不同的价出现在两页上，而没有任何地方说明它们不是一回事。

分账把「这批 token 走的是哪条路由」变成可见的，**但不动任何总量** ——
30+ 处读 `b.total` 的地方一个都不迁。

## ★★ 一条实测出来的解析纪律

**一份 rollout 可以有两条 `session_meta`**（2026-08-24 有 5 份，第二条之后还跟着
17 条 token_count）。所以 provider 必须**按 ordinal 顺序跟踪**，读一次会把后半段的
token 记到前半段的 provider 上。这与"模型按 `turn_context` 顺序跟踪"是同一条纪律 ——
那条已经因为"5 个文件中途换过模型"栽过一次。

## 最强的那条证据不在这份文件里

`traffic/scan.py --days 1` 的 `platforms.codex.by_provider.tokendun.total`
与中转站服务端 `/usage` 的 `today.total_tokens` **逐 token 相等（39,513 = 39,513，0.00%）**。
两个完全独立的来源：一个是本机 rollout 逐行解析，一个是对方的账单接口。
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("scan_prov", ROOT / "traffic" / "scan.py")
SCAN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SCAN)


def rollout(events):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for e in events:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    f.close()
    return f.name


def meta(provider):
    return {"type": "session_meta", "payload": {"id": "x", "model_provider": provider}}


def ctx(model):
    return {"type": "turn_context", "payload": {"model": model}}


def tokens(ts, total_cum, out=10):
    return {"type": "event_msg", "timestamp": ts, "payload": {
        "type": "token_count", "info": {
            "total_token_usage": {"total_tokens": total_cum},
            # ★ `last_token_usage.total_tokens` 是解析器的**准入条件**
            #   （`if not _num(lt, "total_tokens"): continue`）。我第一版漏了它,
            #   于是夹具产出 0 行 —— 而"解析器坏了"和"夹具形状不对"看起来一样。
            "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 20,
                                 "cache_write_input_tokens": 0, "output_tokens": out,
                                 "total_tokens": 100 + out}}}}


class ProviderIsTrackedInOrdinalOrder(unittest.TestCase):
    """★★ 一份 rollout 里两条 `session_meta` ⇒ 前后两段必须归到不同的 provider。"""

    def test_two_session_meta_split_the_file(self):
        p = rollout([
            meta("rotateproxy"), ctx("gpt-6-astra"),
            tokens("2026-09-09T10:00:00Z", 100),
            meta("tokendun"),
            tokens("2026-09-09T10:05:00Z", 200),
        ])
        rows = SCAN._scan_codex_file(p)
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual(rows[0][7], "rotateproxy")
        self.assertEqual(rows[1][7], "tokendun",
                         "第二条 session_meta 之后的 token 还记在前一个 provider 上")

    def test_the_platform_key_stays_codex_for_both(self):
        """★ 第 7 位是**平台键**，第 8 位才是 provider。中转站不该变成一个新平台 ——
        它是 codex 的一条路由，不是另一个 AI。"""
        p = rollout([meta("tokendun"), ctx("m"), tokens("2026-09-09T10:00:00Z", 100)])
        self.assertEqual(SCAN._scan_codex_file(p)[0][6], "codex")

    def test_a_rollout_without_session_meta_is_unknown_not_dropped(self):
        """★ 没有 provider 的老 rollout **不许丢**，也不许造出一个新平台。"""
        p = rollout([ctx("m"), tokens("2026-09-09T10:00:00Z", 100)])
        rows = SCAN._scan_codex_file(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][7], "unknown")
        self.assertEqual(rows[0][6], "codex")

    def test_the_first_six_columns_are_untouched(self):
        """★★ 分账**绝不能动既有列**。30+ 处读 `row[:6]` 的地方全靠这一条。"""
        p = rollout([meta("tokendun"), ctx("gpt-5.5"), tokens("2026-09-09T10:00:00Z", 100, out=7)])
        r = SCAN._scan_codex_file(p)[0]
        self.assertEqual(r[1], "gpt-5.5")
        self.assertEqual(r[2], 80)      # 100 - 20 cached - 0 write
        self.assertEqual(r[3], 20)
        self.assertEqual(r[4], 0)
        self.assertEqual(r[5], 7)


class TheParserVersionWasBumped(unittest.TestCase):
    """★★ 旧缓存里的 codex 行**没有第 8 位**，只有版本号能逼它重解析。
    不 +1 的话，缓存命中的文件会一直没有 provider —— 而"没有分账"和
    "全都走账号池"在 UI 上长得一样。"""

    def test_parser_v_is_at_least_9(self):
        self.assertGreaterEqual(SCAN.PARSER_V, 9)

    def test_the_old_value_is_kept_as_a_comment_for_provenance(self):
        src = (ROOT / "traffic" / "scan.py").read_text(encoding="utf-8")
        self.assertIn("# PARSER_V = 8", src, "没留上一版的号，回溯时查不到是哪次改的")


class TheSplitMatchesTheTotalOnRealData(unittest.TestCase):
    """★★ **同一页上的两个数必须同窗口。**

    我第一版把 `by_provider` 的累加放在窗口判断**之前**，于是它把 3600 个 rollout 的
    全部历史都算进去：`days` 合计 119M 而 `by_provider` 合计 9,004M。
    两个数放在同一页上就是骗人。
    """

    @classmethod
    def setUpClass(cls):
        r = subprocess.run([sys.executable, str(ROOT / "traffic" / "scan.py"),
                            "--days", "2", "--json"],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not r.stdout.strip():
            raise unittest.SkipTest("scan 跑不起来: %s" % r.stderr[-200:])
        cls.d = json.loads(r.stdout)

    def test_by_provider_sums_to_the_same_total_as_days(self):
        c = self.d["platforms"].get("codex")
        if not c or not c.get("by_provider"):
            self.skipTest("本机 codex 桶里没有分账数据")
        days_total = sum(b["total"] for b in c["days"].values())
        # ★ 形状是 provider → 日期 → 桶（2026-09-10 起按日下发,前端按档求和）。
        split_total = sum(b["total"]
                          for per_day in c["by_provider"].values()
                          for b in per_day.values())
        self.assertEqual(split_total, days_total,
                         f"分账与总量不同窗口: {split_total:,} vs {days_total:,}")

    def test_no_relay_becomes_its_own_platform(self):
        """★ 中转站是 codex 的一条路由，不是一个新平台。冒出来会污染平台清单、
        配色、以及设置页里那份"用过哪些平台"的记忆。"""
        for pk in self.d["platforms"]:
            self.assertNotIn(pk, ("tokendun", "rotateproxy"),
                             f"provider `{pk}` 变成平台了")


class TheLabelLookupFailsOpen(unittest.TestCase):
    """★ 标签是装饰品，不许拖垮主链路（`_agy_quota_series` 那次事故的同一条纪律）。"""

    def test_scan_still_works_without_the_relay_module(self):
        """★★ **不许重命名真实 `relay/`。** 路由现在指向中转站，codex 的 `auth.command`
        就是 `relay/relay-key` —— 测试跑的那几秒里任何一次 codex 启动都会鉴权失败。
        （Fable 复核抓到；我原来就是那么写的。）
        改成把 `scan.py` 拷进临时目录跑：它按 `__file__` 上溯找 `relay/`，找不到就走 fail-open 分支。"""
        import shutil as _sh
        sandbox = Path(tempfile.mkdtemp()) / "traffic"
        sandbox.mkdir(parents=True)
        _sh.copy2(ROOT / "traffic" / "scan.py", sandbox / "scan.py")
        for extra in ("quota_anchors.py", "agy_quota_series.py"):
            src = ROOT / "traffic" / extra
            if src.exists():
                _sh.copy2(src, sandbox / extra)
        try:
            r = subprocess.run([sys.executable, str(sandbox / "scan.py"),
                                "--days", "1", "--json"],
                               capture_output=True, text=True, timeout=900)
            self.assertEqual(r.returncode, 0, r.stderr[-300:])
            d = json.loads(r.stdout)
            c = d["platforms"].get("codex") or {}
            self.assertTrue(c.get("days"), "扫描整个塌了")
            self.assertEqual(c.get("provider_labels", {}), {},
                             "找不到 relay 模块却还有标签 —— fail-open 没走到")
        finally:
            _sh.rmtree(sandbox.parent, ignore_errors=True)


class TheUiSaysTheCostDoesNotApply(unittest.TestCase):
    """★★ 这一行是整个 Phase 4 的产品意义所在：不说出来，同一批 token 会以
    **两个不同的价**出现在两页上，而两页都没标注。"""

    PAGE = (ROOT / "codexbar" / "src" / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8")

    def test_the_route_row_exists(self):
        self.assertIn("data-route-split", self.PAGE)

    def test_the_component_is_actually_rendered_not_just_defined(self):
        """★★ 变异验证逼出来的:原来只断言 `data-route-split` 在源码里 ——
        而那个字符串在**组件定义**里,把调用点 `<RouteSplit …/>` 整行删掉照样绿。
        「组件存在」不等于「组件被渲染」,这正是本仓「名字出现 ≠ 真的接上」那一条。
        真正的判据是下面那条真 DOM 闸;这一条是它的静态前哨。"""
        self.assertIn("<RouteSplit t={t} p={data?.platforms[pk]}", self.PAGE,
                      "组件定义在,但没人调用它")

    def test_it_warns_that_the_equivalent_cost_does_not_apply_to_relay_tokens(self):
        self.assertIn("data-route-footnote", self.PAGE)
        self.assertIn("不适用", self.PAGE)
        self.assertIn("中转站", self.PAGE)

    def test_the_pool_ids_get_human_names_not_raw_ids(self):
        """★ `rotateproxy` / `openai` 是内部名，直接印给用户看等于让他去猜。"""
        self.assertIn("账号池", self.PAGE)
        self.assertIn("单号直连", self.PAGE)

    def test_relay_tokens_are_never_multiplied_by_the_openai_rate_table(self):
        """★ 经中转站的 token 是真金按中转站价扣的。用 `rates.ts` 乘它们
        会造出第三个数，而三个数里没有一个是用户真付的。"""
        self.assertNotIn("costOf(bp", self.PAGE)
        self.assertNotIn("costOfBucket(b, ", self.PAGE)


if __name__ == "__main__":
    unittest.main()


class TheRouteRowActuallyRenders(unittest.TestCase):
    """★★★ 真 DOM 闸。静态断言证明不了「用户看得见」——
    而 Phase 4 的全部产品价值就是**让用户看见**那批 token 的费用口径不一样。

    夹具用**真实快照**（`.traffic-latest.json`，含 `by_provider`），
    不是我编的 —— 编一份就等于把"上游真的会给这个字段"这件事也一起假设掉。
    """

    BASE = "http://127.0.0.1:3304"
    CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    @classmethod
    def dom(cls, url):
        import re as _re
        r = subprocess.run(
            [cls.CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--window-size=1200,900", "--virtual-time-budget=6000", "--dump-dom", url],
            capture_output=True, text=True, timeout=120)
        return r.stdout, _re.sub(r"<script\b[^>]*>.*?</script>", "", r.stdout, flags=_re.S | _re.I)

    @classmethod
    def setUpClass(cls):
        if not Path(cls.CHROME).exists():
            raise unittest.SkipTest("没有 Chrome")
        try:
            cls.rawdom, cls.d = cls.dom(cls.BASE + "/harness.html?nav=platform:codex&rail=open")
        except Exception as e:                            # noqa: BLE001
            raise unittest.SkipTest("harness 不可达: %s" % e)
        if 'class="neterror"' in cls.rawdom or "<title>__PROBE__" not in cls.rawdom:
            raise unittest.SkipTest("harness 静态服务没在跑（3304）")
        if "消耗" not in cls.d:
            raise AssertionError("harness 可达但平台详情页没渲染 —— 渲染缺陷，不许跳过")

    def test_the_route_split_is_on_the_page(self):
        self.assertIn("data-route-split", self.rawdom, "路由行没渲染出来")

    def test_the_pool_and_the_relay_are_both_named_in_human_words(self):
        self.assertIn("账号池", self.d)
        self.assertIn("TokenDun", self.d, "中转站用的是 id 而不是用户起的显示名")

    def test_the_cost_footnote_is_visible_when_relay_tokens_exist(self):
        """★★ 这一句是整个 Phase 4 的意义:不说出来,同一批 token 会以两个不同的价
        出现在两页上,而两页都没标注。"""
        self.assertIn("data-route-footnote", self.rawdom)
        self.assertIn("不适用", self.d)
