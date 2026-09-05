"""`scan.py` 的**主路径不得被附加功能拖垮**,以及打包资源不得漏带脚本。

## 这条闸的来历(2026-09-05,真事故)

给 `scan.py` 加了 agy 额度序列(`_agy_quota_series`)之后,**用户点「刷新」毫无反应**。
真因是两层叠加:

  ① `traffic/agy_quota_series.py` **没加进 `tauri.conf.json` 的 `resources`**,
     所以安装包里的 `scripts/traffic/` 只有 `scan.py`,旁边没有那个模块;
  ② 而 `_agy_quota_series` **不是 fail-open** —— import 失败直接冒泡,
     于是 `scan.py --json` 退出码 1、**stdout 一个字节都没有**,
     `run_traffic` 拿到失败,整页用量数据刷不出来。

★★ 症状里没有任何东西指向 agy。用户看到的只是"刷新没反应",
   而坏掉的是**与 agy 毫无关系的 token 用量统计**。
   这正是本仓反复强调的那类:**一个纯附加的次要功能,绝不能有能力搞挂主路径。**

## 两条断言，各堵一层

① **藏掉可选模块,主扫描仍须正常出数**(退出码 0 + platforms 非空)。
   只堵第 ② 层就够让事故不再发生 —— 这是"深度防御"里更靠内的那道。
② **`scan.py` 运行时按路径加载的每个同目录模块,都必须在打包资源里**。
   这道堵的是第 ① 层,让功能在安装包里真的可用,而不只是"不崩"。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "traffic" / "scan.py"
CONF = ROOT / "codexbar" / "src-tauri" / "tauri.conf.json"
# ★ 把本机的解析缓存复制进临时 store。**纯粹是为了快**:每条用例都要真跑一次 scan,
#   不带缓存就是全量重解析(实测 ~25s/次 → 4 条用例 100s+),带上就是 ~1s。
#   慢到 100 秒的套件迟早被人跳过,那等于闸不存在。
#   ⚠️ 只**读**仓库的缓存、复制一份走;所有写入都落在临时目录,不碰真文件。
CACHE = ROOT / ".traffic-cache.json"


def _seed_store(d):
    if CACHE.is_file():
        shutil.copy(CACHE, Path(d) / ".traffic-cache.json")


class MainScanSurvivesMissingExtras(unittest.TestCase):
    """① 可选模块缺席 ⇒ 主扫描照常出数。"""

    def _run_isolated(self, keep):
        """把 traffic/ 复制到临时目录,只保留 `keep` 里的可选模块,再跑一次 scan。"""
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "traffic"
            t.mkdir(parents=True)
            shutil.copy(SCAN, t / "scan.py")
            for name in keep:
                shutil.copy(ROOT / "traffic" / name, t / name)
            _seed_store(d)
            env = dict(os.environ)
            env["CODEX_ROTATE_STORE"] = d
            p = subprocess.run([sys.executable, str(t / "scan.py"), "--days", "7", "--json"],
                               capture_output=True, text=True, timeout=600, env=env)
            return p

    def test_scan_works_without_agy_quota_series(self):
        """★★ 事故本体:藏掉 `agy_quota_series.py`,扫描**必须**仍然成功。"""
        p = self._run_isolated(keep=[])
        self.assertEqual(p.returncode, 0,
                         "少一个可选模块就整个挂掉了 —— 用户会看到「刷新没反应」\n"
                         + p.stderr[-800:])
        self.assertTrue(p.stdout.strip(), "stdout 是空的,调用方拿不到任何数据")
        d = json.loads(p.stdout)
        self.assertTrue(d.get("platforms"), "主数据(platforms)没了")
        self.assertIsNone(d.get("agy_quota"),
                          "模块都不在了却给出了额度序列 —— 那只能是编的")

    def test_scan_survives_a_broken_optional_module(self):
        """★★ 真正压 fail-open 的那一条。

        ⚠️ 这条是补写的,补写的理由值得记:最初只有"藏掉模块"那一条,
        而它**拆掉 `try/except` 仍然全绿** —— 因为那个场景被 `is_file()` 的显式检查挡住了,
        `try/except` 一次都没被触发。**测试通过的理由和它声称的理由不是同一个**,
        典型的空守卫。这里让模块**存在但一 import 就抛**,才真正走到 `exec_module`。
        """
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "traffic"
            t.mkdir(parents=True)
            shutil.copy(SCAN, t / "scan.py")
            # 语法合法但 import 期必抛 —— 只有 fail-open 能兜住
            (t / "agy_quota_series.py").write_text(
                "raise RuntimeError('boom')\n", encoding="utf-8")
            _seed_store(d)
            env = dict(os.environ)
            env["CODEX_ROTATE_STORE"] = d
            p = subprocess.run([sys.executable, str(t / "scan.py"), "--days", "7", "--json"],
                               capture_output=True, text=True, timeout=600, env=env)
        self.assertEqual(p.returncode, 0,
                         "可选模块自己炸了,却把主扫描一起带走 —— 用户看到「刷新没反应」\n"
                         + p.stderr[-800:])
        d2 = json.loads(p.stdout)
        self.assertTrue(d2.get("platforms"), "主数据没了")
        self.assertIsNone(d2.get("agy_quota"))

    def test_scan_still_produces_the_series_when_module_is_present(self):
        """★ 反向:模块在时**必须**真的产出(或因样本不足给 None,但不得抛)。

        没有这条,上面那条可以靠"把整个功能删掉"来满足 —— 那是把闸拆了当修好。
        """
        p = self._run_isolated(keep=["agy_quota_series.py"])
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        d = json.loads(p.stdout)
        self.assertIn("agy_quota", d, "顶层键消失了")

    def test_series_never_lands_in_platforms(self):
        """★★ 单位不同的两本账绝不能合流:进了 platforms 就会被当 token 加进总数。"""
        p = self._run_isolated(keep=["agy_quota_series.py"])
        d = json.loads(p.stdout)
        self.assertNotIn("agy_quota", d["platforms"])
        for k, v in d["platforms"].items():
            with self.subTest(platform=k):
                self.assertNotIn("consumed_pct", json.dumps(v),
                                 "额度百分比混进了 token 平台数据")


class BundledResourcesCoverRuntimeImports(unittest.TestCase):
    """② `scan.py` 按路径加载的同目录模块,必须都在 `tauri.conf.json` 的 resources 里。"""

    @classmethod
    def setUpClass(cls):
        cls.src = SCAN.read_text(encoding="utf-8")
        cls.res = json.loads(CONF.read_text(encoding="utf-8"))["bundle"]["resources"]

    def test_parser_found_the_resources(self):
        """★ 先证明解析没打空 —— 空 dict 会让下面的断言全绿。"""
        self.assertGreaterEqual(len(self.res), 4)
        self.assertTrue(any("scan.py" in k for k in self.res))

    def test_every_sibling_module_loaded_at_runtime_is_bundled(self):
        """扫 `parent / "xxx.py"` 这种运行时按路径加载的写法,逐个核对打包清单。"""
        names = set(re.findall(r'parent\s*/\s*"([A-Za-z_][A-Za-z0-9_]*\.py)"', self.src))
        self.assertTrue(names, "没抓到任何运行时加载的模块 —— 断言可能打空了")
        bundled = {Path(k).name for k in self.res}
        for n in sorted(names):
            with self.subTest(module=n):
                self.assertIn(n, bundled,
                              "{} 会在运行时被 scan.py 加载,却没进 tauri.conf.json 的 "
                              "resources —— 安装包里会缺它".format(n))

    def test_sampler_is_bundled_too(self):
        """采样器由 `bin/agy` 起,同样必须进包,否则装了 app 的机器采不到样本。"""
        self.assertIn("agy_quota_sampler.py", {Path(k).name for k in self.res})


if __name__ == "__main__":
    unittest.main()
