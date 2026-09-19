"""★★ **在任何测试跑起来之前,把会写盘的旁路重定向到临时目录。**

## 为什么是一个 `test_*.py` 而不是 `tests/__init__.py`

因为 `python3 -m unittest discover -s tests -p 'test_*.py'` **不会导入 `tests/__init__.py`**
——它把 `tests/` 当顶层目录、按 `test_x` 而不是 `tests.test_x` 导入。
我第一版就写在 `__init__.py` 里,而 `test_isolation_is_actually_active` 当场判红。
`__init__.py` 仍然保留:`python -m unittest tests.test_portalock` 那种调用形式走的是包路径,
CI 里就有一条。**两条入口各管一半,缺一条就有一半没防护。**

发现的时机也值得记:这个模块本身是**因为 `--dump-dom` 之外的另一次"证明它真的生效"**
才存在的 —— 断言写成「隔离变量必须已设置」,而不是「代码里有隔离逻辑」。

## 它防的是什么(2026-09-06 真事故)

`tests/test_grok_degrade_contract.py` 拿夹具 auth 起子进程跑 `grok-quota`。
`grok-quota` 新增的锚点账本写入没有隔离口,于是**三个假账号
(`https://auth.x.ai::c1/c2/client-1`,used 恒 35%)被写进了真实的
`<store>/.quota-anchors.json`**,而那些假锚点会直接参与 UI 的「未启动」判定。
测试污染了生产数据,且没有任何一处会为此变红。

当时有 **9 个**测试文件在起这三个采集脚本,一个都没隔离 store。逐个去补是
「写下来但没有闸」的老路:下一个新测试照样踩,而症状是安静的。

## 为什么不直接改 `CODEX_ROTATE_STORE`

那个变量同时决定 `STORE` / `AUTH_DIR` / `STATE`,而且在 `codex-rotate` **import 时**求值。
在这里改它会让一整批现存测试指向一个空目录 —— 爆炸半径远超要解决的问题。
`CODEXBAR_QUOTA_ANCHORS` 只影响账本这一个文件,零连带。

★ 模块**顶层**就设(不是 `setUpModule`):discover 会先导入全部测试模块、再执行,
  所以顶层赋值必定早于任何一个子进程被拉起,与文件名的字母序无关。
"""
import atexit
import os
import shutil
import tempfile
import unittest

if not os.environ.get("CODEXBAR_QUOTA_ANCHORS"):
    _d = tempfile.mkdtemp(prefix="codexbar-test-anchors-")
    os.environ["CODEXBAR_QUOTA_ANCHORS"] = os.path.join(_d, ".quota-anchors.json")
    atexit.register(shutil.rmtree, _d, True)

# ★★ agy 的真登录态在 **macOS 钥匙串**里（`agy/pool.py` 的 `KEYRING_SVC`）。
#   钥匙串**没有临时目录这种东西** —— 重定向 `AGY_TOKEN_FILE` 对它完全无效，
#   一条用例调到 `install_live()` 就能覆盖掉用户当前的 agy 登录态，
#   代价是重新走一遍浏览器 OAuth。所以整条通路在测试里默认关死。
#   （与 2026-09-06 那次「夹具写进真账本」同族，只是这次的账本是系统钥匙串。）
os.environ.setdefault("AGY_KEYRING", "0")

# ★★★ **launchctl 一律关死。**（2026-09-19 真事故）
#   `connector.remove()` 会 `launchctl bootout` 四个常驻服务,而服务 label 是**固定的**,
#   不随任何环境变量改变 —— 只隔离 plist 路径（`CODEXBAR_LAUNCH_AGENTS`）挡不住它。
#   实测:跑一次 `test_connector` 就把真机上的 proxy/quotad/autosync/dawnprobe 全停了,
#   轮换当场断掉,而整套测试**全绿**。与 2026-09-06「夹具写进真账本」同一形状:
#   测试污染生产,且没有任何一处会为此变红。
os.environ.setdefault("CODEXBAR_LAUNCHCTL", "0")


class IsolationIsInPlace(unittest.TestCase):
    def test_launchctl_is_disabled(self):
        """★★★ 判据是「变量**已设置**」，不是「代码里有隔离逻辑」。

        2026-09-19 实测：跑一次 `test_connector` 就把真机上的四个常驻服务全 bootout 了
        —— 轮换当场断掉，而整套测试全绿。服务 label 是固定的，隔离 plist 路径挡不住它。
        """
        self.assertEqual(os.environ.get("CODEXBAR_LAUNCHCTL"), "0",
                         "★★★ launchctl 没被关死 —— 测试会停掉用户真实的常驻服务")

    def test_the_connector_actually_honours_it(self):
        """行为闸：隔离开着时 `remove()` 一次 launchctl 都不许真跑。

        ★ 只断言变量被设置不够 —— `connector` 完全可以不读它（那正是这次事故的形状：
          隔离存在、但被绕过的那条路径没接上）。所以这里把 `subprocess.run` 换成探针，
          真调一次 `remove()`，数它有没有被碰。
        """
        import subprocess as _sp
        import sys as _sys
        import tempfile as _tf
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        import connector as _c
        calls = []
        orig = _sp.run

        class _Fake:
            returncode, stdout, stderr = 0, "", ""

        def spy(args, *a, **k):
            # ★★ launchctl 一律**拦下不放行** —— 这条闸要能做变异验证（去掉隔离口应当变红），
            #   而放行的话那次变异会**真的**再把用户的常驻服务 bootout 一遍。
            #   验证工具本身不许有破坏性副作用。
            if args and args[0] == "launchctl":
                calls.append(args)
                return _Fake()
            return orig(args, *a, **k)

        _sp.run = spy
        try:
            with _tf.TemporaryDirectory() as d:
                os.environ["CODEXBAR_LOCAL_BIN"] = str(_P(d) / "bin")
                os.environ["CODEXBAR_LAUNCH_AGENTS"] = str(_P(d) / "agents")
                os.environ["CODEX_HOME"] = str(_P(d) / "home")
                _c.remove(_P(d) / "store")
        finally:
            _sp.run = orig
            for k in ("CODEXBAR_LOCAL_BIN", "CODEXBAR_LAUNCH_AGENTS", "CODEX_HOME"):
                os.environ.pop(k, None)
        self.assertEqual(calls, [],
                         f"★★★ 隔离开着却真调了 launchctl：{calls}")

    def test_the_agy_keyring_path_is_disabled(self):
        """★ 判据是**变量已设置**，不是"代码里有隔离逻辑" —— 后者正是上一次
        让隔离只写在 `__init__.py` 里（discover 根本不导入它）而没被发现的原因。"""
        self.assertEqual(os.environ.get("AGY_KEYRING"), "0",
                         "agy 钥匙串通路没关 —— 测试可能覆盖用户真实的 agy 登录态")

    def test_ledger_is_redirected(self):
        p = os.environ.get("CODEXBAR_QUOTA_ANCHORS")
        self.assertTrue(p, "锚点账本没有被重定向 —— 测试会写进真实数据")
        self.assertNotEqual(
            os.path.dirname(os.path.realpath(p)),
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            "重定向指回了仓库目录 —— 等于没重定向")


if __name__ == "__main__":
    unittest.main()
