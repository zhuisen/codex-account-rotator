"""中转站余额的**手动刷新**与**旧读数披露**（用户 2026-09-21：「中转站新增余额刷新的功能」）。

## 在这之前的状态

余额与用量来自**同一次** `/usage`，而刷新入口只在下面那块「用量」里。看余额的人在
「当前出口」卡上 —— 那张卡上一个刷新入口都没有，且它把可能是旧的余额**当现值画出来**。

## 两件事必须一起做，只做前者是半成品

1. **刷新** —— 复用同一份快照的 `force` 重取。`/usage` 只读账单、**不计费**（实测 2.34s）。
   ★ 绝不另起一条取数路径：余额与用量同源，两条路会造出第二个真源。
2. **旧读数标记** —— 取数失败时 `monitor.py::collect` 会**保留旧 `data` 并标 `stale`**
   （那是对的：「读不到」不能清空成 0）。但页面此前一个字都没说 ⇒ 几小时前的余额
   和刚读到的余额**长得一模一样**。而余额是钱。
   ★ 没有 ② 的话，点了 ↻ 也不知道到底刷到没有 —— 按钮会变成一个安慰剂。

★ 判据取 `entry.stale`，**不是**自己拿 `fetched_at` 算岁数：后者分不出「这次取到了，
  只是数本来就没变」和「这次根本没取到」。前者是 `monitor.py` 在失败那一刻写下的**事实**。
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
CARD = SRC / "components" / "relay" / "OutletCards.tsx"
TABLE = SRC / "components" / "relay" / "RelayTable.tsx"
SECTION = SRC / "components" / "RelaySection.tsx"
HARNESS = "http://127.0.0.1:3304"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _code(p):
    s = p.read_text(encoding="utf-8")
    return re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s))


def _dump(query):
    import urllib.request
    if not Path(CHROME).exists() or not (APP_DIR / "harness.html").exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                        "--window-size=1300,900", "--virtual-time-budget=9000",
                        "--dump-dom", f"{HARNESS}/harness.html?{query}"],
                       capture_output=True, text=True, timeout=180)
    return r.stdout


class TheRefreshReusesTheOneSnapshot(unittest.TestCase):
    """★★ 余额与用量同源 —— 绝不为余额另起一条取数路径。"""

    def test_the_card_gets_its_refresh_from_the_usage_hook(self):
        code = _code(SECTION)
        self.assertIn("refresh: refreshUsage", code,
                      "★★ 没有复用 useRelayUsage 的 refresh")
        self.assertIn("onRefreshUsage={() => void refreshUsage()}", code,
                      "★ 刷新没接到「当前出口」卡上")

    def test_there_is_no_second_fetch_path_for_balance(self):
        """★★ 出现第二条取数命令就是造了第二个真源，两者迟早分叉。"""
        code = _code(CARD) + _code(SECTION)
        self.assertNotIn("invoke(", code,
                         "★★ 余额侧直接 invoke 了 —— 必须走 useRelayUsage 这一条")

    def test_the_busy_state_is_shared_so_it_cannot_double_fire(self):
        code = _code(CARD)
        self.assertIn("if (!usageBusy) onRefreshUsage()", code,
                      "★ 正在取数时还能再点 —— 会叠发外网请求")

    def test_clicking_it_does_not_also_switch_the_outlet(self):
        """★★★ ↻ 坐在「切到中转站」那张**可点的卡**里。不拦冒泡的话，点刷新会**顺带切换出口**
        —— 而切过去之后每次 codex 都真扣余额（实测一句 trivial prompt $0.0863）。
        """
        code = _code(CARD)
        i = code.index('data-act="relay-balance-refresh"')
        self.assertIn("e.stopPropagation()", code[i:i + 260],
                      "★★★ 点刷新会连带切换出口 —— 那是要花钱的")


class AStaleBalanceSaysSo(unittest.TestCase):
    """★★★ 余额是钱，「这是什么时候读的」必须跟着它走。"""

    def test_the_marker_is_driven_by_the_stale_fact_not_by_an_age_guess(self):
        """⚠️ 断言打在**性质**上（这一行读的是 `curUsage.stale`），不是某个字面写法。

        第一版写死 `const stale = !!curUsage?.stale;`，于是把 `!!x` 换成 `x === true`
        这种语义完全相同的改写也判红 —— 变异实测当场抓到。**一条会假红的闸，
        用户学会的是忽略它**（本仓铁律），所以这里只管"它读没读那个事实"。
        真正的行为闸在 `ItReallyRendersInEveryRelayState`。
        """
        code = _code(CARD)
        m = re.search(r"const\s+stale\s*=\s*([^\n;]+);", code)
        self.assertIsNotNone(m, "找不到 stale 的判据")
        self.assertIn("curUsage", m.group(1))
        self.assertIn(".stale", m.group(1),
                      "★★★ 旧读数判据不是 `stale` —— 自己按 fetched_at 算岁数分不出"
                      "「这次取到了但数没变」和「这次根本没取到」")
        self.assertNotIn("Date.now", m.group(1), "★★★ 判据里混进了时间推断")

    def test_the_money_colour_does_not_change(self):
        """★ 第一版把金额染成警告琥珀 `#E0901C`，与金额琥珀 `#E0A21C` **肉眼分不出**
        （本仓已记过这对的 ΔE 只有 2.6），等于加了个无效区分还多造一个琥珀。"""
        code = _code(CARD)
        i = code.index("余额 <b")
        self.assertNotIn("#E0901C", code[i:i + 160],
                         "★ 金额色又跟着 stale 变了 —— 两个琥珀分不出")

    def test_both_surfaces_say_the_same_thing(self):
        """★★ 同一个事实在同一屏的两处要说同一句话（§5c 页面统一性）。"""
        for p, who in ((CARD, "当前出口卡"), (TABLE, "中转站表格")):
            with self.subTest(surface=who):
                self.assertIn("data-relay-balance-stale", _code(p),
                              f"★★ {who} 上没有旧读数标记 —— 同一个号两处说法不一致")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class ItReallyRendersInEveryRelayState(unittest.TestCase):
    """★★ 静态断言看不出「该出现时没出现 / 不该出现时出现了」。

    ⚠️ `stale` 这一档**夹具是这一轮才加的**。在此之前 harness 只有 `unreachable`/`auth`
      两种失败态，而它们**没有 `data`**，走的是"读不到"那条路 —— 也就是说
      「取数失败但保留了旧数据」这个**生产里最常见的形态**，一个像素都没被验过。
    """

    EXPECT = {              # relay 夹具 → (↻ 个数, 旧读数标记个数)
        "relay": (1, 0),    # 正常
        "stale": (1, 2),    # 失败但保留旧数据 ⇒ 卡 + 表行各一个
        "mixed": (1, 0),    # 两家都正常
        "unreachable": (1, 0),  # 失败且**没有**旧数据 ⇒ 走「读不到」那条路，不是旧读数
    }

    @classmethod
    def setUpClass(cls):
        cls.dom = {}
        for k in cls.EXPECT:
            d = _dump(f"nav=relay&relay={k}")
            if d is None:
                raise unittest.SkipTest("harness 静态服务（3304）没在跑")
            cls.dom[k] = d

    def test_the_page_actually_rendered(self):
        """★★ 先正面证明页面在 —— 零渲染时「标记不存在」恒真。"""
        for k, d in self.dom.items():
            with self.subTest(relay=k):
                self.assertIn("当前出口", d, f"relay={k} 中转站页没渲染")

    def test_each_state_shows_exactly_the_right_markers(self):
        for k, (refresh, stale) in self.EXPECT.items():
            d = self.dom[k]
            with self.subTest(relay=k):
                self.assertEqual(d.count('data-act="relay-balance-refresh"'), refresh,
                                 f"relay={k} 的刷新入口个数不对")
                self.assertEqual(d.count("data-relay-balance-stale"), stale,
                                 f"relay={k} 的旧读数标记个数不对")

    def test_the_stale_fixture_still_shows_a_real_balance(self):
        """★ 「旧的」不等于「没有」—— 标了 stale 也必须照常显示那个数。"""
        self.assertIn("$69.88", self.dom["stale"],
                      "★ 标成旧读数之后余额不见了 —— 那是把『旧的』当成了『没有』")


if __name__ == "__main__":
    unittest.main(verbosity=2)
