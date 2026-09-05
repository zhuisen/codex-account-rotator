"""陈旧的额度快照必须有标记,且池级不许用单个 max/min 冒充全池状态(2026-09-05)。

## 事故

一个 token 已失效的号被 `probe --all` 静默跳过,它的 quota 已经陈旧 **3.8 天**,
仍标着 `quota_status: "ok"`,卡片上**没有任何提示**;而池级「上次刷新」取的是
`max(captured_at)`,被每 300s 刷新的活号盖成「刚刚」——**主动把这件事藏了起来**。
`StaleMark` 此前只接了 grok/agy,codex 账号卡一个都没接。

## 三条口径（经 codex / grok / agy 三方评审收敛）

① ★★ **陈旧判据锚定采集心跳,不锚定窗口长度。**
   曾考虑按窗口比例（「周窗口陈旧 1 小时无所谓」），但那个前提是错的:
   周额度也可能几小时烧光,而一个 token 已失效 10 小时的号会因为「相对周窗口不算久」
   被判新鲜,调度器继续往黑洞里打请求。**窗口长度决定预算周期,不决定观测有效期。**
② ★★ **池级给覆盖度,不给单个 max/min。** 三方一致指出那是假两难:
   `max`（现状）被活号盖成「刚刚」,`min` 被一个弃用号永久拉垮、天天谎报全池故障。
   两者都证明不了「上次全池刷新成功」。
③ ★ **陈旧 ≠ 故障,不上告警色。** 合盖休眠唤醒的一瞬间全池都会陈旧,那是事实;
   把它染红只会训练用户忽略所有告警（agy 提出的边界）。

## 断言
判据只有一个真源（`QUOTA_STALE_SEC`）、缺 `captured_at` 给 `null` 不给 0、
池级返回覆盖度、账号卡真的接上了标记。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "codexbar" / "src" / "helpers.ts"
CARD = ROOT / "codexbar" / "src" / "components" / "AccountCard.tsx"


class StalenessCriterion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = TS.read_text(encoding="utf-8")

    def test_threshold_exists_and_is_anchored_to_polling(self):
        """★ 阈值必须是**采集周期的倍数**,不是拍的整数。quotad 全池扫描 300s。"""
        m = re.search(r"export const QUOTA_STALE_SEC = ([^;]+);", self.src)
        self.assertIsNotNone(m, "没有单一阈值真源")
        val = eval(m.group(1).replace("* 60", "* 60"))  # noqa: S307 — 源里只有算术
        self.assertGreaterEqual(val, 300 * 3, "阈值短于 3 个扫描周期 —— 一次抖动就会误报")
        self.assertLessEqual(val, 300 * 24, "阈值太长 —— 一个死了两小时的号还显示正常")

    def test_criterion_does_not_use_window_length(self):
        """★★ 口径①:判据里不许出现 window_minutes —— 那正是被三方否掉的做法。"""
        i = self.src.index("export function quotaAgeSec")
        body = self.src[i:self.src.index("\n}", i)]
        self.assertNotIn("window_minutes", body,
                         "陈旧判据用了窗口长度 —— 周额度也能几小时烧光,这个前提是错的")

    def test_missing_captured_at_is_null_not_zero(self):
        r"""★ 缺 `captured_at` ⇒ `null`(未知)。给 0 会被读成「刚刚读到的」——
        正好把最坏情况显示成最好的。

        ⚠️ 第一版这条是**空守卫**:它 `assertNotRegex(body, r"captured_at \?\? 0")`,
        而变异写的是 `cap ?? 0` —— **同前缀不等于同标识符**,拼写换一下就绕过去了。
        现在改成查行为形状:必须有一条「为空就返回 null」的早退,且函数体内
        **任何** `?? 0` 都不允许(那正是把未知抹成 0 的写法)。
        """
        i = self.src.index("export function quotaAgeSec")
        body = self.src[i:self.src.index("\n}", i)]
        self.assertRegex(body, r"==\s*null\s*\?\s*null",
                         "没有「为空 ⇒ null」的早退 —— 未知会被算成一个数")
        self.assertNotRegex(body, r"\?\?\s*0\b",
                            "函数体里出现了 `?? 0` —— 用 0 兜底缺失的时间戳,"
                            "会把「从没读到过」显示成「刚刚读到的」")

    def test_account_carries_age_and_flag(self):
        for f in ("quotaAgeSec: number | null", "quotaStale: boolean"):
            with self.subTest(field=f):
                self.assertIn(f, self.src)


class PoolLevelReportsCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = TS.read_text(encoding="utf-8")

    def test_pool_freshness_returns_counts_not_a_single_timestamp(self):
        """★★ 口径②:必须给覆盖度。"""
        self.assertIn("export function poolFreshness", self.src)
        i = self.src.index("export function poolFreshness")
        sig = self.src[i:i + 400]
        for k in ("fresh", "stale", "unknown", "oldestAgeSec"):
            with self.subTest(key=k):
                self.assertIn(k, sig, "覆盖度里缺 %s" % k)

    def test_old_max_helper_is_documented_as_insufficient(self):
        """`poolRefreshedAt` 保留（它回答的是另一个问题），但必须写明它不能读成「全池都新」。"""
        i = self.src.index("export function poolRefreshedAt")
        doc = self.src[max(0, i - 700):i]
        self.assertIn("poolFreshness", doc,
                      "旧的 max 版本没有指向覆盖度 —— 下一个人还会拿它当全池状态")


class NoOrphanFields(unittest.TestCase):
    """★★ 后端算出来、没人消费 = 孤儿字段,本仓明令的反模式。

    「后端有字段」不等于「已披露」—— 这条铁律在本仓被违反过不止一次,
    而且有一次**修那条规则的补丁本身**又新造了一个孤儿字段。
    """
    def test_unknown_accounts_enter_the_denominator(self):
        """★★ 评审抓出:`{fresh:1, stale:0, unknown:1}` 会显示成「全池 1 个都是新的」——
        把一个**从没读到过**的号说成新的,正是这条链路一路在防的那种谎。
        分母必须是**全部账号**,不是「我算得出来的那部分」。"""
        app = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
        i = app.index("freshness.fresh")
        seg = re.sub(r"\{/\*.*?\*/\}", "", app[max(0, i - 900):i + 900], flags=re.S)
        self.assertIn("freshness.unknown", seg,
                      "unknown 没有进池级展示 —— 从没读到过的号会被算成「新的」")
        self.assertRegex(seg, r"freshness\.fresh\s*\+\s*freshness\.stale\s*\+\s*freshness\.unknown",
                         "分母漏了 unknown")

    def test_pool_freshness_is_consumed_by_ui(self):
        src = "".join(p.read_text(encoding="utf-8")
                      for p in (ROOT / "codexbar" / "src").rglob("*.ts*")
                      if p.name != "helpers.ts")
        self.assertIn("poolFreshness", src,
                      "poolFreshness 只在 helpers 里算,没有任何 UI 消费 —— 孤儿字段")
        self.assertIn("freshness.stale", src,
                      "覆盖度算出来了但没画出来")


class CardActuallyShowsIt(unittest.TestCase):
    """★ 判据存在 ≠ 用户看得见。此前 StaleMark 只接了 grok/agy,codex 卡一个都没接。"""

    @classmethod
    def setUpClass(cls):
        cls.src = CARD.read_text(encoding="utf-8")

    def test_card_imports_and_renders_stale_mark(self):
        self.assertIn("import StaleMark", self.src)
        self.assertIn("a.quotaStale", self.src,
                      "账号卡没有消费 quotaStale —— 后端有字段不等于用户看得见")

    def test_stale_mark_is_not_alarm_coloured(self):
        """★★ 口径③:陈旧不是故障。染红会在每次休眠唤醒后全池亮红,训练用户忽略告警。"""
        i = self.src.index("a.quotaStale")
        seg = self.src[i:i + 700]
        self.assertIn('tone="muted"', seg,
                      "陈旧标记用了告警色 —— 合盖唤醒时全池会一起亮")
        for bad in ('tone="red"', 'tone="amber"'):
            with self.subTest(tone=bad):
                self.assertNotIn(bad, seg)

    def test_note_says_what_it_is_and_is_not(self):
        """文案要同时说清「这是几时的数」和「这不代表额度有问题」。"""
        i = self.src.index("a.quotaStale")
        seg = self.src[i:i + 900]
        self.assertIn("不是现在的值", seg)
        self.assertIn("不代表额度有问题", seg,
                      "只说旧、不说「这不是故障」,用户会当成告警")


if __name__ == "__main__":
    unittest.main()
