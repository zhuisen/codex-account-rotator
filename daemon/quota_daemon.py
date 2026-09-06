#!/usr/bin/env python3
"""codex-rotate quota daemon — keeps state.json's quota continuously accurate, INDEPENDENT of any UI
(SwiftBar / CodexBar). Three loops, all ZERO quota cost:

  1. activity-driven (every WATCH_SECS)  — ★ the one that makes the display feel live. Cheap local
     stats detect that codex actually DID something, then the official usage endpoint is read for the
     affected account(s). Quota only moves when you use codex, so a timer is both wasteful while idle
     and laggy while active; this inverts that.

  2. rollout tail (every TICK_SECS)      — `quota --save` attributes the newest plain-codex rollout's
     rate_limit event to the ACTIVE account. Local file read, instant, but only covers the active
     account and only when plain codex actually wrote a rollout.

  3. usage API sweep (every USAGE_SECS)  — `refresh-all` reads GET /backend-api/codex/usage for EVERY
     account. Authoritative, covers non-active accounts, 401 identifies revoked tokens. Also the floor
     that keeps things correct if every activity signal somehow misses.
     ★ 它还有第二个触发口:**窗口跨过重置时刻立刻扫一次**(`_reset_crossed`)。旧读数在那一刻
     语义上就作废了,而 UI 会如实显示"未知"—— 固定节拍下那段未知最长要挂 300s,
     偏偏又是用户最想看到新数的时候。

★ 三条循环的到点判断一律走 `_due()`,不是裸的 `now - last >= T`:墙钟回拨会让后者
  **静默地**把下一次执行推迟一个回拨的量。见 `_due` 的注释。

★ Why loop 3 still exists under loop 1: the activity signals are heuristics about a third party's
files. Loop 3 does not care why a signal was missed — it re-establishes truth on a fixed cadence.

★ Why polling the endpoint is affordable: the old probe sent a real (billed) POST /codex/responses just
to read quota headers. The official endpoint is a plain GET — no quota, no tokens.

★ Why the activity path refreshes ONE account, not the pool: /usage answers 403 (Cloudflare bot
challenge) to bursts, and the account being consumed is the active one (or, under cxp, `last_aid`).
Sweeping all N on every keystroke-ish event would burn the budget for no new information.
"""
import contextlib
import datetime
import importlib.machinery
import io
import sys
import time
from pathlib import Path

# 自解析仓库根(本文件在 <repo>/daemon/ 下),别写死绝对路径 —— 换台机器/换 clone 路径就废。
ROT = str(Path(__file__).resolve().parent.parent / "codex-rotate")
cli = importlib.machinery.SourceFileLoader("cli", ROT).load_module()

WATCH_SECS = 1      # activity poll — 4 cheap stats (~0.02ms), no network
DEBOUNCE_SECS = 3   # let a burst of turns settle into one refresh
MIN_GAP_SECS = 20   # floor between activity-driven API reads (endpoint rate-limits bursts)
TICK_SECS = 15      # rollout tail (local file read)
USAGE_SECS = 300    # full-pool sweep
RESCAN_SECS = 60    # how often to re-find the newest rollout file

# /usage sits behind an INTERMITTENT Cloudflare bot challenge: a 403 says nothing about the account or
# about our request rate (measured 2026-08-01 — three back-to-back GETs all returned 200 minutes after
# a 403). A challenged activity refresh therefore drops that update on the floor and the display stays
# stale until the next trigger, which may be a long way off. Retry on a short ladder instead of waiting.
RETRY_BACKOFF = (8, 20, 45)

# 墙钟回拨多少秒以内算"抖动",照常等待;超过就判到点、重新对时。见 `_due`。
CLOCK_BACK_TOL_SECS = 300
# 重置驱动的扫描之间的地板。扫描失败(/usage 的 bot challenge)时不至于每秒重试。
RESET_SWEEP_MIN_GAP = 60

HISTORY = Path.home() / ".codex/history.jsonl"


def _due(now, last, period):
    """到点了吗 —— **兼容墙钟被改动**。

    `now - last` 正常是正数,但**它可以是负的**:NTP 校正、用户改系统时间、
    VM/容器恢复快照,都会让"上次"落在"现在"之后。朴素的 `>= period` 在那之后会把
    下一次扫描**推迟整整一个回拨的量**(可能是几小时),而这件事**没有任何症状** ——
    日志里只是安静地少了几行,额度数字停在旧值,看上去和"没人用 codex"一模一样。

    ★ 为什么不干脆换 `time.monotonic()`:macOS 的 monotonic **不含睡眠时间**
      (`CLOCK_UPTIME_RAW`)。合盖三小时再打开,墙钟走了 3h 而 monotonic 几乎没动 ⇒
      唤醒后还要再等一个完整周期才刷新,而"合盖唤醒"恰恰是全池数据最旧、
      用户最想立刻看到新数的那一刻。所以留在墙钟上,只把负数这一侧补齐。
    """
    d = now - last
    return d >= period or d < -CLOCK_BACK_TOL_SECS


def _reset_crossed(state, now):
    """有没有哪个账号的额度窗口,在**上次读数之后**跨过了重置时刻。

    跨过的那一刻,旧读数在语义上就作废了(`helpers.ts::winRem` 会把它显示成"未知",
    而不是编一个"满额"出来),可全池扫描最坏还要等 300s —— 窗口重置正是用户
    最想立刻看到新数的那一刻,却偏偏是显示"未知"最久的一段。

    ★★ 判据必须是「**快照拍摄于重置之前**」,不能只是「重置时刻已过」。
      后者在服务端迟迟不更新 `resets_at` 时会**恒为真**,把兜底节拍变成每 60s 一扫,
      在 /usage 的 bot challenge 面前就是自找 403。这样写还顺带**自我清零**:
      扫描成功后 `captured_at > resets_at`,条件自动不再成立,不需要额外记"已触发过"。

    ★ 这是「`captured_at` vs `resets_at`」这条判据的又一份副本(另外三份:
      `helpers.ts::winRem` · `lib.rs` 托盘 · `proxy.py::_win_used`)。它们回答
      "这个读数还能不能信",这里回答"该不该现在就去拿新的" —— 同一条线上的两个问题。
    """
    for slot in (state.get("slots") or {}).values():
        if not isinstance(slot, dict) or slot.get("auth_dead"):
            continue
        q = slot.get("quota") or {}
        cap = q.get("captured_at") or 0
        if not cap:
            continue
        for wkey in ("primary", "secondary"):
            ra = ((q.get(wkey) or {}) if isinstance(q.get(wkey), dict) else {}).get("resets_at")
            if ra and cap < ra <= now:
                return True
    return False


def log(msg):
    """Timestamped. Without one it is impossible to tell from the log whether a refresh fired DURING a
    codex run or after it finished — which is exactly the question when tuning the trigger."""
    sys.stderr.write(f"[quotad {time.strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()


def _day_dirs():
    """Today's and yesterday's session dirs. A dir's mtime changes when a file is CREATED in it, which
    is how a brand-new session is noticed without walking 3400+ rollout files. Yesterday is included so
    a session started before local midnight keeps being watched."""
    today = datetime.date.today()
    for d in (today, today - datetime.timedelta(days=1)):
        yield cli.SESSIONS / f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def _mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


class ActivityWatch:
    """Fingerprint of 'has codex done anything'. Deliberately multi-source: each signal covers a path
    the others miss, and no single one is guaranteed.
      • history.jsonl  — appended per interactive prompt (misses headless `codex exec`)
      • day dirs       — a NEW session file appears (covers exec; misses appends to an open session)
      • newest rollout — appends inside an ongoing session (needs a periodic rescan to follow a new file)
      • last_proxy_ts  — cxp proxy traffic, which may bypass the local paths above entirely
    """

    def __init__(self):
        self.rollout = None
        self.rollout_scanned = 0.0
        self.fp = None

    def _newest_rollout_path(self, now):
        if self.rollout is None or _due(now, self.rollout_scanned, RESCAN_SECS) or not self.rollout.exists():
            self.rollout_scanned = now
            self.rollout = cli._newest_rollout()   # Path | None
        return self.rollout

    def fingerprint(self, now, state):
        p = self._newest_rollout_path(now)
        return (
            _mtime(HISTORY),
            tuple(_mtime(d) for d in _day_dirs()),
            _mtime(p) if p else 0.0,
            state.get("last_proxy_ts", 0),
        )

    def changed(self, now, state):
        fp = self.fingerprint(now, state)
        first = self.fp is None
        moved = (not first) and fp != self.fp
        self.fp = fp
        return moved


def refresh_one(aid, slot, is_active):
    """One account, one GET. Mirrors cmd_refresh_all's per-account body without the pool loop.
    -> (got_reading, msg)."""
    q, msg = cli._probe_quota(aid, slot, is_active)
    if q:
        cli._mutate_state(lambda st, a=aid, qq=q: st["slots"].setdefault(a, {}).update(
            {"quota": qq, "quota_status": "ok"}))
    return q is not None, msg


def refresh_active(reason):
    """Refresh the account(s) that activity could have consumed: the active one, plus `last_aid` when
    the proxy served a DIFFERENT account (under cxp the active slot is not the one being spent).
    -> True when EVERY target produced a fresh reading; False means something should retry."""
    s = cli._state()
    active = s.get("active")
    targets = [active] if active else []
    last_aid = s.get("last_aid")
    if last_aid and last_aid != active and time.time() - s.get("last_proxy_ts", 0) < 300:
        targets.append(last_aid)
    out, all_ok, tried = [], True, False
    for aid in targets:
        slot = (s.get("slots") or {}).get(aid)
        if not slot or slot.get("auth_dead"):
            continue
        tried = True
        ok, msg = refresh_one(aid, slot, aid == active)
        all_ok = all_ok and ok
        out.append(f"{slot.get('label', aid[:8])}:{msg}")
        time.sleep(1.5)
    if out:
        log(f"{reason} → {' '.join(out)}")
    # Nothing to refresh (no live target) is "done", not "retry forever".
    return all_ok if tried else True


def tick_rollout():
    # hold the cross-process state mutex for the whole load→attribute→save, exactly as the CLI's main()
    # does for STATE_LOCKED commands — calling cmd_quota directly would otherwise bypass that lock and
    # could race the proxy. Swallow cmd_quota's stdout (it prints the quota JSON).
    with cli._state_mutex():
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_quota(["--save"])


def tick_usage():
    """Refresh EVERY account from the official usage endpoint. cmd_refresh_all does its own targeted
    _mutate_state per account (it must not hold the state mutex across network I/O)."""
    with contextlib.redirect_stdout(io.StringIO()):
        cli.cmd_refresh_all([])


def main():
    log(f"started · activity={WATCH_SECS}s(debounce {DEBOUNCE_SECS}s, gap {MIN_GAP_SECS}s) · "
        f"rollout={TICK_SECS}s · sweep={USAGE_SECS}s (all GET, zero quota)")

    watch = ActivityWatch()
    last_usage = last_tick = last_event_refresh = last_reset_sweep = 0.0
    pending_since = None
    retry_at, retry_n = None, 0

    while True:
        now = time.time()
        try:
            state = cli._state()
        except Exception as e:
            log(f"state err: {e}")
            time.sleep(WATCH_SECS)
            continue

        # --- 1. activity-driven -------------------------------------------------
        try:
            if watch.changed(now, state):
                pending_since = now              # keep pushing the deadline out while activity continues
                retry_at, retry_n = None, 0      # newer activity supersedes an in-flight retry ladder

            due = (pending_since is not None and _due(now, pending_since, DEBOUNCE_SECS)
                   and _due(now, last_event_refresh, MIN_GAP_SECS))
            # The retry ladder ignores MIN_GAP: a challenged read produced NO data, so retrying it is
            # not "another poll of a thing we already know", it is the first successful poll.
            due = due or (retry_at is not None and now >= retry_at)

            if due:
                pending_since, retry_at = None, None
                last_event_refresh = now
                if refresh_active("activity" if retry_n == 0 else f"retry#{retry_n}"):
                    retry_n = 0
                elif retry_n < len(RETRY_BACKOFF):
                    retry_at = time.time() + RETRY_BACKOFF[retry_n]
                    retry_n += 1
                else:
                    retry_n = 0              # give up; the 300s sweep is the backstop
        except Exception as e:
            log(f"activity err: {e}")

        # --- 2. rollout tail ----------------------------------------------------
        if _due(now, last_tick, TICK_SECS):
            last_tick = now
            try:
                tick_rollout()
            except Exception as e:
                log(f"rollout err: {e}")

        # --- 3. full-pool sweep -------------------------------------------------
        # 两个触发口。固定节拍是**兜底**;窗口刚跨过重置点则是**即时失效** ——
        # 那一刻旧读数已经作废,而它偏偏是显示"未知"最久的一段(最坏 300s)。
        reset_due = (_due(now, last_reset_sweep, RESET_SWEEP_MIN_GAP)
                     and _reset_crossed(state, now))
        if _due(now, last_usage, USAGE_SECS) or reset_due:
            if reset_due:
                last_reset_sweep = now
                log("window reset crossed → sweep now (not waiting for the 300s tick)")
            last_usage = now
            try:
                tick_usage()
            except Exception as e:
                log(f"usage err: {e}")

        time.sleep(WATCH_SECS)


if __name__ == "__main__":
    main()
