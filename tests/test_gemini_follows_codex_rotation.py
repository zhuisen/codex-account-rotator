"""Gemini（agy）轮换与总览**按 codex 的规则**（用户 2026-09-24 拍板）。

## 用户选的三件事
1. 换号时机：**每次启动 agy 都挑容量最高**（带 5pp 迟滞），不再「粘到 15% 才换」；
2. 同步 codex 的：**置顶插队**、**池子空时借用开关**、**「下一个」单一实现**；
3. 总览：**照搬 codex 的 `RunwayHero`**，「下一个」角标，去掉「建议切到 X」与 `USE`；续航先显示「—」。

## ★★★ 这份文件取代了什么（别当成闸被删了）
`test_agy_rank_common_basis.py`（整份）与 `test_gemini_tab_matches_codex.py::TheGeminiTabHasAHeroLikeCodex`
守的是**前端自己排**的 Gemini 推荐（共同窗口基准、最优/USE、建议切到）。那套机制本身被用户撤掉了 ——
它与 wrapper 真正装进去的号是两份实现（不看置顶、不看停用、不看阈值），codex 那边已因此栽过。
不变量「界面报的号 = 真挑号器会挑的号」由下面的 `TheFrontendDoesNotRank` 接着守，而且更强。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

SRC = ROOT / "codexbar" / "src"


def q(r, reset="2099-01-01T00:00:00Z"):
    return {"gemini": {"remaining": r, "reset": reset}}


def acc(r=None, **kw):
    a = {"label": kw.pop("label", None)}
    if r is not None:
        a["quota"] = q(r)
    a.update(kw)
    return a


def strip_ts(src):
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(?<![:/])//[^\n]*", "", src)


class ThePickerFollowsCodex(unittest.TestCase):
    """行为闸：直接调**唯一**的选号实现 `agy/pool.py::pick`。"""

    def test_capacity_first_when_nothing_is_pinned(self):
        pool = {"accounts": {"a": acc(0.6), "b": acc(0.9), "c": acc(0.8)}}
        self.assertEqual(P.pick(pool, None), ("b", "new"))

    def test_pins_jump_the_queue_in_click_order(self):
        """★★ 置顶插队、按点击先后排队：先点的先用 —— 哪怕它容量更低。"""
        pool = {"pinned": ["c", "a"], "accounts": {"a": acc(0.95), "b": acc(1.0), "c": acc(0.5)}}
        self.assertEqual(P.pick(pool, None)[0], "c")
        pool["accounts"]["c"] = acc(0.05)            # 置顶号见底 ⇒ 轮到第二个置顶号
        self.assertEqual(P.pick(pool, None)[0], "a")

    def test_hysteresis_keeps_the_current_account_within_5pp(self):
        pool = {"accounts": {"cur": acc(0.96), "b": acc(1.0)}}
        self.assertEqual(P.pick(pool, "cur"), ("cur", "sticky"))

    def test_but_switches_beyond_it(self):
        """★★ 反向：差 10pp 就换 —— 旧规则（粘到 15%）在这里会**不换**。"""
        pool = {"accounts": {"cur": acc(0.9), "b": acc(1.0)}}
        self.assertEqual(P.pick(pool, "cur"), ("b", "new"))

    def test_hysteresis_never_crosses_a_pin(self):
        """★ 迟滞不许跨置顶档（同 codex 的「迟滞不得跨档」）：点亮了就立刻用它。"""
        pool = {"pinned": ["b"], "accounts": {"cur": acc(1.0), "b": acc(0.98)}}
        self.assertEqual(P.pick(pool, "cur")[0], "b")

    def test_off_dead_and_exhausted_are_never_picked(self):
        pool = {"accounts": {
            "off": acc(1.0, rotate_off=True),
            "dead": acc(1.0, last_health={"ok": False, "kind": "invalid_grant"}),
            "low": acc(0.10),
            "ok": acc(0.40)}}
        self.assertEqual(P.pick(pool, None)[0], "ok")

    def test_unknown_quota_ranks_after_known(self):
        """★ 读不到 ≠ 满额：不知道的号排在有读数的之后（同 codex 的「未知排最后」）。"""
        pool = {"accounts": {"unknown": acc(None), "known": acc(0.3)}}
        self.assertEqual(P.pick(pool, None)[0], "known")

    def test_borrow_when_the_pool_is_dry(self):
        pool = {"accounts": {"a": acc(0.05), "off": acc(0.9, rotate_off=True)}}
        self.assertEqual(P.pick(pool, "a"), ("off", "borrow"))

    def test_borrow_off_means_no_switch(self):
        """★★ 关掉借用 = 不动停用的号（agy 照用当前号跑），不是换一个别的。"""
        pool = {"borrow_off": True, "accounts": {"a": acc(0.05), "off": acc(0.9, rotate_off=True)}}
        self.assertEqual(P.pick(pool, "a"), (None, "none"))

    def test_an_explicit_switch_is_honoured_only_while_usable(self):
        pool = {"live_wanted": "b", "accounts": {"a": acc(1.0), "b": acc(0.5)}}
        self.assertEqual(P.pick(pool, "a"), ("b", "wanted"))
        pool["accounts"]["b"] = acc(0.05)
        self.assertEqual(P.pick(pool, "a")[0], "a")


class TheBoardHasCodexShape(unittest.TestCase):
    """`next --json` 与 `codex-rotate next --json` **同形** —— 总览直接复用 `RunwayHero`。"""

    POOL = {"pinned": ["b"], "accounts": {
        "a": {"label": "A", "quota": q(0.9), "quota_summary": [{"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.9, "resetTime": "2099-01-01T00:00:00Z"},
            {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": 0.95, "resetTime": "2099-01-02T00:00:00Z"}]}]},
        "b": {"label": "B", "quota": q(0.7)},
        "c": {"label": "C", "quota": q(0.9), "rotate_off": True}}}

    def test_the_keys_match_the_ts_interfaces(self):
        """★★ 从 TS 源里**现解析** `Board` / `BoardAcct` 的字段，不在这里抄一份。"""
        ts = (SRC / "hooks" / "useRotationBoard.ts").read_text(encoding="utf-8")

        def fields(name):
            body = re.search(r"export interface %s \{([\s\S]*?)\n\}" % name, ts).group(1)
            return set(re.findall(r"(\w+)\??:", body))
        b = P.board(self.POOL, "a", now=0)
        self.assertTrue(fields("Board") <= set(b), fields("Board") - set(b))
        self.assertTrue(fields("BoardAcct") <= set(b["queue"][0]), fields("BoardAcct") - set(b["queue"][0]))

    def test_next_is_what_pick_says(self):
        b = P.board(self.POOL, "a", now=0)
        self.assertEqual(b["next"]["aid"], P.pick(self.POOL, "a")[0])
        self.assertEqual(b["next"]["pin"], 1, "★ 置顶位次要带出来（卡片角标 / Hero 靠它）")

    def test_off_goes_to_rest_and_runway_is_honestly_unknown(self):
        b = P.board(self.POOL, "a", now=0)
        self.assertEqual([e["aid"] for e in b["rest"]], ["c"])
        self.assertIsNone(b["runway_active_hours"], "★ agy 没有消耗记录 —— 算不出就是 None，不是 0")


class TheCliStoresPinAndBorrowInThePool(unittest.TestCase):
    """真跑 `agy-rotate pin/borrow`（临时池）—— 真源在池里，wrapper 在 app 没开时也要读。"""

    def run_cli(self, d, *args):
        env = {**os.environ, "AGY_POOL_STORE": str(d), "AGY_KEYRING": "0",
               "AGY_TOKEN_FILE": str(Path(d) / "tok.json")}
        r = subprocess.run([sys.executable, str(ROOT / "agy-rotate"), *args],
                           capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        return json.loads((Path(d) / ".agy-pool.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="agy-pin-")
        (Path(self.d) / ".agy-pool.json").write_text(json.dumps(
            {"accounts": {"s1": {"label": "one"}, "s2": {"label": "two"}}}), encoding="utf-8")

    def test_pin_toggle_stores_subs_in_click_order(self):
        self.run_cli(self.d, "pin", "--toggle", "two")
        p = self.run_cli(self.d, "pin", "--toggle", "one")
        self.assertEqual(p["pinned"], ["s2", "s1"], "★ 存 sub、按点击先后")
        p = self.run_cli(self.d, "pin", "--toggle", "two")
        self.assertEqual(p["pinned"], ["s1"])

    def test_borrow_is_stored_inverted_and_default_deletes_the_key(self):
        p = self.run_cli(self.d, "borrow", "--off")
        self.assertIs(p.get("borrow_off"), True)
        p = self.run_cli(self.d, "borrow", "--on")
        self.assertNotIn("borrow_off", p, "★ 恢复默认要**删键** —— 否则「缺省」有两种表示")


class TheFrontendDoesNotRank(unittest.TestCase):
    """★★★ 单一实现：界面上的「下一个」只来自 `read_agy_board`，前端不再自己排 Gemini。"""

    def test_auto_pick_and_next_share_one_picker(self):
        cli = (ROOT / "agy-rotate").read_text(encoding="utf-8")
        for fn in ("cmd_auto", "cmd_pick"):
            seg = cli[cli.index(f"def {fn}("):cli.index("\ndef ", cli.index(f"def {fn}(") + 5)]
            self.assertIn("P.pick(pool, live_sub)", seg, f"★★★ {fn} 没走唯一的选号实现")
        seg = cli[cli.index("def cmd_next("):cli.index("\ndef ", cli.index("def cmd_next(") + 5)]
        self.assertIn("P.board(pool, live_sub)", seg)

    def test_the_overview_and_menubar_badge_come_from_the_board(self):
        app = strip_ts((SRC / "App.tsx").read_text(encoding="utf-8"))
        mb = strip_ts((SRC / "MenuBar.tsx").read_text(encoding="utf-8"))
        self.assertIn("isBest={agyBoard?.next?.aid === a.sub}", app)
        self.assertIn("mbAgyBoard?.next?.aid === a.sub", mb)
        self.assertIn('<RunwayHero t={t} board={agyBoard} privacy={privacy} source="agy" />', app)
        for gone in ("agyBest", "建议切到", "agyRank"):
            self.assertNotIn(gone, app, f"★★★ 前端又在自己排 Gemini（{gone}）")

    def test_the_board_ipc_is_read_only(self):
        """★★ 只读查询绝不走会广播的写通道（2026-09-21 自激回环）。"""
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("async fn read_agy_board")
        seg = rs[i:rs.index("\n}", i)]
        self.assertIn('"next"', seg)
        self.assertNotIn("emit(", seg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
