"""「谁在被用」在界面上只许有**一个**答案，而且必须来自真挑号器。

## 起因（2026-09-21 用户截图）

一屏上同时出现三个都读作「在用」的东西：

  · 顶部 `正在使用 qq55 [临时借用]`  —— `last_aid`，代理最近真的用了谁
  · wing 卡 `当前` + 动作条 `✓ 当前`  —— `state.active`，**上次 CLI 切换**，只有直连才用
  · Yu 卡 `USE`                      —— `recommended()` = **剩余最多**

用户原话：「一个界面出现了三个使用」。三者含义各不相同，但文案让人读成同一件事。

## 其中 `USE` 是一句**假话**，不只是重名

`recommended()` 按「剩余最多」排，**既不看置顶也不看停用**。截图当场证伪：
Yu（置顶 #2、剩 51%）挂着 `USE`，而真挑号器 `codex-rotate next` 说**下一个是 wing**（置顶 #1）。

★★ 它与同日从 banner 上删掉的「建议切到 X」是**同一份作废逻辑**，只是换成了角标形态。
  本仓铁律：「下一个请求会用谁」只许有一份实现 —— 前端有账号数据但**没有挑号器**，
  照着排序键再写一份，症状就是**界面信誓旦旦地报一个代理根本不会挑的号，两边都不报错**。

## 定稿（用户逐项选的）

| 位置 | 文案 | 真源 |
|---|---|---|
| 顶部续航条 | 正在使用 / 下一个 | `codex-rotate next`（`board`） |
| 卡片高亮角标 | **下一个** | 同上的 `board.next` |
| 卡片右上角标 | **直连** | `state.active`（auth.json 里那个号） |

⚠️ **agy 档保留 `USE`**：agy 没有逐请求挑号器，手动切号就是它的机制，
  「推荐切到谁」在那边仍然成立。判据因此不能写成「全库不许出现 USE」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"


def _strip(src: str) -> str:
    """★ 断言前剥注释 —— 这几份文件的注释里**逐字写着** `recommended()` 和 `USE`，
    不剥的话断言会撞上正在解释这条规则的说明文字（本仓形态④，踩过五次）。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(?<![:/])//[^\n]*", "", src)


def _call_site(src: str, needle: str, span: int = 1400) -> str:
    """取 `<AccountCard …>` / `<AccountRow …>` 这一处调用的完整属性串。"""
    i = src.find(needle)
    if i < 0:
        return ""
    j = src.find("/>", i)
    return src[i:j if j > 0 else i + span]


class TheCodexTabHasExactlyOneAnswer(unittest.TestCase):
    APP = property(lambda self: _strip((SRC / "App.tsx").read_text(encoding="utf-8")))
    MB = property(lambda self: _strip((SRC / "MenuBar.tsx").read_text(encoding="utf-8")))

    def test_the_card_highlight_comes_from_the_real_picker(self):
        """★★★ 卡片的高亮角标必须由 `board.next` 驱动，不是 `recommended()`。"""
        call = _call_site(self.APP, "<AccountCard")
        self.assertTrue(call, "★★ 找不到 codex 档的卡片调用 —— 断言打空了")
        self.assertIn("isBest={board?.next?.aid === a.aid}", call,
                      "★★★ 卡片高亮不是来自真挑号器 —— 它会报一个代理不会挑的号")
        self.assertNotIn("hero?.aid", call,
                         "★★★ 又用回了 `recommended()`（剩余最多，不看置顶不看停用）")

    def test_the_menubar_says_the_same_thing(self):
        """★★ §5c 页面统一性：同一件事在两个界面必须来自同一处。

        此前菜单栏与总览**各挂一份** `recommended()`，说的是同一句假话。
        """
        call = _call_site(self.MB, "<AccountRow")
        self.assertTrue(call, "★★ 找不到菜单栏的账号行调用 —— 断言打空了")
        self.assertIn("mbBoard?.next?.aid === a.aid", call,
                      "★★ 菜单栏的高亮角标没走真挑号器")
        self.assertNotIn("hero?.aid", call, "★★ 菜单栏又用回了 `recommended()`")

    def test_the_two_surfaces_do_not_use_two_different_sources(self):
        """★ 双向：两边都必须是 `board.next`，只改一边等于制造了新的不一致。"""
        for name, src in (("App.tsx", self.APP), ("MenuBar.tsx", self.MB)):
            with self.subTest(f=name):
                self.assertIn("useRotationBoard(", src,
                              f"★ {name} 没接真挑号器")

    def test_the_codex_card_does_not_say_当前(self):
        """★★ 「当前」与顶部的「正在使用」撞名却说的是另一回事（直连号 vs 代理在用）。

        ⚠️ 判据打在**传给组件的文案**上，不是全文搜「当前」——
          动作条里「✓ 当前」「把当前号切到 X」等等都合法，全文搜必假红，
          而一条会假红的闸，用户学会的是忽略它（本仓形态④/⑫）。
        """
        call = _call_site(self.APP, "<AccountCard")
        self.assertIn('curLabel="直连"', call,
                      "★★ codex 卡片的右上角标没改成「直连」—— 与顶部「正在使用」撞名")
        self.assertIn("curTitle=", call, "★ 改了名就必须给一句解释它到底是什么")

    def test_the_agy_tab_keeps_its_own_wording(self):
        """★ agy **没有逐请求挑号器**，手动切号就是它的机制 ——
        那边的「推荐切到谁」仍然成立，别顺手一起改掉。"""
        agy = _call_site(self.APP, "isBest={agyBest?.sub === a.sub}")
        self.assertTrue(agy, "★★ 找不到 agy 档的卡片调用 —— 断言打空了")
        self.assertNotIn("bestLabel=", agy,
                         "★ agy 档不该被改成「下一个」—— 它没有逐请求挑号器")


class TheBorrowFallbackIsSwitchable(unittest.TestCase):
    """★★ 用户 2026-09-21：「我明明停止轮换了，应该就不能去调用」。

    代理最后一层兜底原本硬编码为「借一个已停用的号」。两种取舍都成立
    （借 = codex 不中断 / 不借 = 设置说话算数但那段时间用不了），所以做成开关。
    """

    def test_the_proxy_actually_reads_the_switch(self):
        """★★★ 「后端有字段 ≠ 有人读它」—— 只存不读就是「界面说关着、代理照借」。"""
        px = _strip((ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8"))
        self.assertIn('s.get("borrow_off")', px, "★★★ 代理没读这个开关")
        i = px.index("relaxed = [(aid, sl)")
        self.assertIn('borrow_off', px[max(0, i - 400):i],
                      "★★ 开关没挡在借用那一支前面 —— 读了但没用上")

    def test_off_means_the_proxy_says_why_instead_of_going_silent(self):
        """★ 关掉之后 codex 会失败，用户必须能看出「是我自己关的」而不是「轮换坏了」。"""
        px = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        self.assertIn("你已关闭", px, "★ 关掉借用后直接静默失败 —— 那会变成一次无头排查")

    def test_the_default_is_the_old_behaviour(self):
        """★★ 存**反向**（`borrow_off`）：缺省（无键）必须等于既有行为。

        正向命名要写迁移，而漏迁移的机器会**静默改变行为**且零报错 ——
        与 `rotate_off` / `auto_off` 同一条理由。
        """
        cli = _strip((ROOT / "codex-rotate").read_text(encoding="utf-8"))
        self.assertIn('"borrow_off"', cli, "★★ 开关不是反向存的")
        self.assertNotIn('"borrow_on"', cli, "★★ 存成了正向 —— 缺省会变成「禁止借用」")
        i = cli.index("def cmd_borrow")
        seg = cli[i:cli.index("\ndef ", i + 1)]
        self.assertIn('pop("borrow_off", None)', seg,
                      "★ 恢复默认要**删键**，不是写 False —— 否则「缺省」有两种表示")

    def test_the_settings_page_reads_the_real_source(self):
        """★ 真源在 `state.json`（代理在 app 没开时也要读），不在 localStorage。"""
        sp = _strip((SRC / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8"))
        self.assertIn('invoke<{ borrow_off?: boolean }>("read_state")', sp,
                      "★★ 设置页没从 state.json 读这个开关")
        self.assertIn('["borrow",', sp, "★ 设置页没接上写入命令")

    def test_it_can_tell_cannot_read_from_switched_off(self):
        """★★★ 本仓头号铁律在这一格上的形态：读不到 ≠ 已关闭。"""
        sp = (SRC / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")
        self.assertIn("不是「已关闭」", sp,
                      "★★★ 读不到时显示成「关」—— 那是两件相反的事")


if __name__ == "__main__":
    unittest.main(verbosity=2)
