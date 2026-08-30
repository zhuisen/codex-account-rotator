"""跨平台的 `fcntl.flock` 兼容层 —— 为 Windows 提供**语义等价**的跨进程文件锁。

## 为什么需要它

`codex-rotate`、`proxy/proxy.py`、`daemon/quota_daemon.py` 都在**模块顶层** `import fcntl`。
Windows 没有这个模块，三个进程会在 import 阶段直接 `ModuleNotFoundError`，一行业务代码都跑不到。

## 为什么不是 `msvcrt.locking`

`msvcrt.locking` 看起来是显然的替代品，实际只满足本仓库依赖的四条性质里的一条：

| 性质 | flock | msvcrt.locking | LockFileEx |
|---|---|---|---|
| (a) 阻塞等待，无上限 | ✓ | **✗ `LK_LOCK` 重试约 10 秒后放弃并抛 `OSError`** | ✓ |
| (b) 非阻塞探测 | ✓ `LOCK_NB` | ✓ `LK_NBLCK` | ✓ `LOCKFILE_FAIL_IMMEDIATELY` |
| (c) 进程死亡时由内核释放 | ✓ | ✓ | ✓ |
| (d) 异常类型可被调用方区分 | `BlockingIOError` | ✗ 抛 `OSError(EDEADLOCK)` | 本模块转换成 `BlockingIOError` |

(a) 是致命的：`.refresh.lock` 要**跨一整个 OAuth POST** 持有（实测可达 30 秒）。
`msvcrt.locking(LK_LOCK)` 会在约 10 秒后放弃 —— 于是第二个刷新者**拿到了它以为的锁**，
两个进程同时刷同一个账号的 refresh_token。而 refresh_token 是**一次性**的，
两边互相作废 = **掉号**。这正是 CHANGELOG 里 B7/B8/B14 那串连环杀号事故的成因。

所以走 `LockFileEx`：它在内核里阻塞，没有超时上限。

(d) 也不能省：`_cred_lock(nonblock=True)` 的调用方（autosync）靠 `BlockingIOError`
判断「别人正持锁，这轮跳过」。如果抛的是别的类型，那条 except 就接不住，
异常会往上冒 —— 而症状是 autosync 静默停摆，不是报错。

## 已知的语义差异（**不要假装没有**）

- **flock 是「劝告锁」，Windows 的字节范围锁是「强制锁」。** 本仓库所有写者都走这里加锁，
  所以行为一致；但如果将来有代码**不加锁直接写**，POSIX 上会成功，Windows 上会被拒。
- **同一进程内重复加锁**：flock 对同一个 fd 重复 `LOCK_EX` 是升级（不阻塞自己）；
  `LockFileEx` 对**同一句柄**的重叠范围会死锁。本仓库两处都是
  `with open(...) as lf: flock(lf, ...)` —— 每次开新句柄，不触发这个差异。
  ⚠️ 别把这些锁改成「打开一次、长期持有、反复加锁」的形态。
- 锁的是文件的**第一个字节**（偏移 0，长度 1），不是整个文件。范围只要各方一致即可，
  文件本身是零字节的哨兵，从不写内容。
"""

import os
import sys

# POSIX：直接把 fcntl 的名字转出去，零行为差异。
if os.name != "nt":
    from fcntl import LOCK_EX, LOCK_NB, LOCK_SH, LOCK_UN, flock  # noqa: F401

else:  # ---- Windows ----
    import ctypes
    import msvcrt
    from ctypes import wintypes

    # 与 fcntl 同值，方便调用方 `flags & LOCK_NB` 这类写法照旧成立。
    LOCK_SH = 0x01
    LOCK_EX = 0x02
    LOCK_NB = 0x04
    LOCK_UN = 0x08

    _LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    _LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    _ERROR_LOCK_VIOLATION = 33

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", wintypes.LPVOID),
            ("InternalHigh", wintypes.LPVOID),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.LockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED),
    ]
    _k32.LockFileEx.restype = wintypes.BOOL
    _k32.UnlockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED),
    ]
    _k32.UnlockFileEx.restype = wintypes.BOOL

    def _handle(f):
        """接受文件对象或 fd，与 `fcntl.flock` 的调用约定一致。"""
        fd = f if isinstance(f, int) else f.fileno()
        return msvcrt.get_osfhandle(fd)

    def flock(f, flags):
        """`fcntl.flock` 的 Windows 等价物。

        ★ 非阻塞失败时抛 **`BlockingIOError`** —— 与 POSIX 一致。抛别的类型会让调用方
          那条 `except BlockingIOError` 接不住，autosync 会静默停摆而不是跳过本轮。
        """
        h = _handle(f)
        ov = _OVERLAPPED()

        if flags & LOCK_UN:
            if not _k32.UnlockFileEx(h, 0, 1, 0, ctypes.byref(ov)):
                raise OSError(ctypes.get_last_error(), "UnlockFileEx failed")
            return

        mode = 0
        if not flags & LOCK_SH:
            mode |= _LOCKFILE_EXCLUSIVE_LOCK
        if flags & LOCK_NB:
            mode |= _LOCKFILE_FAIL_IMMEDIATELY

        # 不带 FAIL_IMMEDIATELY 时在内核里阻塞，**没有超时上限** —— 这正是不用
        # msvcrt.locking 的原因（它约 10 秒就放弃，而 refresh 锁要跨 30 秒的 OAuth POST）。
        if _k32.LockFileEx(h, mode, 0, 1, 0, ctypes.byref(ov)):
            return

        err = ctypes.get_last_error()
        if flags & LOCK_NB and err == _ERROR_LOCK_VIOLATION:
            raise BlockingIOError(err, "file is locked by another process")
        raise OSError(err, "LockFileEx failed")


def install_as_fcntl():
    """把本模块注册成 `fcntl`，让顶层 `import fcntl` 的模块无需改动即可运行。

    只在 Windows 上生效；POSIX 上是空操作，绝不遮蔽真的 `fcntl`。
    """
    if os.name == "nt":
        sys.modules.setdefault("fcntl", sys.modules[__name__])
