#!/usr/bin/env python3
"""额度窗口的**锚点账本** —— 把「这个 `resets_at` 是真的,还是跟着 `now` 在滑」
从**一次读数的推断**换成**多次观测的事实**。

## 它替掉的是什么

`helpers.ts::resetAnchorUnknown` 是个**单样本点估计**:`|resets_at − captured_at − 窗口| < 90s`
就判定「锚点不可信」,UI 写「待确认」。那个判据本身没错(2026-09-05 实测四个号,
浮动的差 <1s、锚定的差 14411s,相隔三个数量级),但它有一条**结构性的天花板**:

    一个**刚刚**首次使用的真窗口,它的 `resets_at − captured_at` 也恰好等于整窗。

所以点估计**永远分不出**「闲置浮动」和「刚锚定」,只能说「待确认」,而且**永远确认不了** ——
闲置的号一直显示「待确认」,用户拿不到任何解释。这不是判据不准,是**一个样本里没有那个信息**。

判别信息在**时间序列**里:再看一眼就够了。

    浮动: 每次读数的 reset 都往前挪,挪的量 == 两次读数的间隔  (它锚的是 now)
    锚定: reset 一动不动,而 now 在走                          (它锚的是窗口起点)

本模块就记这件事。★ **代价是它只能后验** —— 第一次读到时仍然只能说「待确认」,
所以 `unknown` 必须回落到点估计,而不是当成一种新的否定。

## 与 `agy_quota_series.py` 的分工(别合并)

那份记的是**水位随时间的下降量**(消耗了多少),单位是额度百分比;
这份记的是**窗口边界的身份**(reset 是不是同一个)。同一批读数喂两本账,
问的是两个问题。合并会得到一个既不能回答消耗、也不能回答边界的东西。

## 不变量(改这个文件前先读)

- ★★ **合并锚点时绝不更新 `row["reset"]`。** 一个每轮滑 20s 的浮动 reset,如果每次合并都把
  行里的 reset 跟着改掉,它就会**永远落在容差内**,于是 `last_seen − first_seen` 一路增长,
  最后被判成「静止了很久」—— 恰好把要抓的东西认证成它的反面。行的 reset 是**第一次见到的值**,
  后来的读数只能相对它做判断。闸在 `tests/test_quota_anchors.py`。
- ★ **容差必须远小于「静止判定」的时长。** `JITTER_SECS`(60) 吸收的是整秒截断和时钟抖动;
  `HOLD_SECS`(900) 是「静止这么久才算锚定」。两者靠得太近时,采样间隔小于容差的浮动窗口
  会一路合并进同一行 —— 这正是上一条要挡的形态,两条一起才闭合。
- ★ **`unknown` 不是「不是锚定」。** 三态,不是二值。调用方拿到 `unknown` 必须回落到既有判据,
  不能当成 `floating` —— 那会把「还没看够」讲成「确定没启动」。
- ★ 任何异常都不得冒泡到调用方(见 `note()`)。本模块是**纯附加**的次要功能,
  2026-09-05 已经有过一次「附加功能把主用量扫描整个搞挂」的事故。
"""
import json
import os
import time
try:
    import fcntl                       # POSIX
except ModuleNotFoundError:            # Windows —— 语义等价的 LockFileEx 兼容层,见 portalock.py
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import portalock as fcntl          # noqa: N813
from contextlib import contextmanager
from pathlib import Path

#: 同一个锚点两次读出来允许差多少秒。上游给的是整秒截断值,加上时钟抖动,几秒量级。
#: 60 是留给 RPC 往返和跨进程时钟的余量,**不是**用来容纳"滑得慢的浮动窗口"的。
JITTER_SECS = 60

#: `resets_at` 保持不变、而 `now` 走了这么久 ⇒ 认定锚点是真的。
#: 取 900s = quotad 全池扫描周期(300s)的 3 倍:够穿过一两次扫描失败,又远短于任何真实窗口。
HOLD_SECS = 900

#: 判「浮动」需要多少个**连续**滑动的锚点。2 = 三次读数。
#: ★ 定成正数而不是 1,是因为要说的是一句**肯定句**(「它在跟着 now 滑」),
#:   而一次滑动也可能是别的原因(服务端换了窗口起点)造成的。
MIN_SLIDES = 2

#: 「这个窗口真被用过」的门槛。服务端只回整数百分比,1% 以下结构性不可见,
#: 所以 2 是"确实动过"的最小可信证据。
MIN_USED_PCT = 2

#: 每个窗口保留多少条锚点。周窗口一年 52 条;5h 窗口一天 ~5 条,64 条约两周。
#: 上限存在的理由是**浮动窗口每轮都会新开一行** —— 没有上限时它会无限增长。
MAX_ROWS = 64

SCHEMA_V = 1
FILENAME = ".quota-anchors.json"


def default_path():
    """账本落点。与 `state.json` 同目录 —— 三个来源(codex/grok/agy)必须写同一份,
    而 `CODEX_ROTATE_STORE` 是本仓唯一被所有入口统一设置的那个目录
    (Rust 侧 `spawn()` 对每个子进程都设,launchd 由 install 脚本设)。

    ★ 在调用时读环境变量,不在 import 时 —— 模块顶层做这件事会让测试没法换目录,
      也会让「按路径 import」这个本仓允许的做法带上副作用。

    ★★ **`CODEXBAR_QUOTA_ANCHORS` 是给测试用的隔离口,优先级最高。**
      它**只影响这一个文件的落点**,不像 `CODEX_ROTATE_STORE` 那样连带改掉
      `STORE`/`AUTH_DIR`/`STATE` —— 所以在测试里设它是零爆炸半径的。
      2026-09-06 真踩过:`tests/test_grok_degrade_contract.py` 用夹具 auth 跑 `grok-quota`,
      而 `_note_anchors` 把三个假账号写进了**真实**账本,那些假锚点会直接参与
      UI 的「未启动」判定。本仓铁律「测试绝不写真实数据」的又一个形态,
      而它之所以能发生,是因为账本这条路是新的、没人想到要隔离。
      现在 `tests/__init__.py` 统一设它,**新测试无需知道这件事**。
    """
    override = os.environ.get("CODEXBAR_QUOTA_ANCHORS")
    if override:
        return override
    root = os.environ.get("CODEX_ROTATE_STORE")
    if not root:
        root = str(Path(__file__).resolve().parent.parent)
    return str(Path(root) / FILENAME)


def empty():
    return {"v": SCHEMA_V, "sources": {}}


def load(path=None):
    """读账本。读不到 / 坏了 / 版本对不上 ⇒ 返回空账本,**不抛**。

    ★ 版本不同就整份丢弃而不是迁移:这本账**没有不可再生的内容** ——
      它记的是观测,重新观测几轮就补回来了。为一份可再生的数据写迁移代码
      是净负债(而迁移代码正是那种写完就再也没人跑过的代码)。
    """
    try:
        with open(path or default_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or data.get("v") != SCHEMA_V:
            return empty()
        if not isinstance(data.get("sources"), dict):
            return empty()
        return data
    except Exception:
        return empty()


def save(anchors, path=None):
    """原子落盘(先写 `.tmp<pid>` 再 rename)。失败静默 —— 见模块头「纯附加」那条。

    带 pid 是因为 quotad / app / CLI 可能同时写,共用一个临时名会互相截断。
    """
    target = path or default_path()
    tmp = "%s.tmp%d" % (target, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(anchors, ensure_ascii=False))
        os.replace(tmp, target)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def _bucket(anchors, source, key, create=False):
    src = anchors.setdefault("sources", {}) if create else (anchors.get("sources") or {})
    if create:
        return src.setdefault(source, {}).setdefault(key, [])
    return ((src.get(source) or {}).get(key)) or []


def rows(anchors, source, key):
    """该窗口的锚点,按 `reset` 升序。排序而不是按观测顺序:陈旧读数偶尔会晚到,
    照观测顺序切区间会切出负时长。"""
    out = [r for r in _bucket(anchors, source, key) if isinstance(r, dict)]
    return sorted(out, key=lambda r: int(r.get("reset") or 0))


def record(anchors, source, key, reset, used, now=None):
    """记一次读数。→ 账本是否变化(调用方据此决定要不要落盘)。

    `used` 是**已用**百分比(0~100)。三个来源口径不同(grok 给已用、agy 给剩余),
    ★ **归一化是调用方的事** —— 在这里猜方向,就等于把一个能静默算反的判断
      藏进一个没有上下文的公共函数里。
    """
    now = time.time() if now is None else float(now)
    try:
        reset = int(reset)
    except (TypeError, ValueError):
        return False
    if reset <= 0:
        return False
    used = float(used or 0)

    bucket = _bucket(anchors, source, key, create=True)
    for row in bucket:
        if not isinstance(row, dict):
            continue
        if abs(int(row.get("reset") or 0) - reset) <= JITTER_SECS:
            # ★★ 这里**不写** row["reset"] —— 见模块头第一条不变量。
            changed = (used > row.get("max_used", 0.0)
                       or now > row.get("last_seen", 0.0))
            row["max_used"] = max(float(row.get("max_used") or 0.0), used)
            row["last_seen"] = max(float(row.get("last_seen") or 0.0), now)
            row["n"] = int(row.get("n") or 1) + 1
            if used >= MIN_USED_PCT and not row.get("confirmed"):
                row["confirmed"] = True
                changed = True
            return changed

    # 新锚点。「这是一个真的周期边界」需要证据:要么它自己有消耗,
    # 要么**紧邻的上一个**锚点有过消耗(有消耗的旧窗口 → 回到 0% 的新窗口 = 确实重置了)。
    # 没有任何证据时不标 confirmed —— 闲置时 reset 一路漂,那不是一串真周期。
    prev = [r for r in bucket
            if isinstance(r, dict) and int(r.get("reset") or 0) < reset - JITTER_SECS]
    latest_prev = max(prev, key=lambda r: int(r.get("reset") or 0), default=None)
    confirmed = (used >= MIN_USED_PCT
                 or bool(latest_prev and latest_prev.get("max_used", 0) >= MIN_USED_PCT))
    row = {"reset": reset, "first_seen": now, "last_seen": now, "max_used": used, "n": 1}
    if confirmed:
        row["confirmed"] = True
    bucket.append(row)

    # 裁剪保留**最新**的那些(按 reset)。浮动窗口每轮开一行,不裁会无限长。
    if len(bucket) > MAX_ROWS:
        bucket.sort(key=lambda r: int(r.get("reset") or 0))
        del bucket[:len(bucket) - MAX_ROWS]
    return True


def _slide_run(series):
    """尾部有多少个**连续**锚点是「reset 跟着时间一起往前挪」的。

    判据 `|Δreset − Δt| <= JITTER`:reset 前移的量正好等于两次首见的间隔
    ⇒ 服务端每次都在回「此刻 + 整窗」,它锚的是 `now` 不是窗口起点。

    ★ 只看尾部且遇到不满足就停:窗口**用过之后**会真的锚定,那之后的行不该被
      更早的一串漂移拖着继续报 floating。
    """
    run = 0
    for i in range(len(series) - 1, 0, -1):
        prev, cur = series[i - 1], series[i]
        d_reset = int(cur.get("reset") or 0) - int(prev.get("reset") or 0)
        d_time = float(cur.get("first_seen") or 0) - float(prev.get("first_seen") or 0)
        if d_time <= 0:
            break
        if abs(d_reset - d_time) <= JITTER_SECS:
            run += 1
        else:
            break
    return run


def verdict(anchors, source, key, reset, now=None):
    """这个 `reset` 的锚点可信吗。**三态**,不是二值。

        anchored  reset 在 `HOLD_SECS` 内一动没动,而 `now` 走了 —— 它锚的是真实窗口起点
        floating  连续 `MIN_SLIDES` 个锚点都跟着时间挪 —— 服务端在回「此刻 + 整窗」
        unknown   还没看够。★ 调用方**必须回落到既有判据**,不能当成 floating

    `used_max` 一并带出来:判「未启动」还是「刚锚定」时,零消耗是必要条件之一 ——
    有真实消耗却仍在漂,说明发生的是别的事,那种时候不该下断言。
    """
    now = time.time() if now is None else float(now)
    series = rows(anchors, source, key)
    cur = None
    try:
        reset = int(reset)
    except (TypeError, ValueError):
        reset = 0
    if reset > 0:
        for row in series:
            if abs(int(row.get("reset") or 0) - reset) <= JITTER_SECS:
                cur = row
                break

    held = 0.0
    samples = 0
    used_max = 0.0
    if cur:
        held = max(0.0, float(cur.get("last_seen") or 0) - float(cur.get("first_seen") or 0))
        samples = int(cur.get("n") or 0)
        used_max = float(cur.get("max_used") or 0.0)

    slides = _slide_run(series)
    if held >= HOLD_SECS:
        state = "anchored"
    elif slides >= MIN_SLIDES:
        state = "floating"
    else:
        state = "unknown"
    return {"state": state, "held_secs": int(held), "samples": samples,
            "slides": slides, "used_max": round(used_max, 2)}


def cycles(anchors, source, key, span, limit=8, now=None):
    """→ `[{start, end, max_used, current}]`,最新的排最前。

    `span` = 窗口时长(秒)。每条锚点的 `reset` 减去 span 就是那个周期的起点;
    下一条锚点的起点封住上一条的终点(锚点之间可能有观测断档,直接用 reset 当终点会重叠)。

    ★ **闲置漂移的锚点不算周期**:没有 `confirmed` 的行全部排除,一条都不剩时只留最新一条
      —— 那是「当前读数」不是「一段历史」,但把它藏掉会让 UI 分不出「没有历史」和「没在读」。
    """
    now = time.time() if now is None else float(now)
    series = rows(anchors, source, key)
    series = [r for r in series
              if r.get("confirmed") or float(r.get("max_used") or 0) >= MIN_USED_PCT] or series[-1:]

    out = []
    for i, row in enumerate(series):
        reset = int(row.get("reset") or 0)
        start = reset - span
        end = min(reset, int(series[i + 1].get("reset") or 0) - span) if i + 1 < len(series) else reset
        if end <= start:
            continue
        # 读数断了就不会再有新锚点,最后一条也可能早已过期 —— 那是历史,不是进行中。
        # 但「进行中」只能是最后一条:多标一条会被前端当成当前周期,另一条就没了。
        out.append({"start": start, "end": end,
                    "max_used": round(float(row.get("max_used") or 0.0), 2),
                    "current": i + 1 == len(series) and reset > now})
    return out[-limit:][::-1]


@contextmanager
def _ledger_lock(path):
    """跨进程写锁。**`note()` 的 load→record→save 必须整段持有它。**

    ★★★ 四方评审 2026-09-07 #6（四家一致），2026-09-12 修。
       `save()` 是原子的（tmp + rename），所以文件**从不会坏** —— 正因如此这个 bug
       完全不出声。坏的是**更新丢失**：quotad / app / CLI 三个进程都调 `note()`，
       A 读 → B 读 → A 写 → B 写，A 那次观测就没了。
       而这本账判的是「窗口锚定没锚定」，丢观测**直接改判**：`anchored` 会退回
       `floating`，UI 于是在一次刚花过钱的探针之后反说「窗口未启动」。
       ⚠️ 我当初在模块头声称的不变量 (d) 是假的 —— 它写着"同一份账本由多个来源安全共享"。

    ★ **拿不到锁就照常写下去**（fail-open），与本模块「整体 fail-open,恒不抛」一致：
      丢一次观测远好过让 `scan.py` 卡住 —— 2026-09-05 的事故形态正是一个纯附加功能
      把与它无关的 token 统计整个搞挂。所以这里宁可退回到旧的竞态，也不阻塞调用方。
    """
    lf = None
    try:
        lf = open(path + ".lock", "a+")
        fcntl.flock(lf, fcntl.LOCK_EX)
    except Exception:
        lf = None                      # 建不了/锁不上 —— 无保护地继续，别把调用方拖死
    try:
        yield
    finally:
        if lf is not None:
            try:
                lf.close()             # close 隐式释放 flock
            except Exception:
                pass


def note(source, key, reset, used, now=None, path=None):
    """load → record → save → verdict 的一次性入口,给三个采集脚本用。

    ★★ **整体 fail-open,恒不抛。** 2026-09-05 的事故形态:一个纯附加的次要功能
      (agy 消耗序列)因为 import 失败而让 `scan.py` 退出码 1、stdout 零字节,
      把**与它毫无关系的** token 统计整个搞挂,用户看到的是「点刷新没反应」。
      账本读不出来时的正确行为是「这一轮没有锚点信息」,不是「这一轮什么都没有」。

    → verdict dict;彻底失败时返回 `unknown` 态(而不是 None) ——
      调用方永远拿到同一个形状,少一条 `if x is None` 就少一处能忘掉的分支。
    """
    try:
        # ★★ 整段 load→record→save 在**同一把锁**里。只锁 save 是没用的：
        #    竞态发生在"读到旧值"那一刻，不是写的那一刻。
        target = path or default_path()
        with _ledger_lock(target):
            anchors = load(path)
            if record(anchors, source, key, reset, used, now):
                save(anchors, path)
            return verdict(anchors, source, key, reset, now)
    except Exception:
        return {"state": "unknown", "held_secs": 0, "samples": 0, "slides": 0, "used_max": 0.0}
