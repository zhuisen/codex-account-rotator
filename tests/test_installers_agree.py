"""两个平台的服务安装器必须定义**同一组服务**。

`scripts/install-launchd.sh`(macOS) 与 `scripts/install-windows.ps1`(Windows) 是典型的
「一份两地」：加一个服务、改一个入口脚本、换一个端口，只改一边就会让某个平台**静默少一个
常驻进程** —— 而症状是「额度不更新」「代理连不上」这类看起来跟安装器毫无关系的现象。

★ 这不是理论风险：v0.12.11 取消 keepalive/refreshquota 时只有 macOS 那份存在，
  而 2026-08-31 才发现 Windows 端**压根没有任何常驻服务**，账号池那半在 Windows 上半残了
  三个版本。闸的成本是几行，代价是一整个平台的功能静默缺失。

判据刻意只打在**服务集合与入口脚本**上，不比对触发器 —— 两边的触发语义本来就不同
（launchd `WatchPaths` 文件监视 vs Task Scheduler 只能轮询），强行对齐等于把一个
真实的平台差异伪装成一致。差异写在 `install-windows.ps1` 的文件头，不在这里。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install-launchd.sh"
PS1 = ROOT / "scripts" / "install-windows.ps1"


class InstallersDefineTheSameServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sh = SH.read_text(encoding="utf-8")
        cls.ps = PS1.read_text(encoding="utf-8")

    def _sh_services(self):
        """macOS：`emit <name> …`。注释里也写着 emit，所以先剥注释行。"""
        body = "\n".join(l for l in self.sh.splitlines() if not l.lstrip().startswith("#"))
        names = re.findall(r"^emit\s+([a-z][a-z0-9_-]*)", body, re.M)
        self.assertTrue(names, "从 install-launchd.sh 里一个 emit 都没解析到 —— 断言可能打空了")
        return set(names)

    def _ps_services(self):
        """Windows：`@{ Name = "proxy"; … }`。同样先剥注释。"""
        body = "\n".join(l for l in self.ps.splitlines() if not l.lstrip().startswith("#"))
        names = re.findall(r'Name\s*=\s*"([a-z][a-z0-9_-]*)"', body)
        self.assertTrue(names, "从 install-windows.ps1 里一个服务都没解析到 —— 断言可能打空了")
        return set(names)

    def test_same_service_set(self):
        """★★ 两边的服务名集合必须完全相同。"""
        a, b = self._sh_services(), self._ps_services()
        self.assertEqual(
            a, b,
            "两个安装器的服务集合不一致 —— 某个平台会静默少一个常驻进程。\n"
            "  macOS  : %s\n  Windows: %s\n  只在 macOS: %s\n  只在 Windows: %s"
            % (sorted(a), sorted(b), sorted(a - b), sorted(b - a)))

    def test_same_entry_scripts(self):
        """入口脚本也要一致 —— 改了 quotad 的路径只改一边，另一个平台就跑不起来。"""
        wants = {
            "proxy": "proxy.py",
            "quotad": "quota_daemon.py",
            "autosync": "codex-rotate",
        }
        for svc, script in wants.items():
            self.assertIn(script, self.sh, "install-launchd.sh 里找不到 %s 的入口 %s" % (svc, script))
            self.assertIn(script.replace("/", "\\"), self.ps.replace("/", "\\"),
                          "install-windows.ps1 里找不到 %s 的入口 %s" % (svc, script))

    def test_proxy_port_matches(self):
        """代理端口两边必须一致 —— 不一致的症状是 codex 连不上，而两个文件各自都"对"。"""
        a = re.search(r"CRP_PORT.*?(\d{4,5})", self.sh)
        b = re.search(r"CRP_PORT\s*=\s*\"(\d{4,5})\"", self.ps)
        self.assertIsNotNone(a, "install-launchd.sh 里没找到 CRP_PORT —— 断言可能打空了")
        self.assertIsNotNone(b, "install-windows.ps1 里没找到 CRP_PORT —— 断言可能打空了")
        self.assertEqual(a.group(1), b.group(1),
                         "两边的代理端口不一致：macOS=%s Windows=%s" % (a.group(1), b.group(1)))

    def test_windows_uses_pythonw_not_python(self):
        """★ Windows 上必须用 `pythonw.exe`。

        用 `python.exe` 的话每个常驻服务都会挂一个**永远杵在那里的控制台窗口**，
        重启一次弹一次 —— 与 app 内那个 CREATE_NO_WINDOW 是同一类问题，
        只是这次窗口来自计划任务而不是子进程。
        """
        body = "\n".join(l for l in self.ps.splitlines() if not l.lstrip().startswith("#"))
        # ★ 判据打在**候选列表本身**上，不是「文件里出现过 pythonw 这个词」。
        #   第一版就是后者，变异测试当场证伪：把 `pythonw.exe` 改成 `python.exe` 之后，
        #   `pythonw3.exe` 还在文件里，子串断言照样绿 —— 子串存在 ≠ 规则存在。
        cands = re.search(r"foreach\s*\(\s*\$c\s+in\s+@\((.*?)\)\)", body, re.S)
        self.assertIsNotNone(cands, "找不到解释器候选列表 —— 断言可能打空了")
        names = re.findall(r'"([^"]+)"', cands.group(1))
        self.assertTrue(names, "候选列表是空的")
        bad = [n for n in names if not n.lower().startswith("pythonw")]
        self.assertEqual(bad, [], "候选里有非 pythonw 的解释器 %s —— "
                                  "每个常驻服务都会挂一个永不消失的控制台窗口" % bad)
        self.assertIn("<Hidden>true</Hidden>", body,
                      "任务没有设 Hidden —— pythonw 之外还需要它才真的无窗口")

    def test_windows_forces_utf8_output(self):
        """★ 日志也要强制 UTF-8。

        Windows 上 Python 的 stdout 默认走本地代码页，日志里的中文会变成乱码 ——
        与 v1.0.3 修的那个（Rust 读 stdout）同源，这里是写日志文件那一侧。
        """
        self.assertIn("PYTHONUTF8", self.ps, "Windows 安装器没有强制 UTF-8 输出")


if __name__ == "__main__":
    unittest.main()
