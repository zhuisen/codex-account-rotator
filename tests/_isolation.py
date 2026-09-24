"""测试隔离的**唯一实现** —— 任何会起 agy / codex 脚本子进程的测试模块都必须 import 它。

★★★ 为什么不只放在 `tests/__init__.py`（2026-09-24 事故）：
  `python3 -m unittest discover -s tests -p 'test_agy*'` 这种按文件名过滤的跑法
  **既不导入 `tests/__init__.py`，也匹配不到 `test_isolation_bootstrap.py`** ⇒ 隔离一个都没生效 ⇒
  测试夹具 `new@x.y` 被写进了用户真实的钥匙串（agy 登录态），`auth/agy/new.json` 落进真凭证目录，
  还有测试经 `bin/agy` 对**真实账号池**跑了 `auto`。隔离不能依赖「跑法恰好对」。
  闸：`tests/test_isolation_bootstrap.py::EveryScriptSpawningTestImportsTheIsolation`。

★ 全部用 setdefault 语义：调用方显式指定过的不覆盖。
"""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("CODEXBAR_QUOTA_ANCHORS"):
    _d = tempfile.mkdtemp(prefix="codexbar-test-anchors-")
    os.environ["CODEXBAR_QUOTA_ANCHORS"] = os.path.join(_d, ".quota-anchors.json")
    atexit.register(shutil.rmtree, _d, True)
# 钥匙串**没有临时目录这种东西** —— 只能关掉。
os.environ.setdefault("AGY_KEYRING", "0")
os.environ.setdefault("CODEXBAR_LAUNCHCTL", "0")
# ★★ agy 账号池默认也指到临时目录：`bin/agy` → `agy-rotate auto` 对真池跑一次，
#   装进钥匙串的就是**真凭证**（Google 签发），源头那道 `is_google_issued` 挡不住它。
if not os.environ.get("AGY_POOL_STORE"):
    _p = tempfile.mkdtemp(prefix="codexbar-test-agypool-")
    os.environ["AGY_POOL_STORE"] = _p
    atexit.register(shutil.rmtree, _p, True)
