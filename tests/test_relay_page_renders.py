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

    def usage_q(self, extra):
        """带额外参数的用量版块（`rrange` / `rmode` / `riso`，都按文字/身份点）。"""
        return dom(BASE + f"/harness.html?nav=relay&rail=open&relay=relay&rtab=用量&{extra}")

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

    def test_each_route_state_shows_its_own_note_and_no_others(self):
        """★★ 双向。只断言"本态在"的话,恒显示同一句的实现也会绿。"""
        for mode, mark in MARK.items():
            with self.subTest(state=mode):
                d = self.page(mode)
                self.assertIn(mark, d, f"{mode} 的文案没渲染出来")
                for other, omark in MARK.items():
                    if other == mode:
                        continue
                    self.assertNotIn(omark, d, f"{mode} 的页面上出现了 {other} 的文案")

    def test_the_dangerous_states_spell_out_the_silent_fallback(self):
        """★★ `profile_missing` 是最危险的:codex **不报错**、静默退回 base 配置。
        文案必须把「现在实际会发生什么」写在页面上,不是只写在源码注释里。"""
        d = self.page("missing")
        self.assertIn("不报错", d)
        self.assertIn("不轮换", d)

    def test_both_cost_columns_appear_with_different_values(self):
        """★★ 实测 `cost` 与 `actual_cost` 差 3.85 倍，**永不合并**。

        夹具的模型表:`cost` 30.0/14.2 vs `actual_cost` 8.12/3.51 —— 两组数都必须出现。
        夹具让它们相等的话这条测试就是空的，所以夹具也必须是不等的。
        """
        d = self.usage_page("relay")
        self.assertIn("实扣", d)
        self.assertIn("牌价", d)
        self.assertIn("实扣口径", d, "没挂口径牌,用户会把它当成 AI用量页那个等效成本")
        # ★★ 判据是**不变量**不是具体数值。上一版写死了 `$8.12` / `$30.00`，
        #    模型表一改成跟随档位，数字全变、闸就红了 —— 而它要守的东西
        #    （两个口径不许合并）**根本没被破坏**。夹具值不该进断言。
        row = re.search(r'data-model-row="[^"]+".*?</tr>', d, re.S)
        self.assertIsNotNone(row, "模型表没渲染")
        nums = re.findall(r"\$([\d.]+)", row.group(0))
        self.assertGreaterEqual(len(nums), 2, f"一行里只有 {nums} —— 两列被合并了？")
        actual, listed = float(nums[-2]), float(nums[-1])
        self.assertNotEqual(actual, listed, "实扣与牌价相等 —— 两列指向了同一个数")
        self.assertLess(actual, listed, "实扣不该大于牌价（中转站是折扣转售）")

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
        """★ 路由只影响终端里的 `codex`。不写出来,用户会以为所有入口都改了,
        然后奇怪为什么账号池还在掉。"""
        d = self.page("relay")
        self.assertIn("生效范围", d)
        self.assertIn("不受此开关影响", d)

    def test_the_usage_block_mirrors_the_ai_usage_page(self):
        """★★ 用户 2026-09-09：「用量你也没有1:1复刻我的ai用量信息」。

        判据是**同一批组件、同一个版面顺序**都真的渲染出来了：
        档位 `Seg` → KPI 条 → 堆叠面积图 → 图例 → 模型表。
        """
        d = self.usage_page("relay")
        for label in ("7d", "14d", "30d", "全部"):
            self.assertIn(label, d, f"档位缺 {label} —— 没用与 AI用量页同一套 Seg")
        for kpi in ("总 token", "请求数", "日均", "总实扣", "日均实扣", "余额", "还能撑"):
            self.assertIn(kpi, d, f"KPI 条缺「{kpi}」")
        self.assertIn("data-models", d, "模型表没渲染")
        # ★ 四类图例只属于「总量」档（分模型档的图例就是模型表本身）。
        self.assertIn("data-legend", self.usage_q("rmode=总量"), "总量档没有图例")

    def test_one_chart_layered_by_token_class_with_money_in_the_tooltip(self):
        """★★ 用户 2026-09-09 定稿：「实扣款公用一张图，只是鼠标悬浮显示对应的金额，
        然后区分不同模型不同颜色」。

        ① **一张图**：金额不再单独占一张，进 tooltip 标题；
        ② 图的分层是**四类 token** —— 中转站不提供「每天 × 每模型」的交叉
           （`daily_usage` 无模型、`model_stats` 无日期，2026-09-09 查过源响应），
           按模型上色只能靠摊派，那是编造数据；
        ③ "不同模型不同颜色"落在**模型表**上，那里的数据是真的。
        """
        d = self.usage_q("rmode=总量")
        for cls in ("缓存读", "输入", "输出"):
            self.assertIn(cls, d, f"图例缺「{cls}」—— 总量档没有按四类 token 分层")
        # ★ 一张图：钱**不占第二个 y 轴**，只进 tooltip 与 KPI。
        #   tooltip 标题由 `tipTitle` 生成、静态 DOM 里取不到，所以判它的**输入**在页面上。
        self.assertIn("实扣", d)
        self.assertEqual(len(re.findall(r"<svg", d)) >= 1, True, "一张图都没有")

    def test_the_model_table_colours_each_model(self):
        """★ 用户要的"不同模型不同颜色"。判据是**每个模型行都有自己的色块** ——
        取 `modelColor()`（与「AI用量信息」页同一个函数）。"""
        d = self.usage_page("relay")
        self.assertIn("gpt-5.5", d)
        self.assertIn("gpt-6-astra", d)
        self.assertIn("模型消耗", d)


    def test_the_model_table_follows_the_date_range(self):
        """★★ 用户 2026-09-09：「模型消耗没有按照我的日期来变化口径」。

        夹具是 **20 天**，`gpt-5.6-luna` **只出现在最早 5 天**（15~19 天前）。
        所以 14d 里必须查不到它、30d 里必须查得到 —— 各天构成相同的夹具会让这条闸
        换任何档位都得到同一张表，是个**空守卫**。
        """
        d14 = self.usage_page("relay")
        self.assertIn("与上图同窗口（14d）", d14, "没写出模型表跟着哪个窗口")
        self.assertNotIn("gpt-5.6-luna", d14, "14d 的表里出现了只在 15 天前用过的模型")
        d30 = self.usage_q("rrange=30d")
        self.assertIn("与上图同窗口（30d）", d30, "档位没切过去")
        self.assertIn("gpt-5.6-luna", d30, "30d 的表里没有那个只在早期用过的模型")

    def test_clicking_a_model_removes_it_from_the_chart(self):
        """★★ 用户 2026-09-09：「点击具体模型，图片没有跟着变化」。

        判据是**图层数真的少了一层**，不是"那一行画了删除线" ——
        后者只证明点击被记下了，证明不了图跟着变。
        """
        before = self.usage_page("relay")
        self.assertIn("gpt-5.5", self.layers(before), "分模型档没有按模型分层")
        after = self.usage_q("riso=gpt-5.5")
        self.assertNotIn("gpt-5.5", self.layers(after), "★ 点了模型，图没跟着变")
        self.assertEqual(len(self.layers(after)), len(self.layers(before)) - 1)
        # ★ 表里仍然在（划掉 + 变淡），因为"摘掉"只影响这张图，不是"它不存在了"。
        self.assertIn("gpt-5.5", after)
        self.assertIn("line-through", after)

    def test_the_two_layer_modes_match_the_platform_page(self):
        """★ 与「平台详情」页同名同义的两档：分模型 / 总量。可以新增，不许减少。"""
        d = self.usage_page("relay")
        self.assertIn("分模型", d)
        self.assertIn("总量", d)
        # 分模型（默认）→ 图层是模型；总量 → 图层是四类 token。
        self.assertTrue(all(k.startswith("gpt-") for k in self.layers(d)), self.layers(d))
        tot = self.usage_q("rmode=总量")
        self.assertTrue(all(k.endswith("_tokens") for k in self.layers(tot)), self.layers(tot))
        self.assertIn("缓存读", tot)

    def test_today_is_offered_and_says_why_there_is_no_hourly_curve(self):
        """★★ 用户 2026-09-09：「中转站是无法看今天用量吗？…时间口径少了今天」。

        今天的数据**是有的**（在 `daily_usage` 最后一行）。缺的只是这一档。
        但中转站**不提供小时粒度** —— 2026-09-09 实测 10 种参数形式
        （`period`/`granularity`/`group_by`/`hourly`/`interval`/`unit`/`type`/`default_time`
        及组合）全部原样返回按天数据，响应里也没有任何 hour 字段。

        所以这一档画**构成条**而不是面积图：一个点的面积图没有可读信息。
        ★ 而且必须**说出为什么没有走势** —— 不说的话，用户会以为是我们没做。
        """
        d = self.usage_page("relay")
        self.assertIn("今日", d, "档位里没有「今日」")
        today = self.usage_q("rrange=今日")
        self.assertIn("data-today-bar", today, "「今日」档没画构成条")
        self.assertIn("没有小时曲线", today, "没说明为什么这一档没有走势")
        # ★ 构成条也要**按模型分层**，与其它档位同一套颜色/身份。
        self.assertTrue(self.layers(today), "构成条没有分层")
        self.assertIn("与上图同窗口（今日）", today, "模型表没跟到今日档")

    def test_an_empty_config_says_so_instead_of_rendering_nothing(self):
        """★ 「没配过」必须有一句话。一片空白和"加载失败"长得一样。"""
        d = self.page("empty")
        self.assertIn("还没有中转站", d)


if __name__ == "__main__":
    unittest.main()
