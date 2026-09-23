"""两条 2026-09-23 的用户需求，各一组**行为闸**（真渲染 + 真计时，不是源码文本匹配）。

## ① 菜单栏跟着代理轮换走

用户原话：「现在是代理轮换的状态，我希望菜单栏显示的账号信息跟着代理轮换走」。

此前菜单栏（托盘标题 + 弹窗里高亮的那一行）读的都是 `state.active` —— **上次 CLI 切换**
留下的号，也就是 `~/.codex/auth.json` 里那个，只有**不走代理直连**时才用得上。
逐请求轮换下 `active` 可以几天不变，菜单栏就一直挂着一个代理根本没在用的号。
现在改读 `last_aid`（proxy.py 每次成功响应后写入），取不到才退回 `active`。

★★ **夹具里 `last_aid` 与 `active` 必须不同**（make_harness.py 已这样造）——
  两者相同时，读哪个都是同一个像素，改没改都绿（本仓形态⑩）。本文件第一条先证这个前提。

## ② 卡片动作弹层打开后到点直接收回（不论是否在操作；时长 = `CARD_ACTIONS_LIFE_MS`，同日 30→10→5 秒）

★ 用 Chrome headless 的 `--virtual-time-budget` **真的让时间走过去**，而不是断言源码里有个数字：
  那种断言在「计时器根本没挂上」「挂上了但被每次渲染重置」时同样是绿的。
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
HARNESS = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _probe(page_file, query, js, width=1300, budget=9000):
    import urllib.request
    src = APP_DIR / page_file
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / ("mfprobe_" + page_file)
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>{js}</script></body>", 1), encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            f"--window-size={width},900", f"--virtual-time-budget={budget}",
                            "--dump-dom", f"{HARNESS}/{page.name}?{query}"],
                           capture_output=True, text=True, timeout=240)
        m = re.search(r"__MF__(\{.*?\})\s*</title>", r.stdout, re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        page.unlink(missing_ok=True)


# 菜单栏：读出高亮（「✓ 在用」）落在哪一行，以及夹具里 active / last_aid 各是谁。
_MB_PROBE = r"""
setTimeout(function () {
 // ★ 夹具经打桩的 IPC 读 —— harness 的 `STATE` 在闭包里，全局取不到（第一版就栽在这，
 //   两个 label 都是 null，「前提成立」那条当场判红才发现）。
 window.__TAURI_INTERNALS__.invoke('read_state', {}).then(function (S) {
  var out = {};
  function lab(aid) { return S && S.slots && S.slots[aid] ? S.slots[aid].label : null; }
  out.activeLabel = S ? lab(S.active) : null;
  out.lastLabel = S ? lab(S.last_aid) : null;
  out.rows = [].slice.call(document.querySelectorAll('.mb-row-info')).length;
  out.inUse = [];
  [].slice.call(document.querySelectorAll('.mb-row-info')).forEach(function (r) {
    if ((r.textContent || '').indexOf('在用') >= 0) {
      var n = r.querySelector('.mb-row-name');
      out.inUse.push(n ? n.textContent.trim() : '?');
    }
  });
  out.oldWord = [].slice.call(document.querySelectorAll('.mb-row-info'))
      .some(function (r) { return /✓ 当前/.test(r.textContent || ''); });
  document.title = '__MF__' + JSON.stringify(out);
 });
}, 2800);
"""


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheMenubarHighlightsWhatTheProxyIsUsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _probe("harness-menubar.html", "w=352&tab=acc", _MB_PROBE, width=520)
        if cls.r is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_the_fixture_can_tell_the_two_apart(self):
        """★★ 前提：夹具里两者不同。相同的话下面那条改没改都绿。"""
        self.assertTrue(self.r["activeLabel"] and self.r["lastLabel"],
                        f"★★ 夹具没给出 active / last_aid：{self.r}")
        self.assertNotEqual(self.r["activeLabel"], self.r["lastLabel"],
                            "★★ 夹具里 active == last_aid —— 这组闸没有判别力")

    def test_it_actually_rendered_rows(self):
        self.assertGreaterEqual(self.r["rows"], 3, f"★ 菜单栏账号行没渲染：{self.r}")

    def test_exactly_one_row_is_in_use_and_it_is_the_proxys(self):
        """★★★ 高亮**只有一行**，且是 `last_aid` 那个号，不是 `active`。"""
        self.assertEqual([self.r["lastLabel"]], self.r["inUse"],
                         f"★★★ 「在用」落在 {self.r['inUse']}，"
                         f"应是代理最近用的 {self.r['lastLabel']}（不是 CLI 切换的 {self.r['activeLabel']}）")

    def test_the_old_wording_is_gone(self):
        """★ 「✓ 当前」是 `active` 那套语义的文案，留着会与「在用」并存成两个答案。"""
        self.assertFalse(self.r["oldWord"], "★ 菜单栏行里还有「✓ 当前」")


class TheTrayTitleFollowsTheProxyToo(unittest.TestCase):
    """托盘标题在 Rust 里，harness 渲染不到 —— 只能守**判据的形状**，并与前端比对。

    ⚠️ 这是结构闸不是行为闸，已知它拦不住「写对了但读错了字段名」以外的错误。
      托盘的像素证据只能靠真机（TCC 挡住了截屏，见 CLAUDE.md §2）。
    """

    def test_rust_prefers_last_aid_and_falls_back_to_active(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("fn format_tray_title()")
        seg = rs[i:rs.index("\nfn ", i + 1)]
        code = "\n".join(l.split("//")[0] for l in seg.splitlines())
        self.assertIn('state["last_aid"]', code, "★★ 托盘没读 last_aid —— 仍停在上次 CLI 切换的号")
        self.assertIn("contains_key(last)", code,
                      "★ 没核 last_aid 还在池子里 —— 指向已删的号时托盘会显示 `codex`")
        self.assertIn('state["active"]', code, "★ 取不到 last_aid 时没退回 active")

    def test_frontend_uses_the_same_rule(self):
        """★ 跨语言两份实现，判据必须一致：都是「last_aid 在池里就用它，否则 active」。"""
        ts = (ROOT / "codexbar" / "src" / "hooks" / "useStore.ts").read_text(encoding="utf-8")
        self.assertRegex(ts, r"inUseNode\s*=\s*\(state\.last_aid\s*&&\s*state\.slots\?\.\[state\.last_aid\]\)"
                             r"\s*\?\s*state\.last_aid\s*:\s*state\.active",
                         "★ 前端的「在用」判据与托盘不一致")


# 卡片动作弹层：点开 → 时长一半时在 → 到点 +600ms 不在；另一组 80% 时按一下键，到点 +600ms 照样不在。
# ★★ 时间点**从 `CARD_ACTIONS_LIFE_MS` 推导**，不写死（用户同一天把时长调了三次：30→10→5 秒，
#    写死的话每调一次测试就要跟着改，而漏改的那一版会在错误的时刻取样、判据悄悄失效）。
# ★ 「一半时还在」同时挡「收得太早」。
_CARD_PROBE = r"""
setTimeout(function () {
  var out = {};
  var card = document.querySelector('[data-aid]');
  out.card = !!card;
  if (card) card.click();
  var poke = %(poke)s;
  function has() { return !!document.querySelector('[data-actions]'); }
  setTimeout(function () { out.at5 = has(); }, __HALF__);
  if (poke) setTimeout(function () {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', bubbles: true }));
  }, __POKE__);
  setTimeout(function () { out.at11 = has();
    document.title = '__MF__' + JSON.stringify(out); }, __AFTER__);
}, 2600);
"""


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheActionPopoverClosesItselfOnTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        life = _const("CARD_ACTIONS_LIFE_MS")
        if not life:
            raise unittest.SkipTest("读不到 CARD_ACTIONS_LIFE_MS —— 探针无从定时")
        def probe(poke):
            js = (_CARD_PROBE % {"poke": poke}).replace("__HALF__", str(life // 2)) \
                 .replace("__POKE__", str(life * 4 // 5)).replace("__AFTER__", str(life + 600))
            return _probe("harness.html", "nav=home", js, budget=life + 6000)
        cls.idle, cls.busy = probe("false"), probe("true")
        if cls.idle is None or cls.busy is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_it_opened_in_the_first_place(self):
        """★★ 先证它**打开过**（时长一半时还在）—— 没打开时「到点后不在」是白绿。"""
        self.assertTrue(self.idle["card"], "★★ 找不到卡片")
        self.assertTrue(self.idle["at5"], "★★ 点了卡片动作弹层没出来 —— 下面几条都没有意义")

    def test_it_closes_after_ten_seconds(self):
        self.assertFalse(self.idle["at11"], "★★★ 到点 600ms 了，动作弹层还在")

    def test_activity_does_not_keep_it_open(self):
        """★★ 用户定的语义：**到点直接收回，不管动与不动**。

        第一版做成了「有操作就重置计时」，被用户否掉。这条守住现在的语义：
        到 80% 时按了一下键，到点 600ms 后**必须已经收回**。
        """
        self.assertTrue(self.busy["at5"], "★★ 这一组也没打开过 —— 下面的判断没意义")
        self.assertFalse(self.busy["at11"], "★★ 有操作就不收了 —— 用户要的是到点就收")


# 收回动画 + 倒计时细线（用户 2026-09-23 从 demo 里选 A · 原路退回 + 细线）。
_EXIT_PROBE = r"""
setTimeout(function () {
  var out = {};
  var card = document.querySelector('[data-aid]');
  if (card) card.click();
  function bar() { return document.querySelector('[data-actions]'); }
  function snap(tag) {
    var b = bar(), o = { present: !!b };
    if (b) {
      var cs = getComputedStyle(b), tk = b.querySelector('[data-actions-countdown]');
      o.leaving = b.hasAttribute('data-leaving');
      o.anim = cs.animationName; o.dur = cs.animationDuration; o.pe = cs.pointerEvents;
      if (tk) { var ts = getComputedStyle(tk); o.tick = { anim: ts.animationName, dur: ts.animationDuration }; }
    }
    out[tag] = o;
  }
  setTimeout(function () { snap('open'); }, __HALF__);
  setTimeout(function () { snap('mid'); }, __MID__);
  setTimeout(function () { snap('after'); document.title = '__MF__' + JSON.stringify(out); }, __AFTER__);
}, 2600);
"""


def _ms(css_time):
    """'0.14s' / '140ms' / '10s' → 毫秒。"""
    v = css_time.strip().split(",")[0]
    return float(v[:-2]) if v.endswith("ms") else float(v[:-1]) * 1000


def _const(name):
    src = (ROOT / "codexbar" / "src" / "helpers.ts").read_text(encoding="utf-8")
    m = re.search(rf"export const {name} = ([\d_]+);", src)
    return int(m.group(1).replace("_", "")) if m else None


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheActionPopoverLeavesTheWayItCame(unittest.TestCase):
    """★★ 收回不许「一帧就没了」（用户：「现在太生硬了」）。

    生硬的根因：动作条是条件渲染，弹出有 160ms 动画，收回是**组件直接卸载、0ms**。
    所以这组闸量的是**退场那一刻它还在、且正在播退场动画**，不是「源码里有个 cbSink」——
    后者在「keyframes 写了但组件照样立即卸载」时同样是绿的，而那正是原来的缺陷。
    """

    @classmethod
    def setUpClass(cls):
        cls.life, cls.exit = _const("CARD_ACTIONS_LIFE_MS"), _const("CARD_ACTIONS_EXIT_MS")
        if not cls.life:
            raise unittest.SkipTest("读不到 CARD_ACTIONS_LIFE_MS —— 探针无从定时")
        # ★ 「到点后 70ms」取样退场中的样子（退场共 EXIT+40ms），「到点后 600ms」确认已卸载。
        js = _EXIT_PROBE.replace("__HALF__", str(cls.life // 2)) \
                        .replace("__MID__", str(cls.life + 70)).replace("__AFTER__", str(cls.life + 600))
        cls.r = _probe("harness.html", "nav=home", js, budget=cls.life + 6000)
        if cls.r is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_it_opened(self):
        self.assertTrue(self.r["open"]["present"], "★★ 动作条没打开过 —— 下面几条都没意义")
        self.assertFalse(self.r["open"]["leaving"], "★ 刚打开就标成了退场中")

    def test_it_is_still_there_and_sinking_right_after_the_timer(self):
        """★★★ 计时器到点后 70ms：必须**还在**，且在播 cbSink。立即卸载 = 原来那个生硬。"""
        mid = self.r["mid"]
        self.assertTrue(mid["present"], "★★★ 到点那一刻直接没了 —— 没有退场动画")
        self.assertTrue(mid["leaving"], "★★ 还在但没标退场态")
        self.assertEqual("cbSink", mid["anim"], f"★★ 退场播的不是 cbSink：{mid['anim']}")
        self.assertEqual(self.exit, round(_ms(mid["dur"])),
                         "★ 退场时长不是 CARD_ACTIONS_EXIT_MS —— CSS 与常量分叉了")
        self.assertEqual("none", mid["pe"], "★ 退场中还能点 —— 会点中一个正在消失的按钮")

    def test_it_is_gone_after_the_exit(self):
        self.assertFalse(self.r["after"]["present"], "★★ 退场播完了还挂着")

    def test_the_countdown_line_runs_for_exactly_the_life(self):
        """★★ 细线时长必须**等于**收回计时器 —— 它是预告，预告不准比没有更糟。

        期望值从 helpers.ts 现读（不在测试里抄一个 10000），两处同源才有意义。
        """
        tick = self.r["open"].get("tick")
        self.assertIsNotNone(tick, "★★ 打开的动作条里没有倒计时细线")
        self.assertEqual("cbTick", tick["anim"], f"★ 细线没在播 cbTick：{tick}")
        self.assertIsNotNone(self.life, "★ 没从 helpers.ts 读到 CARD_ACTIONS_LIFE_MS")
        self.assertEqual(self.life, round(_ms(tick["dur"])),
                         f"★★ 细线走 {tick['dur']}，而收回计时器是 {self.life}ms —— 预告与实际对不上")


if __name__ == "__main__":
    unittest.main(verbosity=2)
