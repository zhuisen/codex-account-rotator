"""「使用重置卡」—— 全 app **唯一不可逆**的花费动作（2026-10-01 用户要求：用最近到期的那张）。

一张卡用掉就没了，所以这份闸守的是「**什么时候绝不能发请求**」与「**什么才算成功**」：

| 不变量 | 为什么 |
|---|---|
| 选**最近到期**、且**有到期日**的那张 | 用户要求；没有到期日的卡「不知道多久过期」≠「最近过期」，不能当最近 |
| ~~没有可重置窗口 ⇒ 不发~~ **2026-10-01 撤销** | 用户实测额度没见底也能用卡并要求放开；服务端是最终裁判，成败只认 `windows_reset`，前后张数核对 |
| 成功**只认** `windows_reset > 0` | 200 + `windows_reset: 0`（实测 `no_credit`）是「没生效」，不能报成「已使用」 |
| 请求号（`redeem_request_id`）先落盘；没确认成功就复用 | 网络在发出去之后断了，重试若换新号就可能再用掉第二张 |
| 请求结果未知 ⇒ 既不报成功也不清掉请求号 | 「这一枪没打中」与「确实没生效」不能是同一个值 |

端点与请求体是 2026-10-01 实测的（见 `codex-rotate` 里 `CREDIT_CONSUME_PATH` 上的注释）；
这里**一次真实请求都不发** —— 网络函数全部打桩。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import contextlib
import importlib.machinery
import io
import importlib.util
import json
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader("codex_rotate_uc", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader("codex_rotate_uc", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


CR = load()
NOW = time.time()


def iso(days):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(NOW + days * 86400))


def card(cid, days, status="available"):
    return {"id": cid, "status": status, "expires_at": None if days is None else iso(days)}


class PickSoonest(unittest.TestCase):
    def test_nearest_expiry_wins(self):
        c = CR._pick_soonest_credit([card("far", 20), card("near", 3), card("mid", 9)])
        self.assertEqual(c["id"], "near")

    def test_unusable_cards_are_never_picked(self):
        cs = [card("gone", 1, "redeemed"), card("expired", -1), card("nodate", None),
              {"status": "available", "expires_at": iso(2)}, card("ok", 8)]
        self.assertEqual(CR._pick_soonest_credit(cs)["id"], "ok",
                         "★★ 选到了已用掉 / 已过期 / 没到期日 / 没 id 的卡")

    def test_nothing_usable_is_none(self):
        self.assertIsNone(CR._pick_soonest_credit([card("n", None), card("r", 2, "redeemed")]))
        self.assertIsNone(CR._pick_soonest_credit(None))


class Outcome(unittest.TestCase):
    def test_only_windows_reset_counts_as_success(self):
        j = lambda **k: json.dumps(k).encode()
        self.assertEqual(CR._consume_outcome(200, j(code="ok", credit={"id": "x"}, windows_reset=2))[0], "reset")
        # 实测：不存在的卡 → 200 + no_credit + windows_reset 0
        self.assertEqual(CR._consume_outcome(200, j(code="no_credit", credit=None, windows_reset=0))[0], "no_effect")
        # 只有 credit 非空、没重置窗口 —— 也不是成功
        self.assertEqual(CR._consume_outcome(200, j(code="x", credit={"id": "x"}, windows_reset=0))[0], "no_effect")
        self.assertEqual(CR._consume_outcome(200, j(windows_reset=True))[0], "no_effect", "★ bool 不是数字")

    def test_unknown_is_not_failure_and_not_success(self):
        self.assertEqual(CR._consume_outcome(None, b"timeout")[0], "unknown")
        self.assertEqual(CR._consume_outcome(200, b"<html>")[0], "unknown")
        self.assertEqual(CR._consume_outcome(500, b"")[0], "http_error")
        self.assertEqual(CR._consume_outcome(429, b"")[0], "http_error")


class Flow(unittest.TestCase):
    """真跑 `cmd_use_credit`，网络与状态全打桩。"""

    def setUp(self):
        self.aid = "acct-1"
        self.state = {"active": "other", "slots": {
            self.aid: {"label": "Egan", "file": "egan.json",
                       "credits": {"available": 3, "applicable": 1, "at": NOW}}}}
        self.detail = [card("far", 20), card("near", 3), card("mid", 9)]
        self.posts = []
        self.post_result = (200, json.dumps({"code": "ok", "credit": {"id": "near"}, "windows_reset": 1}).encode())
        self.after_available = 2
        self.orig = {k: getattr(CR, k) for k in ("_state", "_mutate_state", "_probe_quota", "_fetch_credit_detail",
                                                 "_load_json", "_account_id", "_access_exp", "_api_post")}
        CR._state = lambda: self.state
        CR._mutate_state = lambda fn: fn(self.state)
        CR._load_json = lambda p: {"tokens": {"access_token": "t", "account_id": self.aid}}
        CR._account_id = lambda auth: self.aid
        CR._access_exp = lambda tok: NOW + 3600

        def probe(aid, slot, is_active):
            c = self.state["slots"][aid].get("credits") or {}
            if self.posts:                       # 发完之后的核对读数
                c["available"] = self.after_available
                c["at"] = time.time()
            return {}, "ok"
        CR._probe_quota = probe
        CR._fetch_credit_detail = lambda aid, slot, act: (self.detail, "HTTP 200")

        def post(tok, path, body, timeout=25):
            self.posts.append((path, dict(body)))
            return self.post_result
        CR._api_post = post
        self.addCleanup(lambda: [setattr(CR, k, v) for k, v in self.orig.items()])

    def run_cmd(self, *extra):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
            CR.cmd_use_credit(["Egan", *extra])
            raise SystemExit(0)                  # 成功路径是正常 return
        return cm.exception.code

    def test_success_spends_the_nearest_card_and_records_it(self):
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(len(self.posts), 1, "★★ 一次调用只许发一次请求")
        path, body = self.posts[0]
        self.assertEqual(path, CR.CREDIT_CONSUME_PATH)
        self.assertEqual(body["credit_id"], "near", "★★ 没用最近到期的那张")
        self.assertTrue(body["redeem_request_id"])
        sl = self.state["slots"][self.aid]
        self.assertNotIn("credit_redeem", sl, "成功后请求号应清掉")

    def test_it_still_sends_when_the_quota_is_not_exhausted(self):
        """用户 2026-10-01 拍板：额度没见底（`applicable == 0`）也要能用卡。反向对照：旧闸会在这里拒绝。"""
        self.state["slots"][self.aid]["credits"]["applicable"] = 0
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(len(self.posts), 1, "★★ 没有可重置窗口就被客户端拦下了 —— 用户明确要求放开")

    def test_a_stale_or_unreadable_reading_does_not_block_either(self):
        self.state["slots"][self.aid]["credits"]["at"] = NOW - 3600
        CR._probe_quota = lambda *a: (None, "HTTP 403")     # 刷不新
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(len(self.posts), 1)

    def test_without_an_applicable_window_the_outcome_is_still_judged_by_the_server(self):
        """放开闸之后，成败判据更要硬：服务端说没重置任何窗口 ⇒ 失败，不能因为「是我们发的」就报成功。"""
        self.state["slots"][self.aid]["credits"]["applicable"] = 0
        self.post_result = (200, json.dumps({"code": "not_applicable", "credit": None, "windows_reset": 0}).encode())
        self.assertEqual(self.run_cmd("--json"), 1)

    def test_refuses_dead_expired_or_mismatched_accounts(self):
        self.state["slots"][self.aid]["auth_dead"] = True
        self.assertEqual(self.run_cmd("--json"), 1)
        del self.state["slots"][self.aid]["auth_dead"]
        CR._access_exp = lambda tok: NOW - 5
        self.assertEqual(self.run_cmd("--json"), 1)
        CR._access_exp = lambda tok: NOW + 3600
        CR._account_id = lambda auth: "someone-else"
        self.assertEqual(self.run_cmd("--json"), 1)
        self.assertEqual(self.posts, [])

    def test_no_dated_card_means_no_request(self):
        self.detail = [card("a", None)]
        self.assertEqual(self.run_cmd("--json"), 1)
        self.assertEqual(self.posts, [])

    def test_no_effect_is_failure_and_keeps_the_request_id_for_retry(self):
        self.post_result = (200, json.dumps({"code": "no_credit", "credit": None, "windows_reset": 0}).encode())
        self.assertEqual(self.run_cmd("--json"), 1, "★★ 没重置任何窗口却报成功")
        rid1 = self.posts[0][1]["redeem_request_id"]
        self.assertEqual(self.state["slots"][self.aid]["credit_redeem"]["redeem_request_id"], rid1)
        self.run_cmd("--json")                    # 重试
        self.assertEqual(self.posts[1][1]["redeem_request_id"], rid1,
                         "★★★ 重试换了新请求号 —— 网络断过的那一次若其实生效了，这里会再用掉第二张")

    def test_unknown_result_keeps_the_request_id_and_is_not_success(self):
        self.post_result = (None, b"timed out")
        self.assertEqual(self.run_cmd("--json"), 1)
        self.assertIn("credit_redeem", self.state["slots"][self.aid])

    def test_a_different_card_gets_a_fresh_request_id(self):
        """反向对照：请求号只在**同一张卡**上复用，否则永远发同一个 id。"""
        self.post_result = (200, json.dumps({"code": "x", "credit": None, "windows_reset": 0}).encode())
        self.run_cmd("--json")
        self.detail = [card("another", 1)] + self.detail
        self.run_cmd("--json")
        self.assertNotEqual(self.posts[0][1]["redeem_request_id"], self.posts[1][1]["redeem_request_id"])


import re
import tempfile  # noqa: F401  (保持与其它测试同形)

SRC = ROOT / "codexbar" / "src"
BASE = "http://127.0.0.1:3304/harness.html?nav=home"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Wiring(unittest.TestCase):
    def test_the_command_is_registered(self):
        self.assertIn("use-credit", CR.CMDS)

    def test_the_gui_may_call_it(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("const ALLOWED_CMDS")
        self.assertIn('"use-credit"', rs[i:rs.index("];", i)], "★★ 白名单没放行 —— 按钮点了只会报 disallowed command")

    def test_the_button_only_needs_an_expiry_date_not_a_usable_window(self):
        code = re.sub(r"\{/\*[\s\S]*?\*/\}", "", (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8"))
        i = code.index("onUseCredit && a.cards > 0")
        seg = code[i:i + 1400]
        # ★ 判据要打在**三元的条件本身**上（子串会在别的分支的 title 里也出现 —— 变异实测抓到过一次空守卫）。
        #   2026-10-01 用户拍板放开「额度见底才能用」：条件只剩「有到期日」。
        self.assertIn("a.cardExp ?", seg, "★★ 没按「有到期日」收口 —— CLI 要求有到期日，否则画出一个必被拒的按钮")
        self.assertNotIn("a.cardsUsable > 0 &&", seg, "★★ 又把「现在有可重置窗口」加回来了 —— 用户明确要求放开")

    def test_the_footer_badge_is_clickable_and_two_step(self):
        card = (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8")
        self.assertIn("onUse=", card, "★★ 角标没接 onUse")
        badge = re.sub(r"\{/\*[\s\S]*?\*/\}", "", (SRC / "components" / "CardBadge.tsx").read_text(encoding="utf-8"))
        self.assertIn("stopPropagation", badge, "★★ 点角标会同时触发卡片选中")
        self.assertIn("armed", badge, "★★★ 角标一点就直接用卡 —— 不可逆动作必须两段确认")


def _render():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import urllib.request
    try:
        urllib.request.urlopen(BASE, timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": 1300, "height": 900})
        pg.goto(BASE, timeout=30000); pg.wait_for_timeout(3000)
        n = pg.evaluate("document.querySelectorAll('[data-aid]').length")
        out = []
        for i in range(n):
            pg.evaluate(f"document.querySelectorAll('[data-aid]')[{i}].click()"); pg.wait_for_timeout(450)
            out.append(pg.evaluate("""() => { const c = document.querySelector('[data-aid][style*="border-color"], [data-aid]');
              const bar = document.querySelector('[data-actions]'); if (!bar) return null;
              const t = bar.innerText.replace(/\\n/g, ' ');
              return {text: t, disabled: bar.querySelectorAll('[data-use-credit-disabled]').length,
                      overflow: bar.scrollWidth > bar.clientWidth + 1}; }"""))
        br.close()
    return [o for o in out if o]


class RendersInTheActionBar(unittest.TestCase):
    def test_enabled_shows_the_expiry_and_is_not_clipped_disabled_is_marked(self):
        r = _render()
        if r is None:
            self.skipTest("没有 playwright 或 harness 静态服务（3304）没在跑")
        self.assertTrue(r, "★★ 一张卡的动作条都没渲染出来 —— 闸此刻没有判别力")
        enabled = [o for o in r if re.search(r"用卡 \d\d-\d\d", o["text"])]
        disabled = [o for o in r if o["disabled"]]
        self.assertGreaterEqual(len(enabled), 2, "★★ 有卡有到期日的号都该有「用卡 MM-DD」（含 applicable=0 的号，用户 2026-10-01 要求放开）")
        self.assertEqual(disabled, [], "★★ 夹具里每个有卡的号都有到期日，不该有被置灰的")
        self.assertFalse([o for o in enabled if o["overflow"]], "★ 按钮把动作条撑出了横向溢出")


def _badge_probe():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import urllib.request
    try:
        urllib.request.urlopen(BASE, timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": 1300, "height": 900})
        pg.goto(BASE, timeout=30000); pg.wait_for_timeout(3000)
        h0 = pg.evaluate("[...document.querySelectorAll('[data-aid]')].map(c=>Math.round(c.getBoundingClientRect().height))")
        n = pg.locator("[data-card-badge-use]").count()
        b = pg.locator("[data-card-badge-use]").first
        before = b.inner_text()
        b.click(); pg.wait_for_timeout(300)
        out = {"n": n, "before": before, "armed": b.inner_text(),
               "bars": pg.evaluate("document.querySelectorAll('[data-actions]').length"),
               "h_same": h0 == pg.evaluate("[...document.querySelectorAll('[data-aid]')].map(c=>Math.round(c.getBoundingClientRect().height))")}
        pg.wait_for_timeout(5400)
        out["after"] = b.inner_text()
        br.close()
    return out


class TheFooterBadgeIsATwoStepButton(unittest.TestCase):
    def test_first_click_only_arms_it_and_it_disarms(self):
        r = _badge_probe()
        if r is None:
            self.skipTest("没有 playwright 或 harness 静态服务（3304）没在跑")
        self.assertGreaterEqual(r["n"], 2, "★★ 页脚角标没有可点的 —— 闸此刻没有判别力")
        self.assertRegex(r["armed"], r"确认用 \d\d-\d\d\?", "★★★ 第一次点没有「上膛」—— 不可逆动作一点就花")
        self.assertEqual(r["bars"], 0, "★★ 点角标同时选中了卡片（没 stopPropagation）")
        self.assertTrue(r["h_same"], "★ 上膛后卡片高度变了 —— 页脚必须恒为一行")
        self.assertEqual(r["after"], r["before"], "★ 5 秒没二次点击应自动退回")


if __name__ == "__main__":
    unittest.main(verbosity=2)
