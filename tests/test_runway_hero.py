"""总览顶部的「续航条」（用户 2026-09-21 从六个方向的 demo 里选的 **D + 左侧账号环**）。

## 它取代的那条 banner 错在哪（两条都是实测，不是观感）

用户的原话是「感觉是弃用状态」。查下来不是长相旧，是**两个前提都已经不成立**：

1. 标题「当前使用中」读的是 `state.active` —— 那是**上次 CLI 切换**留下的，而代理是
   **逐请求**挑号。2026-09-21 实测到过两者不一致（`active=wing`，代理实际给 `Huo`）⇒
   那行标题**会错，且错得没有任何迹象**。现在取 `last_aid`（代理最近一次真的用了谁），
   并把「多久以前」写出来 —— 逐请求轮换下「正在」是有时效的。
2. 「建议切到 X」按剩余最多者算，**既不看置顶也不看停用** ⇒ 它会劝你推翻自己刚设的置顶，
   甚至推荐一个已 `rotate_off` 的号。而在「默认容量最高优先 + 置顶插队」之后，
   "手动挑最空的号"这件事本身就没有意义了。**整个按钮删除。**

## 新增的那个数：还能撑多久

用 `state.json` 的 `quota_marks`（额度跨整数百分点时记一条）算消耗速度。
★★★ 口径必须**跟着数字一起显示**，否则就是骗人：它是 **活跃小时**不是自然小时
（没在用 codex 时池子一点不掉），而且是过去 24h 的速度。样本不足时显示 `—`，
**绝不写 0** —— 「算不出来」与「撑不了多久」在这块版面上是相反的两件事。

## ★★ 高度是硬约束

用户：「不要增加目前的 banner 高度，可以降低但不能增加」。
旧 Hero 实测 **1300 宽下 112px、880 下 128px**。新的实测 **98px（两档都是）**。
闸量的是**渲染后的真实高度** —— 它由内边距 / 环尺寸 / 行高 / 换行四者合成，
断言源码里那几个常量会漏掉任何一种撑高的方式。
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
HARNESS = "http://127.0.0.1:3304"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: 旧 Hero 的实测高度（2026-09-21，替换前量的）。**这是上限，不是目标。**
OLD_HEIGHT = {1300: 112, 880: 128}

_PROBE = r"""
const out = {};
const el = document.querySelector('[data-runway-hero]');
if (el) {
  const r = el.getBoundingClientRect();
  out.h = Math.round(r.height);
  out.ov = Math.round(el.scrollWidth - el.clientWidth);
  out.segs = el.querySelectorAll('[data-runway-seg]').length;
  out.rest = el.querySelectorAll('[data-runway-rest]').length;
  out.hours = (el.querySelector('[data-runway-hours]') || {}).textContent || '';
  out.note = (el.querySelector('[data-runway-note]') || {}).textContent || '';
  out.pin = el.querySelectorAll('[data-runway-pin]').length;
  out.stranded = (el.querySelector('[data-runway-stranded]') || {}).textContent || '';
  out.borrowed = (el.querySelector('[data-runway-borrowed]') || {}).textContent || '';
  out.hoursEl = !!el.querySelector('[data-runway-hours]');
  // ★ 每段的**真实像素宽** + 它该写的名字 + 实际写了什么 + 有没有被裁。
  //   「装不装得下」是像素问题，判据就得拿像素来判 —— 拿占比当代理量已经错过一次。
  out.segw = [].slice.call(el.querySelectorAll('[data-runway-seg]')).map(function (n) {
    return { w: Math.round(n.clientWidth),
             name: (n.getAttribute('title') || '').split(' ')[0],
             shown: (n.textContent || '').trim(),
             over: n.scrollWidth > n.clientWidth + 1 };
  });
  const hEl = el.querySelector('[data-runway-hours]');
  const uEl = el.querySelector('[data-runway-unit]');
  out.unit = (uEl || {}).textContent || '';
  // ★ 「跟着数字一起显示」是字面要求：同一个父节点才算跟着。
  out.unitWithNumber = !!(hEl && uEl && hEl.parentNode === uEl.parentNode);
  out.text = (el.textContent || '').replace(/\s+/g, ' ');
}
// ⚠️ **必须 `innerText` 不能 `textContent`**：harness 把探针脚本**内联进 body**，
// 而 `textContent` 连 `<script>` 里的源码一起算 —— 第一版因此命中了探针自己注释里的
// 「当前使用中」四个字，两档全假红。`innerText` 只取渲染出来的文字。
out.oldHero = /当前使用中|建议切到/.test(document.body.innerText || '');
document.title = '__RH__' + JSON.stringify(out);
"""


def _probe(width=1300, query="nav=home"):
    import urllib.request
    src = APP_DIR / "harness.html"
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / "rhprobe.html"
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>setTimeout(() => {{{_PROBE}}}, 2600);</script></body>", 1),
        encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            f"--window-size={width},900", "--virtual-time-budget=9000",
                            "--dump-dom", f"{HARNESS}/rhprobe.html?{query}"],
                           capture_output=True, text=True, timeout=180)
        m = re.search(r"__RH__(\{.*?\})\s*</title>", r.stdout, re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        page.unlink(missing_ok=True)


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class ItNeverGetsTallerThanTheBannerItReplaced(unittest.TestCase):
    """★★★ 用户给的硬约束：「可以降低但不能增加」。"""

    #: ★★★ **每个会改变版面的分支都要量，不能只量默认那一档。**
    #
    #   2026-09-21 实测：见底态在 880 下右列被挤到第二行，hero 从 94px 撑到 **167px**
    #   —— 而当时这条闸只跑默认夹具，**全绿**。根因是 flex 按 `flex-basis` 分行而
    #   左列写的是 `auto`（取 max-content）；收缩只发生在行内，救不回换行的那一下。
    #   ★ 一条只覆盖了默认分支的尺寸闸，在其余分支上**等于不存在**。
    CASES = [("正常", "nav=home"), ("见底", "nav=home&pool=stranded")]

    @classmethod
    def setUpClass(cls):
        cls.r = {(w, name): _probe(w, q) for w in OLD_HEIGHT for name, q in cls.CASES}
        if any(v is None for v in cls.r.values()):
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_it_actually_rendered(self):
        """★★ 先正面证明它在 —— 没渲染时「高度 ≤ 上限」会因为 `h` 缺失而假绿。"""
        for (w, name), d in self.r.items():
            with self.subTest(width=w, case=name):
                self.assertIn("h", d, f"{w} 宽 · {name} 下续航条没渲染：{d}")
                self.assertGreater(d["h"], 40, f"{w} 宽 · {name} 下高度异常：{d['h']}")

    def test_height_never_exceeds_the_old_hero(self):
        for (w, name), d in self.r.items():
            with self.subTest(width=w, case=name):
                self.assertLessEqual(d["h"], OLD_HEIGHT[w],
                                     f"★★★ {w} 宽 · {name} 下高 {d['h']}px，"
                                     f"超过旧 banner 的 {OLD_HEIGHT[w]}px")

    def test_it_never_overflows_sideways(self):
        """★ 横向溢出与撑高是同一族缺陷的两个出口：装不下时要么换行(撑高)要么溢出。
        只守一侧时，另一侧的退化**完全看不见**。"""
        for (w, name), d in self.r.items():
            with self.subTest(width=w, case=name):
                self.assertLessEqual(d.get("ov", 0), 1,
                                     f"★ {w} 宽 · {name} 下横向溢出 {d.get('ov')}px")

    def test_the_old_banner_is_really_gone(self):
        """★ 「当前使用中」与「建议切到」两句都必须从 **codex 档**消失。

        ⚠️ 范围是 codex 档 —— **Gemini 档那条 hero 没有过时，别顺手删**：
          agy 是**启动前**换凭证、没有逐请求挑号器，所以在那一档「当前使用中」是真话，
          「建议切到」也确实是你要手动做的动作。两档的机制本来就不同。
        """
        for (w, name), d in self.r.items():
            with self.subTest(width=w, case=name):
                self.assertFalse(d["oldHero"],
                                 f"★ {w} 宽 · {name} 下旧 banner 的文案还在")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheHonestyLineTravelsWithTheNumber(unittest.TestCase):
    """★★★ 「5.9 小时」离开那句口径就是假话 —— 它是**活跃小时**不是自然小时。"""

    @classmethod
    def setUpClass(cls):
        cls.ok = _probe(1300)
        cls.none = _probe(1300, "nav=home&runway=none")
        #: `?runway=none` 夹具里的样本数（make_harness.py 的 `next --json` 桩）。
        cls.none_samples = 3
        if cls.ok is None or cls.none is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_the_unit_is_stated_next_to_the_number(self):
        """★ 判据打在**单位自己的节点**上，不是整条 hero 的文本。

        ⚠️ 第一版写的是 `assertIn("活跃小时", text)`，而下面那行披露里也有这四个字
          （「活跃小时不是自然小时」）⇒ **把数字旁边的单位整个删掉它照样绿**。
          本仓空守卫形态③。`unitWithNumber` 再管住「跟着」二字：同父节点。
        """
        self.assertEqual("活跃小时", self.ok["unit"],
                         "★★★ 没写「活跃小时」—— 这个数会被读成自然小时")
        self.assertTrue(self.ok["unitWithNumber"],
                        "★★ 单位没和数字在同一行 —— 离开那个数它就不是披露了")
        self.assertIn("样本", self.ok["note"], "★★ 没写样本数 —— 无从判断这个估计靠不靠谱")

    def test_when_it_cannot_be_computed_it_says_so_instead_of_zero(self):
        """★★★ 「算不出来」与「撑不了多久」是相反的两件事，而 0 会被读成后者。

        ⚠️ 这一档**必须有夹具**（`?runway=none`）—— 本机样本一直充足，
          没有开关的话这条分支一个像素都验不到，而截图会正常渲染、探针报干净。
        """
        self.assertIn("—", self.none["hours"],
                      f"★★★ 算不出来时没显示「—」：{self.none['hours']!r}")
        self.assertNotIn("0", self.none["hours"], "★★★ 算不出来时写了 0")
        # ★ 判据用「算不出来」——**只有这一支才有**的词。第一版用的是「不是」，
        #   而另一支写着「活跃小时**不是**自然小时」⇒ 把这一支整句删掉照样绿（形态⑩：
        #   这条断言的绿是隔壁那句给的）。变异当场抓到，顺带暴露出它是条**死分支**。
        self.assertIn("算不出来", self.none["note"],
                      f"★★ 显示「—」却没说为什么：{self.none['note']!r}")
        self.assertIn(str(self.none_samples), self.none["note"],
                      "★ 没写现有几条样本 —— 用户无从判断再等多久会有数")
        # ★★ 反向：算得出来的时候**不许**挂着这句借口，否则它退化成常驻噪音。
        self.assertNotIn("算不出来", self.ok["note"],
                         "★★ 续航算得出来却还挂着「算不出来」")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class ItSaysSoWhenThePoolRunsDry(unittest.TestCase):
    """★★★ 「系统推翻了你的设置」必须当面说，不能只写进 proxy.log。

    2026-09-21 真实事故：九个号里 5 个冷却 / 3 个被手动停用 / 1 个凭证失效 ⇒ 一个可用的
    都没有，代理走最后一层兜底**借用了一个已停用的号**（这是设计：在「codex 整个不能用」
    与「多用一个你不想用的号」之间选后者）。它把 `⚠️ 所有号都被停用了自动轮换` 写进了
    `proxy.log` —— **而用户不读 proxy.log**。他看到的是卡片上冒出一个不该出现的号，
    报过来的原话是「轮换失效了，禁用轮换的账号也被使用了」。

    ★ 缺的从来不是那条判断，是**披露**。本仓规矩：告警放在眼睛已经在的地方，
      且文本要说「做什么」。
    ⚠️ 这一档**必须有夹具**（`?pool=stranded`）—— 本机绝大多数时候池子是好的，
      没有开关的话这条分支一个像素都验不到，而截图会正常渲染、探针报干净。
    """

    @classmethod
    def setUpClass(cls):
        cls.dry = _probe(1300, "nav=home&pool=stranded")
        cls.ok = _probe(1300)
        if cls.dry is None or cls.ok is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_it_says_the_pool_is_dry(self):
        self.assertIn("不可用", self.dry["stranded"],
                      f"★★★ 池子见底却没说：{self.dry['stranded']!r}")

    def test_it_says_which_account_it_had_to_borrow(self):
        """★★ 「这个号本来不该被用」要写在**号名旁边** —— 那是眼睛第一个落点。"""
        self.assertIn("临时借用", self.dry["borrowed"],
                      "★★ 借用了一个不可用的号却没标出来 —— 用户只会看到设置被无视")

    def test_it_breaks_down_why_and_says_what_to_do(self):
        """★ 只说「坏了」没用：要说**各是什么原因**，以及此刻能动的那个旋钮。"""
        note = self.dry["note"]
        for word in ("冷却", "停用", "失效"):
            with self.subTest(word=word):
                self.assertIn(word, note, f"★ 没说清有几个是「{word}」：{note!r}")
        self.assertIn("打开轮换", note,
                      "★★ 没告诉用户怎么办 —— 停用的号是他此刻唯一能动的旋钮")

    def test_it_never_prints_a_zero_hour_runway_when_dry(self):
        """★★★ 见底时可用池的余量恰好是 0，算出来就是「续航 ≈ 0 小时」——**那是假话**。

        冷却的号一小时内就回来。「撑不了多久」与「暂时被锁在外面」是相反的两件事，
        而这块版面上 0 会被读成前者。所以这一支**根本不画那个数字**，改说多久回来。
        """
        self.assertFalse(self.dry["hoursEl"],
                         "★★★ 池子见底时仍在画续航数字 —— 它此刻恒为 0，是假话")
        self.assertIn("分钟后回来", self.dry["text"],
                      "★★ 没说多久能恢复 —— 那是用户唯一想知道的数")

    def test_the_borrow_tag_dies_with_the_borrow(self):
        """★★★ 「临时借用」只在**借用仍在发生**时亮，不许描述几小时前那一次。

        用户 2026-09-21 截图：池子早已恢复（4 个号可用、下一个是 wing），顶部却还挂着
        红色的「临时借用 qq55」—— 那说的是 **3 小时前**的事。`cur` 是 `last_aid`
        （代理最近一次用了谁），它天然会落后于现在。
        ★ **一盏描述过去、却长得像现在的红灯**，本仓判过死刑：它训练用户忽略所有告警。
          披露的寿命跟着它描述的那个事实走，事实结束它就该灭。

        ⚠️ 这一条**必须用 `?pool=recovered`**：默认夹具里 `cur` 本来就可用，
          改不改判据它都是绿的（形态⑩：判据档位要挑只有被测那条能挡住的输入）。
        """
        r = _probe(1300, "nav=home&pool=recovered")
        if r is None:
            self.skipTest("harness 静态服务（3304）没在跑")
        self.assertGreaterEqual(r["segs"], 1, "★ 夹具没让池子恢复 —— 前提不成立，这条验不到")
        self.assertEqual("", r["borrowed"],
                         "★★★ 池子已恢复，却还挂着「临时借用」—— 那是几小时前的事")
        self.assertEqual("", r["stranded"], "★★ 池子已恢复却还报见底")

    def test_the_alarm_is_absent_when_the_pool_is_fine(self):
        """★★ 反向：池子正常时**不许**挂着这条告警。

        一盏长亮又无从消除的灯，本仓判过死刑 —— 它训练用户忽略所有指示器。
        """
        self.assertEqual("", self.ok["stranded"], "★★ 池子正常却报见底")
        self.assertEqual("", self.ok["borrowed"], "★★ 池子正常却说在临时借用")
        self.assertTrue(self.ok["hoursEl"], "★ 池子正常时反而不画续航数字了")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheBarSaysWhoIsInAndWhoIsOut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _probe(1300)
        # ★ 两档都要量：「装得下」在不同窗宽下是**不同的**结论，
        #   只量一档就是把那一档当成了全部（这正是上面那条缺陷的成因）。
        cls.by_width = {w: _probe(w) for w in (1300, 880)}
        if cls.r is None or any(v is None for v in cls.by_width.values()):
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_every_usable_account_gets_a_segment(self):
        self.assertGreaterEqual(self.r["segs"], 3, f"色带里段数太少：{self.r['segs']}")

    def test_the_unusable_ones_are_one_merged_segment(self):
        """★★ 合成一段，不是每号一段。实测：三个灰段各 11px 宽而名字要 22px ⇒
        **每一个都横向溢出**，且 11px 上的名字本来就读不出内容。"""
        self.assertEqual(self.r["rest"], 1,
                         f"★★ 不可用的号不是合成一段：{self.r['rest']}")

    def test_a_name_is_either_written_in_full_or_not_at_all(self):
        """★★ 截断的名字比没有名字**更糟** —— `Ase…` 会被读成另一个号。"""
        for w, d in self.by_width.items():
            for seg in d["segw"]:
                with self.subTest(width=w, seg=seg["name"]):
                    self.assertFalse(seg["over"],
                                     f"★★ 「{seg['shown']}」被裁了（{seg['w']}px）")

    def test_a_segment_wide_enough_shows_its_name(self):
        """★★★ 反向：**写得下就必须写**，否则那一段只是一块无名色块。

        ⚠️ 这条是 2026-09-21 实测缺陷的闸。第一版按「占比 ≥ 0.14」判，而占比**不是宽度** ——
          1300 宽下 `Egan` 那段占 13.1%，换算 **75px**，4 个字母只要 28px，却被挡掉了。
          阈值当时是按 880 标定的，**一次观测被当成了保证**。
        ★ 这里用 `7px/字` 的**宽松上界**（真实 ≈5.6）——判据只对"绰绰有余"的段开口，
          边界段两可，不制造假红：一条会假红的闸，用户学会的是忽略它。
        """
        for w, d in self.by_width.items():
            for seg in d["segw"]:
                need = len(seg["name"]) * 7 + 12
                if seg["w"] >= need:
                    with self.subTest(width=w, seg=seg["name"]):
                        self.assertEqual(seg["name"], seg["shown"],
                                         f"★★★ {seg['w']}px 写得下「{seg['name']}」"
                                         f"（只要 {need}px）却没写")

    def test_the_pin_is_visible_on_the_banner(self):
        """★ 置顶决定钱花在哪个号上 —— 顶部这条是最该说出来的地方。"""
        self.assertGreaterEqual(self.r["pin"], 1, "★ 置顶角标没画出来")


class TheOrderComesFromTheOneImplementation(unittest.TestCase):
    """★★★ 「下一个请求会用谁」只许有**一份**实现。

    前端有账号数据但没有挑号器；照着排序键再写一份 TS，两份必然分叉，而症状是
    **界面信誓旦旦地报一个代理根本不会挑的号，两边都不报错**。
    本仓已经因为"测试抄了一份排序键"栽过一次（改真排序行对闸毫无影响）。
    """

    def test_the_cli_imports_the_real_picker(self):
        """★ 判据打在**代码形态**上，不是「这几个字出现过」。

        ⚠️ 第一版写的是 `assertIn("PX.usable(", seg)` —— 而 `rest = …not PX.usable…`
          那一行也含这个子串 ⇒ **把候选那一行换成自己写的判据它照样绿**
          （本仓空守卫形态①：子串存在 ≠ 规则存在）。变异当场抓到。
        ★ 候选与排除**必须是同一个谓词的两面**，所以两行都断言 —— 只断言一侧时，
          它在没覆盖的那一向上等于不存在（形态⑪）。
        ⚠️ 取上下文用**函数边界**不是定长切片：`src[i:i+2600]` 会滑进下一个函数
          （形态：定长切片取上下文是危险的）。
        """
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        i = src.index("def cmd_next")
        j = src.index("\ndef ", i + 1)
        seg = "\n".join(l for l in src[i:j].splitlines() if not l.strip().startswith("#"))
        self.assertIn("if PX.usable(a, sl, now)]", seg,
                      "★★★ 候选不是代理那份判据算出来的")
        self.assertIn("if not PX.usable(a, sl, now)]", seg,
                      "★★★ 排除不是同一个判据的另一面 —— 会出现两边都不认的号")
        self.assertIn("PX._sort_avail(", seg, "★★★ `next` 没用代理那份排序")

    def test_the_frontend_does_not_reimplement_it(self):
        hook = (SRC / "hooks" / "useRotationBoard.ts").read_text(encoding="utf-8")
        code = re.sub(r"(?<![:/])//.*", "", re.sub(r"/\*[\s\S]*?\*/", "", hook))
        # ⚠️ 2026-09-21：链路改道后这条断言**跟着延长一段**，不变量一个字没变。
        #   前端不再直接点名 `next --json`（那走的是会广播的 `run_rotate`，造出了自激回环），
        #   改走只读 IPC `read_rotation_board`；而那条 Rust 命令里跑的**仍然是**
        #   `codex-rotate next --json`。所以判据从「前端提到 next」变成
        #   **「前端 → 只读 IPC → 真 CLI」三段都在**，比原来更强：
        #   它同时挡住「前端自己算」和「Rust 桩里返回假数据」两种退化。
        self.assertIn('invoke<string>("read_rotation_board")', code,
                      "★★ 前端没走那条只读 IPC")
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("async fn read_rotation_board")
        seg = rs[i:rs.index("\n}", i)]
        self.assertIn('arg("next").arg("--json")', seg,
                      "★★★ 那条只读 IPC 没去跑真的 `codex-rotate next --json`")
        for banned in ("sort(", "_pin_rank", "plan === \"pro\""):
            self.assertNotIn(banned, code,
                             f"★★★ 前端自己排序了（`{banned}`）—— 那是第二份实现")

    def test_the_filter_is_shared_too(self):
        """★ 候选判据（dead / 冷却 / 停用）同样只许一份 —— 2026-09-21 从 `_pick` 抽出。"""
        px = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in px.splitlines() if not l.strip().startswith("#"))
        self.assertIn("def usable(aid, sl, now):", code, "★ 公共判据不在了")
        self.assertIn("usable(aid, sl, now)", code.split("def _pick")[1][:900],
                      "★★ `_pick` 没走那份公共判据 —— 两边会分叉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
