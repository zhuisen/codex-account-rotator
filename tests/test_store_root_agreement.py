"""★★★ 全仓所有 python 入口必须对「数据目录在哪」给出**同一个**答案。

`CODEX_ROTATE_STORE` 是本仓统一的数据目录变量。Windows 上 CodexBar 每次更新会把
**整个安装目录换掉**，所以数据目录必须与安装目录分开 —— 这个变量就是分开的方式。

## 为什么这是一条闸，而不是一条约定

不一致的后果**不报错**，是脑裂：`relay-ctl` 把 `route.local.json` 写进数据目录，
代理去读安装目录里的那份 ⇒ **切了路由代理毫不知情**，UI 显示"当前：中转站"、
实际请求还发去 chatgpt.com。`auth/` / `state.json` 同理；两把跨进程锁
（`.refresh.lock` / `.state.lock`）落在不同路径上**等于没有锁** ——
`codex-rotate` 与代理会同时刷同一个号的 token。

实测 2026-09-10：八处认这个变量，`proxy/proxy.py` 是唯一的例外。

## ⚠️ 这条闸**只验一半**，另一半在 `test_installers_pass_the_store.py`

这里往 subprocess 里**自己注入**变量，所以它证明的是「**给了**变量时两处算得一样」。
它永远证明不了「launchd / 计划任务**供给了**这个变量」—— 而 2026-09-10 四方评审
三个面板独立指出：代码改完了、没人喂它，安装器里一个任务都没带。
两条闸缺一不可，别把这条当成"脑裂已解决"的证据。
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ★ 每一项都是"这个文件读了这个环境变量"。加新入口时必须同时加进来 ——
#   这份清单就是判据本身，不是文档。
# ⚠️ 原来这里是 `(路径, 变量名)` 的二元组，而下面 `for rel, _ in ENTRIES` 把第二列丢掉了 ——
#    清单在**广告一份它并不具备的覆盖**（评审抓到）。真要按变量名判就得逐个 import，
#    那是另一条闸的事；这里只判"读没读"，所以退回成一维清单，不留假承诺。
ENTRIES = [
    "proxy/proxy.py",
    "traffic/scan.py",
    "traffic/rotation.py",
    "traffic/quota_anchors.py",
    "traffic/agy_quota_sampler.py",
    "relay/store.py",
    "codex-rotate",
]


class EveryEntryPointHonoursTheStoreVariable(unittest.TestCase):

    def test_every_python_entry_point_reads_the_variable(self):
        """★ 判据是**源码里真的读了这个环境变量**，不是"文件里出现过这个名字"。

        只 grep 名字的话，一句解释它的注释就能让闸永远绿 —— 本仓记过的空守卫形态④。
        所以剥掉注释和字符串字面量之后再找 `os.environ...("CODEX_ROTATE_STORE")`。
        """
        pat = re.compile(r"""environ(?:\.get\(|\[)\s*["']CODEX_ROTATE_STORE["']""")
        missing = []
        for rel in ENTRIES:
            src = (ROOT / rel).read_text(encoding="utf-8")
            # 去掉整行注释与 docstring 段落:注释里正解释着这条规则。
            code = "\n".join(ln for ln in src.splitlines()
                             if not ln.lstrip().startswith("#"))
            code = re.sub(r'"""(?:.|\n)*?"""', "", code)
            if not pat.search(code):
                missing.append(rel)
        self.assertEqual(missing, [],
                         f"★★ 这些入口不认 CODEX_ROTATE_STORE，会与其余入口脑裂: {missing}")

    def test_proxy_and_relay_store_resolve_to_the_same_root(self):
        """★★ 真正跑一遍两个模块，比对它们算出来的根 —— 这是"两份实现在同一个
        边界输入上是否一致"的直接检验，比读源码强。

        `proxy.py` 会起服务器,所以只 import 不运行(它的 `main()` 在 `__main__` 里)。
        """
        fixture = str(Path(tempfile.gettempdir()) / "codexbar-store-agreement-fixture")
        for env_root in (None, fixture):
            with self.subTest(env=env_root):
                env = dict(os.environ)
                env.pop("CODEX_ROTATE_STORE", None)
                if env_root:
                    env["CODEX_ROTATE_STORE"] = env_root
                out = subprocess.run(
                    [sys.executable, "-c",
                     "import sys; sys.path.insert(0, %r)\n"
                     "import importlib.util as u, pathlib\n"
                     "spec = u.spec_from_file_location('pxy', %r)\n"
                     "m = u.module_from_spec(spec); spec.loader.exec_module(m)\n"
                     "from relay import store\n"
                     "print(str(m.STORE)); print(str(pathlib.Path(store.store_path()).parent.parent))"
                     % (str(ROOT), str(ROOT / "proxy" / "proxy.py"))],
                    capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr[-2000:])
                # ★ `.split()` 会按**任意空白**切 —— 路径里有空格（Windows 用户名常见）
                #   就变成 `ValueError: too many values to unpack`，而那是个假红。
                a, b = out.stdout.splitlines()
                self.assertEqual(a, b,
                                 f"★★ proxy.py 算出 {a}，relay/store.py 算出 {b} —— 脑裂")
                if env_root:
                    # ★ 比 `Path` 不比字符串:Windows 上 `str(Path("/tmp/x"))` 是 `\tmp\x`，
                    #   直接比原串会永远不等 —— 又一个假红。
                    self.assertEqual(Path(a), Path(env_root),
                                     f"★ 设了 CODEX_ROTATE_STORE 却没用上: {a}")

    def test_the_default_is_byte_for_byte_unchanged(self):
        """★ 反向闸：**不设**该变量时必须与改动前逐字相同（仓库根）。
        这条修法的全部安全性就建立在"默认值没变"上。"""
        env = dict(os.environ); env.pop("CODEX_ROTATE_STORE", None)
        out = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util as u\n"
             "spec = u.spec_from_file_location('pxy', %r)\n"
             "m = u.module_from_spec(spec); spec.loader.exec_module(m)\n"
             "print(str(m.STORE))" % str(ROOT / "proxy" / "proxy.py")],
            capture_output=True, text=True, env=env, cwd="/", timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip(), str(ROOT))


if __name__ == "__main__":
    unittest.main()
