"""刘海额度条（`codexbar/src-tauri/src/notch.rs` + `codexbar/src/NotchHud.tsx`）的静态闸。

守的都是「错了不报错、只是看着怪」的那一类：
  · 尺寸常量分在 Rust / TSX / CSS 三处，对不上时面板被裁或偏到一边；
  · 少了 fullScreenAuxiliary，切到全屏应用就不见了 —— 2026-10-17 用户实测确认过要的就是全屏可见；
  · 新窗口没进 capabilities，invoke/listen 全部静默失败，刘海上永远是一条空槽；
  · 默认关是用户定的（2026-10-17），被顺手改成默认开会让所有人的刘海上多出一条东西。

2026-10-17 四方评审（Opus 5.5 / gpt-6.1-sol / gemini-4-argon / grok-4.7）之后加了两层：
  · **行为闸**：`notchSegs.ts` 是纯函数，node 直接跑真文件 —— 画什么、旧数怎么标、读不到怎么说、
    设置页那一行怎么说「开着但没显示」，都在边界输入上断言，不再只核源码长什么样；
  · **结构闸**：评审抓到的每一类缺陷各一条（数据源、合盖不拆窗、坐标、抢焦点、吞点击、代次、权限）。

不 import 任何项目模块、不碰凭证；node 那半只读 `codexbar/src/*.ts`。
"""
try:
    # ★ 本文件只起 node（跑 notchSegs.ts），不起任何脚本；但它断言了 `agy-quota-updated` 这类事件名，
    #   `test_isolation_bootstrap` 按子串把它算作脚本测试 —— 照规矩引入隔离，免得以后真加了脚本测试时漏掉。
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "codexbar"
RS = APP / "src-tauri" / "src" / "notch.rs"
LIB = APP / "src-tauri" / "src" / "lib.rs"
TSX = APP / "src" / "NotchHud.tsx"
CSS = APP / "src" / "notch.css"
SETTINGS = APP / "src" / "pages" / "SettingsPage.tsx"
APP_TSX = APP / "src" / "App.tsx"
SEGS = APP / "src" / "notchSegs.ts"
CAPS = APP / "src-tauri" / "capabilities"
DATA = APP / "src" / "hooks" / "useNotchData.ts"


def code_only(path):
    """去掉注释再匹配 —— 注释里正写着那些词（verification.md 形态⑫）。"""
    s = path.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"])//[^\n]*", "", s)


_code = code_only


def run_segs(expr):
    """把 notchSegs.ts 连同它 import 的 agy.ts / helpers.ts 拷进临时目录（改写成带扩展名的路径），用 node 跑。"""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        for name in ("helpers.ts", "agy.ts", "notchSegs.ts"):
            src = (APP / "src" / name).read_text(encoding="utf-8")
            src = re.sub(r'from "\./(helpers|agy)"', r'from "./\1.ts"', src)
            (d / name).write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % ((d / "notchSegs.ts").as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _one(path, pattern, what):
    hits = re.findall(pattern, path.read_text(encoding="utf-8"), re.M)
    assert len(hits) == 1, f"{path.name} 里 {what} 命中 {len(hits)} 次，应为 1"
    return hits[0]


class SizesAgree(unittest.TestCase):
    def test_panel_width_is_the_same_in_three_places(self):
        rs = float(_one(RS, r"^pub const PANEL_W: f64 = (\d+(?:\.\d+)?);", "PANEL_W"))
        tsx = float(_one(TSX, r"^const PANEL_W = (\d+);", "PANEL_W"))
        css = float(_one(CSS, r"--pw: (\d+)px", "--pw"))
        self.assertEqual(rs, tsx, "notch.rs 与 NotchHud.tsx 的面板宽不一致 ⇒ 面板被裁或偏到一边")
        self.assertEqual(rs, css, "notch.rs 与 notch.css 的 --pw 不一致")

    def test_flare_matches_the_css(self):
        rs = float(_one(RS, r"^const FLARE: f64 = (\d+(?:\.\d+)?);", "FLARE"))
        css = float(_one(CSS, r"--flare: (\d+)px", "--flare"))
        self.assertEqual(rs, css, "notch.rs 的 FLARE 与 notch.css 的 --flare 不一致")

    def test_window_has_room_for_the_whole_blurred_glow(self):
        """光晕带 blur，窗口留的透明边装不下时，模糊的边缘会被窗口裁出一圈直边。
        blur(σ) 往外 2σ 才淡到 2% —— 第一版按 1σ 留边，用户一眼看出「限制了范围」（2026-10-17）。"""
        css = _code(CSS)
        flare = float(_one(RS, r"^const FLARE: f64 = (\d+(?:\.\d+)?);", "FLARE"))
        gx = float(_one(RS, r"^const GLOW_X: f64 = (\d+(?:\.\d+)?);", "GLOW_X"))
        gy = float(_one(RS, r"^const GLOW_Y: f64 = (\d+(?:\.\d+)?);", "GLOW_Y"))
        layers = re.findall(r"(?m)^\.nh-glow \.(g\d) \{(.*?)\}", css, re.S)
        self.assertEqual([n for n, _ in layers], ["g1", "g2"], "光晕应是贴边 g1 + 散开 g2 两层")
        for name, body in layers:
            extra_w = float(re.search(r"width: calc\(var\(--nw\) \+ var\(--flare\) \* 2 \+ (\d+)px\)", body).group(1))
            extra_h = float(re.search(r"height: calc\(var\(--nh\) \+ (\d+)px\)", body).group(1))
            top = float(re.search(r"top: (-?\d+)px", body).group(1))
            blur = float(re.search(r"filter: blur\((\d+)px\)", body).group(1))
            self.assertGreaterEqual(flare + gx, flare + extra_w / 2 + 2 * blur, f"{name}：两侧透明边装不下光晕 + 2σ")
            self.assertGreaterEqual(gy, top + extra_h + 2 * blur, f"{name}：下方透明边装不下光晕 + 2σ")


class WindowBehaviour(unittest.TestCase):
    def test_sits_above_the_menubar(self):
        self.assertEqual(_one(RS, r"setLevel: (\d+)isize", "setLevel"), "26",
                         "层级必须是 NSStatusWindowLevel+1，低了会被菜单栏盖住")

    def test_visible_over_full_screen_apps(self):
        line = _one(RS, r"let behavior: usize = (.+);", "collectionBehavior")
        self.assertIn("1 << 8", line, "少了 fullScreenAuxiliary(1<<8)，全屏应用里就看不到了")
        self.assertIn("1 << 0", line, "少了 canJoinAllSpaces(1<<0)，切桌面就不见了")

    def test_turning_off_destroys_the_window(self):
        src = RS.read_text(encoding="utf-8")
        body = src[src.index("pub fn set_enabled"):]
        off = body[:body.index("return Ok(Status { active: false, reason: None });")]
        self.assertIn("drop_window(app)", off, "关掉时要销毁窗口，隐藏的 WKWebView 仍常驻两个系统进程")
        self.assertIn("remove_monitors()", off, "关掉时要拆鼠标监听")
        drop = src[src.index("fn drop_window("):src.index("fn reconcile(")]
        self.assertIn(".destroy()", drop, "drop_window 是销毁，不是隐藏")

    def test_commands_are_registered(self):
        lib = LIB.read_text(encoding="utf-8")
        block = re.search(r"generate_handler!\[(.*?)\]\)", lib, re.S)
        self.assertIsNotNone(block, "找不到 invoke_handler 的 generate_handler![...]")
        for cmd in ("set_notch_hud", "notch_geometry", "notch_panel_height"):
            self.assertRegex(block.group(1), rf"\b{cmd}\b", f"{cmd} 没注册进 invoke_handler")

    def test_window_has_capabilities(self):
        caps = [json.loads(f.read_text(encoding="utf-8")) for f in CAPS.glob("*.json")]
        mine = [c for c in caps if "notch" in c["windows"]]
        self.assertTrue(mine, "notch 窗口不在任何 capability 里 ⇒ invoke/listen 全部静默失败")

    def test_window_gets_only_what_it_needs(self):
        """★ 原来并进 default，顺带拿到了自启动开关、通知、窗口操作 —— 它只画一条线（评审 2026-10-17）。"""
        caps = [json.loads(f.read_text(encoding="utf-8")) for f in CAPS.glob("*.json")]
        mine = [c for c in caps if "notch" in c["windows"]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["windows"], ["notch"], "notch 不能和别的窗口共用一份 capability")
        self.assertEqual(mine[0]["permissions"], ["core:default"])

    def test_page_is_built(self):
        self.assertIn("notch.html", (APP / "vite.config.ts").read_text(encoding="utf-8"),
                      "vite 没把 notch.html 打进包，窗口会是空白")


class DefaultsAndColour(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(_one(SETTINGS, r"^\s*notchHud: (\w+),", "notchHud 默认值"), "false")

    def test_startup_only_turns_it_on_when_enabled(self):
        app = APP_TSX.read_text(encoding="utf-8")
        self.assertRegex(app, r"if \(st\.notchHud\) invoke\(\"set_notch_hud\"",
                         "启动时只在开着的情况下调用；无条件调用会让关着的用户也建一次窗口")

    def test_uses_the_tray_colour_rule(self):
        """刘海条和托盘标题是同一类"瞄一眼"的指示，必须同一套颜色（ui.md「额度色阈值只有一条规则」）。
        ★ 改成行为断言：原来的正则核的是那一行字，换个写法就红、写错阈值却可能照样绿。"""
        r = run_segs("[49.9, 50, 1, 0.6, 0.4, 0].map(m.segColor)")
        amber, green, red = "#E0901C", "#27B26B", "#E0524D"
        self.assertEqual(r, [amber, green, amber, amber, red, red],
                         "<50 琥珀、≥50 绿；**显示成 0 的**才标红（剩 0.4% 时环上写着 0，颜色必须跟着它）")
        for f in (TSX, SEGS):
            self.assertNotIn("quotaLevel", code_only(f), "别换成卡片那套 ≤10 红 —— 会和托盘标题说法不一")

    def test_the_ring_number_and_the_colour_agree_at_zero(self):
        self.assertEqual(run_segs("[0.4, 0.6, 100.4, -3].map(m.ringNum)"), [0, 1, 100, 0])


AGY_ACC = {"sub": "s1", "label": "A", "email": "a@x"}


def snap(**kw):
    base = {"schema": 1, "fetched_at": 1_800_000_000, "available": True, "reason": None, "detail": None,
            "pid": None, "last_good": None,
            "quota": {"groups": [{"name": "Gemini", "buckets": [
                {"bucket_id": "g5", "window": "5h", "remaining_percent": 72.4, "reset_at": None},
                {"bucket_id": "gw", "window": "weekly", "remaining_percent": 91.0, "reset_at": None}]}]}}
    base.update(kw)
    return base


class WhatTheStripShows(unittest.TestCase):
    """`notchSegs.ts` 在边界输入上的行为 —— 读不到 ≠ 满格，旧数要说清楚为什么旧。"""

    def test_codex_dead_and_unread_are_grey_not_full(self):
        r = run_segs('[m.codexSegs({status:"dead",windows:[{label:"5h",pct:80,reset:"1h"}]}, false),'
                     ' m.codexSegs({status:"live",windows:[]}, false),'
                     ' m.codexSegs({status:"live",windows:[{label:"5h",pct:40,reset:"2h"},{label:"周",pct:90,reset:"3d"}]}, false),'
                     ' m.codexSegs(undefined, false), m.codexSegs({status:"live",windows:[]}, true)]')
        dead, unread, two, none, off = r
        self.assertEqual([(x["pct"], x["reset"]) for x in dead], [(None, "失效")], "★★ 死号的旧窗口数字不许画出来")
        self.assertEqual([(x["pct"], x["reset"]) for x in unread], [(None, "待刷新")])
        self.assertEqual([x["pct"] for x in two], [40, 90], "每个窗口一段，原值照传")
        self.assertEqual((none, off), ([], []))

    def test_agy_fresh_reading_is_not_marked_stale(self):
        r = run_segs("m.agySegs(%s, false)" % json.dumps(snap()))
        self.assertEqual([(x["pct"], bool(x.get("stale"))) for x in r], [(72.4, False), (91.0, False)])

    def test_agy_last_good_is_stale_and_says_so(self):
        s = snap(available=False, reason="network_error", quota=None,
                 last_good={"fetched_at": 1_800_000_000, "quota": snap()["quota"]})
        r = run_segs("m.agySegs(%s, false)" % json.dumps(s))
        self.assertTrue(all(x["stale"] for x in r))
        self.assertTrue(all("上次读到的数" in x["title"] for x in r), r)
        self.assertFalse(any("没在跑" in x["title"] for x in r),
                         "★ 原来一律写「agy 现在没在跑」—— 读失败的原因多得很，那句是编的")

    def test_agy_carried_bucket_is_stale_with_its_own_reason(self):
        s = snap()
        s["quota"]["groups"][0]["buckets"][1]["seen_at"] = 1_800_000_000
        r = run_segs("m.agySegs(%s, false)" % json.dumps(s))
        five, week = r
        self.assertFalse(five.get("stale"), "现读的那一格不降级")
        self.assertTrue(week["stale"])
        self.assertIn("沿用", week["title"])

    def test_agy_installed_but_unread_is_one_grey_slot(self):
        s = snap(available=False, reason="network_error", detail="HTTP 503", quota=None)
        r = run_segs("m.agySegs(%s, false)" % json.dumps(s))
        self.assertEqual([(x["pct"], x["reset"]) for x in r], [(None, "读不到")],
                         "★ 整段消失和「没装 agy」长得一样；读不到要占一个灰槽")
        self.assertIn("HTTP 503", r[0]["title"])

    def test_agy_not_installed_or_off_draws_nothing(self):
        r = run_segs("[m.agySegs(%s, false), m.agySegs(%s, true), m.agySegs(null, false)]"
                     % (json.dumps(snap(available=False, reason="not_installed", quota=None)), json.dumps(snap())))
        self.assertEqual(r, [[], [], []])

    def test_agy_pool_without_a_known_current_account_does_not_borrow_a_number(self):
        r = run_segs("[m.agySegs(%s, false, true), m.agySegs(null, true, true)]" % json.dumps(snap()))
        self.assertEqual([(x["pct"], x["reset"]) for x in r[0]], [(None, "当前号未知")])
        self.assertEqual(r[1], [], "平台关了就什么都不画")


class TheSettingsRowTellsTheTruth(unittest.TestCase):
    """★ 原来没有刘海屏时开关照样变绿、屏幕上什么都没有、也没有任何原因（四方评审一致）。"""

    def test_on_without_a_notch_says_why_nothing_shows(self):
        on, off, err, unknown, fine = run_segs(
            '[m.notchRowDesc(true,{active:false,reason:"no_notch"},null),'
            ' m.notchRowDesc(false,{active:false,reason:"no_notch"},null),'
            ' m.notchRowDesc(true,null,"build failed"),'
            ' m.notchRowDesc(true,null,null), m.notchRowDesc(true,{active:true,reason:null},null)]')
        self.assertIn("没有检测到刘海屏", on)
        self.assertIn("自动出现", on, "开盖后会自己出来 —— 要说出来，不然用户会以为得重开一次")
        self.assertIn("没有刘海屏", off)
        self.assertIn("没能打开：build failed", err)
        self.assertNotIn("⚠", unknown, "还没问到 ⇒ 不下结论")
        self.assertNotIn("⚠", fine)

    def test_the_toggle_uses_the_answer_and_rolls_back_on_error(self):
        code = code_only(SETTINGS)
        i = code.index('label="刘海额度条"')
        row = code[i:i + 1600]
        self.assertIn("notchRowDesc(s.notchHud, notchSt, notchErr)", row)
        self.assertRegex(row, r'invoke<NotchStatus>\("set_notch_hud"[^)]*\)\s*\.then\(\(st\) => setNotchSt',
                         "开关要收下 Rust 的回答（显示着没有 / 为什么）")
        self.assertNotRegex(row, r"\.catch\(\(\) => \{\}\)", "★ 不许再吞错 —— 失败要回滚开关并说原因")
        self.assertIn("notchHud: !next", row, "失败时把开关拨回去")
        self.assertIn('invoke<NotchStatus>("notch_status")', code, "进设置页先问一次现在的状态")


class ReviewFindingsStayFixed(unittest.TestCase):
    """2026-10-17 四方评审抓到的每一类各一条。"""

    def setUp(self):
        self.rs = code_only(RS)
        self.hud = code_only(TSX)

    def test_agy_number_comes_from_the_pool_like_the_menubar(self):
        """★★ 本机 RPC 自 agy 1.2 起恒 csrf_required，只拿它 = 画一个几周前的 last_good（本机实测 24.5 天前）。"""
        self.assertIn("agyPool.snapshotOf(agyCur, agySnap)", self.hud)
        self.assertIn("useAgyPool(false)", self.hud, "★ 刘海窗口不做保鲜（那是菜单栏的活），只读盘 + 收广播")
        self.assertIn("const { state, agy: agySnap } = useNotchData();", self.hud,
                      "本机那份只作 snapshotOf 的归属候选，且只听推送（不用自带定时器的 useAgyQuota）")
        self.assertNotRegex(self.hud, r"useAgyPool\([^)]*background", "保鲜只能有一个 webview（菜单栏）")

    def test_the_tracking_thread_never_touches_nswindow_or_tao_cursor(self):
        """★ `cursor_position()` 按主屏 scale 换物理坐标，原来除以刘海窗口的 scale ⇒ 混合 DPI 下坐标减半。"""
        self.assertNotIn("cursor_position(", self.rs)
        self.assertNotIn("scale_factor(", self.rs)
        body = self.rs[self.rs.index("fn track("):self.rs.index("fn ensure_window(")]
        self.assertIn("mouse_desktop(&g)", body, "唤醒与跟踪必须同一套坐标算法")
        self.assertNotIn("place(&", body, "后台线程只能经 place_soon 派回主线程")

    def test_stale_threads_check_their_generation(self):
        body = self.rs[self.rs.index("fn track("):self.rs.index("fn ensure_window(")]
        self.assertIn("ENABLE_GEN.load(Ordering::SeqCst) != gen", body, "关掉之后旧跟踪线程不许再把窗口展开")
        self.assertIn("compare_exchange(me, 0", body, "只清自己那一号，不抹掉新线程的标记")
        so = self.rs[self.rs.index("fn set_open("):self.rs.index("fn track(")]
        self.assertIn("OPEN_GEN.load(Ordering::SeqCst) == gen", so, "旧的收起计时不许裁掉新一轮动画")
        se = self.rs[self.rs.index("pub fn set_enabled("):]
        self.assertIn("ENABLE_GEN.fetch_add", se)

    def test_losing_the_notch_screen_removes_the_window(self):
        """★★ 合盖后层级 26 的窗口原来留在原地，被系统挪到外接屏菜单栏正中（一块黑块）。"""
        rc = self.rs[self.rs.index("fn reconcile("):self.rs.index("fn on_mouse(")]
        self.assertRegex(rc, r"None => if app\.get_webview_window\(LABEL\)\.is_some\(\) \{ drop_window\(app\); \}")
        self.assertIn("ensure_window(app, &g)", rc, "开盖后要能自己建出来")
        om = self.rs[self.rs.index("fn on_mouse("):self.rs.index("fn install_monitors(")]
        self.assertIn("reconcile(app)", om)

    def test_monitors_are_installed_even_without_a_notch(self):
        se = self.rs[self.rs.index("pub fn set_enabled("):self.rs.index("pub fn status(")]
        self.assertLess(se.index("install_monitors(app)"), se.index("let Some(g) = geometry() else"),
                        "★ 没有刘海屏也要先装监听，否则合盖时打开、开盖后永远不出现")
        self.assertIn('reason: Some("no_notch")', se)

    def test_collapsed_strip_lets_clicks_through_and_never_takes_focus(self):
        self.assertIn("setIgnoresMouseEvents: true", self.rs, "建窗时先穿透")
        pl = self.rs[self.rs.index("fn place("):self.rs.index("fn place_soon(")]
        self.assertIn("pass_clicks(&win, !open)", pl, "收起穿透、展开才接点击")
        self.assertNotIn(".show()", self.rs, "★ tao 的 show = makeKeyAndOrderFront，会抢主窗口焦点（⌘1/2/3 失灵）")
        self.assertIn("orderFrontRegardless", self.rs)
        self.assertIn(".accept_first_mouse(true)", self.rs, "不在前台时第一下点击也要算数")

    def test_window_state_plugin_leaves_it_alone(self):
        lib = code_only(LIB)
        m = re.search(r"with_denylist\(&\[([^\]]*)\]\)", lib)
        self.assertIsNotNone(m)
        self.assertIn('"notch"', m.group(1), "★ 不进黑名单，插件会把展开态尺寸存下、下次建窗时恢复回来")

    def test_first_open_event_is_not_lost(self):
        self.assertIn('v["open"] = Value::Bool(notch::is_open())', code_only(LIB))
        self.assertRegex(self.hud, r"Promise\.all\(uns\)\.then\(\(\) => invoke",
                         "监听注册好之后再问一次当前展开态")
        self.assertIn('"notch-geom"', self.hud, "改分辨率 / 换屏后前端的刘海尺寸要跟着变")



class PushNotPoll(unittest.TestCase):
    """用户 2026-10-17：刘海网页进程改成数据变化时再推送。打开刘海条时它的 WebContent 曾 60s 平均 0.25%，
    来源是借用了主界面/菜单栏那两个自带定时器的 hook。"""

    def test_does_not_borrow_the_polling_hooks(self):
        code = _code(TSX)
        for hook in ("useStore", "useAgyQuota", "useQuotaSidecar"):
            self.assertNotRegex(code, rf"\b{hook}\b", f"刘海条不许用 {hook}：它自带 30s 定时器")
        self.assertRegex(code, r"useNotchData\(\)", "刘海条要走只听推送的 useNotchData")

    def test_data_hook_only_listens(self):
        code = _code(DATA)
        self.assertNotIn("setInterval", code, "取数 hook 里不许有周期定时器")
        self.assertNotIn("run_agy_quota", code, "刘海条只读 sidecar，不发起取数（会起 python）")
        self.assertNotIn("read_auth_tokens", code, "额度窗口用不到 token，别每次连全部 token 一起读")
        self.assertRegex(code, r'listen\("state-changed"', "要跟着 state.json 的推送重读")
        self.assertRegex(code, r'listen\("agy-quota-updated"', "要跟着 agy sidecar 的推送重读")

    def test_the_pool_hook_is_push_only_when_neither_enabled_nor_background(self):
        """刘海用 `useAgyPool(false)`。它的每个定时器都必须挡在 enabled / background 之后，
        否则刘海窗口会跟着跑 30s 心跳（甚至起取额度的子进程）。"""
        pool = _code(APP / "src" / "hooks" / "useAgyPool.ts")
        n = pool.count("setInterval")
        self.assertGreater(n, 0)
        for i in [j for j in range(len(pool)) if pool.startswith("setInterval", j)]:
            eff = pool[pool.rfind("useEffect(", 0, i):i]
            self.assertRegex(eff, r"if \(!(enabled|background)\) return;", "池 hook 的定时器没挡在 enabled / background 之后")
        self.assertIn("listen(POOL_EVT", pool, "池文件变了要跟着读盘")
        self.assertIn("listen<LivePayload>(LIVE_EVT", pool, "当前号变了要跟着换")

    def test_the_only_interval_runs_while_the_panel_is_open(self):
        code = _code(TSX)
        self.assertEqual(code.count("setInterval"), 1, "只允许面板展开时那一个倒计时定时器")
        i = code.index("setInterval")
        guard = code.rfind("if (!open) return;", 0, i)
        self.assertNotEqual(guard, -1, "唯一的定时器必须挂在 `if (!open) return;` 之后")
        self.assertLess(i - guard, 120, "定时器离 open 守卫太远，可能不在同一个 effect 里")



class ActivityGlow(unittest.TestCase):
    """用户 2026-10-17：收起态改成光晕。平时颜色 = 额度、慢呼吸；有平台在跑 = 平台色、快呼吸
    （Codex 青绿、agy 蓝、同时跑左右各半），停下恢复额度色。"""

    def test_glow_breathes_slowly_and_faster_while_working(self):
        css = _code(CSS)
        for g in ("g1", "g2"):
            idle = float(re.search(rf"(?m)^\.nh-glow \.{g} \{{[^}}]*animation: nh-breathe[-\w]* ([\d.]+)s", css).group(1))
            run = float(re.search(rf"(?m)^\.nh-active \.nh-glow \.{g} \{{ animation-duration: ([\d.]+)s; \}}", css).group(1))
            self.assertLess(run, idle, f"{g}：在跑时必须比平时呼吸得快")

    def test_two_layers_do_not_breathe_in_lockstep(self):
        """两层同周期同相位，看着就是一块整齐的光在一明一暗 —— 用户嫌的正是「太整齐规则」。"""
        css = _code(CSS)
        dur = {g: re.search(rf"(?m)^\.nh-glow \.{g} \{{[^}}]*animation: nh-breathe[-\w]* ([\d.]+)s", css).group(1)
               for g in ("g1", "g2")}
        self.assertNotEqual(dur["g1"], dur["g2"], "两层呼吸周期要错开")

    def test_glow_hides_when_open_or_empty(self):
        css = _code(CSS)
        self.assertRegex(css, r"(?m)^\.nh-quiet \.nh-glow, \.nh-open \.nh-glow \{ opacity: 0; \}",
                         "展开面板时、以及没有任何数据时，光晕要收掉")
        self.assertRegex(css, r"(?m)^\.nh-quiet \.nh-glow i, \.nh-open \.nh-glow i \{ animation: none; \}",
                         "收掉后不能还在跑动画（白耗 CPU）")

    def test_holds_still_under_reduce_motion(self):
        css = _code(CSS)
        m = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*)\}\s*$", css, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"\.nh-glow i \{ animation: none;", "开了「减弱动态效果」光晕就不该再动")

    def test_colour_means_quota_unless_a_platform_is_working(self):
        code = _code(TSX)
        self.assertRegex(code, r"const glow = lit\.length > 0 \? platformGlow : quotaGlow;",
                         "平时是额度色，在跑才换平台色")
        self.assertRegex(code, r"s\.pct == null \? UNKNOWN : segColor\(s\.pct\)",
                         "额度色走 segColor（与托盘同一条），读不到用 UNKNOWN 而不是当 0 画红")
        self.assertNotRegex(code, r'UNKNOWN = "#E0524D"', "读不到不能画成红色")

    def test_activity_is_pushed_by_rust(self):
        code = _code(TSX)
        self.assertRegex(code, r'listen<[^>]+>\("notch-activity"', "要跟着 Rust 的活动推送")
        self.assertRegex(code, r'invoke<[^>]+>\("notch_activity"\)', "首次挂载要取一次当前状态")
        self.assertRegex(code, r'lit\.length > 0 && "nh-active"', "活动状态没接到 class 上")
        self.assertNotIn("last_proxy_ts", code, "codex 会定时 GET /models，代理照样刷新 last_proxy_ts —— 停手后仍会亮")
        lib = LIB.read_text(encoding="utf-8")
        block = re.search(r"generate_handler!\[(.*?)\]\)", lib, re.S).group(1)
        self.assertRegex(block, r"\bnotch_activity\b")

    def test_rust_reads_the_right_files(self):
        rs = _code(RS)
        self.assertRegex(rs, r'n\.starts_with\("rollout-"\) && n\.ends_with\("\.jsonl"\)', "Codex 看 rollout 写入")
        self.assertRegex(rs, r'n\.ends_with\("\.db-wal"\)', "agy 是 WAL 库，生成时写的是 -wal，只看主库会永远判成空闲")
        self.assertNotIn("last_proxy_ts", rs)
        self.assertRegex(rs, r"if changed \{ let _ = app\.emit_to\(LABEL, \"notch-activity\", a\); \}", "只在变了才推")



class ActivityWatcher(unittest.TestCase):
    """评审 2026-10-17（PR #1 退回意见）：检测线程快速开关后会丢；没有刘海屏时也在每 2s 扫文件。"""

    def setUp(self):
        rs = code_only(RS)
        self.watch = rs[rs.index("fn watch_activity("):rs.index("pub fn activity(")]
        self.ensure = rs[rs.index("fn ensure_window("):rs.index("fn drop_window(")]

    def test_a_new_watcher_takes_over_instead_of_bailing_out(self):
        self.assertNotIn("WATCHING", code_only(RS), "布尔标记：快速关了再开时新线程起不来、旧线程随后退出 ⇒ 一条都没有")
        self.assertIn("WATCHER.store(me", self.watch, "新起的一条直接接管")
        self.assertIn("WATCHER.load(Ordering::SeqCst) == me", self.watch, "旧的看到不是自己就退")
        self.assertIn("ENABLE_GEN.load(Ordering::SeqCst) == gen", self.watch, "同 track：开关换代后旧线程退出")
        self.assertIn("WATCHER.compare_exchange(me, 0", self.watch, "退出时只清自己那一号")
        head = self.watch[:self.watch.index("std::thread::spawn")]
        self.assertNotIn("return", head, "起线程前不许因为「已经有一条」就退出 —— 那条可能正要因换代退出")

    def test_runs_only_while_the_window_exists(self):
        self.assertIn("app.get_webview_window(LABEL).is_some()", self.watch, "窗口没了（合盖 / 外接屏）就别再扫文件")
        self.assertEqual(self.ensure.count("watch_activity(app)"), 2,
                         "建窗和「窗口已在、只是重新打开」两条路都要接上检测线程（set_enabled 每次都换代）")
        se = code_only(RS)
        se = se[se.index("pub fn set_enabled("):se.index("pub fn status(")]
        self.assertNotIn("watch_activity", se, "不能在 set_enabled 里无条件起 —— 没有刘海屏时也会跑")


if __name__ == "__main__":
    unittest.main()
