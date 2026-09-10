"""★★ 行为闸：中转站的六个路由态**真的渲染出来了**。

2026-09-09 起中转站不再是独立页 —— 选号/增删在「总览」(`RelaySection`)，
金额在「AI用量信息」(`RelayCost`)。`?nav=relay` 保留为总览的别名。

静态断言（源码里有那个字符串）证明不了「用户看得见」—— 而"看不见"正是这一页
最要紧的失败模式：`relayRouteNote` 漏一个 case 就返回 `undefined`，
路由卡**整块不渲染**，而"卡片没了"和"一切正常"在截图里长得一模一样。

## 双向断言，缺一半就等于没测

每个态断言 **本态的标记词在 DOM 里，且另外五个都不在**。
只做前一半的话，一个"恒显示同一句"的实现照样全绿。

## 跳过的纪律（本仓栽过）

「服务没起来」和「页面渲染不出东西」必须分开：
后者是**渲染缺陷不是环境问题**，跳过它等于把真缺陷当环境问题放走。
判据：Chrome 拿不到页面时渲染自己的错误页（`class="neterror"`）。
"""
import os
import re
import shutil
import subprocess
import unittest

BASE = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 每个态**只属于它**的标记词。取自 `relay.ts::relayRouteNote` 的 title/body。
MARK = {
    "pool": "走账号池",
    "relay": "走中转站",
    "missing": "rotateproxy.config.toml 不存在",
    "offroute": "已停用，但路由还指着它",
    "orphan": "路由指向一个已删除的中转站",
    "corrupt": "路由文件损坏",
}


SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)


def dom(url, size="1200,900"):
    """★★ **必须剥掉 `<script>` 再断言。**

    harness 把夹具和探针**内联**进 HTML，而 `--dump-dom` 会把 `<script>` 的内容
    原样吐出来。直接在原始 DOM 上断言"另外五个态的文案不在"，会被**夹具里的字符串**
    命中 —— 于是双向断言的后一半永远失败，而它失败的原因和"实现真的画错了"
    看起来一模一样。我第一版就是这么被误导的。

    也不能用探针的 `text` 字段：它是 `innerText.slice(0, 700)`，
    我们要断言的模型表在 700 字之后。
    """
    if not shutil.which(CHROME) and not os.path.exists(CHROME):
        raise RuntimeError("没有 Chrome")
    r = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--window-size={size}", "--virtual-time-budget=6000", "--dump-dom", url],
        capture_output=True, text=True, timeout=120)
    return SCRIPT_RE.sub("", r.stdout)


def raw(url, size="1200,900"):
    """不剥脚本的原始 DOM —— 只用来判「服务是否可达 / 探针是否跑过」。"""
    r = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--window-size={size}", "--virtual-time-budget=6000", "--dump-dom", url],
        capture_output=True, text=True, timeout=120)
    return r.stdout


class RelayPageRenders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.raw = raw(BASE + "/harness.html?nav=relay&rail=open&relay=relay")
            cls.probe = SCRIPT_RE.sub("", cls.raw)
        except Exception as e:                       # noqa: BLE001
            raise unittest.SkipTest("harness 不可达: %s" % e)
        if 'class="neterror"' in cls.raw or "<title>__PROBE__" not in cls.raw:
            raise unittest.SkipTest(
                "harness 静态服务没在跑（devport codexbar 的 3304），跳过行为闸")
        # ★ 到这里说明服务是好的。再拿不到页面内容,就是**渲染缺陷**,不许跳过。
        if "中转站" not in cls.probe:
            raise AssertionError(
                "harness 可达、探针也在，但 DOM 里没有「中转站」标题 —— "
                "这是渲染缺陷不是环境问题，不许跳过")

    def page(self, mode):
        """「总览」—— 路由选择与中转站增删在这里。"""
        return dom(BASE + f"/harness.html?nav=relay&rail=open&relay={mode}")

    def layers(self, d):
        """图里**真有几层**。★ 只看图例/表格证明不了"图跟着变了" ——
        隔离一个模型时表还在（划掉），只有图才该少一条带。"""
        return re.findall(r'data-layer="([^"]+)"', d)

    def usage_page(self, mode):
        """中转站页的**「用量」版块**（页内两块之一，用户 2026-09-09：
        「ui里面有两个版块切换啊。一个是账号，一个是用量」）。

        ★ 走 `?rtab=用量` 真点一次，而不是靠"两块都在 DOM 里"蒙混 ——
          隐藏的那块也会进 `--dump-dom`，不点就等于没验"用户看得见"。
        """
        return dom(BASE + f"/harness.html?nav=relay&rail=open&relay={mode}&rtab=用量")

    def usage_q(self, extra, mode="relay"):
        """带额外参数的用量版块（`rrange` / `rmode` / `riso`，都按文字/身份点）。

        ★ 夹具走 `mode=` 形参，**不能**在 `extra` 里再写一个 `relay=`：
          `URLSearchParams.get` 取的是**第一个**值，重复的同名参数会被静默丢掉。
          实测踩过：`extra="relay=sparse&rrange=7d"` 实际跑的仍是稠密夹具，
          而"轴上 7 个日期"那条断言在两份夹具下**都绿** —— 闸看着通过，其实没测到。
        """
        return dom(BASE + f"/harness.html?nav=relay&rail=open&relay={mode}&rtab=用量&{extra}")

    def test_the_nav_click_actually_landed_on_this_page(self):
        """★ 先证导航真的点到了这一页。侧栏原来是**按位置**点的，插入/删除页都会静默点错 ——
        而"点错页"和"这一页没渲染"在 DOM 断言里长得一样。

        ★★ 中转站是**独立版块**（用户 2026-09-09 定稿：「新增一个版块放中转站的内容信息，
        而不是共用版块」）。一度并进总览+用量两页，被否。
        """
        self.assertIn('data-page="relay"', self.raw,
                      "侧栏里没有「中转站」项 —— nav 点错了,或 bundle 是旧的")
        self.assertIn('data-page-body="relay"', self.raw,
                      "点到了但页面没渲染 —— 这是渲染缺陷,不是导航问题")
        self.assertIn('data-section="relay"', self.raw, "「账号」版块没渲染")
        self.assertIn("data-relay-tabs", self.raw,
                      "页内没有「账号 / 用量」两块的切换器")

    # 健康的两态。设计稿把"现在走哪个出口"交给了出口卡（`在用` 角标 + `✓ 当前`），
    # 所以它们**不再**渲染文字提示 —— 常亮的告警会被训练成噪音。
    HEALTHY = {"pool", "relay"}

    def test_each_abnormal_route_state_shows_its_own_note_and_no_others(self):
        """★★ 双向。只断言"本态在"的话，恒显示同一句的实现也会绿。

        ⚠️ 2026-09-10 改版：健康的 `pool`/`relay` 两态不再出文字（见 `HEALTHY`），
           所以它们从这条闸移到下面 `test_the_healthy_states_are_shown_on_the_card`。
           **四个异常态一个都不能少** —— 它们是静默失败唯一会出声的地方。
        """
        for mode, mark in MARK.items():
            if mode in self.HEALTHY:
                continue
            with self.subTest(state=mode):
                d = self.page(mode)
                self.assertIn(mark, d, f"{mode} 的文案没渲染出来")
                for other, omark in MARK.items():
                    if other == mode:
                        continue
                    self.assertNotIn(omark, d, f"{mode} 的页面上出现了 {other} 的文案")

    def test_the_healthy_states_are_shown_on_the_card_not_as_a_warning(self):
        """★★ 健康态的"现在走哪个出口"由**出口卡**回答，而且必须回答得出来。

        判据两条，缺一不可：
        ① 对应那张卡有 `data-outlet-active` —— 否则用户根本看不出走的是哪个；
        ② 页面上**没有**任何异常态的文案 —— 健康时弹告警比不弹更糟。
        """
        for mode in sorted(self.HEALTHY):
            with self.subTest(state=mode):
                d = self.page(mode)
                m = re.search(r'data-outlet="(\w+)" data-outlet-active="1"', d)
                self.assertIsNotNone(m, f"{mode}：没有任何一张出口卡标成「在用」")
                self.assertEqual(m.group(1), mode, f"{mode}：标成在用的是 {m.group(1)}")
                self.assertIn("在用", d)
                for other, omark in MARK.items():
                    if other in self.HEALTHY:
                        continue
                    self.assertNotIn(omark, d, f"{mode}（健康）却显示了 {other} 的告警")

    def test_the_dangerous_states_spell_out_the_silent_fallback(self):
        """★★ `profile_missing` 是最危险的:codex **不报错**、静默退回 base 配置。
        文案必须把「现在实际会发生什么」写在页面上,不是只写在源码注释里。"""
        d = self.page("missing")
        self.assertIn("不报错", d)
        self.assertIn("不轮换", d)

    def test_the_page_shows_the_charged_amount_never_the_list_price(self):
        """★★★ `cost`（牌价）与 `actual_cost`（真实扣款）实测差 3.85 倍，**永不混用**。

        ⚠️ 原契约是「两列并排、各自标注」。设计稿去掉了牌价那一列 —— 于是风险从
           「两个数被合并」变成了「**剩下的那一个其实是牌价**」，而页面上再没有
           第二个数可以对照。所以判据换成**值本身**：

        夹具的 `today.cost = 0.36`、`today.actual_cost = 0.0863`（差 4.2 倍，
        夹具让它们相等的话这条闸就是空的）。出口卡上的「今日实扣」必须是后者。
        """
        d = self.page("relay")
        self.assertIn("实扣", d)
        self.assertIn("$0.0863", d, "★★ 「今日实扣」印的是牌价不是实扣款")
        self.assertNotIn("$0.36", d, "★★ 牌价出现在了页面上，而它没有任何标注")
        # 用量块必须挂口径牌 —— 否则用户会把它当成 AI用量页那个「等效成本」。
        u = self.usage_page("relay")
        self.assertIn("实扣口径", u, "没挂口径牌")
        self.assertNotIn("牌价", u, "牌价那一列已按设计稿去掉，它又回来了")

    def test_unknown_money_renders_as_a_dash_not_zero(self):
        """★★ 「读不到」和「真的是 0」用户的下一步动作完全相反。
        `?relay=never` 的夹具把 balance / today 全设成 null。"""
        d = self.usage_page("never")
        self.assertIn("—", d)
        self.assertIn("活跃日样本不足", d, "runway 读不到时没说出原因")
        self.assertNotIn("$0.00", d, "★ 读不到被画成了 0 —— 两者的下一步动作完全相反")

    def test_a_failing_relay_reports_its_state_instead_of_showing_zeros(self):
        for mode, needle in (("unreachable", "unreachable"), ("auth", "auth"),
                             ("nobill", "no_billing_endpoint")):
            with self.subTest(mode=mode):
                d = self.usage_page(mode)
                self.assertIn("用量读不到", d)
                self.assertIn(needle, d)

    def test_the_key_is_never_rendered_in_full(self):
        """★★ 夹具里**故意放了一个完整的诱饵 key**（`sk-DECOY-…`）。

        没有诱饵的话这条断言永远红不了 —— 它是个**空守卫**：
        "页面里没有完整 key"在一个根本不含完整 key 的夹具上恒成立。
        Fable 复核抓到的。"""
        d = self.page("relay")
        self.assertIn("0f39111c7caf", d, "指纹没渲染")
        self.assertNotIn("sk-DECOY", d, "★ 把完整 key 渲染到页面上了")

    def test_a_disabled_relay_is_not_shown_as_a_failure(self):
        """★ 停用是**用户的选择**,不是故障。原来渲染成
        "用量读不到（disabled）：undefined" —— 把选择说成故障,还带个 undefined。"""
        d = self.usage_page("disabled")
        self.assertIn("已停用", d)
        self.assertNotIn("用量读不到", d)
        self.assertNotIn("undefined", d)

    def test_the_scope_of_the_switch_is_on_the_page(self):
        """★★ 生效范围必须**两侧都点名**，且判据打在**渲染出来的文字**上。

        ⚠️ 这条原来是 `assertIn("不受此选择影响", d)` —— 只查"有一句排除说明存在"，
           不查**谁在哪一侧**。VS Code 从"不生效"被挪到"生效"侧那次改动，
           这条和它在 `test_relay_route_copy.py` 里的兄弟**双双全绿**。
           两份实现同一条规则，所以同时错。

        这一份有 DOM，所以它比源码级那份更强：JSX 注释根本不会出现在这里，
        不需要先剥注释。
        """
        d = self.page("relay")
        self.assertIn("生效范围", d)
        seg = d[d.index("生效范围"):][:400]
        self.assertIn("不生效", seg, "只说了生效的那半")
        self.assertLess(seg.index("不生效"), seg.index("VS Code"),
                        f"★ VS Code 落在「生效」那一侧: {seg[:200]}")
        self.assertIn("cxd", seg, "逃生口没写出来")

    def test_the_usage_block_has_the_three_parts_the_design_specifies(self):
        """★★ 设计稿 §4 的三段：工具行 → KPI 条 → 模型小图阵。

        ⚠️ 这条闸原名 `..._mirrors_the_ai_usage_page`，判的是"与 AI用量页同一批组件"
           （堆叠面积图 + 图例 + 模型表）—— 那是用户 2026-09-09 的要求。
           2026-09-10 的设计稿**改了这个决定**（改成每模型一张小图卡），
           所以旧契约是**被取代**，不是被违反。留档在这里，免得下一个人照旧文档去"修复"。
        """
        d = self.usage_page("relay")
        for label in ("今日", "7d", "14d", "30d"):
            self.assertIn(label, d, f"档位缺 {label}")
        # ★ 不能直接 `assertNotIn("全部", d)`：按站筛选里有「全部站」，子串会撞车
        #   （本仓空守卫形态①：子串存在 ≠ 规则存在）。按**档位的完整文本节点**判。
        self.assertNotIn(">全部<", d, "★ 设计稿去掉了「全部」档，它又回来了")
        for kpi in ("总 token", "请求数", "日均", "模型数", "总实扣", "余额 · 还能撑"):
            self.assertIn(kpi, d, f"KPI 条缺「{kpi}」")
        self.assertIn("data-kpi-bar", d, "KPI 条没渲染")
        self.assertIn("data-model-grid", d, "模型小图阵没渲染")
        self.assertIn("data-model-card", d, "一张模型卡都没有")
    def test_each_model_card_carries_its_own_numbers(self):
        """★★ 每张卡自带：占比 / token / 轮数 / 峰值 / 实扣 / 走势线（设计稿 §4）。

        ⚠️ 原契约是「一张堆叠图 + 钱在 hover 里」（用户 2026-09-09 定稿）。
           设计稿改成每模型一张卡之后，钱不再藏在 hover 里而是印在卡上 ——
           **更容易看见，不是更少**。旧闸留档见上一条。
        """
        d = self.usage_page("relay")
        card = d[d.index("data-model-card"):]
        card = card[:card.index("data-model-card", 10)] if card.count("data-model-card") > 1 else card[:2500]
        for piece in ("轮", "峰 ", "实扣", "<svg", "<path"):
            self.assertIn(piece, card, f"卡上缺「{piece}」")
        # ★ 走势线必须是**真路径**，不是一个空的 `d=""` —— 后者渲染出来是一张白卡。
        paths = re.findall(r'<path data-spark="[^"]*" d="(M[^"]+)"', card)
        self.assertTrue(paths, "卡上没有走势线路径")
        self.assertGreater(len(paths[0]), 20, f"走势线是空的: {paths[0]}")
    def test_each_model_card_gets_its_own_colour(self):
        """★ 同一个模型在本 app 各页**同色**（`modelColor()` 是唯一来源）。
        卡的色块、走势线 stroke、底部胶囊条必须是同一个颜色 —— 三处不一致时
        用户会以为它们是三个不同的东西。"""
        d = self.usage_page("relay")
        self.assertIn("gpt-5.5", d)
        self.assertIn("gpt-6-astra", d)
        cards = re.findall(r'data-model-card="([^"]+)"', d)
        self.assertGreaterEqual(len(cards), 2, f"卡片数不对: {cards}")
        colours = set(re.findall(r'stroke="(#[0-9a-fA-F]{6})"', d))
        self.assertGreaterEqual(len(colours), 2,
                                f"★ 两个模型用了同一个颜色: {colours}")
    def test_the_model_cards_follow_the_date_range(self):
        """★★ 用户 2026-09-09：「模型消耗没有按照我的日期来变化口径」。

        夹具是 **20 天**，`gpt-5.6-luna` **只出现在最早 5 天**（15~19 天前）。
        所以 14d 里必须查不到它、30d 里必须查得到 —— 各天构成相同的夹具会让这条闸
        换任何档位都得到同一批卡，是个**空守卫**。

        ★ 判据同时打在 `data-model-window` 上：那是卡阵**自己声明**的窗口，
          比"页面上某处出现了 14d"强 —— 档位 Seg 上本来就一直印着所有档位。
        """
        d14 = self.usage_page("relay")
        self.assertIn('data-model-window="14"', d14, "卡阵没声明它的窗口")
        self.assertNotIn("gpt-5.6-luna", d14, "14d 里出现了只在 15 天前用过的模型")
        d30 = self.usage_q("rrange=30d")
        self.assertIn('data-model-window="30"', d30, "档位没切过去")
        self.assertIn("gpt-5.6-luna", d30, "30d 里没有那个只在早期用过的模型")
    def test_clicking_a_card_focuses_it_and_dims_the_rest(self):
        """★★ 设计稿 §5：点卡片 = 聚焦（该卡描边变模型色，其余 opacity .35），再点取消。

        ⚠️ 原契约是「点模型行 = 从图里摘掉」（用户 2026-09-09）。设计稿改成聚焦 ——
           两者的差别是**减法 vs 强调**：摘除会改变图的构成，聚焦不改任何数字。
           判据打在 `data-model-focused` + 其余卡的 opacity 上，不是"那一行画了删除线"。
        """
        before = self.usage_page("relay")
        self.assertNotIn("data-model-focused", before, "还没点就已经有聚焦态")
        after = dom(BASE + "/harness.html?nav=relay&rail=open&relay=relay"
                           "&rtab=用量&rcard=gpt-5.5")
        self.assertIn('data-model-focused="1"', after, "★ 点了卡片，没有进入聚焦态")
        focused = re.findall(r'data-model-card="([^"]+)" data-model-focused', after)
        self.assertEqual(focused, ["gpt-5.5"], f"聚焦的不是被点的那张: {focused}")
        # ★ 其余卡必须**真的变暗** —— 只给被点的加描边证明不了"其余变暗"。
        self.assertIn("opacity:0.35", after.replace(" ", ""),
                      "★ 其余卡没有变暗，聚焦只做了一半")
    def test_the_layer_mode_toggle_is_gone_by_design(self):
        """★ 「分模型 / 总量」两档已被设计稿取消（2026-09-10）。

        留这条闸不是为了守住"没有"，而是为了**留下取消的记录**：
        下一个人看到「平台详情」页有这两档、中转站没有，会以为是漏做。
        四类 token 的分解仍然在数据里（`view.cls`），只是这一页不再画它 ——
        它回答的是"构成"，而这一页问的是"哪个模型在烧钱"。
        """
        d = self.usage_page("relay")
        self.assertNotIn("data-legend", d, "四类图例回来了 —— 设计稿里没有它")
        self.assertNotIn("data-layer=", d, "堆叠图层回来了")
    def test_today_is_offered_and_says_why_there_is_no_hourly_curve(self):
        """★★ 用户 2026-09-09：「中转站是无法看今天用量吗？…时间口径少了今天」。

        今天的数据**是有的**（在 `daily_usage` 最后一行）。缺的只是**小时粒度** ——
        2026-09-09 实测 10 种参数形式（`period`/`granularity`/`group_by`/`hourly`/
        `interval`/`unit`/`type`/`default_time` 及组合）全部原样返回按天数据。

        ★ 必须**说出为什么没有走势** —— 不说的话用户会以为是我们没做。
          设计稿没写这句话（它的样例是 14d），但那是一条实测出来的事实，不能因为
          稿里没有就删掉。
        """
        d = self.usage_page("relay")
        self.assertIn("今日", d, "档位里没有「今日」")
        today = self.usage_q("rrange=今日")
        self.assertIn('data-model-window="today"', today, "档位没切到今日")
        self.assertIn("data-today-note", today, "「今日」档没解释为什么没有走势")
        self.assertIn("不提供小时曲线", today)
        # ★ 今日档仍要出卡 —— 「没有小时曲线」不等于「没有数据」。
        self.assertIn("data-model-card", today, "今日档一张卡都没有")
    def test_the_window_is_calendar_days_not_days_with_data(self):
        """★★★ 档位必须按**自然日**切，不是"最近 N 个有数据的日期"（Fable 评审抓到）。

        中转站的 `daily` 只含有请求的日子。按"有数据的天"截，7d 档实测跨了 **23 个
        自然日**、页面却标「7d」，而 `日均 = 总量 ÷ 7` 虚高 **3.3×**。
        这与 CLAUDE.md 对 `scan.py` 判过死刑的是同一类错，而这一页自称与
        「AI用量信息」1:1 —— 那边一直是自然日口径。

        ⚠️ **必须用稀疏夹具**（`?relay=sparse`：只有 5 天有数据，散布在 24 个自然日里）。
           稠密夹具下两种实现结果**完全一样**，闸换任何档位都绿 —— 空守卫。
        """
        d = self.usage_q("rrange=7d", mode="sparse")
        # ★ 轴标签随堆叠图一起没了（设计稿改成小图卡）。新锚点是**走势线的点数** ——
        #   Catmull-Rom 路径里每两点之间一段 `C`，所以 `C` 的个数 = 天数 - 1。
        #   这比"页面上出现了 7d"强得多：档位 Seg 上本来就一直印着所有档位。
        path = re.search(r'<path data-spark="[^"]*" d="(M[^"]+)"', d)
        self.assertIsNotNone(path, "没有走势线 —— 探针坏了，不是窗口错了")
        pts = path.group(1).count("C") + 1
        self.assertEqual(pts, 7,
                         f"7d 档的走势线有 {pts} 个点 —— 不是 7 个自然日")
        # 日均 = 窗口总量 ÷ **自然日数**。夹具每个有数据的日子恰好 1,000,000 token，
        # 7d 窗口里有 2 天（今天 / 2 天前）⇒ 2M ÷ 7 = 285.7K，而按"有数据的天"是 1M。
        self.assertIn("285.7K", d, "★ 日均用了「有数据的天」当分母 —— 会虚高数倍")
        self.assertNotIn("日均 1M", d)
        # ★ 反向：稠密夹具（每天都有数据）下 7d 也必须是 7 个点，别把修法做成"永远补零到 7"
        #   之外的什么东西。
        dense = re.search(r'<path data-spark="[^"]*" d="(M[^"]+)"', self.usage_q("rrange=7d"))
        self.assertIsNotNone(dense)
        self.assertEqual(dense.group(1).count("C") + 1, 7)

    def test_the_previous_window_must_be_equal_length_and_fully_observed(self):
        """★★★ 环比的上一窗口必须**等长、不与当前窗口重叠、且整段可观测**。

        原实现 `slice(Math.max(0, len-2n), len-n)` 有两个洞：`len-n` 为负时 JS `slice`
        把负数 end 当**从尾部倒数** ⇒ "上一窗口"落在当前窗口**内部**（总量和自己的
        子集比）；且没有等长校验 ⇒ 1 天可以冒充 7 天的上期。
        实测本机真快照：7d 档「环比 ↑148757.6%」、14d 档「↑87.7%」，
        而注释一直承诺"样本不够就说 —"。

        补零之后还有第三种：某天没有行 = **观测过、当天为 0**，还是**根本没观测过**？
        后者不能入分母 —— 拿没观测过的日子当 0 去比，涨幅是凭空的。
        """
        # ★★ 判据档位必须选**部分重叠**的那一档，不能随手挑一档。
        #    30d 档看着也是「—」，但那是被 `mk()` 的 `if (!before) return null` 兜住的
        #    （上期一条数据都没有），**根本没走到**这条守卫 —— 拿它当判据是空守卫，
        #    实测：删掉守卫后 30d 档照样绿。
        #    稀疏夹具有数据的日子是 今天 / 2 / 9 / 16 / 23 天前，
        #    14d 档的上期（14~27 天前）里恰好只有「23 天前」那一天被观测过 ⇒ 部分重叠，
        #    正是守卫要挡的形状。删掉守卫会拿 1M 当 14 天的上期，算出 ↑200%。
        # ★ 判据打在 `data-delta` 上，不是文案：设计稿的环比是**裸的** `↑4.4%`
        #   （没有"环比"两个字），而未知时只能写「环比 —」—— 两种措辞下没有稳定的
        #   文字锚点，而 `↑` 这个字符页面别处也会出现。
        d14 = self.usage_q("rrange=14d", mode="sparse")
        self.assertIn('data-delta="none"', d14,
                      "★ 上一窗口只有 1/14 天被观测过，却拿它当整段基数比 —— 涨幅是凭空的")
        self.assertIn("环比 —", d14, "「不可比」必须**说出来**，不能只是不显示")
        # 反向：7d 档的上期（7~13 天前）整段落在观测范围内且有数据 ⇒ 必须给真数，
        # 否则"修法"退化成了永远显「—」，那同样是假的。
        d7 = self.usage_q("rrange=7d", mode="sparse")
        self.assertRegex(d7, r'data-delta="(up|down)"',
                         "★ 上期可观测却拒绝比较 —— 修法退化成了永远显 —")

    def test_money_kpis_refuse_to_add_across_currencies(self):
        """★★★ 一家 USD、一家 CNY 时，「总实扣 / 日均实扣 / 余额」不许给一个数。

        原实现把所有中转站的钱直接相加、币种取**第一家**的 —— 得到的数
        不属于任何一种货币，而它长得和一个正常金额一模一样。

        ⚠️ **必须用 `?relay=mixed`**：单家夹具下"相加"与"不相加"结果完全相同，
           这条闸在别的夹具上恒绿。
        """
        d = self.usage_q("rrange=30d", mode="mixed")
        self.assertIn("多币种，不可相加", d,
                      "★ 混币时没说出来 —— 用户会把那个数当成真金额")
        # ★ 双向：既要有那句话，也要**那几个金额真的变成了 `—`**。
        #   只判提示语的话，一个"提示照显、数照加"的实现同样全绿。
        seg = d[d.index("总实扣"):]
        seg = seg[:400]
        self.assertNotIn("$", seg,
                         f"★★ 混币时仍然打出了带币种的金额: {seg[:200]}")
        self.assertIn("—", seg)

    def test_a_single_currency_still_shows_the_money(self):
        """★ 反向闸：只有一家（或全同币种）时必须照常给数 ——
        否则"修法"退化成"永远不显示金额"，那同样是错的。"""
        d = self.usage_q("rrange=30d")
        self.assertNotIn("多币种，不可相加", d)
        seg = d[d.index("总实扣"):][:400]
        self.assertIn("$", seg, f"★ 单币种下金额消失了: {seg[:200]}")

    def test_an_empty_config_says_so_instead_of_rendering_nothing(self):
        """★ 「没配过」必须有一句话。一片空白和"加载失败"长得一样。"""
        d = self.page("empty")
        self.assertIn("还没有中转站", d)


if __name__ == "__main__":
    unittest.main()
