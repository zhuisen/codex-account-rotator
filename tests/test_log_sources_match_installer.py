"""运行日志的来源清单必须跟着**安装脚本真正 emit 的任务**走（2026-09-14 体检查出）。

## 来历

`scripts/install-launchd.sh` 的 `log_path()` 上面就写着：

    # Log paths are NOT uniformly "$REPO/<name>.log": the proxy writes beside its own source,
    # and CodexBar's log page reads these exact literals (src-tauri/src/lib.rs read_logs).
    # Keep the two in sync.

**写下来了，但没有任何闸为此变红** —— 于是它朝两个方向同时漂：

| 方向 | 实际 |
|---|---|
| 多出来 | `keepalive.log`（最后写入 2026-08-26）· `refreshquota.log`（08-12）—— 这两个任务 08-29 就取消了，脚本不再 emit，plist 也已不在盘上 |
| 少掉了 | `dawnprobe.log` · `autosync.log` —— 其中 **dawnprobe 是全仓唯一会自动花钱的任务** |

叠加旧的「先到先得」截断，实测 300 行预算里 **152 行是 8 月的尸体**，`quotad.log` 被砍一半，
09-14 刚按用户要求加的 `agy.log` **一行都露不出来**。

★ 这就是本仓那条「**写下来但没有闸的规则一定会被违反，包括被写它的人**」的又一次实证。
  这一轮的交付物因此是这个文件，不是又一行注释。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "scripts" / "install-launchd.sh").read_text(encoding="utf-8")
RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

# launchd 之外的来源：不是任务，是 wrapper / CLI 的运行留痕，所以不参与"任务集合一致"那条。
NON_JOB_SOURCES = {"agy"}


def _installer_jobs():
    """安装脚本**真正** emit 的任务名。判据打在 `emit <name>` 上，不是注释里提到的名字。"""
    src = re.sub(r"^\s*#[^\n]*$", "", INSTALLER, flags=re.M)   # ★ 剥注释：注释里退役任务名还在
    return set(re.findall(r"^emit\s+(\w+)", src, re.M))


def _installer_log_path(job):
    """复刻 `log_path()` 的 case 规则。★ proxy 是特例，写在自己源码旁边。"""
    return "proxy/proxy.log" if job == "proxy" else "{}.log".format(job)


def _rs_sources():
    """`LOG_SOURCES` 里的 (任务名, 日志路径)。"""
    m = re.search(r"const LOG_SOURCES[^=]*=\s*&\[(.*?)\n\];", RS, re.S)
    assert m, "★ LOG_SOURCES 不见了 —— 这条闸在守一个不存在的东西"
    body = re.sub(r"//[^\n]*", "", m.group(1))      # ★ 剥行尾注释
    return dict(re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', body))


class TheLogSourcesTrackTheInstaller(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.jobs = _installer_jobs()
        cls.srcs = _rs_sources()

    def test_anchors_exist(self):
        """★ 先证明两边都还在。任何一边改名，下面的集合比较都会静默变成空对空。"""
        self.assertTrue(self.jobs, "★ 安装脚本里一个 `emit` 都没解析到 —— 正则失效了")
        self.assertTrue(self.srcs, "★ LOG_SOURCES 解析为空")
        self.assertIn("dawnprobe", self.jobs, "★ 安装脚本不再装 dawnprobe？判据要重写")

    def test_every_installed_job_has_its_log_on_the_page(self):
        """★★★ 主闸。少一个的代价是**那个任务的成败永远不可见** ——
        而 dawnprobe 少掉时，看不见的正是唯一会自动花钱的东西。"""
        for job in sorted(self.jobs):
            with self.subTest(job=job):
                self.assertIn(
                    job, self.srcs,
                    "★ 安装脚本装了 `{}`，但 LOG_SOURCES 里没有它 —— 它的日志在界面上不存在".format(job))
                self.assertEqual(
                    self.srcs[job], _installer_log_path(job),
                    "★ `{}` 的日志路径两边对不上（脚本写 {}，Rust 写 {}）".format(
                        job, _installer_log_path(job), self.srcs[job]))

    def test_no_retired_job_lingers_in_the_list(self):
        """★★ 反方向：脚本不再 emit 的任务，不许留在清单里占预算。

        留着的代价不是"多几行"，是**它按先到先得吃掉现役源的额度**（本轮实测 152/300）。
        将来重新启用 keepalive/refreshquota，是在脚本里加回 `emit`，这里跟着加 ——
        而不是现在先把名字留着（那就是本仓禁止的「没人渲染的骨架」）。
        """
        for name in sorted(self.srcs):
            if name in NON_JOB_SOURCES:
                continue
            with self.subTest(source=name):
                self.assertIn(
                    name, self.jobs,
                    "★ LOG_SOURCES 里的 `{}` 不是安装脚本会装的任务 —— 退役残留".format(name))

    def test_the_retired_pair_is_actually_gone(self):
        """★ 点名守这次的两具尸体：它们**同时**从脚本和清单里消失才算修好。"""
        for dead in ("keepalive", "refreshquota"):
            with self.subTest(job=dead):
                self.assertNotIn(dead, self.jobs)
                self.assertNotIn(dead, self.srcs)

    def test_agy_is_still_collected(self):
        """★ agy 不是 launchd 任务，但用户点名要看它（CLAUDE.md）。别在清退退役源时误伤。"""
        self.assertIn("agy", self.srcs, "★ agy.log 被顺手删掉了 —— 那是用户点名要的")


class TheBudgetIsReservedNotFirstComeFirstServed(unittest.TestCase):
    """★★ 旧实现：每份取 100 行依次 push、最后 `truncate(300)` = 先到先得。

    那让清单里**靠前**的文件决定后面还有没有得看，而排序本身毫无语义。
    「被挤掉」和「这个源没有日志」在界面上长得一模一样。
    """

    def setUp(self):
        i = RS.index("fn read_logs()")
        self.body = re.sub(r"//[^\n]*", "", RS[i:RS.index("\n}", i)])

    def test_there_is_a_per_source_reserve(self):
        self.assertIn("reserve", self.body,
                      "★ 没有保底配额 —— 先到先得回来了，末尾的源会被静默吃掉")

    def test_the_reserve_is_derived_not_hardcoded(self):
        """★ 配额必须**由源数算出来**。写死一个数的话，加第 6 个源时总额就超了，
        而超出的部分又会退回"被谁截掉"这种看不见的行为。"""
        self.assertRegex(
            self.body, r"LOG_BUDGET\s*/\s*LOG_SOURCES\.len\(\)",
            "★ 保底配额是写死的，不是按源数算的")

    def test_it_no_longer_truncates_the_concatenation(self):
        """★★ 变异方向「把被断言的东西整个删掉」：只要那句 `truncate` 回来，
        无论上面配额算得多漂亮，末尾的源照样被砍。"""
        self.assertNotIn("lines.truncate(", self.body,
                         "★ `truncate` 回来了 —— 先到先得的截断又生效了")


if __name__ == "__main__":
    unittest.main()
