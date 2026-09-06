"""两个 webview 的**进行态**必须互相看得见(2026-09-06)。

## 缺口

用户:「菜单栏我点击了刷新,进去了主界面刷新情况没有显示正在刷新」。

两个 webview 早就共用**数据**(`.traffic-latest.json` + `traffic-updated`)和**完成信号**
(Rust 在 `run_rotate` 末尾 `emit("state-changed")`),唯独**进行态**(`loadingAction` /
`busy`)一直是各自的 React state。于是对方只在动作**结束**时才知情 ——
整个执行期间(刷新全池要逐号 GET + 1.5s 节流;冷路径扫描 ~23s)它显示得像什么都没发生。

## 修法与它自带的新风险

`useBusyMirror` 走 Tauri 事件广播 `action-busy`。但**镜像来的状态是别人告诉我的,
我无法确认它还成立** —— 一盏点得亮、灭不掉的灯,是本仓判过死刑的形态。
所以熄灯必须有**三条互相独立**的路径:

  ① 对方发的结束事件(`announce(null)`,在 `finally` 里 —— 异常路径也要熄);
  ② Rust / 扫描器发的完成信号(`state-changed` / `traffic-updated`)——
     **不经过发起方**,所以对方 webview 崩溃或重载时只有这条能救;
  ③ 硬超时 `STUCK_SEC` 兜底。

★★ 还有一条容易漏的:**不能回放自己的事件**。Tauri 的 `emit` 广播给**包括自己在内**的
所有窗口,不按窗口标签过滤的话,发起方 `finally` 清掉本地态之后镜像还亮着 ——
表现为按钮转圈**停不下来**,比原缺陷更糟。

## 行为闸怎么验的

harness 一次只渲染一个 webview,所以"跨窗口"这件事只能靠注入事件来验:
`?busyfrom=<action>` 发一条 `from: 'other-window'` 的 `action-busy`(真机上另一个窗口
发来的正是这个形状),`?busyself=<action>` 是它的**反向对照** —— 自己发的必须被忽略。
没有这对开关,这次改动在 harness 里**一个像素都验不到**,而截图会正常渲染、探针会报干净。
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
MIRROR = SRC / "hooks" / "useBusyMirror.ts"
STORE = SRC / "hooks" / "useStore.ts"
TRAFFIC = SRC / "hooks" / "useTraffic.ts"
BASE = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def strip_ts(src):
    """剥注释。★ 不剥就是空守卫 —— 解释这条规则的注释里每个词都有。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def dom(url, size="1200,900"):
    p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--window-size=" + size,
                        "--virtual-time-budget=3000", "--dump-dom", url],
                       capture_output=True, text=True, timeout=120)
    return p.stdout


class ThreeIndependentWaysToTurnItOff(unittest.TestCase):
    """★★ 镜像态必须能自己熄灭。少一条路径就多一种"永远转圈"的形态。"""

    @classmethod
    def setUpClass(cls):
        cls.src = strip_ts(MIRROR.read_text(encoding="utf-8"))

    def test_peer_end_event(self):
        self.assertRegex(self.src, r"if \(!m\.action\)", "① 收不到对方的结束事件")

    def test_backend_completion_signals(self):
        """★★ 这两条**不经过发起方** —— 对方 webview 崩溃/重载时唯一能救的。"""
        for ev in ("state-changed", "traffic-updated"):
            with self.subTest(event=ev):
                self.assertIn('listen("%s"' % ev, self.src,
                              "② 没监听 %s —— 发起方一死镜像就永远亮着" % ev)

    def test_hard_timeout(self):
        self.assertIn("STUCK_SEC", self.src, "③ 没有硬超时兜底")
        m = re.search(r"const STUCK_SEC = (\d+)", MIRROR.read_text(encoding="utf-8"))
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 600, "超时太长 —— 等于没有兜底")
        self.assertGreaterEqual(int(m.group(1)), 60, "超时太短 —— 会把还在跑的动作提前熄掉")

    def test_self_events_are_filtered(self):
        """★★ 不过滤自己的广播 ⇒ `finally` 清了本地态,镜像还亮着 ⇒ 转圈停不下来。"""
        self.assertRegex(self.src, r"m\.from === selfLabel",
                         "没有按窗口标签过滤自己的事件")


class BothCallSitesAnnounceInFinally(unittest.TestCase):
    """★ `announce(null)` **必须在 `finally`**。放在 try 末尾的话,
    catch 分支里再抛一次就漏掉熄灯,对方一直转圈。"""

    def _finally_block(self, path, anchor):
        src = strip_ts(path.read_text(encoding="utf-8"))
        i = src.index(anchor)
        j = src.index("finally", i)
        return src[j:src.index("}", src.index("{", j))]

    def test_store_run_announces_in_finally(self):
        self.assertIn("announce(null)",
                      self._finally_block(STORE, "const run = useCallback"))

    def test_traffic_scan_announces_in_finally(self):
        self.assertIn("announce(null)",
                      self._finally_block(TRAFFIC, "const scan = useCallback"))

    def test_both_announce_a_start(self):
        for path, tag in ((STORE, "announce(actionId)"), (TRAFFIC, 'announce("traffic-scan")')):
            with self.subTest(file=path.name):
                self.assertIn(tag, strip_ts(path.read_text(encoding="utf-8")))

    def test_store_does_not_swallow_the_traffic_action(self):
        """★ 两个 hook 共用同一条广播通道。不筛就会把 `traffic-scan` 塞进
        `loadingAction` —— 眼下碰巧没有按钮匹配它,但那是"碰巧无害"。"""
        src = strip_ts(STORE.read_text(encoding="utf-8"))
        self.assertIn('"traffic-scan"', src, "没有把流量扫描从账号池动作里筛掉")


class RemoteBusyActuallyRenders(unittest.TestCase):
    """★★ 行为闸。静态断言证明不了「用户真的看得见」——
    而"看不见"正是这次要修的东西本身。harness 不可达则跳过,不假绿。"""

    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = dom(BASE + "/harness.html?nav=home&rail=open&grok=ok")
        except Exception as e:                      # noqa: BLE001
            raise unittest.SkipTest("harness 不可达: %s" % e)
        if "刷新全池" not in cls.probe:
            raise unittest.SkipTest("harness 没渲染出按钮，跳过")

    def test_baseline_is_idle(self):
        """★ 先证明基线是"没在转" —— 否则下面那条在"恒显示刷新中"时也会绿。"""
        self.assertIn("刷新全池", self.probe)
        self.assertNotIn("刷新中…", self.probe)

    def test_main_window_mirrors_the_menubar(self):
        d = dom(BASE + "/harness.html?nav=home&rail=open&grok=ok&busyfrom=refresh-all")
        self.assertIn("刷新中…", d,
                      "另一个窗口在刷新全池,这边毫无表示 —— 正是用户报的那个缺陷")

    def test_menubar_mirrors_the_main_window(self):
        d = dom(BASE + "/harness-menubar.html?w=352&grok=ok&busyfrom=refresh-all", "520,900")
        self.assertIn("刷新中…", d, "菜单栏没镜像主界面的进行态")

    def test_traffic_page_mirrors_a_remote_scan(self):
        d = dom(BASE + "/harness.html?nav=traffic&rail=open&busyfrom=traffic-scan")
        self.assertIn("扫描中", d, "对方在扫描,用量页没表示")

    def test_self_emitted_event_is_ignored(self):
        """★★ 反向对照。少了自过滤,发起方自己的按钮会转圈停不下来 ——
        没有这条,把过滤那行删掉不会有任何测试变红。"""
        d = dom(BASE + "/harness.html?nav=home&rail=open&grok=ok&busyself=refresh-all")
        self.assertNotIn("刷新中…", d,
                         "自己发的广播被当成远端状态收回来了 —— 按钮会转圈停不下来")


if __name__ == "__main__":
    unittest.main()
