"""★★ 打包清单闸：`lib.rs` 里每个从 `script_dir()` 拼出来的路径，都必须在
`tauri.conf.json` 的 `bundle.resources` 里。

## 为什么必须泛化，而不是逐个手列

同类事故 2026-09-05 发生过一次：脚本在仓库里好好的、`cargo check` 通过、
开发机 `npm run tauri dev` 一切正常 —— 因为开发时 `script_dir()` 指向仓库。
**只有装出来的 app 会炸**，而症状是那一页空白，和"还没有数据"长得一样。

手列一份清单只会在下一个新脚本出现时再漏一次。这里改成**从源码里解析**：
`lib.rs` 想跑什么，清单里就必须有什么。两边任何一边动了，闸自己会跟。

## 顺带守包结构

`relay/` 是 Python 包（`monitor.py` 里 `from . import store`）。
少一个 `__init__.py`，装出来的 app 起 python 时报 `ImportError`，
而**开发机永远复现不了**（仓库里那份一直在）。
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB_RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"
CONF = ROOT / "codexbar" / "src-tauri" / "tauri.conf.json"

# `format!("{}/relay-ctl", script_dir())` / `format!("{}/traffic/scan.py", script_dir())`
SCRIPT_REF = re.compile(r'format!\(\s*"\{\}/([^"]+)"\s*,\s*script_dir\(\)\s*\)')


def resources():
    return json.loads(CONF.read_text(encoding="utf-8"))["bundle"]["resources"]


def strip_comments(src):
    """去掉行注释 —— 否则注释里提到的路径会被当成真的引用（本仓的老形态：
    断言匹配到了自己写的解释性注释）。"""
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))


class EveryScriptLibRsRunsIsBundled(unittest.TestCase):
    def test_the_probe_finds_something(self):
        """★ 先证探针本身有效。一个匹配数为 0 的正则会让整条闸恒绿 ——
        本仓的老教训：扫描器查了 0 个对象却报"干净"。"""
        refs = SCRIPT_REF.findall(strip_comments(LIB_RS.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(refs), 4, f"只解析到 {len(refs)} 处 script_dir() 引用，正则可能失效了")

    def test_every_referenced_script_is_in_the_manifest(self):
        refs = sorted(set(SCRIPT_REF.findall(strip_comments(LIB_RS.read_text(encoding="utf-8")))))
        targets = set(resources().values())
        missing = [r for r in refs if f"scripts/{r}" not in targets]
        self.assertEqual(missing, [], f"lib.rs 会跑但没进打包清单: {missing}")

    def test_every_manifest_source_actually_exists(self):
        """★ 反方向：清单里写了但仓库里没有的文件，打包时会静默少一个 ——
        `tauri build` 对缺失资源不一定报错。"""
        conf_dir = CONF.parent
        missing = [src for src in resources()
                   if not (conf_dir / src).resolve().exists()]
        self.assertEqual(missing, [], f"清单指向不存在的文件: {missing}")


class ThePythonPackageShipsWhole(unittest.TestCase):
    """`relay/` 是包（`from . import store`）。少一个文件 = 装出来的 app 起 python 就 ImportError，
    而开发机永远复现不了 —— 仓库里那份一直在。"""

    def test_every_file_the_package_needs_is_bundled(self):
        targets = set(resources().values())
        for name in ("__init__.py", "store.py", "monitor.py"):
            with self.subTest(f=name):
                self.assertIn(f"scripts/relay/{name}", targets,
                              f"relay/{name} 没进打包清单")

    def test_the_package_really_is_a_package_not_two_loose_modules(self):
        """★ 判据是**源码里真的用了相对导入**，不是我在这里假设它是包。
        哪天有人改成绝对导入，上面那条对 `__init__.py` 的要求就该跟着变。"""
        src = (ROOT / "relay" / "monitor.py").read_text(encoding="utf-8")
        self.assertIn("from . import", src)
        self.assertTrue((ROOT / "relay" / "__init__.py").exists())

    def test_the_key_helper_is_gone(self):
        """★ 2026-09-09「一个 provider，两种上游」之后，codex 不再自己去取中转站的 key ——
        **代理**直接从 `relays.local.json` 读并放进 Authorization 头。`relay/relay-key`
        及其 `auth.command` 接线随之删除。

        钉住"它不该回来"：留一个没人调用的取 key 脚本，下一个人会以为那条路还活着，
        并照着它去查一个根本不会执行的鉴权链路。
        """
        self.assertFalse((ROOT / "relay" / "relay-key").exists(),
                         "relay-key 又出现了 —— 新架构里没有任何东西会执行它")


class TheRelayCommandsAreRegistered(unittest.TestCase):
    """★ 写了 `#[tauri::command]` 但忘了进 `invoke_handler` ⇒ 前端 `invoke` 报
    "command not found"，而那条报错在 webview 控制台里，用户只看到按钮没反应。"""

    def test_each_relay_command_is_in_the_invoke_handler(self):
        src = strip_comments(LIB_RS.read_text(encoding="utf-8"))
        handler = src[src.index("generate_handler!["):]
        for name in ("read_relay_snapshot", "run_relay_usage", "relay_ctl"):
            with self.subTest(cmd=name):
                self.assertIn(f"fn {name}", src, f"{name} 根本没定义")
                self.assertIn(name, handler, f"{name} 没注册进 invoke_handler")


if __name__ == "__main__":
    unittest.main()
