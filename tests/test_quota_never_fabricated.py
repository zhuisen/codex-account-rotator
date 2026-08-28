"""额度数字**绝不可以被编造**：没读到就是没读到，不是「满额」。

## 背景

2026-08-28 排查「一会 100% 一会 87%」时，三方评审（fable / codex / grok）在根因之外
另外挖出**三处**共同的形态：把「缺少观测」当成「观测到了满额」。

| 位置 | 谁在用 | 编造了什么 |
|---|---|---|
| `codexbar/src/helpers.ts` `winRem` | 主窗口 UI | `resets_at` 一过 → 直接 `return 100` |
| `codexbar/src-tauri/src/lib.rs` 托盘 | 菜单栏标题 | 同上，独立第二份实现 |
| `proxy/proxy.py` `_win_used` | **选号器 `_pick`** | 同上，**外加**「压根没有读数 → 当 0% 已用」 |

前两处只是画错数字；**第三处影响真实分流** —— 一个额度未知的号会被排成「完全空闲」，
从而**优先**被选中，压过一个有真实读数的号。本机实测 Pro1 的排序键第二位就是编造的 0。

## 判据（grok 提出，比"过期就未知"更准）

`resets_at` 过了**不等于**已确认重置。但也不该一律作废 —— 分两种：

* 快照 `captured_at` **晚于** `resets_at` ⇒ 这份读数本来就是重置之后拍的，`used_percent`
  属于新窗口，**可以信**（服务端回了一个已经过期的 `resets_at`，读数却是新的）。
* 快照 **早于** `resets_at`、而现在已经过了 ⇒ 窗口重置了但**还没有任何新读数** ⇒ **未知**。

## 未知在两侧的语义

* 显示层：该窗口整个不参与 `tightest`（`buildWindow` 拿到 null 就丢弃），
  全都未知时走**已有的** `—`／「未探测」路径。不新增一种"假装知道"的渲染。
* 选号器：未知**不是一个百分比**，不能塞进同一条轴。改为**先分层再排序** ——
  有读数的一律排在未知之前，层内按已用升序。数据完整时行为**完全不变**；
  全都未知时并列，退回原有顺序。
  ★ 方向是「有测量的优先于没测量的」，而不是「未知 = 最空闲」。后者是把一个
    **没有发生的观测**当成了最有利的观测。
"""
import importlib.machinery
import importlib.util
import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"


def load(mod_name, path):
    """按路径加载。两个目标的顶层都只有常量/锁，无 I/O、无网络（服务器启动在 __main__ 下）。"""
    loader = importlib.machinery.SourceFileLoader(mod_name, str(path))
    spec = importlib.util.spec_from_loader(mod_name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def strip_comments(src: str) -> str:
    """注释里正解释着这些规则（写着 `return 100`、`resets_at` 等），朴素匹配必被它染绿。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


# ★★ 必须**相对真实时钟**取偏移，不能钉死一个绝对秒数。
#    第一版写死 `NOW = 1_800_000_000`(2027-01)，而被测代码比较的是真实 `time.time()`(2026-08) ——
#    于是 `PAST = NOW - 3600` 在真实时间里**仍然是未来**，「已过期」那条分支**从未被执行**，
#    两条测试测的根本不是它们声称的东西。变异测试当场抓到（改成 `return 0` 也不红）。
#    （仓库既有规矩：夹具里绝不冻结绝对日期，用相对今天的偏移。）
NOW = time.time()
PAST = NOW - 3600            # 真的已经过去的重置点
FUTURE = NOW + 3600


class PickerNeverInventsHeadroom(unittest.TestCase):
    """选号器：没有读数 ≠ 完全空闲。"""

    @classmethod
    def setUpClass(cls):
        cls.px = load("crp_proxy", ROOT / "proxy" / "proxy.py")

    def test_anchors_exist(self):
        for fn in ("_win_used", "_used"):
            self.assertTrue(hasattr(self.px, fn), "{} 不见了 —— 断言可能打空了".format(fn))

    def test_missing_reading_is_not_reported_as_zero_used(self):
        """★★ 压根没有读数的窗口，不能返回 0（= 完全空闲）。"""
        slot = {"quota": {"primary": {"window_minutes": 10080},          # 没有 used_percent
                          "captured_at": NOW}}
        self.assertNotEqual(self.px._win_used(slot, "primary"), 0,
                            "没有读数被当成 0% 已用 —— 这个号会被排成最空闲、优先选中")

    def test_no_quota_at_all_is_not_reported_as_zero_used(self):
        self.assertNotEqual(self.px._win_used({}, "primary"), 0,
                            "整个 quota 缺失被当成 0% 已用")

    def test_expired_reset_without_a_fresh_reading_is_not_zero(self):
        """★★ 过了重置点但快照更旧 ⇒ 没有任何新读数确认它真的重置了。"""
        slot = {"quota": {"primary": {"used_percent": 91.0, "window_minutes": 300,
                                      "resets_at": PAST},
                          "captured_at": PAST - 600}}          # 快照早于重置点
        got = self.px._win_used(slot, "primary")
        self.assertNotEqual(got, 0,
                            "重置点一过就当成满额 —— 没有任何观测确认过它")

    def test_expired_reset_WITH_a_fresh_reading_is_trusted(self):
        """反向：快照晚于重置点 ⇒ 读数属于新窗口，必须照常采信，不能一并作废。"""
        slot = {"quota": {"primary": {"used_percent": 4.0, "window_minutes": 300,
                                      "resets_at": PAST},
                          "captured_at": PAST + 60}}           # 快照晚于重置点
        self.assertEqual(self.px._win_used(slot, "primary"), 4.0,
                         "重置后拍的新读数被误当成未知 —— 那会让真实数据白白丢掉")

    def test_a_measured_account_outranks_an_unknown_one(self):
        """★★ 这条是本次修复的**行为**判据：有读数的号必须排在未知的号前面。

        改动前未知 = (0, 0)，稳赢任何真实读数；一个额度未知的号会持续抢走流量。
        """
        known = {"quota": {"primary": {"used_percent": 5.0, "window_minutes": 10080,
                                       "resets_at": FUTURE},
                           "captured_at": NOW}}
        unknown = {"quota": {"primary": {"window_minutes": 10080}, "captured_at": NOW}}
        self.assertLess(self.px._used(known), self.px._used(unknown),
                        "额度未知的号排在了有真实读数的号前面")

    def test_ordering_among_known_accounts_is_unchanged(self):
        """数据完整时行为**完全不变** —— 这是这次改动的兼容性底线。"""
        def acct(u):
            return {"quota": {"primary": {"used_percent": u, "window_minutes": 10080,
                                          "resets_at": FUTURE},
                              "captured_at": NOW}}
        self.assertLess(self.px._used(acct(5.0)), self.px._used(acct(9.0)))
        self.assertLess(self.px._used(acct(0.0)), self.px._used(acct(1.0)))

    def test_all_unknown_accounts_tie(self):
        """全都未知时并列 —— 退回原有顺序，不引入新的偏好。"""
        a = {"quota": {"primary": {"window_minutes": 10080}, "captured_at": NOW}}
        b = {"quota": {"primary": {"window_minutes": 300}, "captured_at": NOW}}
        self.assertEqual(self.px._used(a), self.px._used(b))


class DisplayNeverFabricatesFullQuota(unittest.TestCase):
    """两个展示层实现（TS 主窗 + Rust 托盘）都不许把「过期」画成 100%。

    ★ 这两处没有测试运行器，只能做**源码判据**。所以断言打在**函数体**上而不是全文，
      并且每一条都做过变异验证（改回 `return 100` 会红）。
    """

    def test_typescript_winRem_requires_a_confirming_reading(self):
        ts = strip_comments((SRC / "helpers.ts").read_text(encoding="utf-8"))
        i = ts.index("export function winRem")
        body = ts[i:ts.index("\n}", i)]
        # ★★ 判据打在**比较**上，不是"capturedAt 这个词出现过" —— 它出现在函数签名里，
        #    把函数体换成 `return 100;` 那个词照样在，闸照样绿（变异测试抓到过）。
        self.assertRegex(body, r"capturedAt[^\n]*[<>][^\n]*resets_at|resets_at[^\n]*[<>][^\n]*capturedAt",
                         "winRem 没有把 capturedAt 与 resets_at 做比较 —— "
                         "无法区分「重置后的新读数」与「陈旧快照」")
        self.assertNotRegex(body, r"return\s+100\s*;",
                            "winRem 里出现了 `return 100` —— 剩余量必须由 used_percent 算出来，不能是常数")

    def test_rust_tray_requires_a_confirming_reading(self):
        rs = strip_comments((ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8"))
        # ★★ 同理：要求**真的比较**，而不是 `captured_at` 这个词出现过。
        #    变异 `let confirmed = true;` 会保留 `let cap = q["captured_at"]` 那一行 ——
        #    只查词的话完全看不出来。
        self.assertRegex(rs, r"cap\.map_or\([^)]*\|c\|\s*c\s*>\s*ra\)",
                         "托盘没有把 captured_at 与 resets_at 做比较 —— 与主窗口的判据必然分叉")
        self.assertNotRegex(rs, r"if\s+ra\s*>\s*0\.0\s*&&\s*ra\s*<=\s*now_ts\s*\{\s*100\s*\}",
                            "托盘仍在「过了重置点 → 100」")

    def test_both_surfaces_stay_in_step(self):
        """★ 同一条规则的两份实现（跨语言没法共用）必须同时具备判据。
        漏改任一份的症状是「托盘和窗口显示不一样」，**没有一处会报错**。"""
        ts = (SRC / "helpers.ts").read_text(encoding="utf-8")
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertEqual("captured" in ts, "captured_at" in rs,
                         "两份实现只改了一份 —— 托盘与主窗会各说各的")


class AFresherServerReadingIsNeverRevertedByAnOlderEcho(unittest.TestCase):
    """★ 与「不许编造」同族的另一半：**不许被更差的来源回滚**。

    `_server_reading_is_fresher(existing, candidate)` 决定「已存的快照是否比 rollout 候选更权威」。
    它靠 `SERVER_SOURCES` 判断已存快照是不是**服务端直读**；而 `"proxy"` 一直不在名单里 ——
    proxy 的读数取自 `x-codex-*` 响应头，与 usage-api 同样直接来自服务端，
    却因此被判成"非服务端"，**更旧的本地 rollout 可以合法覆盖它**。

    症状与 100%↔87% 同族：一个数字被更差的来源回滚，而**没有任何一处报错**。
    （2026-08-28 codex 与 fable 两家评审独立指出。）
    """

    @classmethod
    def setUpClass(cls):
        cls.cli = load("codex_rotate_cli_2", ROOT / "codex-rotate")

    def test_anchor_exists(self):
        self.assertTrue(hasattr(self.cli, "SERVER_SOURCES"), "SERVER_SOURCES 不见了")
        self.assertTrue(hasattr(self.cli, "_server_reading_is_fresher"), "判据函数不见了")

    def test_a_proxy_reading_counts_as_a_server_reading(self):
        """★★ 行为判据：proxy 的新快照必须挡住更旧的 rollout。"""
        existing = {"source": "proxy", "captured_at": NOW}
        older_echo = {"event_ts": NOW - 30}
        self.assertTrue(self.cli._server_reading_is_fresher(existing, older_echo),
                        "proxy 的读数没被当成服务端直读 —— 更旧的 rollout 会把它回滚")

    def test_a_genuinely_newer_echo_still_wins(self):
        """反向：真的更新的 rollout 仍应通过。这条改动只补名单，不改新旧的判法。"""
        existing = {"source": "proxy", "captured_at": NOW - 30}
        newer_echo = {"event_ts": NOW}
        self.assertFalse(self.cli._server_reading_is_fresher(existing, newer_echo),
                         "把「更旧的不许覆盖」误做成了「永远不许覆盖」")

    def test_a_rollout_derived_snapshot_is_still_not_protected(self):
        """rollout 派生的快照本来就不是服务端读数，不该因为这次改动被顺带保护。"""
        existing = {"source": None, "captured_at": NOW}
        self.assertFalse(self.cli._server_reading_is_fresher(existing, {"event_ts": NOW - 30}))


if __name__ == "__main__":
    unittest.main()
