"""「扫描新数据源」必须区分**已注册**与**在扫**（`traffic/discover.py`）。

## 为什么需要这条

报告原来只有两档：`已注册` / `新发现`。但一个源可能**已注册却被停用**
（`sources.local.json` 的 `disabled`），此时它有解析器、却**一条记录都不解析**，
而报告照样说「已注册」—— 用户会以为那份数据已经在图里了，没有第二个办法分辨。

这是本仓库那条铁律的又一形态：**「有能力处理」和「确实处理了」不能返回同一个值。**

## 为什么只有这一档能自动启用

用户 2026-08-31 问「扫描出来之后能不能自动入库」。答案分两半：

- **已注册但被停用** ⇒ 可以。它已经有手写解析器，启用只是把 key 从 `disabled` 里拿掉。
- **新发现** ⇒ **不能**。`classify()` 证明的是**算术**（哪个字段子集恒等于 `total`），
  **不是语义** —— 它不告诉你某字段是 input 还是 output、算不算 cache_read。
  而四类 token 单价不同（缓存读还按平台各算折扣），**归错类会静默算出错的费用**。
  这与 `SOURCES` 那条「解析器必须一家一写，猜字段名正是会静默算错数的做法」是同一条。
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    """按路径加载，并**先把 `scan` 从模块缓存里踢掉**。

    ★ `discover.py` 内部走 `from scan import …`，而 `scan` 一进 `sys.modules` 就会被复用 ——
      它的 `LOCAL_CFG` 是在**自己被加载那一刻**由 `CODEX_ROTATE_STORE` 算出来的，
      于是第二个用例读的还是第一个用例的临时目录，断言凭空变红。
      （这与 quotad 那次「SourceFileLoader 在启动时把代码载进内存、之后改文件没用」是同一族问题，
      只不过这次咬的是测试自己。）
    """
    for cached in ("scan", name):
        sys.modules.pop(cached, None)
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / rel))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class DiscoverReportsWhetherSourceIsActuallyScanning(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="discover-enabled-test-")
        os.makedirs(os.path.join(self.dir, "traffic"), exist_ok=True)
        self._old = os.environ.get("CODEX_ROTATE_STORE")
        os.environ["CODEX_ROTATE_STORE"] = self.dir

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CODEX_ROTATE_STORE", None)
        else:
            os.environ["CODEX_ROTATE_STORE"] = self._old

    def _write_disabled(self, keys):
        p = os.path.join(self.dir, "traffic", "sources.local.json")
        Path(p).write_text(json.dumps({"disabled": list(keys)}), encoding="utf-8")

    def test_scanner_honours_the_disabled_list_from_the_data_dir(self):
        """★ 配置必须从**数据目录**读，不是脚本目录。

        脚本会被打进桌面应用的安装包 —— 配置若跟着走，Windows 上每次更新被整个替换、
        macOS 上根本写不进去，用户在设置页点的「停用」下次启动就没了。
        """
        self._write_disabled(["codex"])
        scan = load("scan_off", "traffic/scan.py")
        keys = {s["key"] for s in scan._enabled_sources()}
        self.assertNotIn("codex", keys, "写在数据目录的 disabled 没有生效 —— "
                                        "很可能仍在读脚本目录旁边那份")

        self._write_disabled([])
        scan2 = load("scan_on", "traffic/scan.py")
        self.assertIn("codex", {s["key"] for s in scan2._enabled_sources()},
                      "清空 disabled 后没有恢复")

    def test_discover_exposes_key_and_enabled(self):
        """报告里必须带 `key` 与 `enabled`，前端才能决定给不给「启用」按钮。"""
        self._write_disabled([])
        disc = load("disc", "traffic/discover.py")
        self.assertTrue(hasattr(disc, "_reg_state"), "_reg_state 不见了 —— 断言可能打空了")
        st = disc._reg_state(str(Path.home() / ".codex" / "sessions"))
        self.assertEqual(st.get("key"), "codex", "已注册的根没有映射回 key")
        self.assertIs(st.get("enabled"), True, "未停用时 enabled 应为 True")

    def test_disabled_registered_source_is_not_reported_as_enabled(self):
        """★★ 核心：**有解析器 ≠ 正在扫**。

        两者合并成一个 `known` 布尔，就等于告诉用户「这份数据已经在图里了」，
        而实际上一条都没解析。
        """
        self._write_disabled(["codex"])
        disc = load("disc_off", "traffic/discover.py")
        st = disc._reg_state(str(Path.home() / ".codex" / "sessions"))
        self.assertEqual(st.get("key"), "codex", "停用不该影响它仍然是已注册的")
        self.assertIs(st.get("enabled"), False,
                      "被停用的源报了 enabled=%r —— 用户会以为它的数据已经在图里" % st.get("enabled"))

    def test_unregistered_root_has_no_key_and_unknown_enabled(self):
        """新发现的源：没有 key，`enabled` 是 `None` 而**不是 False**。

        ★ `None` 与 `False` 必须分开：`False` 的意思是「有解析器但被关了，点一下就能开」，
        `None` 是「压根没有解析器，点了也没用」。前端据此决定给不给按钮 ——
        合并成一个值就会给出一个点了没反应的按钮。
        """
        disc = load("disc_new", "traffic/discover.py")
        st = disc._reg_state("/tmp/definitely-not-a-registered-source-xyz")
        self.assertIsNone(st.get("key"))
        self.assertIsNone(st.get("enabled"),
                          "未注册的源 enabled 应为 None(无从谈起),不是 False(可启用)")


if __name__ == "__main__":
    unittest.main()
