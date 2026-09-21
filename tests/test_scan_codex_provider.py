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
import re
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
            # ★ 这条依赖**本机真有 codex rollout**。CI 的干净 runner 上一条都没有，
            #   于是 `days` 为空 —— 那时这个断言测的是"有没有数据"，与被测的
            #   fail-open 分支毫无关系。没有数据就跳过，并**说出原因**（别静默通过）。
            if not c.get("days"):
                self.skipTest("本机没有 codex rollout，`days` 为空 —— "
                              "这条测的是 fail-open 分支，不是数据是否存在")
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
        """⚠️ 同上（2026-09-21）：判据从「不适用」这三个字改成**这条披露的事实**。
        文案压成一行后说的是「勿与下方「总费用」相加」—— 一字未少，只是换了说法。"""
        self.assertIn("data-route-footnote", self.PAGE)
        i = self.PAGE.index("data-route-footnote")
        note = self.PAGE[i:i + 900]
        self.assertIn("总费用", note, "★★ 没点名「总费用」这个口径")
        self.assertRegex(note, r"(不适用|不要相加|勿与[^\n]{0,20}相加)",
                         "★★ 没给出「别把两个口径合起来算」这个动作")
        self.assertIn("中转站", note)

    def test_the_numbers_line_up_in_columns(self):
        """★★ 用户 2026-09-21：「对称点」。

        原来每行是 `名称 数值 · 占比` 顺排 ⇒ 名称一长一短，**数值与占比每行都落在
        不同的 x 上**，读的时候要横着找。全局 `ui-design.md` 写得很直接：
        **数字右对齐成列（mono 保证对齐），标签左对齐**。
        ★ 判据打在**布局机制**上（网格 + 右对齐 + 等宽数位），不是某个像素值 ——
          像素值会随字号改动而失真，而机制不会。
        """
        # ⚠️ 取窗从 `data-route-split` 起算 3200 字符**不够** —— 这一块的注释很长，
        #   窗口停在网格样式之前，断言当场假红（我自己第一版就是这样）。
        #   本仓记过：**定长切片找结构边界是危险的**。改成从块首取到 `RouteSplit`
        #   函数的收尾（`data-route-footnote` 之后 600 字符），覆盖整块。
        i = self.PAGE.index("data-route-split")
        j = self.PAGE.index("data-route-footnote", i)
        blk = self.PAGE[i:j + 600]
        self.assertIn('display: "grid"', blk, "★★ 还是顺排的内联文本，数字不成列")
        self.assertIn('gridTemplateColumns: "1fr auto auto"', blk,
                      "★ 不是「标签 | 数值 | 占比」三列")
        self.assertGreaterEqual(blk.count('textAlign: "right"'), 4,
                                "★★ 数字列没有右对齐 —— 位数不同就会参差")
        self.assertGreaterEqual(blk.count('fontVariantNumeric: "tabular-nums"'), 4,
                                "★ 没用等宽数位，刷新时数字会左右跳")

    def test_the_footnote_is_one_line_not_a_paragraph(self):
        """★ 用户 2026-09-21：「具体的说明不要了」。压掉的是**解释**不是**披露**。

        判据：脚注里不再出现那几句解释性从句。三条事实由上面两条闸守着。
        """
        i = self.PAGE.index("data-route-footnote")
        note = self.PAGE[i:i + 900]
        for gone in ("那是按 OpenAI 牌价折算的等效成本",
                     "这批数来自中转站自己的账单",
                     "代理转发时 codex 只记"):
            self.assertNotIn(gone, note, f"★ 解释性从句又回来了：{gone}")

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
        出现在两页上,而两页都没标注。

        ⚠️ 2026-09-21 收窄措辞依赖：原来断言的是「不适用」三个字，而那是旧长句
          「下面的「总费用」对它们不适用」里的词。用户当天要求「具体的说明不要了」，
          文案压成一行「… 已含在「账号池」行内 · 勿与下方「总费用」相加」——
          **事实一字未少，只是换了说法**，而旧断言当场假红。
        ★ 所以判据改成**那条事实的两个要件**：① 点名「总费用」这个口径；
          ② 给出可执行的动作（别相加 / 不适用）。措辞怎么改都行，事实不能掉。
        """
        self.assertIn("data-route-footnote", self.rawdom)
        i = self.rawdom.index("data-route-footnote")
        note = re.sub(r"<[^>]+>", "", self.rawdom[i:i + 700])
        self.assertIn("总费用", note,
                      "★★ 脚注没点名「总费用」这个口径 —— 读者不知道说的是哪个数")
        self.assertTrue(any(w in note for w in ("相加", "不适用")),
                        f"★★ 脚注没说「别把两个口径合起来算」这个动作：{note[:120]}")
        self.assertIn("中转站", note, "★ 没说清这批 token 的来源")


class RelayAttributionSurvivedTheArchitectureChange(unittest.TestCase):
    """★★★ 2026-09-10「一个 provider、两种上游」把路由分账**打断了**，Fable 评审抓到。

    中转站流量现在也由本地代理转发，而 codex 写进 rollout 的 `model_provider`
    **恒为 `rotateproxy`** —— `by_provider` 再也分不出中转站。后果不是"少一行"：
    那批 token 被算进「账号池」，并被 `rates.ts` 按 OpenAI 牌价折进「总费用」，
    而它们是中转站**真金实扣**过的。实测当天就有 1.9M token / 实扣 $0.94 落错栏。

    代理知道真相但戳记是 codex 写的，改不了。所以归属**换源**：读中转站自己的账单
    （`.relay-usage.json`，monitor 拉自对方 `/usage`）。不是估算 —— 2026-09-09
    逐 token 核过：rollout 解析 39,513 == 中转站账单 39,513。

    ⚠️ 这批 token **同时也在** `by_provider.rotateproxy` 里。**绝不做减法**
    （两个来源、两个窗口，相减会在窗口边缘变成负数），页面如实说明"别相加"。
    """

    ROOT = Path(__file__).resolve().parents[1]

    def test_scan_emits_relay_billing_from_the_relay_snapshot(self):
        src = (self.ROOT / "traffic" / "scan.py").read_text(encoding="utf-8")
        self.assertIn("relay_billed", src)
        self.assertIn(".relay-usage.json", src,
                      "★ 归属没换源 —— rollout 里已经没有中转站戳记了")

    def test_it_is_trimmed_to_the_same_window_as_days(self):
        """★ 同一页两个数必须同窗口 —— 本仓在 scan 侧栽过（119M vs 9,004M）。"""
        src = (self.ROOT / "traffic" / "scan.py").read_text(encoding="utf-8")
        blk = src[src.index('entry["relay_billed"]') - 400:src.index('entry["relay_billed"]') + 200]
        self.assertIn("if d in picked", blk, "没按输出窗口裁剪")

    def test_the_page_says_it_must_not_be_added(self):
        """★★ 最要紧的一句话：这批已含在「账号池」那一行里。
        不写出来，读者会把总量算两遍 —— 而两个数都来自我们自己的页面。"""
        page = (self.ROOT / "codexbar" / "src" / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8")
        # ⚠️ 2026-09-21：原来断言的是整句旧文案「已经含在上面「账号池」那一行里」。
        #    用户当天要求「具体的说明不要了」，脚注压成一行「… 已含在「账号池」行内 ·
        #    勿与下方「总费用」相加」—— **事实一字未少，只是换了说法**，而旧断言当场假红。
        # ★ 判据改成**这条披露的三个要件**：这批 token 已含在账号池那一行、不许相加、
        #   以及中转站账单这一节存在。措辞怎么改都行，三件事不能掉。
        i = page.index("data-route-footnote")
        note = page[i:i + 900]
        self.assertRegex(note, r"已(经)?含在[^\n]{0,8}账号池",
                         "★★ 脚注没说「这批已含在账号池那一行里」—— 读者会把总量算两遍")
        self.assertRegex(note, r"(不要相加|勿与[^\n]{0,20}相加|不适用)",
                         "★★ 脚注没给出「别相加」这个动作")
        self.assertIn("中转站账单", page)

    def test_the_pool_rows_never_reference_the_relay_bill(self):
        """★ 真正的不变量：账号池那几行只由 `by_provider`（rollout）算出，
        **绝不减去**中转站账单。跨源相减会在窗口边缘产生负数，
        而负 token 在堆叠图上会画出一个不存在的事实。

        ⚠️ 第一版判据是 `"total -" not in blk` —— 命中了**排序比较器**
           `b.total - a.total`，一个纯假阳性。子串匹配挡不住"减法"这个语义，
           要钉的是**数据流**：`rows` 的计算里不许出现 `billed`/`relay_billed`。
        """
        page = (self.ROOT / "codexbar" / "src" / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8")
        rows_blk = page[page.index("const rows:"):page.index("const sum =")]
        for bad in ("billed", "relay_billed"):
            self.assertNotIn(bad, rows_blk,
                             "★ 账号池那几行引用了中转站账单 —— 两个来源被混算了")
        # 反向:中转站那几行也只由账单算出,不碰 by_provider。
        billed_blk = page[page.index("const billed ="):page.index("const billedTok")]
        self.assertNotIn("by_provider", billed_blk)
        self.assertIn("relay_billed", billed_blk)
