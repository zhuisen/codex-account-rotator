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
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relay import store  # noqa: E402

TS = (ROOT / "codexbar" / "src" / "relay.ts").read_text(encoding="utf-8")
PY = Path(store.__file__).read_text(encoding="utf-8")


def visible_scope_text():
    """RouteBar 里「生效范围」那段**用户真的看得见**的文字。

    ★★ 必须先剥掉 JSX 注释 `{/* … */}`。2026-09-10 变异实测：注释里正解释着
       「不生效的那半必须同样显眼 —— 用户在 VS Code 里…」，于是 `不生效` 与 `VS Code`
       **两个关键词都落在注释里**，把可见的那句 `<b>不生效：VS Code</b>` 整段删掉，
       两条断言仍然全绿。本仓记过的空守卫形态④（断言打在自己的说明文字上）。
    """
    src = (ROOT / "codexbar" / "src" / "components" / "RouteBar.tsx").read_text(
        encoding="utf-8")
    m = re.search(r"生效范围：(.*?)</div>", src, re.S)
    assert m, "找不到「生效范围」那段可见文案"
    return re.sub(r"\{/\*.*?\*/\}", "", m.group(1), flags=re.S)


def denylist_block():
    """`codex_wants_profile` 里那个 `case` 的候选列表（**不含注释**）。"""
    src = (ROOT / "proxy" / "codex-profile-scope.sh").read_text(encoding="utf-8")
    m = re.search(r'case\s+"\$\{argv\[\$i\]:-\}"\s+in(.*?)\n\s*esac', src, re.S)
    assert m, "解析不出黑名单 —— 探针坏了，不是规则没了"
    block = m.group(1)
    # ★ 注释里出现 `app-server` 也会让断言通过 —— 先剥掉。
    block = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("#"))
    # 只要第一条 `…)` 之前那一段(即候选列表本身),别把整个 case 体吞进来。
    return block[:block.index(")")] if ")" in block else block


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
    「路由 `None` 是孤儿」。而那个态的真实后果是**代理悄悄退回账号池**：codex 照常跑，
    但你选的按量付费被无声忽略，扣的是订阅额度。与"孤儿"完全不是一回事
    （两者的修法不同：孤儿要重新登记，坏文件要重写路由）。文案说错了，用户会往错的方向查。
    ⚠️ 这段原来写的是「cxp 每次 exit 78、codex 一条都跑不起来」—— 那是上一版架构
    （中转站各有一份 profile）的事实，「一个 provider，两种上游」定稿后 cxp 已不读这个文件。"""

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


class TheCopyMustNotOutliveTheArchitectureItDescribed(unittest.TestCase):
    """★★★ **文案里的因果句是对代码的事实断言，会跟着架构一起过期。**

    2026-09-10 抓到两处，都是「上一版架构是对的、这一版还留着」：

    ① `route_corrupt` 的 detail 写着「cxp 会直接 exit 78，codex 一条都跑不起来」。
       「一个 provider，两种上游」定稿之后 `cxp` **根本不读这个路由文件**（它恒用
       `rotateproxy`，只检查 `rotateproxy.config.toml` 在不在）。真实后果是
       `proxy.py::_relay_upstream()` 读不出来就**退回账号池** —— codex 照常跑，
       但用户选的按量付费被无声忽略，扣的是订阅额度。
       ⚠️ 一条**过期的因果**比没有更糟：下次同类问题会被诊断到 cxp 上。

    ② 「生效范围」把 **VS Code** 列在生效那一侧。实测两条独立理由任一条都推翻它：
       扩展自带 codex 二进制、从 `extensionUri` 拼路径启动、根本不查 PATH；
       且它跑的是 `app-server`，而 `app-server` 在黑名单里。

    这两条闸都从**真源**取判据（黑名单从 `codex-profile-scope.sh` 解析），
    不抄清单 —— 黑名单哪天去掉 `app-server`，这里必须红。
    """

    SCOPE = (ROOT / "proxy" / "codex-profile-scope.sh").read_text(encoding="utf-8")
    ROUTEBAR = (ROOT / "codexbar" / "src" / "components" / "RouteBar.tsx").read_text(
        encoding="utf-8")

    def test_route_corrupt_no_longer_blames_cxp(self):
        """★★ **调用它，别 grep 它。**

        ⚠️ 这条最初写成 `body = PY[PY.index('"state": "route_corrupt"'):][:600]` 再判
           `"退回账号池" in body or "账号池" in body` —— 那个 600 字符窗口一路跨到
           `store.py` 下面一行 `# ★ 现在只有一份 profile 需要存在 —— 账号池那份`,
           于是**把 detail 整句后果删光，闸照样绿**（2026-09-10 变异实测）。
           `assertIn("route_corrupt", route_status.__doc__)` 更是同义反复。
           断言打在自己的注释上 —— 本仓记过的空守卫形态④，我又犯了一次。

        现在真的把一份坏路由写进隔离目录，调 `route_status()` 判返回值。
        """
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "store" / "relay").mkdir(parents=True)
        (root / "store" / "relay" / "route.local.json").write_text("[]", encoding="utf-8")
        (root / "codex-home").mkdir()
        old = {k: os.environ.get(k) for k in ("CODEX_ROTATE_STORE", "CODEX_HOME")}

        def restore():
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.addCleanup(restore)
        os.environ["CODEX_ROTATE_STORE"] = str(root / "store")
        os.environ["CODEX_HOME"] = str(root / "codex-home")

        st = store.route_status()
        self.assertEqual(st["state"], "route_corrupt", st)
        detail = st["detail"]
        self.assertNotIn("78", detail,
                         f"★ 还在说 cxp 会 exit 78 —— 已不成立: {detail}")
        self.assertIn("退回账号池", detail,
                      f"★ 没说出真实后果（代理悄悄退回账号池、扣的是订阅额度）: {detail}")

    def test_the_scope_line_names_vscode_as_out_of_scope(self):
        """★ 双向断言：既要出现 VS Code，又要它落在**不生效**那一侧。

        只断言"提到了 VS Code"会被原来那句错的文案照样满足 —— 它也提到了。
        """
        seg = visible_scope_text()
        self.assertIn("VS Code", seg)
        neg = seg.index("不生效")
        self.assertLess(neg, seg.index("VS Code"),
                        f"★ VS Code 出现在「不生效」之前 —— 仍被列为生效入口: {seg[:200]}")

    def test_the_denylist_still_backs_that_claim(self):
        """★★ 文案的第二条理由依赖 `app-server` 在黑名单里。从**真源**核，
        别让文案和黑名单各自漂移。"""
        block = denylist_block()
        self.assertIn("app-server", block,
                      "★ app-server 不在黑名单里了 ⇒ RouteBar 那句理由不再成立，两处要同时改")

    def test_the_denylist_probe_itself_is_not_broken(self):
        """★★ 先证探针**真的**解析到了黑名单。

        ⚠️ 最初写的是 `case\\s+"\\$\\{argv\\[i\\]:-\\}"` —— 源码是 `${argv[$i]:-}`（带 `$`），
           那个正则**一次都没命中过**；整条闸挂在兜底正则
           `\\n\\s*agents\\|[^\\n]*\\)` 上，而它把「agents 是第一个候选」写死了 ⇒
           保留 app-server、只换个顺序，闸就**假红**（2026-09-10 变异实测）。
           一个匹配数为 0 的正则会让整条闸恒绿，这里恰好被兜底救了一半 ——
           两种病一起犯，所以必须单独证明探针有效。
        """
        block = denylist_block()
        # 黑名单里必然有的几个,用来证明捕获到的是真的那一段。
        for name in ("login", "logout", "plugin"):
            self.assertIn(name, block, f"探针没捕到黑名单正文（缺 {name}）: {block[:200]}")
        self.assertNotIn("case", block, "捕获范围溢出到了别的 case 块")


class OnlyTheChargedAmountIsShown(unittest.TestCase):
    """★★ 实测 `cost`（牌价）与 `actual_cost`（真实扣款）差 3.85 倍。

    ⚠️ **契约在 2026-09-10 的设计稿里变了**：原来是「两列并排、各自标注」，
       现在牌价那一列**整个去掉**了，页面上只剩实扣。
       于是风险从「两个数被合并」变成「**剩下的那一个其实是牌价**」——
       而页面上再没有第二个数可以对照。所以判据换成两条：
       ① 源码里 KPI/卡片取的是 `actual_cost` 那条链路（`totalCost` / `grandCost`）；
       ② 页面上不出现「牌价」这个词（出现了就说明第二个口径又回来了，而它没有标注）。
       值本身的判据在 `tests/test_relay_page_renders.py`
       （夹具 `today.cost=0.36` vs `today.actual_cost=0.0863`，渲染出来必须是后者）。
    """

    PAGE = (ROOT / "codexbar" / "src" / "components" / "RelayUsage.tsx").read_text(encoding="utf-8")
    CARD = (ROOT / "codexbar" / "src" / "components" / "relay"
            / "ModelSparkCard.tsx").read_text(encoding="utf-8")

    def test_the_charged_scope_is_labelled(self):
        self.assertIn("总实扣", self.PAGE)
        self.assertIn("实扣口径", self.PAGE, "没挂口径牌")

    def test_the_list_price_column_is_gone(self):
        """★ 双向：既要没有「牌价」这个词，也要**确实还在显示实扣** ——
        只判"没有牌价"的话，一个什么钱都不显示的实现同样全绿。"""
        # ★ 剥掉注释:说明文字里会解释"牌价那一列去掉了"，那不是行为。
        code = re.sub(r"/\*(?:.|\n)*?\*/", "", self.PAGE)
        # ★ 行尾注释也要剥。只剥整行注释时，`const mlist = ...;   // 牌价（参考口径）`
        #   会让这条闸被自己的说明文字判红 —— 本仓空守卫形态④的镜像。
        code = re.sub(r"//[^\n]*", "", code)
        self.assertNotIn("牌价", code, "★ 牌价又回到了页面上，而它没有任何标注")
        self.assertIn("实扣", code)
        self.assertIn("costText", self.CARD, "卡上不显示实扣了")

    def test_the_card_shows_the_charged_amount_not_the_list_price(self):
        """★★ 卡上那个金额必须来自 `totalCost`（= `actual_cost` 求和），
        不是 `totalList`（= `cost` 求和）。两者在源码里只差一个词。"""
        m = re.search(r"costText:\s*money\(([^)]*)\)", self.PAGE)
        self.assertIsNotNone(m, "解析不出卡片金额的来源 —— 判据失效了")
        self.assertIn("totalCost", m.group(1), f"卡上印的不是实扣: {m.group(1)}")
        self.assertNotIn("totalList", m.group(1))

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
        """★ 列表里绝不出现完整 key。

        ⚠️ 2026-09-10 起列表在 `RelayTable.tsx`（`RelaySection` 改成表格版式），
           而且行里只画指纹的**可读前缀**（`sk-73a1…`），括号里的 sha256 前 12 位
           进 `title` —— 它的用途是跨机器比对，不是一眼认人。
        """
        table = (ROOT / "codexbar" / "src" / "components" / "relay"
                 / "RelayTable.tsx").read_text(encoding="utf-8")
        self.assertIn("key_fp", table)
        self.assertNotIn("{r.key}", table, "列表里出现了完整 key")
        self.assertNotIn("r.key}", table.replace("r.key_fp}", ""), "列表里出现了完整 key")

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
    """生效范围那句话必须**两侧都点名**。

    ⚠️ 这个类原来的断言是 `assertIn("不受此选择影响", page)` —— 只查"有没有一句
       排除说明"，不查**谁在哪一侧**。于是把 VS Code 从"不生效"挪到"生效"的那次改动
       照样全绿，错误文案就是这么活下来的（2026-09-10 复盘）。
       它自己的 docstring 当时也还写着「`\\codex` / VS Code / `omc ask codex`
       都走 PATH wrapper、不受影响」—— 四入口统一之后，那三条里有两条是反的。
       **一条只验"提到了"的断言，挡不住"说反了"。**

    真正的两侧判定在 `TheCopyMustNotOutliveTheArchitectureItDescribed`；
    这里只留最基本的存在性，并把逃生口 `cxd` 钉住。
    """

    PAGE = (ROOT / "codexbar" / "src" / "components" / "RouteBar.tsx").read_text(
        encoding="utf-8")

    def test_the_page_states_a_scope_at_all(self):
        self.assertIn("生效范围", self.PAGE)

    def test_both_sides_are_named(self):
        seg = visible_scope_text()
        self.assertIn("不生效", seg, "只说了生效的那半 —— 用户会以为剩下的也跟着切")
        for entry in ("codex", "VS Code", "cxd"):
            self.assertIn(entry, seg, f"{entry} 没被点名")


if __name__ == "__main__":
    unittest.main()
