"""生产代码里不许有**未定义的名字**（`NameError` 静态闸）。

## 为什么要有这条

2026-09-21 把 `_pick` 里的候选判据抽成模块级 `usable()` 时，漏改了**兜底那一支**，
留下一个对已删除的 `rotatable` 的调用：

    avail = [(aid, sl) for aid, sl in slots.items()
             if aid not in exclude and not sl.get("auth_dead") and rotatable(sl)]

★★ 危险的不是这个错本身，是**它藏在哪**：这一支只有「一个干净可用的号都没有」
   （全部冷却/全部 dead）才走到 —— 也就是**池子最紧张、最需要它工作的那一刻**。
   日常每一个请求都走第一支，所以这个 `NameError` 可以安安静静躺几个月，
   等到真出事那天才炸，而炸出来的症状是「codex 整个不能用」。
   Python 解析期不查这个，`ast.parse` 也不查 —— 编译全过。

这正是本仓那条铁律的又一例：**写下来但没有闸的规则一定会被违反，包括被写它的人。**
上一次抽公共函数时同样的话已经写在注释里了。所以这次的交付物是**一条会变红的闸**，
不是又一句叮嘱。

## 判据

`pyflakes` 的 `undefined name`（F821）——**只取这一条**，不做风格检查：
未用的 import / 变量在本仓是常态（大量按平台分支的代码），全开会制造噪音，
而**一条会假红的闸，用户学会的是忽略它**。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 会真正跑起来的 Python：三个常驻进程 + CLI + 纯函数库。
#: ★ 不含 `tests/` 与 `scratch/`：前者有闸自己守，后者是一次性脚本。
TARGETS = [
    "proxy/proxy.py", "daemon/quota_daemon.py", "portalock.py",
    "codex-rotate", "agy-rotate", "grok-quota", "grok-quota-sampler",
]
TARGET_DIRS = ["traffic", "agy", "relay"]


def _files():
    out = [ROOT / t for t in TARGETS if (ROOT / t).exists()]
    for d in TARGET_DIRS:
        if (ROOT / d).is_dir():
            out += sorted((ROOT / d).glob("*.py"))
    return out


def _undefined(paths):
    r = subprocess.run([sys.executable, "-m", "pyflakes", *[str(p) for p in paths]],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    if "No module named pyflakes" in r.stderr:
        raise unittest.SkipTest("没装 pyflakes：`python3 -m pip install pyflakes`")
    return [l for l in r.stdout.splitlines() if "undefined name" in l]


class NothingCallsANameThatDoesNotExist(unittest.TestCase):
    def test_the_scanner_actually_had_something_to_scan(self):
        """★★ 先证明它**查了东西**。

        本仓 2026 年栽过一次「扫描器查了 0 个对象却报干净」，一轮里犯两次，
        差点放行仓库公开。空输入的 pyflakes 退出码是 0、输出是空 ——
        与「全部干净」**逐字节相同**。
        """
        files = _files()
        self.assertGreaterEqual(len(files), 8, f"被扫文件太少，判据失准：{files}")
        for key in ("proxy/proxy.py", "codex-rotate"):
            self.assertTrue(any(str(f).endswith(key) for f in files),
                            f"★★ {key} 不在被扫列表里 —— 最该守的那个没守")

    def test_the_scanner_fires_on_a_known_positive(self):
        """★★ 再证明它**真的会响**。

        探针自己坏了、而坏掉的样子长得像「通过」，是本仓最贵的一类错
        （六问之①）。所以喂一个已知阳性进去看它报不报。
        """
        with tempfile.TemporaryDirectory() as d:
            probe = Path(d) / "known_positive.py"
            probe.write_text("def f():\n    return rotatable(1)\n", encoding="utf-8")
            hits = _undefined([probe])
        self.assertTrue(hits, "★★ 已知阳性没被报出来 —— 这个探针是坏的，闸全部作废")

    def test_production_python_has_no_undefined_names(self):
        """★★★ 正题。

        ⚠️ 这条闸**只拦得住名字不存在**，拦不住名字存在但语义错了
        （把 `usable` 写成 `cooling` 照样过）。那一层仍然只有行为测试守得住。
        """
        hits = _undefined(_files())
        self.assertEqual([], hits, "★★★ 存在未定义的名字：\n  " + "\n  ".join(hits))


if __name__ == "__main__":
    unittest.main(verbosity=2)
