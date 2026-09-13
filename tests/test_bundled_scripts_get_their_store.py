"""★★★ 打进安装包的 python 脚本，**按 `__file__` 推出来的数据目录必须被 Rust 覆盖掉**。

## 这条闸的由来（2026-09-13，用户实报「codex 能切号，agy 不能」）

`agy/pool.py` 这么推数据目录：

    ROOT  = Path(__file__).resolve().parent.parent
    STORE = Path(os.environ.get("AGY_POOL_STORE", str(ROOT)))

在仓库里 `ROOT` 就是仓库根，一切正常。**打进 app 之后 `ROOT` 变成
`CodexBar.app/Contents/Resources/scripts/`** —— 那里面一个账号都没有。
于是 GUI 点「切换」跑的是一个空池：**命令成功、退出码 0、什么也没发生**。
而同一个界面上 codex 的切号是好的（它读的 `CODEX_ROTATE_STORE` 有人喂），
所以症状是"只有 agy 切不动"，指不到真因。

## 判据为什么这么取

本仓已记过一次同族事故：`proxy.py` 认了 `CODEX_ROTATE_STORE`，而两个安装脚本
**四个任务一个都没带这个变量**。教训写成一句话是：
**改了「谁来读」，就必须同时验「谁来写」。**

所以两边都**解析**出来，不手列：
  · 左边 = 打包清单里的 python 文件中，**默认值来自 `__file__`/`ROOT`** 的那些环境变量
    （只有这一类会因为"脚本被搬进 app"而指错地方；`AGY_REAL` / `AGY_KEYRING`
     那种纯开关不在此列，它们本来就该用默认值）
  · 右边 = `spawn_cmd()` 里 `c.env(...)` 真的设过的那些
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB_RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"
CONF = ROOT / "codexbar" / "src-tauri" / "tauri.conf.json"

#: `os.environ.get("X", str(ROOT…))` / `os.environ.get("X") or Path(__file__)…`
#: —— 两种写法都是「默认值跟着脚本自己的位置走」。
_ROOT_DEFAULT = re.compile(
    r'os\.environ\.get\(\s*"([A-Z][A-Z0-9_]+)"\s*(?:,\s*str\(\s*ROOT|\)\s*or\s*Path\(__file__\))')


def bundled_py():
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    base = CONF.parent
    out = []
    for src in conf["bundle"]["resources"]:
        p = (base / src).resolve()
        if p.is_file() and p.suffix in ("", ".py"):
            try:
                if p.suffix == ".py" or p.open("rb").read(2) == b"#!":
                    out.append(p)
            except OSError:
                pass
    return out


def store_vars():
    found = {}
    for p in bundled_py():
        for name in _ROOT_DEFAULT.findall(p.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(name, []).append(p.name)
    return found


def spawn_env():
    src = LIB_RS.read_text(encoding="utf-8")
    i = src.index("fn spawn_cmd(")
    seg = src[i:src.index("\nfn ", i + 10)]
    seg = "\n".join(l for l in seg.splitlines() if not l.lstrip().startswith("//"))
    return set(re.findall(r'c\.env\(\s*"([A-Z][A-Z0-9_]+)"', seg))


class TheProbeItselfWorks(unittest.TestCase):
    def test_some_scripts_are_bundled(self):
        self.assertGreaterEqual(len(bundled_py()), 3,
                                f"只解析到 {[p.name for p in bundled_py()]} —— 打包清单读法坏了")

    def test_at_least_two_store_vars_are_found(self):
        """★ 匹配 0 个变量的正则会让整条闸恒绿 —— 本仓「扫描器查了 0 个对象却报干净」。"""
        self.assertGreaterEqual(len(store_vars()), 2,
                                f"只找到 {store_vars()} —— 正则没跟上写法变化，先修闸")

    def test_spawn_cmd_sets_something(self):
        self.assertGreaterEqual(len(spawn_env()), 2, f"spawn_cmd 里解析到 {spawn_env()}")


class EveryBundledScriptIsToldWhereItsDataLives(unittest.TestCase):
    def test_each_store_var_is_supplied_by_spawn_cmd(self):
        env = spawn_env()
        for name, files in sorted(store_vars().items()):
            with self.subTest(var=name):
                self.assertIn(name, env,
                              f"★★★ {files} 读 {name}，但 spawn_cmd 没喂 ⇒ "
                              f"装机版会在 app 内部找数据（空的），而命令仍然返回成功")

    def test_the_live_credential_path_is_not_hijacked(self):
        """★★ 反方向：`AGY_TOKEN_FILE` 是 **agy 自己的登录态**，必须留在用户家目录。
        把它也"顺手"设成数据目录，等于让 app 去读一个永远不存在的凭证。"""
        self.assertNotIn("AGY_TOKEN_FILE", spawn_env(),
                         "★★ spawn_cmd 覆盖了 agy 的登录态路径 —— 那不是我们的数据")



class TheLedgerHasExactlyOneHome(unittest.TestCase):
    """★★★ agy 额度账本由**采样器写、`scan.py` 读**。两边各自推路径，就会分家。

    2026-09-13 实测：采样器写的是 `ROOT/traffic/agy-quota-ledger`（`ROOT` = 脚本自己的位置），
    `scan.py` 读的是 `_STORE/traffic/agy-quota-ledger`（`_STORE` 认 `CODEX_ROTATE_STORE`）。
    **在仓库里两者恰好相等**，所以一直看不出来；脚本被打进 app 之后
    `ROOT` 变成 `Contents/Resources/scripts/` ⇒ 一个往 app 里写、一个去数据目录读，
    两边各自"正常"，数据永远对不上。本仓「一份事实一个家」的老形态。

    ★ 判据是**真的把两个模块载进来比路径**，不是断言源码里有某个变量名 ——
      后者挡不住"换个写法又分家"。
    """

    def _paths(self, store):
        import importlib.util
        import os as _os
        old = _os.environ.get("CODEX_ROTATE_STORE")
        _os.environ["CODEX_ROTATE_STORE"] = str(store)
        try:
            out = []
            for rel, attr in (("traffic/agy_quota_sampler.py", "LEDGER_DIR"),
                              ("traffic/scan.py", "AGY_QUOTA_LEDGER")):
                spec = importlib.util.spec_from_file_location("ledger_t_%s" % attr, ROOT / rel)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                out.append(getattr(m, attr))
            # 采样器给的是目录，scan 给的是文件
            return (Path(out[0]) / "samples.jsonl").resolve(), Path(out[1]).resolve()
        finally:
            if old is None:
                _os.environ.pop("CODEX_ROTATE_STORE", None)
            else:
                _os.environ["CODEX_ROTATE_STORE"] = old

    def test_writer_and_reader_agree_under_a_relocated_store(self):
        """★ 必须用一个**与仓库不同**的 store 才有判别力 —— 用仓库目录的话
        两种写法恰好相等，闸恒绿（本仓 §7.-1 ⑦：这条断言的绿是谁给的）。"""
        import tempfile
        store = Path(tempfile.mkdtemp())
        w, r = self._paths(store)
        self.assertEqual(w, r, "★★★ 采样器写的和 scan.py 读的不是同一个文件")
        self.assertTrue(str(w).startswith(str(store.resolve())),
                        f"★★ 账本没落在指定的数据目录里: {w}")

if __name__ == "__main__":
    unittest.main()
