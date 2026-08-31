"""常驻服务「在跑旧代码」闸（`codex-rotate` 的 `stale_daemon_gate`）。

## 这个闸为什么存在

2026-08-31：用户报额度在 **100% / 64%** 之间反复跳。根因不是代码错 ——
`limit_id` 白名单（v0.12.9）和「非 2xx 不替换」（v0.12.10）**两个修复在这台机器上从未生效**：

| 进程 | 启动 | 修复落地 |
|---|---|---|
| `quotad` | 08-27 09:30 | `fb9659a` @ 08-28 16:45 |
| `proxy`  | 08-28 17:42 | `9c5504a` @ 08-28 **17:44**（差 2 分钟） |

`quota_daemon.py` 用 `SourceFileLoader` 在**启动时**把整个 `codex-rotate` 载进内存，
所以改 `codex-rotate` 而不重启 quotad，等于什么都没改。
代码改了、165 条测试绿了、发版了、打了 tag、部署了 app —— 修复照样没跑，**三天**。
发现它的是用户，不是任何一道检查。

对照实验（决定性）：拿当时正在写的 rollout 喂给两个版本的 `_find_rl`，
旧版取到 `codex_bengalfox`（模型专属，恒 `used_percent=0.0`）⇒ UI 画 100%；
新版返回 `None` ⇒ 保留真实快照。同一条 rollout 里 `codex` 出现 1057 次、
`codex_bengalfox` 出现 240 次，旧代码取到哪个纯看遍历顺序 —— 所以它表现为**毫无征兆地跳**。

## 这个闸守的三条

1. **进程比它加载的源文件旧 ⇒ warn**，并给出确切的 kickstart 命令。
2. **`quotad` 的源文件清单必须含 `codex-rotate`**。只列 `quota_daemon.py` 会让这次事故
   原样重演 —— 那次改的正是 `codex-rotate`，`quota_daemon.py` 一个字没动。
3. **判定不了 ⇒ `unknown`，绝不 `ok`**。把「查不到」和「确实是新的」合并成一个值，
   等于让这道闸在最需要它的时候（进程查不到）静默放行。
"""
import importlib.machinery
import importlib.util
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_cli():
    """`codex-rotate` 无 .py 后缀，按路径加载。顶层只有常量，无 I/O、无网络。"""
    loader = importlib.machinery.SourceFileLoader("cr_gate", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class StaleDaemonGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_cli()

    def setUp(self):
        self.orig_run = self.cli.subprocess.run
        self.orig_start = self.cli._proc_start_epoch

    def tearDown(self):
        self.cli.subprocess.run = self.orig_run
        self.cli._proc_start_epoch = self.orig_start

    def test_anchors_exist(self):
        """★ 先证明被测目标还在 —— 改名后下面全部会静默打空。"""
        self.assertTrue(hasattr(self.cli, "stale_daemon_gate"), "stale_daemon_gate 不见了")
        self.assertTrue(hasattr(self.cli, "DAEMON_SOURCES"), "DAEMON_SOURCES 不见了")

    def test_quotad_watches_codex_rotate_not_just_its_own_file(self):
        """★★ 这条直接对应 2026-08-31 那次事故。

        那次改的是 `codex-rotate`，`quota_daemon.py` 一个字没动。清单里少了它，
        闸就会说「一切正常」，而 quotad 正跑着三天前的解析逻辑。
        """
        srcs = self.cli.DAEMON_SOURCES["quotad"]
        self.assertIn("codex-rotate", srcs,
                      "quotad 用 SourceFileLoader 载入 codex-rotate，改它必须重启 —— "
                      "清单里没有它，这道闸就挡不住那次事故。当前清单: %s" % srcs)

    def _stub(self, pid_found=True, started_ago_h=1.0):
        """把 pgrep 与启动时刻都打桩 —— 不碰真实进程表。"""
        class R:
            def __init__(self, out): self.stdout = out
        self.cli.subprocess.run = lambda *a, **k: R("4242\n" if pid_found else "")
        self.cli._proc_start_epoch = lambda pid: time.time() - started_ago_h * 3600

    def test_process_older_than_its_code_is_warn(self):
        """① 进程比源文件旧 ⇒ warn。仓库里的源文件此刻就是"刚改过"的状态之外的常态，
        所以这里显式把启动时刻推到很久以前，保证判据成立。"""
        self._stub(started_ago_h=24 * 365)      # 一年前启动:必然比任何源文件旧
        g = self.cli.stale_daemon_gate()
        self.assertEqual(g["level"], "warn", "跑了一年的进程没有被判成旧代码")
        joined = "\n".join(g["lines"])
        self.assertIn("kickstart", joined, "warn 文案没给出修复命令 —— "
                                           "「告诉用户出事了却不说怎么办」是本仓库明令禁止的")

    def test_process_newer_than_its_code_is_ok(self):
        """② 反向:刚启动的进程必须判 ok，否则这道闸恒响 = 等于没有。"""
        self._stub(started_ago_h=-1.0)          # "未来"启动:必然比所有源文件新
        g = self.cli.stale_daemon_gate()
        self.assertEqual(g["level"], "ok", "刚启动的进程被误判成旧代码 —— 恒响的闸会被无视")

    def test_missing_process_is_not_ok(self):
        """③ 服务压根没在跑 ⇒ 不能是 ok。没在跑的 quotad 意味着额度永远不更新。"""
        self._stub(pid_found=False)
        g = self.cli.stale_daemon_gate()
        self.assertNotEqual(g["level"], "ok", "服务没在跑却报 ok")

    def test_undetermined_is_not_ok(self):
        """★★ ④ 算不出启动时刻 ⇒ `unknown`，**绝不能是 ok**。

        这是本仓库的头号铁律在这道闸上的形态:「这一枪没打中」不能和「确实没有」
        返回同一个值。合并的话，闸会恰好在它最该说话的时候（进程信息拿不到）闭嘴。
        """
        self._stub()
        self.cli._proc_start_epoch = lambda pid: None
        g = self.cli.stale_daemon_gate()
        self.assertEqual(g["level"], "unknown",
                         "启动时刻算不出来时报了 %s —— 判定不了必须是 unknown" % g["level"])


if __name__ == "__main__":
    unittest.main()
