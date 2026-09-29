"""CI 出的 .dmg 没有构建期烧录值时，数据目录必须接上**已经在用的**那个（2026-09-26 事故）。

用户在 clone 装机的机器上从 GitHub 更新 CodexBar：新 app 的 `data_dir()` 落到空的 `app_data_dir()`，
账号「全丢」、无法刷新 —— 数据其实还在原来的仓库目录里，launchd 的代理 / quotad 也还在读它，
于是 app 与服务分叉（`.state.lock` 落在两个路径上 = 没有锁）。`deploy.sh` 构建的包有烧录值，
所以这个缺陷**在开发机上永远看不见**，只有从 GitHub 更新的那一刻才炸。

Rust 侧的选择逻辑是纯函数 `pick_data_root`，自带单元测试（6 条）；CI 只跑 `cargo check`，
所以这里把它接进 unittest —— 静态断言接线 + 真跑 `cargo test`（本机没有 cargo 就 skip，skip 不是绿）。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"


class TheSetupUsesTheDiscovery(unittest.TestCase):
    SRC = LIB.read_text(encoding="utf-8")

    def test_the_fallback_goes_through_pick_data_root(self):
        """★★ 函数写了没人调 = 白写（本仓「改了谁来读，没验谁来写」的翻版）。"""
        code = re.sub(r"//[^\n]*", "", self.SRC)
        i = code.index("let data = std::env::var(\"CODEXBAR_STORE\")")
        seg = code[i:code.index("if let Some(d) = data", i)]
        self.assertIn("pick_data_root(", seg, "★★ app_data_dir 兜底没经过 pick_data_root —— CI 包更新后账号仍会「丢」")
        # 顺序：env > 烧录值 > 发现 —— 烧录值必须仍排在发现之前，否则 deploy.sh 装机的行为会变
        self.assertLess(seg.index("CODEXBAR_STORE_DEFAULT"), seg.index("pick_data_root("))

    def test_the_priority_is_app_data_then_services_then_convention(self):
        code = re.sub(r"//[^\n]*", "", self.SRC)
        f = code[code.index("fn pick_data_root("):]
        f = f[:f.index("\n}\n")]
        pos = [f.index("has_state(app_data)"), f.index("codex-rotate.proxy.plist"),
               f.index("Projects/tools/codex-account-rotator")]
        self.assertEqual(pos, sorted(pos), "★ 发现顺序变了（自己已有数据 > 服务在读的 > 约定位置）")


@unittest.skipUnless(shutil.which("cargo") and sys.platform == "darwin", "需要本机 cargo（macOS）")
class TheRustUnitTestsPass(unittest.TestCase):
    def test_store_pick_tests(self):
        r = subprocess.run(["cargo", "test", "--lib", "store_pick", "--manifest-path",
                            str(ROOT / "codexbar" / "src-tauri" / "Cargo.toml")],
                           capture_output=True, text=True, timeout=590)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out[-1500:])
        self.assertRegex(out, r"6 passed", "★★ 一条都没跑到 —— 过滤词失准，闸此刻没有判别力")


if __name__ == "__main__":
    unittest.main(verbosity=2)
