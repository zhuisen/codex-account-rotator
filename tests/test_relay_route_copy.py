"""路由状态的**三方一致**：Python 真源 / TS 类型联合 / switch 分支。

## 为什么必须三方比对，而不是各写各的

`route_status()` 每加一个状态，前端有两个地方要跟：类型联合、`relayRouteNote` 的 switch。
漏掉任何一个的后果都是**静默的**：
  · 漏类型 ⇒ TS 报错（这个还算会响）；
  · 漏 switch ⇒ `relayRouteNote` 返回 `undefined` ⇒ 路由卡整块不渲染 ⇒
    页面上**什么都没有**，而"没有卡片"和"一切正常"在截图里长得一样。

本仓 testing-discipline 的原话：「守卫测试必须从真源推导它要检查的清单。
把清单抄一份进测试，它会恰好在它该发现的那次改动上保持绿色。」
所以这里三方**都是解析出来的**，一份手抄的都没有。

## 另一半：文案必须带动作

每个非正常态背后都是一条 codex **不会报错**的静默失败。文案是它唯一出声的地方，
只说"坏了"等于没说 —— 必须写清楚「现在实际会发生什么」和「你该点什么」。
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relay import store  # noqa: E402

TS = (ROOT / "codexbar" / "src" / "relay.ts").read_text(encoding="utf-8")
PY = Path(store.__file__).read_text(encoding="utf-8")


def python_states():
    """从 `route_status()` 的函数体里解析所有 `"state": "…"`。"""
    body = PY[PY.index("def route_status("):]
    end = body.find("\ndef ", 1)
    body = body[:end if end > 0 else len(body)]
    body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    return set(re.findall(r'"state":\s*"([a-z_]+)"', body))


def ts_union_states():
    m = re.search(r"export type RouteState\s*=\s*(.*?);", TS, re.S)
    assert m, "找不到 RouteState 联合"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def ts_switch_states():
    m = re.search(r"export function relayRouteNote\(.*?\n\}", TS, re.S)
    assert m, "找不到 relayRouteNote"
    return set(re.findall(r'case\s+"([a-z_]+)"\s*:', m.group(0)))


class TheProbesThemselvesWork(unittest.TestCase):
    """★ 先证三个解析器都真的解析到了东西。一个匹配数为 0 的正则会让整份测试恒绿 ——
    本仓的老教训：扫描器查了 0 个对象却报"干净"。"""

    def test_each_side_yields_a_plausible_set(self):
        for name, got in (("python", python_states()), ("ts union", ts_union_states()),
                          ("ts switch", ts_switch_states())):
            with self.subTest(side=name):
                self.assertGreaterEqual(len(got), 5, f"{name} 只解析到 {got}，正则可能失效了")
                self.assertIn("pool", got)


class AllThreeSidesAgree(unittest.TestCase):
    def test_python_equals_ts_union(self):
        self.assertEqual(python_states(), ts_union_states(),
                         "TS 的 RouteState 与 route_status() 的状态集不一致")

    def test_ts_union_equals_switch_cases(self):
        """★ 漏一个 case ⇒ `relayRouteNote` 返回 undefined ⇒ 路由卡整块不渲染。
        而"卡片没了"和"一切正常"在截图里长得一样。"""
        self.assertEqual(ts_union_states(), ts_switch_states(),
                         "switch 少了分支 —— 那个状态下路由卡会整块消失")


def health_gate_states():
    """从 `codex-rotate::relay_route_gate` 里解析它显式处理的状态。"""
    src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
    body = src[src.index("def relay_route_gate("):]
    body = body[:body.index("\ndef ", 1)]
    body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    return set(re.findall(r'state == "([a-z_]+)"', body))


class TheHealthGateHandlesEveryStateToo(unittest.TestCase):
    """★★ 三方变四方。`codex-rotate::relay_route_gate` 是**第四份**状态清单，
    而它原来漏了 `route_corrupt` —— 落进最后的"孤儿"兜底，打印成
    「路由 `None` 是孤儿」。而那个态的真实后果是 **cxp 每次 exit 78、codex 一条都跑不起来**，
    与"孤儿"完全不是一回事。文案说错了，用户会往错的方向查。"""

    def test_the_probe_works(self):
        self.assertGreaterEqual(len(health_gate_states()), 4, health_gate_states())

    def test_health_handles_every_state_the_source_can_return(self):
        missing = python_states() - health_gate_states()
        self.assertEqual(missing, set(),
                         f"health 闸没显式处理这些态（会落进兜底、说错话）: {missing}")


class EveryAbnormalStateTellsYouWhatToDo(unittest.TestCase):
    """★ 本仓铁律：告警文案要说**做什么**。erp-v3 的费率任务曾对着一个重试解决不了的
    条件让用户"重试" —— 一句无法执行的建议比不给建议更浪费时间。"""

    ACTIONS = ("切回账号池", "重新选一次路由", "codex-rotate health", "启用它")

    def _note_body(self, state):
        m = re.search(r'case\s+"%s"\s*:(.*?)(?=case\s+"|\n\s*\}\n)' % state, TS, re.S)
        self.assertIsNotNone(m, f"{state} 没有 case 分支")
        return m.group(1)

    def test_each_bad_state_names_a_concrete_next_step(self):
        for state in sorted(python_states() - {"pool", "relay"}):
            with self.subTest(state=state):
                body = self._note_body(state)
                self.assertTrue(any(a in body for a in self.ACTIONS),
                                f"{state} 的文案没告诉用户该点什么: {body[:120]}")

    def test_the_silent_fallback_is_spelled_out_where_it_applies(self):
        """★★ `profile_missing` 是最危险的一个:codex **不报错**、静默退回 base 配置。
        文案必须把「现在实际会发生什么」讲出来,否则用户以为只是少个文件。"""
        body = self._note_body("profile_missing")
        self.assertIn("不报错", body)
        self.assertIn("不轮换", body)

    def test_the_relay_state_warns_that_it_costs_money(self):
        """★ 切到中转站 = 每次请求都在扣余额。实测一句 trivial prompt 就 $0.0863
        （tokens used 39,513 —— 系统提示+工具定义就这么大）。不写出来是失职。"""
        body = self._note_body("relay")
        self.assertTrue("余额" in body or "付费" in body, body[:120])


class TheTwoCostColumnsAreLabelledDifferently(unittest.TestCase):
    """★★ 实测 `cost` 与 `actual_cost` 差 3.85 倍。页面上必须分列且标注 ——
    合并、或用同一个词描述，就是骗人。

    2026-09-09 起中转站不再是独立页：金额并进「AI用量信息」（`RelayCost`），
    选号/增删并进「总览」（`RelaySection`）。"""

    PAGE = (ROOT / "codexbar" / "src" / "components" / "RelayUsage.tsx").read_text(encoding="utf-8")

    def test_both_columns_exist_and_are_distinctly_labelled(self):
        # 主口径恒为**实扣**（KPI 与图都用它）；牌价只作参考列，压成 muted。
        self.assertIn("总实扣", self.PAGE)
        self.assertIn("日均实扣", self.PAGE)
        self.assertIn("实扣口径", self.PAGE, "没挂口径牌")
        self.assertIn("牌价", self.PAGE)
        # ★ 牌价**绝不进 KPI** —— KPI 是一眼看的地方，放一个"其实没付这么多"的数就是骗人。
        # ★★ 判据只取 `k: "..."` 那几个**标签字面量**，不做整块文本匹配：
        #    整块匹配会命中源码里解释"牌价不进 KPI"的那句注释 —— 同一台机器上
        #    今天第三次踩到"闸被自己的说明文字判红"（另两次在 test_proxy_relay_upstream.py
        #    与 test_relay_store.py）。**说明文字不是行为。**
        # ★ 切片边界用**正则抓那个数组字面量**，不写死"下一个变量叫什么" ——
        #   上一版写死 `const tokLayers`，变量一改名这条闸就 ValueError 崩掉
        #   （崩溃与"断言失败"在 CI 上颜色一样，但前者什么也没验到）。
        m = re.search(r"const kpis[^=]*=\s*\[(.*?)\n  \];", self.PAGE, re.S)
        self.assertIsNotNone(m, "解析不出 kpis 数组 —— 判据失效了")
        kpi = m.group(1)
        labels = re.findall(r'\{\s*k:\s*"([^"]+)"', kpi)
        self.assertTrue(labels, "解析不出 KPI 标签 —— 判据失效了")
        self.assertNotIn("牌价", "".join(labels), f"牌价混进了 KPI 条: {labels}")

    def test_they_are_never_added_together(self):
        """不许出现把两者相加的表达式。"""
        for bad in ("actual_cost + x.cost", "x.cost + x.actual_cost", "cost + d?.total"):
            self.assertNotIn(bad, self.PAGE)

    def test_missing_money_renders_as_a_dash_not_zero(self):
        rel = (ROOT / "codexbar" / "src" / "relay.ts").read_text(encoding="utf-8")
        m = re.search(r"export function money\(.*?\n\}", rel, re.S)
        self.assertIsNotNone(m)
        self.assertIn('return "—"', m.group(0), "读不到时没有显 —，会显成 $0.00")


class TheKeyIsNeverRenderedInFull(unittest.TestCase):
    # 列表在「总览」的 RelaySection；输入框在共用的 RelayBits。
    PAGE = (ROOT / "codexbar" / "src" / "components" / "RelaySection.tsx").read_text(encoding="utf-8")
    FORM = (ROOT / "codexbar" / "src" / "components" / "relay" / "RelayBits.tsx").read_text(encoding="utf-8")

    def test_the_list_shows_only_the_fingerprint(self):
        self.assertIn("key_fp", self.PAGE)
        self.assertNotIn("{r.key}", self.PAGE, "列表里出现了完整 key")

    def test_the_key_input_is_a_password_field_and_starts_empty(self):
        """★★ 绝不把 `key_fp` 回填进 key 框 —— 那串指纹**非空**、会通过校验、
        被当成真 key 写进配置，中转站当场 401，而症状与「key 真的过期了」一模一样。
        （relay-ctl 那半也加了形状识别兜底，两层挡的是同一件事的不同时刻。）"""
        self.assertIn('data-f="key" type="password"', self.FORM)
        self.assertIn('key: ""', self.FORM, "编辑时把 key 预填了")
        self.assertNotIn("key: editing.key_fp", self.FORM)
        self.assertNotIn("value={f.key ?? r.key_fp}", self.FORM)


class TheManualRefreshActuallyForces(unittest.TestCase):
    """★★ 手动 ↻ 必须传 `force`，否则它在合并窗口内（relay 是 300s）是个**空按钮**：
    转一圈、数字纹丝不动，而"刚点过"和"没点中"在 UI 上一模一样。

    原实现 `invoke(runCmd)` 不传参 ⇒ Rust 的 `force: Option<bool>` 恒为 `None`
    ⇒ 那个参数**零调用者**，而 `useRelayUsage` 的 docstring 明写"手动 ↻ 覆盖节流"。
    文档承诺了一个不存在的行为 —— Fable 复核抓到。

    ⚠️ **这是形状闸,不是行为闸。** 它能挡住"顺手把参数删了"，
    挡不住"传了但 Rust 侧忽略"。行为那半要在 harness 里数 force 调用，尚未做 ——
    如实写在这里，别让它看起来比实际更强。
    """

    HOOK = (ROOT / "codexbar" / "src" / "hooks" / "useQuotaSidecar.ts").read_text(encoding="utf-8")
    RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    def test_the_hook_passes_force_on_manual_refresh(self):
        self.assertIn("{ force: true }", self.HOOK,
                      "手动 ↻ 没传 force —— 300s 内它是个空按钮")

    def test_the_rust_side_actually_honours_it(self):
        """★ 传了但对面不看,和没传一样。判据是 `forced` 真的参与了合并判断。"""
        body = self.RS[self.RS.index("async fn run_relay_usage("):]
        body = body[:body.index("\n/// ") if "\n/// " in body else len(body)]
        self.assertIn("force.unwrap_or(false)", body)
        self.assertIn("if !forced {", body, "force 没有参与合并窗口的判断")


class TheScopeOfTheSwitchIsStated(unittest.TestCase):
    """★ 路由只影响交互 shell 里的 `codex`（cxp 的 alias）。
    `\\codex` / `cx` / VS Code / `omc ask codex` 都走 PATH wrapper，**不受影响**。
    不写这一行，用户会以为切完所有入口都改了 —— 然后奇怪为什么池子还在掉。"""

    def test_the_page_says_which_entrypoints_are_affected(self):
        page = (ROOT / "codexbar" / "src" / "components" / "RouteBar.tsx").read_text(encoding="utf-8")
        self.assertIn("生效范围", page)
        self.assertIn("不受此选择影响", page)


if __name__ == "__main__":
    unittest.main()
