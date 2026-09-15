"""版本号 `X.Y.Z+B` 的不变量（用户 2026-09-15 定，正本在 `CLAUDE.md` §3.7）。

    X.Y.Z  住 tauri.conf.json + Cargo.toml   —— **发版**才动（`$release-cut`）
    B      住仓库根的 `BUILD`（一个整数）      —— **每跑一次 `deploy.sh` +1**，发版归 0

## ★★ `B` 跟着**本地部署**动，不是跟着 push 动

⚠️ 我 2026-09-15 一度把它写成「只在 `git push` 时 +1」，**用户当场纠正**：
「本地更新本地版本就需要 `X.Y.Z+B`」。

`B` 回答的是**「我现在装的这份是第几次本地构建」** —— 它唯一的用处就是让用户一眼看出
「刚给我装的那份，和我五分钟前看的那份，不是同一个」。只在 push 时动，那个问题永远答不了。
（这本来就是全局 CLAUDE.md 的原文「B +1 per local build」，是我自己拐弯了。）

## ★ 为什么要有这个文件

版本号在本仓是**惯犯**：曾经"同步 5 处"，发一次版要手改三个前端字符串，漏一个就显示错版本
（`CLAUDE.md` §3.3 的来历）。现在 `X.Y.Z` 收到两处、`B` 收到一处、显示侧收到一个函数 ——
这个文件守的就是"别再散开"。
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "BUILD"
RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
HELPERS = (ROOT / "codexbar" / "src" / "helpers.ts").read_text(encoding="utf-8")
APP = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
SETTINGS = (ROOT / "codexbar" / "src" / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")


def _ts(src):
    """剥掉 TS 注释（含行尾）。本仓注释密度极高，闸撞上自己的说明是惯犯。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


class TheBuildNumberIsASingleInteger(unittest.TestCase):

    def test_the_file_exists_and_is_an_integer(self):
        self.assertTrue(BUILD.exists(), "★ 仓库根的 `BUILD` 不见了")
        raw = BUILD.read_text(encoding="utf-8").strip()
        self.assertRegex(raw, r"^\d+$",
                         "★ `BUILD` 不是一个纯整数：{!r}".format(raw))

    def test_it_is_compiled_in_not_read_at_runtime(self):
        """★ `include_str!` 让 `BUILD` 成为**编译依赖** —— 改了它下次构建必然重编。

        换成运行期读文件的话，会出现「文件改了、二进制里还是旧数字」，
        而那种不一致**没有任何症状**（本仓 `quotad` 跑旧代码那次就是这个形状）。
        """
        self.assertIn('include_str!("../../../BUILD")', RS,
                      "★ `BUILD` 不再是编译期依赖 —— 会出现文件与二进制不一致且无症状")


class TheVersionIsShownFromOnePlace(unittest.TestCase):
    """★★ 两个显示位必须走同一个函数。

    版本号此前是"同步 5 处"、漏一个就显示错版本 —— 这条守的是别再散开。
    """

    def test_there_is_one_helper(self):
        self.assertIn("export async function fullVersion", HELPERS,
                      "★ `fullVersion()` 不见了")

    def test_both_surfaces_use_it(self):
        for name, src in (("App.tsx", APP), ("SettingsPage.tsx", SETTINGS)):
            with self.subTest(file=name):
                self.assertIn("fullVersion()", _ts(src), "★ {} 没走那个 helper".format(name))

    def test_neither_calls_getversion_directly(self):
        """★★ 直接调 `getVersion()` 就绕过了 `+B` —— 而绕过之后两处会显示不同的版本，
        且**看起来都很正常**（一个 `1.5.0`、一个 `1.5.0+3`）。"""
        for name, src in (("App.tsx", APP), ("SettingsPage.tsx", SETTINGS)):
            with self.subTest(file=name):
                self.assertNotIn("getVersion(", _ts(src),
                                 "★★ {} 又直接调 getVersion 了 —— 那一处会丢掉 +B".format(name))

    def test_deploy_bumps_it(self):
        """★★ **`deploy.sh` 自己 +1**，不靠人记得。

        规则写下来而没有闸，一定会被违反（本仓铁律）——
        这条的"闸"就是把动作放进那个唯一的部署入口，而这个测试守着它还在。
        ★ 必须在 `building…` **之前**：`include_str!` 是编译期读的，
          放在 build 之后 = 这次装的二进制里还是旧号，下次才对上。
        """
        sh = (ROOT / "codexbar" / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        self.assertIn("BUILD_FILE", sh, "★★ deploy.sh 不再给 B +1 了")
        self.assertLess(sh.index("BUILD_FILE"), sh.index('echo "==> building'),
                        "★★ B 的 +1 排在 build 之后 —— 这次装的还是旧号")

    def test_a_missing_build_number_shows_no_plus_suffix(self):
        """★ 取不到 `B` 就**只显示 `X.Y.Z`**，不显示 `+?` —— 那是关于版本的一句假话。"""
        i = HELPERS.index("export async function fullVersion")
        seg = _ts(HELPERS[i:HELPERS.index("\n}", i)])
        self.assertIn("return v;", seg, "★ 取不到 B 时没有退回纯 X.Y.Z")
        self.assertNotIn('+?', seg)


class TheBuildNumberStaysOutOfTheManifests(unittest.TestCase):
    """★ `B` 不进 manifest（全局 CLAUDE.md 那条仍然成立）。

    `tauri.conf.json` / `Cargo.toml` 里只能是三段 `X.Y.Z`；
    把 `+B` 写进去 = 每次 push 都要改 manifest，而那是发版才该动的东西。
    """

    def test_tauri_conf_version_is_three_part(self):
        v = json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json")
                       .read_text(encoding="utf-8"))["version"]
        self.assertRegex(v, r"^\d+\.\d+\.\d+$", "★ tauri.conf.json 的版本带了 +B")

    def test_cargo_version_is_three_part(self):
        src = (ROOT / "codexbar" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', src, re.M)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"^\d+\.\d+\.\d+$", "★ Cargo.toml 的版本带了 +B")

    def test_the_two_manifests_agree(self):
        """★ 它们本来就必须一致（§3.3）。顺手在这里再钉一次 —— 这条最便宜。"""
        v1 = json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json")
                        .read_text(encoding="utf-8"))["version"]
        src = (ROOT / "codexbar" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        v2 = re.search(r'^version\s*=\s*"([^"]+)"', src, re.M).group(1)
        self.assertEqual(v1, v2, "★ 两个 manifest 的版本对不上")


class TheDeployRuleIsWrittenDown(unittest.TestCase):
    """★ 「改完就部署，不问」与「B 每次本地部署 +1」是**用户定的规矩**，
    必须留在项目正本里 —— 不然下一个会话又会回来问一遍（或者像我一样记反）。
    """

    #: ⚠️ **绝不在类体/模块层读它。** `CLAUDE.md` 是 gitignored 的（仓库红线），
    #:   CI 的干净 checkout 上**根本不存在** —— 在导入期读就是 `FileNotFoundError`，
    #:   而 pytest 把它算成 collection error，**整个 suite 直接中断**。
    #:   2026-09-15 v1.6.0 那次 CI 就是这么红的：本地 1294 全绿，CI 一条都没跑起来。
    #:   同 `test_doc_boards.py` 的范式：进方法里读，缺了就 `skipTest`。
    @classmethod
    def _claude(cls):
        f = ROOT / "CLAUDE.md"
        if not f.exists():
            raise unittest.SkipTest("CLAUDE.md 不存在（gitignored，CI 的干净 checkout 上没有）")
        return f.read_text(encoding="utf-8")

    def test_the_auto_deploy_rule_is_in_claude_md(self):
        self.assertIn("改完就部署，不要问", self._claude(),
                      "★ 自动部署那条规矩没写进项目 CLAUDE.md")

    def test_it_does_not_also_wave_through_git_push(self):
        """★★ 豁免的**只有** deploy 这一个问题。`git push` 仍然要用户开口（全局规则）。
        把两者混为一谈 = 把代码推到远端而没人同意过。"""
        i = self._claude().index("改完就部署，不要问")
        seg = self._claude()[i:i + 900]
        self.assertIn("`git push` 仍然要用户明确开口", seg,
                      "★★ 没写清 push 不在豁免范围内 —— 那条边界必须显式")

    def test_the_build_bump_trigger_is_written_down(self):
        self.assertIn("每次本地部署 +1", self._claude(), "★ `B` 什么时候加没写下来")

    def test_the_wrong_version_of_the_rule_is_not_lying_around(self):
        """★★ 我写错过一版（「只在 git push 时 +1」）。正本里**不许**再留着那句话 ——
        两句互相矛盾的规矩并存，比只有一句错的更糟：下一个人不知道该信哪句。"""
        self.assertNotIn("只在 `git push` 那一刻 +1", self._claude(),
                         "★★ 写错的那版规矩还留在正本里，和新的那句互相矛盾")


class TheHarnessStubsIt(unittest.TestCase):
    """★★★ 不打桩就是假绿。

    `build_number` 没打桩时会落到 harness 的 default 返回 `null`，
    `fullVersion()` 的 catch 接住 ⇒ 版本退回纯 `X.Y.Z` ⇒ **截图里永远看不到 `+B`**，
    而页面照常渲染、零报错、sweep 报干净。本仓反复记的「打桩缺口 ⇒ 看着像通过」。

    实测（2026-09-15，`--dump-dom` 剥掉 `<script>` 后数）：
        ?build 默认   → 页面上是 `v1.5.0+7`
        ?build=0      → 页面上是 `v1.5.0`（不显示 `+0`）
    """

    HARNESS = (ROOT / "codexbar" / "uishot" / "make_harness.py").read_text(encoding="utf-8")

    def test_the_command_is_stubbed(self):
        self.assertIn("case 'build_number':", self.HARNESS,
                      "★★★ harness 没打桩 build_number —— `+B` 在截图里永远不出现")

    def test_the_zero_case_is_drivable(self):
        """★ 「刚发版、还没本地构建过」那一态也要能渲染 —— 它和"取不到 B"长得一样，
        而两者的含义完全不同。"""
        i = self.HARNESS.index("case 'build_number':")
        self.assertIn("p.get('build')", self.HARNESS[i:i + 200],
                      "★ 没给 `?build=` 开关 ⇒ B=0 那一态验不到")


if __name__ == "__main__":
    unittest.main()
