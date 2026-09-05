#!/usr/bin/env python3
"""agy 额度采样器 —— 定期记下 4 个桶的**剩余**水位,消耗由差分在读取侧算。

## 为什么需要它(而不是扩展现有的 agy-ledger)

`bin/agy` 的账本只覆盖 **print 模式**(近 90 天 34/214 轮 = 15.9%),交互式会话一个字都进不来 ——
因为用量只存在于 `--output-format json` 的 stdout 里,交互态没有那个 stdout。
2026-09-05 实测(310 个 RPC 全表 + 本机文件重扫)确认:**agy 不在任何地方落 token 计数**,
`GetUserAnalyticsSummary` 返回空 `{}`,其余全是「剩余」不是「已消耗」。

所以换个量测:**额度是服务端真值,它不关心你走的是 print 还是交互。**
判别实验(2026-09-05):一次 `agy -p` 调用后 `gemini-weekly` −0.85%、`gemini-5h` −1.01%,
而 3P 两个桶纹丝不动停在 100% —— 差分不但测得到消耗,还能按模型族归属。覆盖率 15.9% → 100%。

★★ **但它与 token 账本是两本账,单位是「额度%」不是 token、不是钱。** 两者不可相加、不可互推。
这个文件只负责把水位记下来,**绝不**试图把 % 换算成 token。

## 记录的是水位,不是消耗 —— 这是刻意的

存 `remaining` 而不是存算好的 `consumed`:消耗是**解释**,它依赖重置检测的口径,
而口径会改。原始水位是事实,事实入库、解释在读取侧现算,口径一变重算即可,不用迁移历史数据。

## 两条必须守住的不变量

① ★★ **`remaining` 上升 ≠ 一定是窗口重置。** 判据用 `reset_at` 变没变,不用"值变大了"。
   把每一次上升都当重置,会把真正的异常(换了账号、接口回了陈旧值)悄悄吞掉 ——
   而那正是本仓反复吃亏的形态。读取侧 `derive()` 里两者分开处理。

② ★★ **必须有心跳。** 只在数值变化时才写,会让「这段时间没消耗」和「这段时间我们没在看」
   在账本里长得一模一样。所以静默期也按 `HEARTBEAT_SECS` 打点 —— 有点 = 我在看且确实没动。

## 生命周期:自己会死,不留孤儿

采样器由 `bin/agy` 在拉起 agy **之前**以独立进程启动(交互态走 `os.execv`,wrapper 自己会被替换掉,
没有"之后"可言)。所以它必须自我终结:
  · 单实例锁(带 pid,陈旧锁自动接管);
  · 连续 `IDLE_ROUNDS` 轮探测不到 agy 进程就退出(额度只在 agy 活着时才动,没 agy 就没有可采的东西);
  · `MAX_LIFETIME_SECS` 硬上限兜底。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FETCHER = ROOT / "agy-quota"
LEDGER_DIR = Path(os.environ.get(
    "AGY_QUOTA_LEDGER_DIR", str(ROOT / "traffic" / "agy-quota-ledger")))
LEDGER = "samples.jsonl"
LOCK = ".sampler.lock"

POLL_SECS = int(os.environ.get("AGY_SAMPLER_POLL", "60"))
# ★★ **拿到第一个读数之前必须快轮询。** agy 有 ~10 秒预热窗口,而 print 模式的调用
#    可能十几秒就结束了 —— 用 60s 的常规节拍去等,**整次调用一个样本都采不到**
#    (实测踩过:第二次调用零样本,而第一次因为冷启动较慢侥幸采到了)。
#    额度只在 agy 活着时可读,错过这个窗口就永远补不回来。
POLL_FAST_SECS = int(os.environ.get("AGY_SAMPLER_POLL_FAST", "2"))
# 快轮询的时间上限:超过它还没读到,说明这次不是"预热中"而是真的没有可读的东西。
FAST_PHASE_SECS = int(os.environ.get("AGY_SAMPLER_FAST_PHASE", "90"))
# 静默期也要打点 —— 否则「没消耗」与「没在看」不可分(见文件头不变量 ②)。
HEARTBEAT_SECS = int(os.environ.get("AGY_SAMPLER_HEARTBEAT", "1800"))
# ★ 空闲判据用**时长**不用轮数:快轮询阶段 2 秒一轮,按轮数算 3 轮 = 6 秒就收工,
#   会在 agy 刚起来还没就绪时把自己关掉。
IDLE_SECS = int(os.environ.get("AGY_SAMPLER_IDLE_SECS", "180"))
MAX_LIFETIME_SECS = int(os.environ.get("AGY_SAMPLER_MAX_LIFETIME", str(24 * 3600)))


def fetch():
    """跑一次 `agy-quota`。→ 解析后的 dict,失败返回 None。

    ★ 复用抓取器,不在这里重写一遍 RPC —— 那套 10 秒预热窗口、双端口探测、
    「两种没有」的语义都在它里面,抄一份就等着两边漂移。
    """
    try:
        p = subprocess.run([sys.executable, str(FETCHER)],
                           capture_output=True, text=True, timeout=60)
        return json.loads(p.stdout)
    except Exception:                       # noqa: BLE001 — 采样失败绝不能弄死采样器
        return None


def flatten(snap):
    """快照 → `{bucket_id: (window, remaining, reset_at)}`,不可用时 None。"""
    if not snap or not snap.get("available") or not snap.get("quota"):
        return None
    out = {}
    for g in snap["quota"].get("groups") or []:
        for b in g.get("buckets") or []:
            bid = b.get("bucket_id")
            if bid:
                out[bid] = (b.get("window"), b.get("remaining_percent"),
                            b.get("reset_at"), g.get("name"))
    return out or None


def row(ts, flat):
    return {
        "ts": int(ts),
        "buckets": [
            {"id": bid, "group": grp, "window": win, "rem": rem, "reset": rst}
            for bid, (win, rem, rst, grp) in sorted(flat.items())
        ],
    }


def same(a, b):
    """两次读数在**水位与重置时刻**上是否完全一致(时间戳不算)。"""
    if a is None or b is None:
        return False
    return {k: v[:3] for k, v in a.items()} == {k: v[:3] for k, v in b.items()}


def append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def take_lock(lock_path):
    """单实例。→ True 表示拿到了。

    ★ 陈旧锁必须能被接管:采样器是被 `bin/agy` 随手拉起的,机器睡眠/强杀都会留下死锁文件,
    不接管的话**采集会从此永久静默** —— 而静默停止采集正是 wrapper 文档里点名的最坏形态。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        old = int(lock_path.read_text().strip())
    except (OSError, ValueError):
        old = None
    if old and old != os.getpid():
        try:
            os.kill(old, 0)      # 只探测存活,不发真信号
            return False         # 有活着的同类,让它干
        except OSError:
            pass                 # 陈旧锁,接管
    try:
        lock_path.write_text(str(os.getpid()))
        return True
    except OSError:
        return False


def agy_alive():
    """★ 用 `ps` + 精确匹配可执行名,不用 `pgrep -f`(自匹配恒真,本仓已记过这个坑)。"""
    try:
        out = subprocess.run(["ps", "-ax", "-o", "comm="],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:                       # noqa: BLE001
        return False
    return any(l.strip().endswith("/agy") or l.strip() == "agy"
               for l in out.splitlines())


def main():
    ledger = LEDGER_DIR / LEDGER
    if not take_lock(LEDGER_DIR / LOCK):
        return 0

    started = time.time()
    last_flat, last_write = None, 0.0
    got_one = False          # 是否已经拿到过至少一个读数(决定快/慢节拍)
    idle_since = None        # 第一次探测不到 agy 的时刻
    try:
        while time.time() - started < MAX_LIFETIME_SECS:
            flat = flatten(fetch())
            now = time.time()
            if flat:
                got_one, idle_since = True, None
                changed = not same(flat, last_flat)
                stale = now - last_write >= HEARTBEAT_SECS
                if changed or stale:
                    append(ledger, row(now, flat))
                    last_flat, last_write = flat, now
            else:
                # 读不到额度。**不写任何东西** —— 写一条空记录会让"没在看"伪装成一次观测。
                if agy_alive():
                    idle_since = None   # 在跑只是还没就绪(预热窗口),不算空闲
                else:
                    if idle_since is None:
                        idle_since = now
                    elif now - idle_since >= IDLE_SECS:
                        break
            # 还没采到第一个读数、且仍在快轮询期内 ⇒ 用快节拍抢那个窗口
            fast = (not got_one) and (now - started < FAST_PHASE_SECS)
            time.sleep(POLL_FAST_SECS if fast else POLL_SECS)
    finally:
        lk = LEDGER_DIR / LOCK
        try:
            if lk.read_text().strip() == str(os.getpid()):
                lk.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
