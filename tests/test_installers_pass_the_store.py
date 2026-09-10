"""★★★ 定时服务必须**显式**拿到数据目录，一个任务都不能漏。

## 为什么这是 critical，而不是"配置没写全"

launchd / 计划任务起的进程**不继承交互 shell 的环境**。plist / task XML 里不写，
子进程就只能按 `__file__` 猜，猜出来的是**安装目录**。

app 侧 `data_dir()`（lib.rs:85）的优先级是
`env CODEXBAR_STORE` > 构建期烧进去的 `CODEXBAR_STORE_DEFAULT` > `app_data_dir()`。
本机 `deploy.sh` 会把仓库路径烧进第二条，于是 app 与服务**碰巧**指向同一处 ——
所以这个缺陷在开发机上**永远看不见**。CI 出的安装包没有那个烧录值，app 落到
`app_data_dir()`，服务仍在安装目录 ⇒ `route.local.json` / `state.json` / `auth/` 分叉；
而 `.refresh.lock` / `.state.lock` 落在两个不同路径上 = **等于没有锁**，
`codex-rotate` 与代理会同时刷同一个号的 refresh_token（一次性凭证，撞了就掉号）。

## 这条闸补的是上一条闸漏掉的方向

`test_store_root_agreement.py` 验的是「**给了**变量时两个模块算得一样」。
它自己往 subprocess 里注入变量，所以永远证明不了「**服务定义供给了**这个变量」。
2026-09-10 四方评审三个面板独立指出：代码改完了、没人喂它。
"""
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHD = ROOT / "scripts" / "install-launchd.sh"
WINDOWS = ROOT / "scripts" / "install-windows.ps1"
VAR = "CODEX_ROTATE_STORE"


class TheLaunchdPlistsCarryTheStore(unittest.TestCase):
    """★ 真的跑一遍安装脚本，读**生成出来的 plist**。

    静态 grep 只能证明脚本里有那个字符串；真正要证的是「每一份 plist 的
    EnvironmentVariables 里都有它」。`launchctl` 打桩（绝不碰真服务），
    `HOME` 指向临时目录（`AGENTS="$HOME/Library/LaunchAgents"` 会跟着走）。
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="codexbar-installer-gate-"))
        (cls.tmp / "home" / "Library" / "LaunchAgents").mkdir(parents=True)
        (cls.tmp / "store").mkdir()
        bin_ = cls.tmp / "bin"; bin_.mkdir()
        # ★ 只桩掉会改系统状态的那一个。`plutil -lint` 是只读校验，留着 —— 它能抓出
        #   重复 key / 畸形 XML，正是这次改动（合并 EnvironmentVariables）的风险点。
        stub = bin_ / "launchctl"
        stub.write_text("#!/bin/sh\nexit 0\n"); stub.chmod(0o755)
        env = dict(os.environ)
        env.update({"HOME": str(cls.tmp / "home"),
                    "PATH": f"{bin_}:{env['PATH']}",
                    VAR: str(cls.tmp / "store")})
        # ★ 不能叫 `cls.run` —— 会覆盖 `TestCase.run`，unittest 直接 TypeError。
        cls.proc = subprocess.run(["bash", str(LAUNCHD)], capture_output=True,
                                 text=True, env=env, cwd=str(ROOT), timeout=120)
        cls.plists = sorted((cls.tmp / "home" / "Library" / "LaunchAgents").glob("*.plist"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_script_ran_and_emitted_every_service(self):
        """★ 先证探针本身有效：0 份 plist 会让下面每条断言**恒绿**。"""
        self.assertEqual(self.proc.returncode, 0,
                         f"安装脚本失败:\n{self.proc.stdout[-2000:]}\n{self.proc.stderr[-2000:]}")
        names = {p.name.rsplit(".", 2)[-2] for p in self.plists}
        self.assertEqual(names, {"autosync", "quotad", "proxy", "dawnprobe"},
                         f"生成出来的服务不对: {names}")

    def test_every_plist_carries_the_store_variable(self):
        for p in self.plists:
            with self.subTest(plist=p.name):
                d = plistlib.loads(p.read_bytes())
                env = d.get("EnvironmentVariables") or {}
                self.assertIn(VAR, env,
                              f"★★ {p.name} 没有 {VAR} —— 它会按 __file__ 猜到安装目录")
                self.assertEqual(env[VAR], str(self.tmp / "store"))

    def test_the_proxy_still_gets_its_port(self):
        """★ 反向闸：把四个字典合成一个的过程中，**原有的变量不能丢**。
        `CRP_PORT` 从 body 挪进了 `ENV_EXTRA`，挪丢了代理会去听默认端口。"""
        proxy = next(p for p in self.plists if p.name.endswith(".proxy.plist"))
        env = plistlib.loads(proxy.read_bytes())["EnvironmentVariables"]
        self.assertEqual(env.get("CRP_PORT"), "8011")

    def test_the_extra_env_does_not_leak_into_the_next_service(self):
        """★★ `ENV_EXTRA` 是模块级变量，`emit` 用完必须清。串味不会报错 ——
        `dawnprobe` 拿到 `CRP_PORT` 不会有任何症状，直到某天它有意义为止。"""
        for p in self.plists:
            if p.name.endswith(".proxy.plist"):
                continue
            env = plistlib.loads(p.read_bytes()).get("EnvironmentVariables") or {}
            self.assertNotIn("CRP_PORT", env, f"{p.name} 串到了 proxy 的变量")

    def test_a_missing_store_directory_fails_loudly(self):
        """★ 指到一个不存在的目录时必须**硬失败**，不能装完再让每个服务各自出错。"""
        env = dict(os.environ)
        env.update({"HOME": str(self.tmp / "home"),
                    "PATH": f"{self.tmp / 'bin'}:{env['PATH']}",
                    VAR: str(self.tmp / "definitely-not-here")})
        r = subprocess.run(["bash", str(LAUNCHD)], capture_output=True, text=True,
                           env=env, cwd=str(ROOT), timeout=60)
        self.assertNotEqual(r.returncode, 0, "不存在的数据目录被静默接受了")
        self.assertIn("数据目录不存在", r.stdout + r.stderr)


class TheWindowsTasksCarryTheStore(unittest.TestCase):
    """Windows 侧没法在 macOS 上执行，所以判据落在**任务表**上 —— 但要判到
    「每个任务的 Env 都含它」，不是「文件里出现过这个词」。"""

    SRC = WINDOWS.read_text(encoding="utf-8")

    def test_every_task_row_gets_the_base_env(self):
        rows = re.findall(r"@\{\s*Name\s*=\s*\"(\w+)\";.*?Env\s*=\s*([^\n]+?)\s*\}(?:,|\s*\n\))",
                          self.SRC, re.S)
        self.assertEqual({r[0] for r in rows},
                         {"proxy", "quotad", "autosync", "dawnprobe"},
                         f"解析不出全部任务行 —— 探针坏了，不是规则没了: {rows}")
        for name, env in rows:
            with self.subTest(task=name):
                self.assertIn("$BaseEnv", env,
                              f"★★ {name} 没带 $BaseEnv ⇒ 它会在安装目录上单干: {env}")

    def test_the_base_env_is_the_store_and_never_the_install_dir(self):
        m = re.search(r"\$BaseEnv\s*=\s*@\{([^}]*)\}", self.SRC)
        self.assertIsNotNone(m, "找不到 $BaseEnv")
        self.assertIn(VAR, m.group(1))
        # ★★ `$Repo` = `$PSScriptRoot/..` = **安装目录本身**。拿它当数据目录，
        #    等于把这条修法原地退回去 —— 而看起来像修好了。
        block = self.SRC[self.SRC.index("$Store = "):self.SRC.index("$BaseEnv")]
        self.assertNotIn("$Repo", block,
                         "★★ 用 $Repo(安装目录)当数据目录兜底 —— Windows 更新时会被整个替换")


if __name__ == "__main__":
    unittest.main()
