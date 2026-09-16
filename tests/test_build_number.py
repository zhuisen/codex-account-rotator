"""版本号 `X.Y.Z+B` 的不变量（用户 2026-09-15 定，正本在 `CLAUDE.md` §3.7）。

    X.Y.Z  住 tauri.conf.json + Cargo.toml   —— **发版**才动（`$release-cut`）
    B      **不住任何文件** —— `src-tauri/build.rs` 从 git 现算

## ★★★ 判据只有一条

    B == 0  →  显示 `vX.Y.Z`    「你跑的这份**就是** release」
    B  > 0  →  显示 `vX.Y.Z+B`  「发版之后本地改过，还没发出去」

`B` = 距最近 tag 的 commit 数，工作区脏再 +1。发版后工作区正好停在 tag 上 ⇒ B=0 ⇒
本地 `deploy.sh` 出来的东西与已发布产物**报同一个版本**。这就是这次改动的全部目的。

## ⚠️ 两次写错，都记在这儿

1. 先写成「只在 `git push` 时 +1」——用户纠正：「本地更新本地版本就需要 `X.Y.Z+B`」。
2. 改成 `deploy.sh` 里的计数器（在 build **之前** +1）——于是 tag 刚推完、本地构建
   就报 `v1.6.0+1`，用户问：「发版了，本地为什么还是 +1，进行了什么修改吗？」**什么都没改。**
   计数器分不出「比 release 多一次构建」和「就是 release」，因为它**不知道 release 这件事**。

★ 第三版换成**派生值**，顺带**删掉了一条规则** —— 没有文件可以忘记重置，也就没有规则
  可以被违反。本仓老教训：写下来但没有闸的规则一定会被违反，**包括被写它的人**。

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
RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
HELPERS = (ROOT / "codexbar" / "src" / "helpers.ts").read_text(encoding="utf-8")
APP = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
SETTINGS = (ROOT / "codexbar" / "src" / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")


def _ts(src):
    """剥掉 TS 注释（含行尾）。本仓注释密度极高，闸撞上自己的说明是惯犯。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


class TheBuildNumberIsDerivedFromGit(unittest.TestCase):

    BUILD_RS = (ROOT / "codexbar" / "src-tauri" / "build.rs").read_text(encoding="utf-8")

    def test_there_is_no_counter_file(self):
        """★★★ 主闸：**不许再出现 `BUILD` 计数器文件**。

        它活过一天，症状是「tag 刚推完、本地构建就报 +1」——
        计数器不知道 release 这件事，所以分不出"多一次构建"和"就是 release"。
        """
        self.assertFalse((ROOT / "BUILD").exists(),
                         "★★★ `BUILD` 计数器文件回来了 —— 它分不出「就是 release」")
        self.assertNotIn("include_str!(\"../../../BUILD\")", RS,
                         "★★★ 又去读那个计数器文件了")

    def test_it_counts_commits_since_the_last_tag(self):
        """★★ 判据是**距最近 tag 的 commit 数**，不是任何形式的自增。"""
        self.assertIn("describe", self.BUILD_RS, "★★ 没有以 tag 为基准")
        self.assertIn("rev-list", self.BUILD_RS, "★★ 没有数 tag 之后的 commit")

    def test_a_dirty_tree_counts_as_modified(self):
        """★ 未提交的改动**也是**「发版之后本地改过」。不算的话，
        `vX.Y.Z` 就会出现在一个并非 release 的构建上 —— 那是关于版本的一句假话。"""
        self.assertIn("status", self.BUILD_RS)
        self.assertIn("porcelain", self.BUILD_RS, "★ 没有把脏工作区算进去")

    def test_it_is_a_compile_time_env_not_a_runtime_read(self):
        """★ 编译期注入（`cargo:rustc-env`）—— 运行期读会出现「树变了、二进制里还是旧数字」，
        而那种不一致**没有任何症状**（本仓 `quotad` 跑旧代码那次就是这个形状）。"""
        self.assertIn("cargo:rustc-env=CODEXBAR_BUILD", self.BUILD_RS)
        self.assertIn('env!("CODEXBAR_BUILD")', RS, "★ lib.rs 没读那个编译期变量")

    def test_it_reruns_when_head_moves(self):
        """★★ 不声明 `rerun-if-changed` 的话 cargo 会**缓存**上次算出来的数字，
        于是切了分支、提交了东西，版本号纹丝不动 —— 静默失准。"""
        self.assertIn("cargo:rerun-if-changed", self.BUILD_RS,
                      "★★ 没声明重算条件 —— cargo 会缓存一个过期的构建号")

    def test_deploy_does_not_bump_anything(self):
        """★★★ `deploy.sh` **不许**再动构建号。它正是上一版把 release 构建打成 `+1` 的地方。"""
        sh = (ROOT / "codexbar" / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        self.assertNotIn("BUILD_FILE", sh, "★★★ deploy.sh 又开始维护计数器了")


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

    #: ⚠️ **判据是英文的**（用户 2026-09-15：项目 CLAUDE.md 全英文，见正本 §3.8）。
    #:   2026-09-16 全文翻译时这两条闸当场变红 —— 它们钉的是**中文原句**。
    #:   这正是本仓记过的形状：**逐字匹配守的是"文本长什么样"，不是"规矩在不在"**。
    #:   所以判据换成翻译后的定稿措辞；改写这段话时要连着这里一起改。
    DEPLOY_RULE = "Deploy after changes; do not ask"
    PUSH_BOUNDARY = "**`git push` still requires the user to ask for it explicitly**"

    def test_the_auto_deploy_rule_is_in_claude_md(self):
        self.assertIn(self.DEPLOY_RULE, self._claude(),
                      "★ 自动部署那条规矩没写进项目 CLAUDE.md")

    def test_it_does_not_also_wave_through_git_push(self):
        """★★ 豁免的**只有** deploy 这一个问题。`git push` 仍然要用户开口（全局规则）。
        把两者混为一谈 = 把代码推到远端而没人同意过。"""
        c = self._claude()
        i = c.index(self.DEPLOY_RULE)
        seg = c[i:i + 900]
        self.assertIn(self.PUSH_BOUNDARY, seg,
                      "★★ 没写清 push 不在豁免范围内 —— 那条边界必须显式")

    def test_the_build_semantics_are_written_down(self):
        c = self._claude()
        self.assertIn("derived from git", c, "★ `B` 怎么来的没写下来")
        self.assertIn('"what you are running IS the release"', c,
                      "★ 最要紧的那条语义（B==0 就是 release）没写下来")

    def test_the_two_wrong_versions_are_not_lying_around(self):
        """★★ 这条规矩我写错过**两次**（先"只在 push 时 +1"，再 deploy.sh 计数器）。
        正本里不许留着任何一版 —— 互相矛盾的规矩并存，比只有一句错的更糟。"""
        c = self._claude()
        wrong_rules = (
            # 中文原版（2026-09-16 全文英译前的措辞）—— 回潮也要红
            "只在 `git push` 那一刻 +1", "每次本地部署 +1",
            # 英文版的等价说法
            "bumped on `git push`", "bumped on every local deploy",
        )
        for wrong in wrong_rules:
            with self.subTest(wrong=wrong):
                self.assertNotIn(wrong, c, "★★ 写错的旧规矩还留在正本里：{}".format(wrong))

    def test_the_language_policy_is_declared(self):
        """★ 用户 2026-09-15：项目 CLAUDE.md 用英文写。把这条**写进文件本身**，
        否则下一个会话会按仓库里满屏的中文"入乡随俗"，规矩就悄悄失效了。"""
        self.assertIn("Language policy for this file", self._claude(),
                      "★ 语言规矩没写进正本")


if __name__ == "__main__":
    unittest.main()


class DeployTellsYouWhichVersionItJustBaked(unittest.TestCase):
    """★★★ `deploy.sh` 必须**当场报出**它烤进产物的版本，并在 `B != 0` 时告警。

    ## 起因（2026-09-17，v1.6.1 发版后）

    用户在界面上看到 `v1.6.1+10`。产物**没错** —— 它确实是在 `git tag` **之前 38 秒**、
    从一个脏工作区构建的（距 `v1.6.0` 9 个 commit + 脏 1 = 10），`B` 从 git 现算就是 10。

    ★ 真正的缺陷是**顺序**：`B` 改成从 git 派生（§3.7）之后，
      `$release-cut` 那条通用顺序（… → build → commit → tag → push）
      **结构性地做不到** `B == 0`，因为构建那一刻 tag 还不存在。
      §3.7 承诺「`B == 0` 就是 release」，§3 的顺序却保证它不成立 ——
      **两条规则从 `B` 变成派生值那一刻起就互相矛盾**。正本已改（§3 新增 4.5）。

    ## 为什么这里要一条闸，而不是再写一句话

    这个缺陷在部署那一刻**完全不可见**：构建成功、app 正常启动、只有版本字符串在撒谎。
    **只能靠事后打开界面才发现的东西，就会由用户来发现，而不是由你。**
    所以判据是「deploy 当场把版本打出来」——把一个隐形事实变成可见事实。
    """

    SH = (ROOT / "codexbar" / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    @staticmethod
    def _code(src):
        """剥掉 shell 注释 —— 注释里正解释着这条规则（本仓空守卫形态④）。"""
        return re.sub(r"(?m)^\s*#.*$", "", src)

    def test_both_branches_report_the_version(self):
        """★★★ **两条分支都要报版本**，不是只有一条。

        ⚠️ 这条的第一版写成「全文里有一处 `deployed … ${VER}` 就算过」——
          于是把 `B != 0` 那条 echo 整个删掉，闸**照样绿**（正则命中了 `B == 0` 那条）。
          空守卫形态①：**子串存在 ≠ 规则存在**。现在逐分支断言。
        """
        code = self._code(self.SH)
        i = code.index('if [ "$B" = "0" ]')
        j = code.index("fi", i)
        zero, nonzero = code[i:j].split("else", 1)
        for name, seg in (("B==0", zero), ("B!=0", nonzero)):
            with self.subTest(branch=name):
                self.assertRegex(seg, r"deployed[^\n]*\$\{?VER",
                                 "★★★ {} 分支不报版本 —— 那一半的版本要等用户打开界面才知道"
                                 .format(name))

    def test_b_is_computed_by_actually_running_it(self):
        """★★★ **行为闸**：把 deploy.sh 算 `B` 的那段**真跑一遍**。

        ⚠️ 第一版是 `assertIn("porcelain", code)` 这类词面断言 —— 于是把
          `B=$((B + 1))` 改成 `B=$B`（脏工作区不再计数）后，`porcelain` 仍在 `if` 条件里，
          闸**照样绿**。词在 ≠ 规则在。只有真跑才分得出来。

        判据是与 `build.rs` 同一个算法：干净树停在 tag 上 → 0；脏树 → +1；多一个 commit → +1。
        """
        import subprocess, tempfile
        snippet = None
        code = self._code(self.SH)
        i = code.index('TAG=$(git describe')
        j = code.index('if [ "$B" = "0" ]', i)
        snippet = code[i:j]
        self.assertIn("rev-list", snippet, "★ 没截到算 B 的那段 —— 断言可能打空了")

        def b_of(setup):
            with tempfile.TemporaryDirectory() as d:
                sh = ("set -e; cd %s; git init -q .; git config user.email a@b.c;"
                      " git config user.name t; echo x > f; git add f;"
                      " git commit -qm init; git tag -a v1.0.0 -m t; %s\n%s\n echo \"B=$B\""
                      % (d, setup, snippet))
                out = subprocess.run(["bash", "-c", sh], capture_output=True,
                                     text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr[-300:])
                return out.stdout.strip().splitlines()[-1]

        self.assertEqual(b_of(":"), "B=0",
                         "★★★ 干净树正停在 tag 上，B 应当是 0 —— 那正是「这份就是 release」")
        self.assertEqual(b_of("echo dirty >> f"), "B=1",
                         "★★★ 脏工作区没有被计入 —— 一个并非 release 的构建会自称是 release")
        self.assertEqual(b_of("echo y > g; git add g; git commit -qm more"), "B=1",
                         "★★★ tag 之后的 commit 没有被计入")

    def test_the_version_actually_resolves(self):
        """★★★ **行为闸**：真跑那行取版本的命令，必须解出版本号而不是 `?`。

        ⚠️ 第一版写成 `$(cd "$(dirname "$0")/.." && pwd)` —— 而脚本开头**已经
          `cd "$ROOT"` 过**，于是那个相对路径解析失败，部署当场打出
          `✓ deployed — v?（B=0…）`。**"报了版本"和"报对了版本"是两件事**，
          只断言"有 VER 这个词"分不出来。所以这里真跑一次。
        """
        import json as _json, re as _re, subprocess, tempfile
        code = self._code(self.SH)
        m = _re.search(r"^VER=\$\(node -p .*$", code, _re.M)
        self.assertIsNotNone(m, "★ 找不到取版本那一行 —— 断言可能打空了")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src-tauri").mkdir()
            (Path(d) / "src-tauri" / "tauri.conf.json").write_text(
                _json.dumps({"version": "9.9.9"}), encoding="utf-8")
            out = subprocess.run(
                ["bash", "-c", 'ROOT=%s\n%s\necho "VER=$VER"' % (d, m.group(0))],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr[-300:])
            self.assertIn("VER=9.9.9", out.stdout,
                          "★★★ 版本解析失败，会打成 `v?` —— 实测发生过一次")

    def test_a_nonzero_b_warns_loudly(self):
        """★★★ `B != 0` 必须告警，且**说出下一步**（本仓 §5d：文本要说"做什么"）。"""
        code = self._code(self.SH)
        i = code.index('if [ "$B" = "0" ]')
        seg = code[i:i + 700]
        self.assertIn("⚠️", seg, "★★★ B≠0 时没有告警")
        self.assertIn("git tag", seg,
                      "★★ 告警没说下一步该干什么 —— 只说'坏了'的告警会被忽略")

    def test_the_zero_case_says_it_is_the_release(self):
        """★ `B == 0` 时正面说出「你跑的这份就是 release」—— 那是 §3.7 的全部意义。"""
        code = self._code(self.SH)
        i = code.index('if [ "$B" = "0" ]')
        self.assertIn("release", code[i:i + 300])

    def test_the_release_order_is_written_down(self):
        """★★ 正本里必须写明「发版时先 tag 再本地 deploy」。

        ⚠️ 这条与 `$release-cut` 的通用顺序**不同**，不写下来的话下一个会话会照通用顺序做，
        然后本地产物又是 `+N`。
        """
        c = self._claude() if hasattr(self, "_claude") else None
        f = ROOT / "CLAUDE.md"
        if not f.exists():
            self.skipTest("CLAUDE.md 不存在（gitignored，CI 的干净 checkout 上没有）")
        t = f.read_text(encoding="utf-8")
        self.assertIn("tag BEFORE you deploy locally", t,
                      "★★ 发版顺序那条没写进正本 —— 下一次又会先 build 后 tag")
