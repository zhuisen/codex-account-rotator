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


class IsolationIsInPlace(unittest.TestCase):
    def test_ledger_is_redirected(self):
        p = os.environ.get("CODEXBAR_QUOTA_ANCHORS")
        self.assertTrue(p, "锚点账本没有被重定向 —— 测试会写进真实数据")
        self.assertNotEqual(
            os.path.dirname(os.path.realpath(p)),
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            "重定向指回了仓库目录 —— 等于没重定向")


if __name__ == "__main__":
    unittest.main()
