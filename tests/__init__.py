"""测试包的**唯一职责**:在任何测试跑起来之前,把会写盘的旁路重定向到临时目录。

## 为什么需要它(2026-09-06 真事故)

`tests/test_grok_degrade_contract.py` 拿夹具 auth 起子进程跑 `grok-quota`。
`grok-quota` 新增的锚点账本写入没有隔离口,于是**三个假账号被写进了真实的
`<store>/.quota-anchors.json`**,而那些假锚点会直接参与 UI 的「未启动」判定 ——
测试污染了生产数据,且没有任何一处会为此变红。

当时有 **9 个**测试文件在起这三个采集脚本,一个都没隔离 store。逐个去补是
「写下来但没有闸」的老路:下一个新测试照样会踩,而症状是安静的。
所以隔离放在**这里** —— 测试包的 import 是 `unittest discover` 的必经之路,
新测试什么都不用知道。

## 为什么不直接改 `CODEX_ROTATE_STORE`

那个变量同时决定 `STORE` / `AUTH_DIR` / `STATE`,而且是在 `codex-rotate` **import 时**
求值的。在这里改它会让一整批现存测试指向一个空目录 —— 爆炸半径远超要解决的问题。
`CODEXBAR_QUOTA_ANCHORS` 只影响账本这一个文件,零连带。

★ 用 `setdefault` 语义:调用方已经显式指定过就不覆盖(`test_quota_anchor_wiring`
  自己要验真实的 `default_path()` 行为)。
"""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("CODEXBAR_QUOTA_ANCHORS"):
    _d = tempfile.mkdtemp(prefix="codexbar-test-anchors-")
    os.environ["CODEXBAR_QUOTA_ANCHORS"] = os.path.join(_d, ".quota-anchors.json")
    atexit.register(shutil.rmtree, _d, True)
