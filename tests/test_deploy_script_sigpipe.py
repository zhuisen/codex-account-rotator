"""`deploy.sh` 不许被自己的管道静默杀掉（SIGPIPE × `set -euo pipefail`）。

## 事故（2026-09-23）

2026-09-21 给 `deploy.sh` 加了「核实跑起来的是不是刚装的那份」，其中一行：

    _running="$(ps -Ao pid=,comm= | awk '$2 ~ /codexbar$/ {print $1; exit}')"

awk 找到第一行就 `exit`，关掉管道读端；`ps` 若还在写，吃 SIGPIPE（exit 141）。
脚本开着 `set -euo pipefail` ⇒ 整条管道算失败 ⇒ `set -e` **当场静默退出整个 deploy.sh**。
后面的「✓ deployed — vX.Y.Z+B」与 B≠0 告警一行都不打 —— 而新包其实**已经装好并启动了**，
所以看上去和成功一模一样。是竞态（`ps` 写得比 awk 退出快就不触发），于是**时好时坏**：
同一天两次 deploy，一次打印完整、一次停在 `==> launching`。

★ 讽刺在于：那段代码本身就是一道「别让失败看起来像成功」的闸。
  **给闸本身也要上闸** —— 否则它失效的样子就是它想防的那个样子。

## 判据

① **行为**：把那一行里的 `ps` 换成一个**确定性的大输出**（远超 64KB 管道缓冲），
   在 `set -euo pipefail` 下真跑。提前退出的消费者在这里**必然** SIGPIPE，不靠运气撞竞态。
② **已知阳性自检**：同一套装置喂旧写法，必须跑出 141 —— 否则装置本身是坏的。
③ **结构**：整份脚本（剥注释后）不许再出现「管道尾巴提前退出」的形态：
   awk 里的 `exit`、`| head`、`| grep -q` / `grep -m`。
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "codexbar" / "scripts" / "deploy.sh"

#: 远大于管道缓冲（macOS 64KB）的确定性输出：20 万行 × ~20 字节 ≈ 4MB，且每行都能被匹配。
BIG = "seq 1 200000 | sed 's|$| /x/codexbar|'"
OLD_LINE = """_running="$(ps -Ao pid=,comm= | awk '$2 ~ /codexbar$/ {print $1; exit}')\""""


def _code(src: str) -> str:
    """剥掉 shell 注释 —— 这份脚本的注释里**逐字写着**旧的坏写法（在解释它为什么坏），
    不剥的话结构断言会撞上正在解释这条规则的说明文字（本仓形态④）。"""
    out = []
    for line in src.splitlines():
        s = line.lstrip()
        if s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def _run_line(line: str) -> int:
    probe = line.replace("ps -Ao pid=,comm=", BIG)
    assert probe != line, "替换没生效 —— 装置没有换上确定性输入"
    r = subprocess.run(["bash", "-c", f"set -euo pipefail\n{probe}\necho SURVIVED"],
                       capture_output=True, text=True, timeout=60)
    return r.returncode if "SURVIVED" not in r.stdout else 0


class DeployIsNotKilledByItsOwnPipe(unittest.TestCase):
    def _current_line(self) -> str:
        code = _code(DEPLOY.read_text(encoding="utf-8"))
        lines = [l.strip() for l in code.splitlines() if l.strip().startswith("_running=")]
        self.assertEqual(1, len(lines), f"★★ 找不到（或不止一处）`_running=` 那一行：{lines}")
        return lines[0]

    def test_the_rig_fires_on_the_known_positive(self):
        """★★ 已知阳性：旧写法在这套装置下**必然**被 SIGPIPE 杀掉（141）。"""
        self.assertEqual(141, _run_line(OLD_LINE),
                         "★★ 旧写法没被杀 —— 装置没有判别力，下面那条的绿不可信")

    def test_the_real_line_survives_pipefail(self):
        self.assertEqual(0, _run_line(self._current_line()),
                         "★★★ deploy.sh 的进程核实那一行在 pipefail 下会被 SIGPIPE 杀掉 ——"
                         "整个 deploy 会在 `==> launching` 之后静默结束")

    def test_the_script_really_runs_under_pipefail(self):
        """★ 前提：脚本确实开着 pipefail。哪天去掉了，上面两条就不再描述真实风险。"""
        self.assertIn("set -euo pipefail", DEPLOY.read_text(encoding="utf-8"))

    def test_no_early_exiting_pipe_tail_anywhere(self):
        """★ 结构：**所有**开着 pipefail 的 shell 脚本都不许有「管道尾巴提前退出」的形态。

        2026-09-23 第一版只查 deploy.sh，一扫就在别处又找到 3 处：`setup-signing.sh` 的
        `grep -q`（竞态时把「证书已存在」判成不存在 → 再造一张）与 `| head -2`，
        `install-launchd.sh` 的 awk `exit`。**同一个坑只查发现它的那个文件 = 等于没查。**
        """
        skip = {".git", "node_modules", "target", "scratch", "swiftbar", "app", "uishot"}
        piped = []
        for p in ROOT.rglob("*"):
            if not p.is_file() or p.suffix not in ("", ".sh") or p.stat().st_size > 400_000:
                continue
            if any(part in skip for part in p.relative_to(ROOT).parts):
                continue
            try:
                txt = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if txt.startswith("#!") and "sh" in txt.splitlines()[0] and "pipefail" in txt:
                piped.append(p)
        self.assertIn(DEPLOY, piped, "★★ 连 deploy.sh 都没扫到 —— 扫描范围坏了，下面的空结果不可信")
        self.assertGreaterEqual(len(piped), 3, f"★ 只扫到 {len(piped)} 个开 pipefail 的脚本：{piped}")
        bad = []
        for p in piped:
            code = _code(p.read_text(encoding="utf-8"))
            for n, line in enumerate(code.splitlines(), 1):
                if "|" not in line:
                    continue
                where = f"{p.relative_to(ROOT)}:{n}"
                if re.search(r"\|\s*awk\b.*\bexit\b", line):
                    bad.append(f"{where} awk 里 exit：{line.strip()}")
                if re.search(r"\|\s*head\b", line):
                    bad.append(f"{where} | head：{line.strip()}")
                if re.search(r"\|\s*grep\s+(-\w*[qm]\w*)", line):
                    bad.append(f"{where} | grep -q/-m：{line.strip()}")
        self.assertEqual([], bad, "★ 这些管道在 `set -euo pipefail` 下会间歇性出错或静默改走分支：\n  "
                         + "\n  ".join(bad))

if __name__ == "__main__":
    unittest.main(verbosity=2)
