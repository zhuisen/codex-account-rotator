"""子进程必须被收尸（2026-09-17，用户实报「CodexBar 会留下僵尸进程」）。

## 缺陷：`let _ = cmd.spawn();` 每跑一次留一个僵尸

**Rust 的 `Child` 没有会 `wait` 的 `Drop`** —— 这是标准库明写的行为，不是本仓的怪癖。
句柄一离开作用域，子进程照常跑；等它自己退出，就变成 `<defunct>`，
**一直挂到父进程 reap 它、或者父进程自己退出**。

本仓两处采样器就是这么写的（`lib.rs` 的定时循环里）：
  定时器每 3 秒一拍、`% 60` ⇒ 每 3 分钟尝试拉一次采样器；
  采样器空闲 180s 后自退 ⇒ 退了就成僵尸、锁文件随之消失 ⇒ 3 分钟后再拉一个。
两个采样器轮流，**持续累积**。

## 实测（2026-09-17，最小复现，两个方向都验了）

    丢弃 Child（原写法）    3 次 spawn -> 僵尸 3
    收尸线程（修复后写法）  3 次 spawn -> 新增僵尸 0

★ 同日在本机数到 17 个僵尸，**一个都不是 CodexBar 的**（它当时的两个 spawn 路径
  正被锁文件抑制着）：10 个属于另一个 app、7 个属于常驻 `agy`（每个 agy 各 1 个）。
  **同一个形状在三个不相干的程序里各犯了一次** —— 它不是谁粗心，
  是这个 API 的默认行为在咬人。所以这条闸守的是**写法**，不是某一处调用点。

## 为什么判据打在"写法"上

僵尸的症状极其温和：进程表里多几行 `<defunct>`，不占 CPU、几乎不占内存，
app 一切正常。**它只有在跑了很久之后、由用户在 `ps` 里发现**——
也就是说，任何"跑一会儿看看"的验证都看不见它。
能在改动当下就变红的，只有对写法的断言。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src-tauri" / "src"


def _rs_sources():
    return sorted(SRC.rglob("*.rs"))


def _strip(src: str) -> str:
    """剥掉 Rust 注释。本仓注释密度极高，而这条规则的说明里就写着
    `let _ = cmd.spawn()` 这个反例 —— 不剥必被自己的说明判红（空守卫形态④）。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


class EverySpawnedChildGetsReaped(unittest.TestCase):

    def test_there_are_rust_sources_to_scan(self):
        """★ 已知阳性自检：扫到 0 个文件时「没有违规」和「没扫」长得一模一样。"""
        files = _rs_sources()
        self.assertTrue(files, "★ 一个 .rs 都没扫到 —— 是路径错了，不是代码干净")
        self.assertTrue(any(".spawn()" in f.read_text(encoding="utf-8") for f in files),
                        "★ 没有任何 `.spawn()` —— 探针多半打空了")

    def test_no_spawn_result_is_discarded(self):
        """★★★ 主闸：**不许丢弃 `spawn()` 的返回值**。

        `let _ = ….spawn();` 与裸 `….spawn();` 都会让 `Child` 立刻被 drop，
        而 drop **不会** reap —— 那正是用户报的那个僵尸。
        """
        bad = []
        for f in _rs_sources():
            code = _strip(f.read_text(encoding="utf-8"))
            for i, line in enumerate(code.splitlines(), 1):
                s = line.strip()
                if ".spawn()" not in s:
                    continue
                # `let _ = …spawn()`：丢弃返回值 —— 正是那个 bug 的形状
                if re.search(r"let\s+_\s*=", s):
                    bad.append("{}:{}  {}".format(f.name, i, s[:88]))
            # 跨行形态：`let _ = py_cmd()` … 若干行 … `.spawn();`
            for m in re.finditer(r"let\s+_\s*=[^;]*?\.spawn\(\)\s*;", code, re.S):
                ln = code[:m.start()].count("\n") + 1
                bad.append("{}:{}  （跨行）{}".format(
                    f.name, ln, " ".join(m.group(0).split())[:88]))

        self.assertEqual(
            sorted(set(bad)), [],
            "★★★ 这些地方丢弃了 `spawn()` 的返回值，每跑一次留一个僵尸：\n  "
            + "\n  ".join(sorted(set(bad)))
            + "\n  → 改走 `spawn_and_reap(cmd)`（起了之后在独立线程里 `wait()` 收尸）。"
              "\n  ⚠️ 不要改成 `.status()`：那会**阻塞定时器**。"
              "\n  ⚠️ 也不要只把 `let _` 换成绑定变量就完事 —— 绑定之后不 `wait()` 一样是僵尸。")

    def test_the_reaper_helper_exists_and_actually_waits(self):
        """★★ `spawn_and_reap` 必须**真的 `wait()`**，而且在**独立线程**里。

        少了 `wait()` 就只是换了个名字的同一个 bug；
        不放线程里则会阻塞那个 3 秒一拍的定时器。
        """
        lib = _strip((SRC / "lib.rs").read_text(encoding="utf-8"))
        self.assertIn("fn spawn_and_reap", lib, "★★ 收尸函数不见了")
        i = lib.index("fn spawn_and_reap")
        body = lib[i:lib.index("\nfn ", i + 10)]
        self.assertIn("thread::spawn", body,
                      "★★ 收尸没放进独立线程 —— 会阻塞 3 秒一拍的定时器")
        self.assertRegex(body, r"\.wait\(\)",
                         "★★★ 收尸函数里没有 `wait()` —— 换了个名字的同一个 bug")

    def test_the_sampler_launches_go_through_it(self):
        """★ 两处采样器（agy / grok）都要走收尸路径 —— 它们正是用户报的那两个。"""
        lib = _strip((SRC / "lib.rs").read_text(encoding="utf-8"))
        self.assertGreaterEqual(
            lib.count("spawn_and_reap("), 3,
            "★ `spawn_and_reap` 的出现次数不足（1 个定义 + 2 个采样器调用点）"
            " —— 有采样器没走收尸")

    def test_python_side_never_leaves_popen_unwaited(self):
        """★ Python 侧同理：裸 `Popen` 不 `wait`/`communicate` 也留僵尸。

        生产脚本一律走 `subprocess.run`（内部会 wait）。这条钉住那个现状 ——
        哪天有人为了"不阻塞"改成 `Popen`，僵尸就会从另一侧回来。
        ⚠️ 测试与已归档的 `scripts/native-resume/` 不在范围内（前者自己管生命周期，
          后者是**定稿弃案**的存档，不参与运行）。
        """
        bad = []
        for f in sorted(ROOT.rglob("*.py")):
            rel = f.relative_to(ROOT).as_posix()
            if rel.startswith(("tests/", "scratch/", "scripts/native-resume/",
                               "codexbar/node_modules/", "codexbar/uishot/app/")):
                continue
            code = re.sub(r"#[^\n]*", "", f.read_text(encoding="utf-8", errors="replace"))
            if "Popen(" in code:
                bad.append(rel)
        self.assertEqual(bad, [],
                         "★ 这些生产脚本用了裸 `Popen`：{}\n"
                         "  → 要么 `subprocess.run`，要么显式 `wait()`/`communicate()`，"
                         "否则子进程退出后留僵尸".format(bad))


if __name__ == "__main__":
    unittest.main()
