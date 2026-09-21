"""**一次悬浮只许出一个说法**（用户 2026-09-21：「取消鼠标悬浮出现 2 个提示悬浮弹窗」）。

## 缺陷长什么样

自定义浮层（`.cb-hoverpop`）的**触发元素**上又挂了原生 `title` ⇒ 鼠标停上去，
系统提示与浮层**同时弹出两层**，而它们说的是同一件事。

实测 2026-09-21（真 DOM，六个页面）：

| | 修前 | 修后 |
|---|---|---|
| 触发角标自带 `title` | 2（`routeBadge` / `dailyBadge`） | **0** |
| 浮层内与底部图例**逐字重复**的 `title` | 20 | **0** |
| 浮层内**独有信息**的 `title`（`N 次请求 · M token`） | 10 | 10（保留） |

★ 判据不是「浮层里一个 `title` 都不许有」—— 格子里那句带的是浮层**没有**的明细，
  删掉是丢信息。要删的是**重复**：与浮层标题、或与浮层底部图例逐字相同的那些。

★★ 顺带删掉一句**假话**：`routeBadge` 的 title 写着「近 90 天」，而那个窗口
  2026-09-10 起就跟着页面档位走（现在是 30d）。**披露层说旧事实比不说更糟** ——
  它正好会让人按错误的窗口去读那几个数。

## 为什么必须是行为闸

「有没有两层同时弹出」是 DOM 关系（触发元素 ⊇ 浮层）决定的，源码里两处可能隔着
几十行、也可能在不同文件。静态 grep 只能查已知的写法，查不到下一个人新加的。
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "http://127.0.0.1:3304"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: 六个页面全扫。★ 只扫一页会漏掉别页新加的浮层 —— 这条闸的价值正在于"下一个"。
PAGES = ["platform:codex", "home", "logs", "relay", "traffic", "settings"]

_PROBE = r"""
const out = { triggers: [], inside: [] };
for (const el of document.querySelectorAll('[title]')) {
  const ttl = (el.getAttribute('title') || '').trim();
  const id = (el.dataset && Object.keys(el.dataset)[0]) || el.tagName;
  const wrap = el.closest('.cb-hoverwrap');
  if (!wrap) continue;
  // ★★★ 判据：`.cb-hoverwrap:hover .cb-hoverpop` —— **悬浮在 wrap 里的任何地方**
  //   都会展开浮层。所以「触发侧」= 在 wrap 里、且**不在 pop 里**。
  //   ⚠️ 第一版写的是 `el.querySelector('.cb-hoverpop') || el.matches('.cb-hoverwrap')`，
  //     而角标是浮层的**兄弟**（既不包含它、也不是 wrap 本身）⇒ 一个都逮不到。
  //     变异实测当场抓到：把 title 挂回角标，闸照样绿。**闸自己是空的**。
  const inPop = el.closest('.cb-hoverpop');
  if (!inPop) { out.triggers.push({ id: id, title: ttl.slice(0, 60) }); continue; }
  // ② 浮层**内部**的 title：只在它与浮层里已有的文字重复时才算缺陷
  const body = inPop.textContent || '';
  if (ttl && body.includes(ttl)) out.inside.push({ id: id, title: ttl.slice(0, 60) });
}
out.nodes = document.querySelectorAll('*').length;
out.titles = document.querySelectorAll('[title]').length;
out.pops = document.querySelectorAll('.cb-hoverpop').length;
document.title = '__DT__' + JSON.stringify(out);
"""


def _probe(nav):
    import urllib.request
    src = APP_DIR / "harness.html"
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / "dtprobe.html"
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>setTimeout(() => {{{_PROBE}}}, 2600);</script></body>", 1),
        encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            "--window-size=1400,1000", "--virtual-time-budget=9000",
                            "--dump-dom", f"{HARNESS}/dtprobe.html?nav={nav}&hover=1"],
                           capture_output=True, text=True, timeout=180)
        m = re.search(r"__DT__(\{.*?\})\s*</title>", r.stdout, re.S)
        return (json.loads(m.group(1)), r.stdout) if m else None
    finally:
        page.unlink(missing_ok=True)


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OneHoverShowsOneThing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {}
        for nav in PAGES:
            r = _probe(nav)
            if r is None:
                raise unittest.SkipTest("harness 静态服务（3304）没在跑")
            cls.res[nav] = r

    def test_the_pages_actually_rendered(self):
        """★★ 先正面证明页面在 —— 零渲染时「没有重复 title」恒真，与通过长得一样。

        ⚠️ 判据用**探针自己数的节点数**，不用某个 `data-` 属性：这个探针会把
          `document.title` 覆盖掉（harness 自己的 `__PROBE__` 就在那里），而
          `data-page-body` 也不是每个页面都有 —— 第一版拿它当判据，六页全假红。
        """
        for nav, (d, _dom) in self.res.items():
            with self.subTest(nav=nav):
                self.assertGreater(d.get("nodes", 0), 150, f"nav={nav} 几乎没渲染：{d}")
                self.assertGreater(d.get("titles", 0), 0,
                                   f"nav={nav} 一个 title 都没有 —— 探针没东西可看")

    def test_the_probe_has_something_to_look_at(self):
        """★★ 若全 app 一个 `.cb-hoverpop` 都没渲染，这条闸就没有判别力。"""
        total = sum(d.get("pops", 0) for d, _ in self.res.values())
        self.assertGreater(total, 0, "★★ 一个自定义浮层都没渲染 —— 这条闸此刻是空的")

    def test_no_popup_trigger_also_carries_a_native_title(self):
        """★★★ 这就是用户报的那条：悬浮时两层同时弹出，且说的是同一件事。"""
        bad = [(nav, x) for nav, (d, _) in self.res.items() for x in d["triggers"]]
        self.assertEqual(bad, [],
                         "★★★ 浮层的触发元素上又挂了 `title` —— 悬浮会弹出两层：\n  "
                         + "\n  ".join(f"{n}: {x['id']} → {x['title']}" for n, x in bad))

    def test_no_title_inside_a_popup_repeats_what_the_popup_already_says(self):
        """★★ 浮层里的 `title` **不是一律禁止** —— 带独有明细的要留（删了是丢信息）。
        禁的是**逐字重复**：与浮层正文（含底部图例）相同的那些。"""
        bad = [(nav, x) for nav, (d, _) in self.res.items() for x in d["inside"]]
        self.assertEqual(bad, [],
                         "★★ 浮层里有与正文逐字重复的 `title`：\n  "
                         + "\n  ".join(f"{n}: {x['id']} → {x['title']}" for n, x in bad))


class TheStaleWindowClaimIsGone(unittest.TestCase):
    """★ 那句 title 还写着「近 90 天」，而窗口 2026-09-10 起跟着页面档位走。

    **披露层说旧事实**比不说更糟 —— 它正好会让人按错误的窗口去读那几个数。
    """

    def test_no_hardcoded_90_day_claim_on_the_route_badge(self):
        """⚠️ **断言前必须剥注释** —— 本仓形态④，我在这条闸上当场又犯了一次：
        第一版直接对原文断言，而**解释「为什么删掉近 90 天」的那段注释里**正写着
        「近 90 天」四个字 ⇒ 恒红。注释密度高的仓里，词匹配永远会撞上说明文字。
        """
        raw = (ROOT / "codexbar" / "src" / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8")
        src = re.sub(r"(?<![:/])//.*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", raw))
        i = src.index("data-route-badge")
        self.assertNotIn("近 90 天", src[max(0, i - 400):i + 400],
                         "★ 「近 90 天」这句假话又回来了 —— 窗口是跟着档位走的")


if __name__ == "__main__":
    unittest.main(verbosity=2)
