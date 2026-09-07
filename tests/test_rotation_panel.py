"""代理轮换泳道(`traffic/rotation.py` + 日志页)。1:1 复刻用户 2026-09-07 的交接稿。

> 本文件取代了 `test_proxy_rotation_panel.py`(同日早些时候写的、给 Rust 版按号台账用的)。
> 那一版被泳道整个取代,它的断言指向已经不存在的 Rust 函数 —— **删掉而不是留着**,
> 留着就是在维护一份守着死代码的绿灯。

## 这一页有五条会**静默出错**的路

**① token 归属靠 `response_id` 精确 join,不是按时间猜。** 按时间猜会在两个号交替的边界上
把 A 的消耗记到 B 头上,而画出来完全正常。

**② 合计 token 是**下界**不是总量。** 只有走过代理的响应能归属;直连 `codex` 的请求根本不
经过这里。稿子把它当完整值写(「612M token」),照抄就等于编造。

**③ 三种「没数字」要说三句不同的话**:读不到 / 窗口内确实零请求 / 只归属到了一部分。
合成一句「暂无数据」就是把「我们没看到」伪装成「确实没有」。

**④ 三类失败的计费含义不同**(`CLAUDE.md` §8「计费相位分界」):
`send err`=没计费 · `stream err`=已计费 · `committed`=**可能已计费**(最贵)。
稿子只画了断流与 429 —— 把 `committed` 一起丢掉,唯一能说"这次可能白花了钱"的信号就没了。

**⑤ 每个号一个专属色。** 纯散列**实测当场撞车**(6 个号进 6 色板,Pro1 与 plus6 同紫),
而两条同色泳道正是这个设计要避免的东西,且不会报任何错。
"""
import importlib.util
import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx"
HARNESS = ROOT / "codexbar" / "uishot" / "make_harness.py"
CONF = ROOT / "codexbar" / "src-tauri" / "tauri.conf.json"

_spec = importlib.util.spec_from_file_location("rot_mod", ROOT / "traffic" / "rotation.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)          # 纯模块:顶层只有常量,不读盘不联网

NOW = time.time()


def strip_js_comments(src):
    """★ 注释里正逐条解释着这些规则,对着原文匹配会**恒绿**(本仓空守卫形态④)。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def log(mins_ago, body, rid=None):
    ts = time.localtime(NOW - mins_ago * 60)
    tag = " #{}".format(rid) if rid else ""
    return "[proxy {}{}] {}".format(time.strftime("%m-%d %H:%M:%S", ts), tag, body)


class TimeParsing(unittest.TestCase):
    def test_a_line_from_today_is_dated_today_not_last_year(self):
        """★ 第一版写成「取第一个不在未来的候选」,把**今天**的行判成去年(365 天前也
        满足任何合理下限)。症状是整页空白而日志完全正常 —— 没有任何东西会报错。"""
        lt = time.localtime(NOW)
        t = R.parse_proxy_ts(lt.tm_mon, lt.tm_mday, lt.tm_hour, lt.tm_min, lt.tm_sec, NOW)
        self.assertIsNotNone(t)
        self.assertLess(abs(t - NOW), 3600, "今天的行被判到了 {:.0f} 天前".format((NOW - t) / 86400))

    def test_new_year_eve_rolls_back(self):
        """日志时间戳**不带年份**。1 月 1 日读到 `12-31` 若按今年算就落在未来 ⇒ 整段历史出窗。"""
        jan1 = time.mktime((2027, 1, 1, 3, 0, 0, 0, 0, -1))
        t = R.parse_proxy_ts(12, 31, 23, 50, 0, jan1)
        self.assertIsNotNone(t)
        self.assertLess(t, jan1, "跨年的行被判成了未来")
        self.assertLess(jan1 - t, 86400, "跨年回退过头")


class LabelAndSegments(unittest.TestCase):
    def test_label_is_the_first_bracket_group(self):
        """★ `stream err [plus5]: [Errno 32] Broken pipe` 里第二组是 errno 不是账号 ——
        取错会造出一个叫 `Errno 32` 的幽灵账号,而它在泳道里长得和真账号一模一样。"""
        self.assertEqual(R._first_label("stream err [plus5]: [Errno 32] Broken pipe"), "plus5")
        self.assertIsNone(R._first_label("rotating proxy on 127.0.0.1:8011"))

    def test_only_billed_requests_create_a_segment(self):
        """★★ `GET /models` 是**纯探活**。把它也算成"在岗",一次探活就会在泳道上画出
        一段假的在岗块 —— 那个号其实一个 token 都没烧。"""
        reqs = [(NOW - 600, "plusA", False), (NOW - 590, "plusA", False)]
        self.assertEqual(R.build_segments(reqs, NOW), [], "免费探活画出了在岗段")

    def test_a_long_idle_gap_splits_the_segment(self):
        """★ 同号但隔了很久要断开:否则整夜没流量会被画成一条 8 小时的在岗块,
        看着像"它扛了一整夜",而那段时间根本没人用。"""
        reqs = [(NOW - 7200, "plusA", True), (NOW - 60, "plusA", True)]
        self.assertEqual(len(R.build_segments(reqs, NOW)), 2)

    def test_enter_reason_comes_from_what_actually_happened(self):
        segs = [{"acc": "A", "start": NOW - 600, "end": NOW - 300, "requests": 3, "tokens": 0},
                {"acc": "B", "start": NOW - 200, "end": NOW, "requests": 3, "tokens": 0}]
        got = R.classify_enter([dict(s) for s in segs], [(NOW - 210, "A", "cool_429")])
        self.assertEqual(got[1]["enter_reason"], "cool_429")
        # 反向:切入前什么都没发生 ⇒ 说「额度轮换」(代理逐请求挑号的默认行为),不是硬套一个原因
        got2 = R.classify_enter([dict(s) for s in segs], [])
        self.assertEqual(got2[1]["enter_reason"], "quota_rotate")


class TokenAttribution(unittest.TestCase):
    """① —— 归属必须是 `response_id` 精确匹配 + 落在该号自己的段里。"""

    def test_tokens_land_in_the_right_account_segment(self):
        segs = [{"acc": "A", "start": NOW - 600, "end": NOW - 400, "requests": 2},
                {"acc": "B", "start": NOW - 300, "end": NOW, "requests": 2}]
        owner = {"resp_1": "A", "resp_2": "B"}
        usage = {"resp_1": {"ts": NOW - 500, "tokens": 100, "model": "m1"},
                 "resp_2": {"ts": NOW - 100, "tokens": 250, "model": "m2"}}
        matched, orphan = R.attribute(segs, owner, usage)
        self.assertEqual((matched, orphan), (2, 0))
        self.assertEqual(segs[0]["tokens"], 100)
        self.assertEqual(segs[1]["tokens"], 250)
        self.assertEqual(segs[1]["by_model"], [{"model": "m2", "tokens": 250}])

    def test_a_response_served_by_another_account_never_leaks_across(self):
        """★★ 时间上落在 B 的段里,但 `resp_owner` 说它是 A 的 —— 必须归给 A 的段,
        不能因为"时间对得上"就记到 B 头上。这正是按时间猜会犯的错。"""
        segs = [{"acc": "A", "start": NOW - 600, "end": NOW - 400, "requests": 1},
                {"acc": "B", "start": NOW - 300, "end": NOW, "requests": 1}]
        R.attribute(segs, {"resp_x": "A"},
                    {"resp_x": {"ts": NOW - 100, "tokens": 999, "model": "m"}})
        self.assertEqual(segs[1]["tokens"], 0, "别人的 token 记到了 B 头上")
        self.assertEqual(segs[0]["tokens"], 999, "归属信息说是 A 的,却没记到 A 头上")

    def test_it_lands_in_the_nearest_segment_not_the_first_match(self):
        """★ 同一个号有多段、容差(SEG_GAP_SECS)又很宽时,两段可能都够得着。
        取第一个匹配会让"这一段烧了多少"张冠李戴,而两段的深浅都还是正常的,看不出来。"""
        segs = [{"acc": "A", "start": NOW - 4000, "end": NOW - 3900, "requests": 1},
                {"acc": "A", "start": NOW - 3400, "end": NOW - 3300, "requests": 1}]
        R.attribute(segs, {"r": "A"}, {"r": {"ts": NOW - 3350, "tokens": 42, "model": "m"}})
        self.assertEqual((segs[0]["tokens"], segs[1]["tokens"]), (0, 42),
                         "落进了较远的那一段 —— 取的是第一个匹配而不是最近的")

    def test_out_of_reach_response_is_counted_as_orphan(self):
        segs = [{"acc": "A", "start": NOW - 600, "end": NOW - 400, "requests": 1}]
        matched, orphan = R.attribute(
            segs, {"r": "A"}, {"r": {"ts": NOW - 40000, "tokens": 9, "model": "m"}})
        self.assertEqual((matched, orphan), (0, 1), "落不进任何段的必须计入 orphan,不许静默丢")
        self.assertEqual(segs[0]["tokens"], 0)

    def test_an_unattributed_response_is_counted_not_dropped(self):
        segs = [{"acc": "A", "start": NOW - 600, "end": NOW, "requests": 1}]
        matched, orphan = R.attribute(segs, {}, {"resp_z": {"ts": NOW, "tokens": 5, "model": "m"}})
        self.assertEqual((matched, orphan), (0, 0))
        self.assertEqual(segs[0]["tokens"], 0, "没有归属信息的响应被硬塞进了某个段")


class CoverageIsDisclosed(unittest.TestCase):
    """② + ③ —— 合计是下界,而三种「没数字」要说三句不同的话。"""

    def test_collect_reports_attribution_coverage(self):
        text = "\n".join([
            log(10, "→ POST /responses [plusA] conv conv=x body=y", "000001"),
            log(10, "affinity resp_aaa → [plusA]", "resp_aaa"),
            log(9, "→ POST /responses [plusA] conv conv=x body=y", "000002"),
            log(9, "affinity resp_bbb → [plusA]", "resp_bbb"),
        ])
        _r, owner, _m, _l, _u, _w = R.scan_proxy_log(text, NOW, NOW - 3600, NOW)
        self.assertEqual(len(owner), 2)
        # 只有一条能对上 rollout ⇒ 覆盖率必须是 1/2,不能报成 100%
        segs = R.build_segments([(NOW - 600, "plusA", True)], NOW)
        matched, _o = R.attribute(segs, owner, {"resp_aaa": {"ts": NOW - 600, "tokens": 7, "model": "m"}})
        self.assertEqual(matched / len(owner), 0.5)

    def test_undated_lines_are_counted_not_dropped(self):
        """★ 老 `[proxy]` 前缀**完全没有时间戳**(实测占全库 27%)。它进不了任何时间窗,
        但悄悄丢掉就是把「我们没看到」伪装成「确实没有」。"""
        text = "\n".join(["[proxy] → POST /responses [plusA] new prev=-",
                          "[proxy] ← 200 [plusA]",
                          log(5, "→ POST /responses [plusA] conv conv=x body=y", "000003")])
        _r, _o, _m, _l, undated, in_window = R.scan_proxy_log(text, NOW, NOW - 3600, NOW)
        self.assertEqual(undated, 2, "无时间戳的行没有被单独计数")
        self.assertEqual(in_window, 1)

    def test_a_traceback_does_not_break_parsing(self):
        text = "\n".join(["Traceback (most recent call last):",
                          "           ~~~~~~~~~~~~~~~~~~~~^^^",
                          "ConnectionResetError: [Errno 54] Connection reset by peer",
                          log(5, "→ POST /responses [plusA] conv conv=x body=y", "000004")])
        reqs, _o, _m, _l, _u, _w = R.scan_proxy_log(text, NOW, NOW - 3600, NOW)
        self.assertEqual([a for (_t, a, _b) in reqs], ["plusA"], "traceback 造出了幽灵账号")

    def test_the_page_says_three_different_things(self):
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        self.assertIn("读不到 proxy/proxy.log", src, "失败态没有自己的文案")
        self.assertIn("in_window_lines", src, "没有区分「窗口内零请求」与「读不到」")
        self.assertIn("代理没有处理过请求", src)
        # ★ 判据打在**真的渲染出百分比**上,不是"`attributed_pct` 这个词出现过" ——
        #   它同时在 interface 声明里,把渲染分支改掉后第一版断言照样绿(变异测试抓到)。
        self.assertRegex(src, r"Math\.round\(cov\.attributed_pct \* 100\)",
                         "覆盖率没有真的渲染出来 —— 合计 token 被当成了总量")
        self.assertIn("setRot(null)", src, "取数失败没有清空,上一窗口的数字会冒充当前窗口")


class BillingPhasesStayDistinct(unittest.TestCase):
    """④ —— 三类失败不可合并。"""

    def test_engine_classifies_all_four_kinds(self):
        text = "\n".join([
            log(9, "stream err [plusA]: [Errno 32] Broken pipe", "1"),
            log(8, "429 → cooled [plusA] 5m, failing over", "2"),
            log(7, "⚠️ committed [plusA]: Remote end closed connection without response — 计费请求", "3"),
            log(6, "send err [plusA]: EOF occurred in violation of protocol — 未完整送达,安全换号", "4"),
        ])
        _r, _o, markers, _l, _u, _w = R.scan_proxy_log(text, NOW, NOW - 3600, NOW)
        self.assertEqual(sorted(k for (_t, _a, k) in markers),
                         ["billed_unknown", "cool_429", "safe_switch", "stream_err"],
                         "四类失败没有分开 —— 花没花钱分不出来了")

    def test_event_text_says_whether_money_was_spent(self):
        """★ 文案必须直接说计费后果。只写「committed」用户读不出它意味着什么。"""
        evs = R._events([], [(NOW - 60, "plusA", "billed_unknown"),
                             (NOW - 50, "plusA", "safe_switch")])
        by = {e["type"]: e["text"] for e in evs}
        self.assertIn("可能已计费", by["billed_unknown"])
        self.assertIn("未计费", by["safe_switch"])

    def test_only_billed_unknown_is_danger_colored(self):
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        i = src.index("const EV_STYLE")
        block = src[i:src.index("};", i)]
        m = re.search(r"billed_unknown:\s*\{[^}]*color:\s*(\w+)", block)
        self.assertIsNotNone(m, "事件样式表里没有 billed_unknown")
        self.assertEqual(m.group(1), "BAD", "「可能已计费」没用危险色 —— 它和无害失败长得一样了")
        m2 = re.search(r"safe_switch:\s*\{[^}]*color:\s*([^,]+)", block)
        self.assertIsNotNone(m2)
        self.assertNotIn("BAD", m2.group(1), "「安全换号」被染成危险色 —— 没花钱的事被报成花钱了")


class ColorsAreDistinct(unittest.TestCase):
    """⑤ —— 纯散列实测撞车,所以必须探测。"""

    def test_six_accounts_get_six_different_colors(self):
        labels = ["plus3", "plus4", "plus5", "plus6", "plus7", "Pro1"]
        got = R.assign_colors(labels)
        self.assertEqual(len(set(got.values())), len(labels),
                         "有两个号同色 —— 两条泳道将无法分辨,而这不会报任何错")

    def test_assignment_does_not_depend_on_input_order(self):
        import random
        labels = ["plus3", "plus4", "plus5", "plus6", "plus7", "Pro1"]
        runs = {tuple(sorted(R.assign_colors(random.sample(labels, len(labels))).items()))
                for _ in range(20)}
        self.assertEqual(len(runs), 1, "配色随输入顺序变 —— 同一个号会换色")

    def test_no_grey_in_the_palette(self):
        """全局 ui-design：灰是"其余"桶的颜色,不给有身份的东西用。"""
        for c in R.ACC_PALETTE:
            r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
            self.assertGreater(max(r, g, b) - min(r, g, b), 30, "{} 是灰的".format(c))


class ShippedAndVerifiable(unittest.TestCase):
    def test_module_is_in_the_bundle_resources(self):
        """★ 运行期按路径加载的模块必须进 `resources`,否则安装包里没有它 ——
        与 `agy_quota_series` 那次「附加功能把主扫描搞挂」同款事故。"""
        import json
        conf = json.loads(CONF.read_text(encoding="utf-8"))
        self.assertIn("../../traffic/rotation.py", conf["bundle"]["resources"])

    def test_harness_can_drive_the_tooltip_and_focus(self):
        """★★ 不打桩/不能驱动 = 假绿。浮层与聚焦是稿子 §2/§3 的**全部内容**,
        没有这两个开关它们在 harness 里一个像素都验不到,而截图会正常渲染、探针报干净。"""
        h = HARNESS.read_text(encoding="utf-8")
        self.assertIn("read_proxy_rotation", h, "harness 没打桩 —— 整页永远画「读不到」")
        self.assertIn("tipseg", h, "没有驱动泳道浮层的开关(稿子 §2 验不到)")
        self.assertIn("focusacc", h, "没有驱动聚焦的开关(稿子 §3 验不到)")
        # ★ 必须派发 `mouseover` 不是 `mouseenter`:React 的 onMouseEnter 是合成事件,
        #   靠根节点上的 mouseover 委托;原生 mouseenter 不冒泡、到不了它。
        #   实测派发 mouseenter:13 个色块全命中、零报错、浮层一个字都没出来。
        # ★★ 断言必须**剥掉注释**再打:上面那段解释文字里就写着 "mouseover" 三个字,
        #   对着原文匹配会恒绿(本仓空守卫形态④)。把 mouseover 换成 mouseenter 时
        #   第一版断言照样绿 —— 它匹配到的是我自己写的注释。
        bare = re.sub(r"//[^\n]*", "", h)
        self.assertRegex(bare, r"dispatchEvent\(new MouseEvent\('mouseover'",
                         "浮层驱动派发的不是 mouseover —— React 的 onMouseEnter 是合成事件,"
                         "靠根节点上的 mouseover 委托,原生 mouseenter 到不了它")

    def test_drivers_wait_instead_of_using_a_fixed_delay(self):
        """★ 泳道要等异步 IPC 回来才渲染。固定延时的驱动会在数据到达前就发,
        实测报「0 个色块」和「命中 1 个但一条泳道都没变暗」—— 两次都长得像选择器写错了。"""
        # ★ 判据打在**重试结构**上,不是函数名:改个名字而递归调用还在时,
        #   按名字查的断言照样绿(变异测试抓到,形态②)。
        bare = re.sub(r"//[^\n]*", "", HARNESS.read_text(encoding="utf-8"))
        for sel in ("[data-seg]", "[data-lane="):
            i = bare.index(sel)
            win = bare[max(0, i - 400):i + 400]
            self.assertIn("tries", win,
                          "{} 的驱动没有重试计数 —— 退回固定延时会在数据到达前就发".format(sel))
            self.assertIn("setTimeout", win, "{} 的驱动没有重试等待".format(sel))


if __name__ == "__main__":
    unittest.main()


class CacheAndSnapshot(unittest.TestCase):
    """用户 2026-09-07:「界面太卡…需要缓存做增量显示,配置要持久化」。

    实测(本机 4188 个 rollout):**扫 rollout 是压倒性大头** —— 1h 0.47s / 24h 1.29s / 7d 2.78s,
    而解析 proxy.log 恒 0.42s、切段与归属都是毫秒级。所以缓存只需盖住 rollout 那一段;
    热缓存实测 7d **3.00s → 0.65s**。
    """

    def test_cache_signature_uses_nanoseconds(self):
        """★★ 秒级签名会漏掉「同一秒内、长度不变的改写」,缓存沿用旧结果且**毫无症状** ——
        数字只是悄悄停在旧值。本仓 `scan.py` 上栽过一次。"""
        src = (ROOT / "traffic" / "rotation.py").read_text(encoding="utf-8")
        i = src.index("def scan_rollouts")
        body = src[i:src.index("\ndef ", i + 10)]
        self.assertIn("st_mtime_ns", body, "缓存签名用了秒级 mtime —— 同秒等长改写会被判成未变动")

    def test_cache_stores_whole_file_not_window_slice(self):
        """★ 缓存整份文件的解析结果,窗口过滤放到**取用**那一步。
        只存"窗口内那部分"的话,用户随手切一下窗口整份缓存就失效了。"""
        src = (ROOT / "traffic" / "rotation.py").read_text(encoding="utf-8")
        i = src.index("def scan_rollouts")
        body = src[i:src.index("\ndef ", i + 10)]
        self.assertIn("解析时**不按窗口过滤**", body)
        self.assertRegex(body, r"parsed\[rid\] = \{", "没有整份存进缓存")

    def test_snapshot_is_written_atomically(self):
        """★ 直接覆写会让并发读者读到半截 JSON —— 主窗口在扫、用户同时点开菜单栏,
        是每天都会发生的时序(同 `.traffic-latest.json`)。"""
        src = (ROOT / "traffic" / "rotation.py").read_text(encoding="utf-8")
        i = src.index("def _save_json")
        body = src[i:src.index("\n\n\n", i)]
        self.assertIn("os.replace", body, "快照不是原子落盘")
        self.assertIn(".tmp", body)

    def test_runtime_artifacts_are_gitignored(self):
        ig = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for f in (".rotation-cache.json", ".rotation-latest.json"):
            self.assertIn(f, ig, "{} 没有 gitignore —— 运行期产物会被提交".format(f))

    def test_page_paints_the_snapshot_before_the_rescan(self):
        """★★ 「先画快照再后台重扫」是修「太卡」的**唯一**那一步。
        判据打在**调用顺序**上:快照那次 invoke 必须在全扫之前。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        i_snap = src.index('"read_rotation_snapshot"')
        i_full = src.index('"read_proxy_rotation"')
        self.assertLess(i_snap, i_full, "全扫排在了快照前面 —— 页面仍然会同步等")

    def test_missing_snapshot_is_not_an_error(self):
        """首次运行本来就没有快照。把它当错误会让页面开局就显示"读不到"。"""
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("fn read_rotation_snapshot")
        body = rs[i:rs.index("\n#[tauri::command]", i)]
        self.assertIn("Ok(Value::Null)", body, "读不到快照时报了错,而那是首次运行的正常状态")

    def test_busy_flag_is_cleared_in_finally(self):
        """★ 失败时不熄灯 ⇒ 那盏「刷新中」长亮又灭不掉,是本仓判过死刑的形态。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        i = src.index("setBusy(true)")
        self.assertRegex(src[i:i + 900], r"finally\s*\{[^}]*setBusy\(false\)",
                         "busy 不是在 finally 里清的")

    def test_window_choice_persists_and_is_validated(self):
        """★ 记住窗口选择;读回来必须**校验在合法集合里** —— localStorage 里是字符串,
        手改过或旧版本留下的值会变成谁都不匹配的窗口,页面永远空着且不报错。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        self.assertIn("localStorage.setItem(WIN_KEY", src, "窗口选择没有持久化")
        i = src.index("function loadWin")
        body = src[i:src.index("\n}", i)]
        self.assertIn("WINDOWS", body, "读回来没有校验合法性")
        self.assertIn("includes(n)", body)


class ProFallbackIsVisible(unittest.TestCase):
    """Pro 保底(用户 2026-09-07:「plus 五小时额度用完自动切到 pro 了…想在轮换版块新增 pro 展示」)。

    ★ 先说清楚:**Pro 本来就在展示** —— 泳道是按 `proxy.log` 里实际服务过的号画的,
      不是按策略画的。真正缺的是**「这是保底被动用了」这个信号**:原来那一段的切入原因
      写的是「额度轮换」,和普通轮换混在一起,于是用户是**自己肉眼**发现切到 Pro 的。

    ★★ **Pro 在岗 ⇒ 当时没有任何可用的 Plus。** 这是 `_pick` 的策略 C 直接推出来的
      (Pro 排在所有 Plus 之后)。所以它等价于「Plus 池干了」——
      是这一页上唯一需要用户去做点什么的信号(等重置 / 用重置卡 / 加号)。
    """

    def test_pro_segments_get_their_own_reason(self):
        segs = [{"acc": "plusA", "start": NOW - 900, "end": NOW - 600, "requests": 3, "tokens": 0},
                {"acc": "Pro1", "start": NOW - 500, "end": NOW, "requests": 5, "tokens": 0}]
        got = R.classify_enter(segs, [], {"plusA": "plus", "Pro1": "pro"})
        self.assertEqual(got[1]["enter_reason"], "pro_fallback",
                         "Pro 的在岗被混进了普通轮换 —— 「Plus 池干了」这个信号就没了")
        self.assertEqual(got[0]["enter_reason"], "window_start")

    def test_plan_decides_not_the_label(self):
        """★ 老号从 Plus 升 Pro 时 **label 一个字都不变** —— 按名字判会漏掉升级后的号,
        也会把一个恰好叫 `production` 的 Plus 号误判成保底档。"""
        segs = [{"acc": "a", "start": NOW - 900, "end": NOW - 600, "requests": 1, "tokens": 0},
                {"acc": "proXX", "start": NOW - 500, "end": NOW, "requests": 1, "tokens": 0}]
        got = R.classify_enter([dict(x) for x in segs], [], {"proXX": "plus"})
        self.assertNotEqual(got[1]["enter_reason"], "pro_fallback", "按 label 判成了 Pro")
        got2 = R.classify_enter([dict(x) for x in segs], [], {"proXX": "pro"})
        self.assertEqual(got2[1]["enter_reason"], "pro_fallback")

    def test_kpi_reports_how_long_pro_covered(self):
        """★ 报**时长**不只是次数:「接管了 3 次」和「接管了 4 小时」是两件事,
        后者才说得出 Plus 池干了多久。"""
        src = (ROOT / "traffic" / "rotation.py").read_text(encoding="utf-8")
        self.assertIn('"pro_secs"', src, "没有汇报保底时长")
        self.assertIn('"pro_segs"', src)

    def test_event_text_names_the_cause(self):
        evs = R._events(
            R.classify_enter(
                [{"acc": "plusA", "start": NOW - 900, "end": NOW - 600, "requests": 2, "tokens": 5},
                 {"acc": "Pro1", "start": NOW - 500, "end": NOW, "requests": 2, "tokens": 7}],
                [], {"plusA": "plus", "Pro1": "pro"}),
            [])
        self.assertTrue(any("Pro 保底接管" in e["text"] for e in evs),
                        "事件文案没说清是保底接管 —— 只写「切到 Pro1」看不出为什么")

    def test_ui_shows_the_pro_badge_and_the_event_type(self):
        """★ 汇总条上那一格「Pro 保底」已按用户 2026-09-07 要求删掉。
        但**信号不能跟着删** —— 它必须仍活在两个位置:泳道徽章 + 独立的事件类型。
        引擎侧 `pro_segs/pro_secs` 也保留:算好的事实不该因为暂时不显示就丢掉。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        self.assertIn('l.plan === "pro"', src, "泳道上没有按 plan 画 PRO 徽章")
        self.assertIn("pro_fallback:", src, "事件类型里没有「Pro 保底」这一类")
        eng = (ROOT / "traffic" / "rotation.py").read_text(encoding="utf-8")
        self.assertIn('"pro_segs"', eng, "引擎不再算保底段数 —— 换个地方想显示时又要重算")

    def test_the_removed_cell_did_not_take_the_signal_with_it(self):
        """★ 反向断言:顶栏那一格确实没了,而事件流里的文案还在。
        「删掉一格」和「把这件事藏起来」是两回事。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        self.assertNotIn('k="Pro 保底"', src, "汇总条那一格还在")
        self.assertIn("Pro 保底接管", src, "连事件文案也一起删了 —— 信号没有落点了")

    def test_pro_fallback_is_not_painted_as_a_failure(self):
        """★ 保底接管是**按设计工作**,不是故障。染成危险红会训练用户忽略真正的告警。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        i = src.index("const EV_STYLE")
        block = src[i:src.index("};", i)]
        m = re.search(r'pro_fallback:\s*\{[^}]*color:\s*"([^"]+)"', block)
        self.assertIsNotNone(m, "事件样式表里没有 pro_fallback")
        self.assertNotIn(m.group(1).upper(), ("#E0524D",), "保底被染成了危险红")


class SummaryStripIsCompact(unittest.TestCase):
    """汇总条(用户 2026-09-07 从三方案 demo 里选的 **B · 单行分隔条**,并入标题行)。"""

    def test_no_more_two_line_kpi_blocks(self):
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        self.assertNotIn("function Kpi(", src, "旧的两行大字 KPI 组件还在 —— 会有两套汇总")
        self.assertIn("function Stat(", src)

    def test_stat_is_at_module_scope(self):
        """★ 写在页面 render 里每次渲染都是新组件类型,React 会整组卸载重建(本仓 `Seg` 那条)。"""
        # ★ 判据是**顶格定义**(第 0 列),不是"排在页面组件前面" —— 位置前后不决定作用域,
        #   写在文件末尾照样是模块作用域。第一版按位置判,把一个正确的实现判红了。
        s = PAGE.read_text(encoding="utf-8")
        self.assertRegex(s, r"(?m)^function Stat\(",
                         "Stat 不在模块顶层 —— 写在页面 render 里会每次渲染重建组件类型")

    def test_the_summary_is_the_one_that_gives_way(self):
        """★★ 指定**唯一让位者**。不给汇总条 `flex: 1 1 0` 的话,空间不够时浏览器会把
        右边的窗口分段控件整项换到第二行 —— 实测「1h 6h 24h 7d」独占一整行,看着像画错了。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        i = src.index("<Stat")
        head = src[max(0, i - 700):i]
        self.assertIn('flex: "1 1 0"', head,
                      "汇总条不是可收缩的 —— 让位的会变成右边的控件")
        self.assertIn("minWidth: 0", head)

    def test_duplicate_subtitle_is_gone(self):
        """★ 标题后面那句副标（`… token · … 次请求 · … 个号`）与汇总条逐字重复,已删。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        self.assertNotIn("次请求", src, "副标还在 —— 同一组数字在同一行说了两遍")


class LaneNameIsNeverTruncated(unittest.TestCase):
    """泳道号名不许被截断(用户 2026-09-07 截图:`Pro1` 变成 `Pr…`)。

    ★★ **这一类缺陷 harness 结构上抓不到** —— `textOverflow: ellipsis` 只改渲染,
      DOM 里的文本仍然是完整的 `Pro1`,而所有探针读的都是 DOM。
      我为此做的"退回旧实现看它是否变红"的反向验证**必然失败**,不是夹具不好。
      (CLAUDE.md 早记过同一条:「名字被截断这类缺陷…是**肉眼**发现的,不是探针。」)
      所以这里守的是**结构前提**:列宽够 + 名字不收缩 + 没有省略号机制,
      三条同时成立时截断在结构上就不可能发生。像素那半由 `?rot=procur` 的截图人工看。
    """

    def test_name_column_fits_the_worst_case(self):
        src = PAGE.read_text(encoding="utf-8")
        m = re.search(r"const NAME_W = (\d+);", src)
        self.assertIsNotNone(m)
        # 圆点 8 + 名字 ~44 + PRO ~34 + 当前 ~40 + 3 个 gap 21 = 147
        self.assertGreaterEqual(int(m.group(1)), 147,
                                "名字列放不下「名字 + PRO + 当前」这个最坏情况")

    def test_the_name_never_gives_way(self):
        """★ 名字是这一行的**身份**。宁可徽章挤,也不能把号名截掉 ——
        「认不出是哪个号」比「时间轴窄 34px」严重得多。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        i = src.index("{l.acc}</span>")
        span = src[max(0, i - 320):i]
        self.assertIn("flexShrink: 0", span, "名字可收缩 —— 徽章一多它就被压掉")
        self.assertNotIn("textOverflow", span, "名字还留着省略号机制 —— 结构上仍可能被截")

    def test_worst_case_has_a_fixture(self):
        """★ 默认夹具的「当前」在 plus4 上 ⇒ 「PRO + 当前 同行」**一次都没被渲染过**,
        而那正是出问题的组合。缺陷探针对"没渲染"是沉默的。"""
        h = HARNESS.read_text(encoding="utf-8")
        self.assertIn("procur:", h, "缺少「Pro 号正在当班」的夹具 —— 最坏情况无法复现")

    def test_redundant_clock_is_gone(self):
        """「现在 xx:xx · 当前号 X」两条信息在这一页都是重复的:时间轴右端标着「现在」,
        当前号在泳道上有「当前」徽章。它还是右侧最长的一项。"""
        src = strip_js_comments(PAGE.read_text(encoding="utf-8"))
        self.assertNotIn("当前号", src, "顶栏那句「现在 · 当前号」还在")
