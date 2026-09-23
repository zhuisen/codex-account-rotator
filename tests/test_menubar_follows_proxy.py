"""两条 2026-09-23 的用户需求，各一组**行为闸**（真渲染 + 真计时，不是源码文本匹配）。

## ① 菜单栏跟着代理轮换走

用户原话：「现在是代理轮换的状态，我希望菜单栏显示的账号信息跟着代理轮换走」。

此前菜单栏（托盘标题 + 弹窗里高亮的那一行）读的都是 `state.active` —— **上次 CLI 切换**
留下的号，也就是 `~/.codex/auth.json` 里那个，只有**不走代理直连**时才用得上。
逐请求轮换下 `active` 可以几天不变，菜单栏就一直挂着一个代理根本没在用的号。
现在改读 `last_aid`（proxy.py 每次成功响应后写入），取不到才退回 `active`。

★★ **夹具里 `last_aid` 与 `active` 必须不同**（make_harness.py 已这样造）——
  两者相同时，读哪个都是同一个像素，改没改都绿（本仓形态⑩）。本文件第一条先证这个前提。

## ② 卡片动作弹层打开 30 秒后直接收回（不论是否在操作）

★ 用 Chrome headless 的 `--virtual-time-budget` **真的让时间走过去**，而不是断言源码里有个 30000：
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


# 卡片动作弹层：点开 → 5s 在 → 31s 不在；另一组 25s 时按一下键，31s 照样不在。
_CARD_PROBE = r"""
setTimeout(function () {
  var out = {};
  var card = document.querySelector('[data-aid]');
  out.card = !!card;
  if (card) card.click();
  var poke = %(poke)s;
  function has() { return !!document.querySelector('[data-actions]'); }
  setTimeout(function () { out.at5 = has(); }, 5000);
  if (poke) setTimeout(function () {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', bubbles: true }));
  }, 25000);
  setTimeout(function () { out.at31 = has(); }, 31000);
  setTimeout(function () { out.at56 = has();
    document.title = '__MF__' + JSON.stringify(out); }, 56000);
}, 2600);
"""


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheActionPopoverClosesItselfAfterThirtySeconds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idle = _probe("harness.html", "nav=home", _CARD_PROBE % {"poke": "false"}, budget=70000)
        cls.busy = _probe("harness.html", "nav=home", _CARD_PROBE % {"poke": "true"}, budget=70000)
        if cls.idle is None or cls.busy is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_it_opened_in_the_first_place(self):
        """★★ 先证它**打开过** —— 没打开时「31 秒后不在」是白绿。"""
        self.assertTrue(self.idle["card"], "★★ 找不到卡片")
        self.assertTrue(self.idle["at5"], "★★ 点了卡片动作弹层没出来 —— 下面几条都没有意义")

    def test_it_closes_after_thirty_idle_seconds(self):
        self.assertFalse(self.idle["at31"], "★★★ 打开 31 秒了，动作弹层还在")

    def test_activity_does_not_keep_it_open(self):
        """★★ 用户定的语义：**30 秒后直接收回，不管动与不动**。

        第一版做成了「有操作就重置计时」，被用户否掉。这条守住现在的语义：
        25 秒时按了一下键，31 秒时**必须已经收回**。
        """
        self.assertTrue(self.busy["at5"], "★★ 这一组也没打开过 —— 下面的判断没意义")
        self.assertFalse(self.busy["at31"], "★★ 有操作就不收了 —— 用户要的是到点就收")

if __name__ == "__main__":
    unittest.main(verbosity=2)
