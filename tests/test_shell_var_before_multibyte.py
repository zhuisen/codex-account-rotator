"""shell 里 `$变量` 后面**紧跟**多字节字符（全角逗号、括号、中文）—— bash 3.2 会把它吞进变量名。

## 2026-09-26 真事故（v1.9.2 里就有；mimo 会话记录 + 本机复现）
`install-launchd.sh` 有一行 `echo "… bootstrap rc=$rc，重试 …"`。macOS 自带 bash 3.2 在 UTF-8 环境下
把 `，` 的首字节 `\\xef` 当成标识符的一部分 ⇒ `set -u` 报 `rc\\xef: unbound variable`：

    $ LANG=en_US.UTF-8 /bin/bash -c 'set -u; rc=1; echo "$rc，"'
    /bin/bash: rc�: unbound variable

这条路径只在「服务装不上」时才走，所以平时看不见；一走，**真错误被换成一句乱码报错**，
stderr 里还带着非法 UTF-8，`connector.py` 用 `text=True` 严格解码 ⇒ 抛 `UnicodeDecodeError`，
用户在设置页看到的是一份 Python Traceback，与真因（launchd 装不上）毫无关系。
修法是 `${rc}`。这份闸扫**全部** shell 脚本，并先证扫描器自己会响（已知阳性）。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `$name` 或 `$1` 后面紧跟一个 ≥0x80 的字节；`${name}` 是安全的，不算。
HAZARD = re.compile(rb"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9])[\x80-\xff]")


def shell_scripts():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    found = []
    for rel in out.splitlines():
        p = ROOT / rel
        if not p.is_file() or "node_modules" in rel or "/target/" in rel:
            continue
        try:
            head = p.read_bytes()[:120]
        except OSError:
            continue
        if rel.endswith(".sh") or re.match(rb"#!.*\b(ba|z)?sh\b", head):
            found.append(p)
    return found


class NoVariableIsFollowedByAMultibyteChar(unittest.TestCase):
    def test_the_scanner_fires_on_the_known_bad_line(self):
        """★ 已知阳性：v1.9.2 里那一行。扫描器不响，下面那条恒绿就毫无意义。"""
        bad = 'echo "  ⛔ $name 装不上（bootstrap rc=$rc，重试 $tries 次）"'.encode()
        self.assertTrue(HAZARD.search(bad))
        self.assertFalse(HAZARD.search('echo "rc=${rc}，重试 $tries 次"'.encode()))

    def test_the_scan_actually_covers_the_scripts(self):
        names = {p.name for p in shell_scripts()}
        self.assertIn("install-launchd.sh", names, "★★ 没扫到安装脚本 —— 文件枚举失准，闸此刻没有判别力")
        self.assertGreaterEqual(len(names), 6)

    def test_no_script_has_one(self):
        hits = []
        for p in shell_scripts():
            for i, line in enumerate(p.read_bytes().split(b"\n"), 1):
                m = HAZARD.search(line)
                if m:
                    hits.append(f"{p.relative_to(ROOT)}:{i}: {line.decode('utf-8', 'replace').strip()[:100]}")
        self.assertEqual(hits, [], "★★ `$变量` 后紧跟多字节字符，bash 3.2 会吞进变量名，改成 `${变量}`：\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main(verbosity=2)
