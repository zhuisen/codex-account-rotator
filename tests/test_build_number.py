"""版本号 `X.Y.Z+B` 的不变量（用户 2026-09-15 定，正本在 `CLAUDE.md` §3.7）。

    X.Y.Z  住 tauri.conf.json + Cargo.toml   —— **发版**才动（`$release-cut`）
    B      住仓库根的 `BUILD`（一个整数）      —— **`git push` 之后 +1**，发版归 0

## ★★ 本地反复 `deploy.sh` 不动 `B`

它要回答的是「我装的这份对应远端哪一次推送」，不是「我今天重编了几次」——
后者没人关心，还会让版本号每天跳十几下。
⚠️ 这条**收窄了**全局 CLAUDE.md 的「B +1 per local build」，以项目这条为准。

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
    """★ 「改完就部署，不问」与「B 只在 push 时 +1」是**用户定的规矩**，
    必须留在项目正本里 —— 不然下一个会话又会回来问一遍。
    """

    CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    def test_the_auto_deploy_rule_is_in_claude_md(self):
        self.assertIn("改完就部署，不要问", self.CLAUDE,
                      "★ 自动部署那条规矩没写进项目 CLAUDE.md")

    def test_it_does_not_also_wave_through_git_push(self):
        """★★ 豁免的**只有** deploy 这一个问题。`git push` 仍然要用户开口（全局规则）。
        把两者混为一谈 = 把代码推到远端而没人同意过。"""
        i = self.CLAUDE.index("改完就部署，不要问")
        seg = self.CLAUDE[i:i + 900]
        self.assertIn("`git push` 仍然要用户明确开口", seg,
                      "★★ 没写清 push 不在豁免范围内 —— 那条边界必须显式")

    def test_the_build_bump_trigger_is_written_down(self):
        self.assertIn("只在 `git push` 那一刻 +1", self.CLAUDE,
                      "★ `B` 什么时候加没写下来")


if __name__ == "__main__":
    unittest.main()
