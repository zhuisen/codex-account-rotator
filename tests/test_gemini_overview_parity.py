"""Gemini 账号版块与 Codex 同形（用户 2026-09-24：「这些都是 gemini 账号版块做不到位、不统一的地方」）。

用户点名三处，修前实测（harness 1300×900）：
① 顶栏右侧「最近刷新 · N/M 新鲜」只在 Codex 档有；
② 停用轮换的 ⊘ 角标只在 codex 卡上画；
③ Gemini 卡 179px vs codex 卡 156px —— 页脚写成 `flexDirection: column`，隐形占位徽章自成第二行，
   多出来的 23px 全是底部空白。

行为闸打在**渲染后的页面**上（高度 / 角标数 / 新鲜度行），静态闸只守「两档共用同一份文案实现」。
harness（127.0.0.1:3304）或 playwright 不在时行为闸 skip —— skip 不是绿。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "codexbar" / "src" / "App.tsx"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness.html?nav=home"

_CACHE = {}


def _render(query):
    if query in _CACHE:
        return _CACHE[query]
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
        pg.goto(BASE + query, timeout=30000)
        pg.wait_for_timeout(3000)
        out = pg.evaluate("""() => {
          const g = document.querySelector('[data-cards-grid]');
          const cards = g ? [...g.children].filter(c => c.hasAttribute('data-aid')) : [];
          const f = document.querySelector('[data-agy-freshness]');
          return { heights: cards.map(c => Math.round(c.getBoundingClientRect().height)),
                   off: g ? g.querySelectorAll('[data-rotate-off]').length : -1,
                   fresh: f ? f.textContent : null };
        }""")
        br.close()
    _CACHE[query] = out
    return out


def _need(q):
    r = _render(q)
    if r is None:
        raise unittest.SkipTest("没有 playwright 或 harness 静态服务（3304）没在跑")
    return r


class TheCardsAreTheSameHeight(unittest.TestCase):
    def test_gemini_cards_match_codex_cards(self):
        codex, gem = _need(""), _need("&agypool=3&click=Gemini")
        self.assertTrue(codex["heights"] and len(gem["heights"]) == 3,
                        f"★★ 夹具没渲染出卡片（codex {codex['heights']} / gemini {gem['heights']}）—— 闸此刻没有判别力")
        self.assertEqual(set(gem["heights"]), {max(codex["heights"])},
                         f"★★ Gemini 卡 {gem['heights']} 与 codex 卡 {codex['heights']} 不等高 —— 页脚又折成两行了？")


class TheRotateOffBadgeIsDrawn(unittest.TestCase):
    def test_present_when_an_account_is_off(self):
        self.assertEqual(_need("&agypool=3&click=Gemini")["off"], 1,
                         "★★ 夹具里第 3 个号 rotate_off，Gemini 卡上却没有 ⊘")

    def test_absent_when_none_is_off(self):
        """反向：没有停用的号时一个都不许画（防「恒画」的空闸）。"""
        self.assertEqual(_need("&agypool=3&agyrotoff=0&click=Gemini")["off"], 0)


class TheFreshnessLineIsShared(unittest.TestCase):
    def test_gemini_tab_shows_it(self):
        f = _need("&agypool=3&click=Gemini")["fresh"]
        self.assertIsNotNone(f, "★★ Gemini 档没有新鲜度行")
        self.assertRegex(f, r"新鲜|都是新的|尚未刷新")

    def test_both_tabs_use_one_formatter(self):
        """★ 文案只有一份实现（`helpers.ts::freshnessLine`）—— 两处各写一套迟早只改一边。"""
        c = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", APP.read_text(encoding="utf-8"))
        self.assertEqual(c.count("{freshnessLine("), 2)
        self.assertNotIn("个陈旧", c, "★ App.tsx 里又手写了一份新鲜度文案")


if __name__ == "__main__":
    unittest.main(verbosity=2)
