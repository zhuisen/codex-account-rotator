#!/usr/bin/env python3
"""Gemini（agy）的「代理轮换」数据 —— 与 `rotation.py::collect` **同形**，日志页直接复用泳道。

## 为什么需要一份单独的（用户 2026-09-24：「代理轮换也改成 codex 和 gemini 两个版块」）

agy 没有代理，所以没有 `proxy.log` 那样的逐请求记录。能诚实拿到的只有两样：
  · **会话**：agy 每次启动写一份 `~/.gemini/antigravity-cli/log/cli-YYYYMMDD_HHMMSS.log`，
    其中 `applyAuthResult: email=…` 是 agy **自己**认证成了哪个号（与探针归属同源的证据）；
    一个长会话中途被钥匙串写回换了身份时，同一份日志里会出现第二条 `applyAuthResult` ——
    按它切段，不把整场会话记在第一个号头上。
  · **换号记录**：`agy.log` 里 `auto 自动切到 / 恢复成你选的 / 借用已停用的` 与 `switch →`。

## 不做的（界面上写明，不画成 0）
  · **按号的 token**：agy 的用量账本不带账号身份，按时间去拼是猜 —— 与 codex 泳道
    「token 归属靠 response_id 精确 join，不是按时间猜」同一条纪律。所以 `tokens` 恒为 0，
    `coverage.attributed_pct` 为 None，前端据 `platform == "agy"` 显示「—」与说明。
  · 泳道时段 = **agy 以这个号的身份在运行**（启动到日志最后一次写入），不是「在消耗」。

纯模块：只读本机日志与池文件，不联网、不碰凭证、不写任何东西。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rotation as R  # noqa: E402  —— 复用配色 / 自然日切分，别抄第二份

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = Path(os.environ.get("AGY_LOG_DIR",
                              str(Path.home() / ".gemini" / "antigravity-cli" / "log")))
_NAME = re.compile(r"cli-(\d{8})_(\d{6})\.log$")
_AUTH = re.compile(r"^I(\d{2})(\d{2}) (\d{2}):(\d{2}):(\d{2})\.\d+\s+\d+ \S+\] applyAuthResult: email=([^\s,]+)",
                   re.M)
_EV = re.compile(r"^\[agy (\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\] (.*)$")
_EV_KIND = (("auto 自动切到", "auto"), ("auto 恢复成你选的", "wanted"),
            ("auto 借用已停用的", "borrow"), ("switch →", "manual"))


def _store():
    return Path(os.environ.get("AGY_POOL_STORE") or os.environ.get("CODEX_ROTATE_STORE") or ROOT)


def _pool():
    try:
        return json.loads((_store() / ".agy-pool.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sessions(start, end, log_dir=None):
    """→ (segments, unattributed, earliest)。每段 `{email, start, end}`，已按身份变化切开。"""
    d = log_dir or LOG_DIR
    segs, unattr, earliest = [], 0, None
    try:
        files = list(d.glob("cli-*.log"))
    except OSError:
        return [], 0, None
    for f in files:
        m = _NAME.search(f.name)
        if not m:
            continue
        try:
            t0 = time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
            t1 = f.stat().st_mtime
        except (OSError, ValueError):
            continue
        earliest = t0 if earliest is None else min(earliest, t0)
        if t1 < start or t0 > end:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        year = int(m.group(1)[:4])
        auths = []
        for a in _AUTH.finditer(text):
            mo, da, hh, mi, ss, email = a.groups()
            try:
                ts = time.mktime((year, int(mo), int(da), int(hh), int(mi), int(ss), 0, 0, -1))
            except (OverflowError, ValueError):
                continue
            if not auths or auths[-1][1] != email:
                auths.append((ts, email))
        if not auths:
            unattr += 1                      # ★ 认不出身份就不归属 —— 不猜
            continue
        for i, (ts, email) in enumerate(auths):
            s = max(t0, ts if i else t0)
            e = auths[i + 1][0] if i + 1 < len(auths) else t1
            s, e = max(s, start), min(e, end)
            if e > s:
                segs.append({"email": email, "start": s, "end": e})
    segs.sort(key=lambda x: x["start"])
    return segs, unattr, earliest


def switch_events(start, end, store=None):
    """`agy.log` 里的换号记录 → `[(ts, kind, label, line)]`。"""
    out = []
    try:
        lines = ((store or _store()) / "agy.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    year = time.localtime(end).tm_year
    for ln in lines:
        m = _EV.match(ln)
        if not m:
            continue
        mo, da, hh, mi, ss, body = m.groups()
        kind = next((k for (p, k) in _EV_KIND if body.startswith(p)), None)
        if not kind:
            continue
        ts = time.mktime((year, int(mo), int(da), int(hh), int(mi), int(ss), 0, 0, -1))
        if ts > end + 86400:                 # 跨年：日志不带年份
            ts = time.mktime((year - 1, int(mo), int(da), int(hh), int(mi), int(ss), 0, 0, -1))
        if start <= ts <= end:
            lab = re.search(r"\[([^\]]+)\]", body)
            out.append((ts, kind, lab.group(1) if lab else None, body))
    return out


def _union(spans):
    """区间并集的总长（秒）。"""
    tot, cur_s, cur_e = 0.0, None, None
    for a, b in sorted(spans):
        if cur_e is None or a > cur_e:
            if cur_e is not None:
                tot += cur_e - cur_s
            cur_s, cur_e = a, b
        else:
            cur_e = max(cur_e, b)
    if cur_e is not None:
        tot += cur_e - cur_s
    return tot


def collect(hours=24.0, now=None, log_dir=None, store=None):
    now = time.time() if now is None else now
    end, start = now, now - hours * 3600
    pool = _pool() if store is None else json.loads((store / ".agy-pool.json").read_text(encoding="utf-8"))
    accs = pool.get("accounts") or {}
    by_email = {(a.get("email") or "").lower(): (sub, a) for sub, a in accs.items()}
    raw, unattr, earliest = sessions(start, end, log_dir)
    evs_raw = switch_events(start, end, store)

    def label_of(email):
        hit = by_email.get(email.lower())
        return hit[1].get("label") if hit else email.split("@")[0]

    segs = []
    for i, s in enumerate(raw):
        acc = label_of(s["email"])
        prev = segs[-1]["acc"] if segs else None
        reason = "window_start" if prev is None else "same"
        if prev is not None and prev != acc:
            logged = [e for e in evs_raw if s["start"] - 180 <= e[0] <= s["start"] + 5 and e[2] == acc]
            reason = ("borrow" if logged and logged[-1][1] == "borrow"
                      else "switch" if logged else "drift")
        segs.append({"acc": acc, "start": s["start"], "end": s["end"], "requests": 1, "tokens": 0,
                     "by_model": [], "enter_reason": reason,
                     "current": s["end"] >= now - 90})
    labels = sorted({s["acc"] for s in segs} | {a.get("label") for a in accs.values() if a.get("label")})
    colors = R.assign_colors(labels)
    in_pool = {a.get("label") for a in accs.values()}

    def quota_pct(lab):
        for a in accs.values():
            if a.get("label") == lab:
                r = ((a.get("quota") or {}).get("gemini") or {}).get("remaining")
                return round(r * 100) if isinstance(r, (int, float)) else None
        return None

    accounts = []
    for lab in labels:
        mine = [s for s in segs if s["acc"] == lab]
        if not mine and lab not in in_pool:
            continue
        accounts.append({"acc": lab, "plan": "", "color": colors.get(lab, "#2dd4bf"), "tokens": 0,
                         "requests": len(mine), "top_model": None, "quota_pct": quota_pct(lab),
                         **({"retired": True} if lab not in in_pool else {})})

    TEXT = {"auto": "自动切到", "wanted": "恢复成你选的", "borrow": "借用已停用的", "manual": "手动切换到"}
    events = [{"t": t, "type": "switch", "from": None, "to": lab, "reason": k,
               "text": f"{TEXT[k]} {lab} · 下次启动 agy 生效", "accs": [lab] if lab else []}
              for (t, k, lab, _b) in evs_raw]
    for i, s in enumerate(segs):
        if i and s["enter_reason"] == "drift":
            events.append({"t": s["start"], "type": "failover", "from": segs[i - 1]["acc"], "to": s["acc"],
                           "reason": "drift",
                           "text": f"{segs[i - 1]['acc']} → {s['acc']} · 没有换号记录 —— "
                                   f"多半是某个仍在跑的 agy 把钥匙串写回了自己的身份",
                           "accs": [segs[i - 1]["acc"], s["acc"]]})
    events.sort(key=lambda e: -e["t"])

    days = R._day_bounds(start, end)
    rows = []
    for lab in [a["acc"] for a in accounts]:
        cells = []
        for (_d, d0, d1) in days:
            # ★ 取**并集**不是求和：本机常有好几个 agy 同时以同一个号在跑（实测一天求和出 139633s，
            #   超过一天的 86400s）。「在岗」问的是这段时间里有没有它，不是它被开了几次。
            secs = _union([(max(s["start"], d0), min(s["end"], d1))
                           for s in segs if s["acc"] == lab and s["end"] > d0 and s["start"] < d1])
            n = sum(1 for s in segs if s["acc"] == lab and d0 <= s["start"] < d1)
            if earliest is not None and d1 <= earliest:
                cells.append("unknown")
            else:
                cells.append({"secs": int(secs), "requests": n, "tokens": 0} if (secs or n) else None)
        rank = None
        for i, sub in enumerate(pool.get("pinned") or []):
            if (accs.get(sub) or {}).get("label") == lab:
                rank = i
        rows.append({"acc": lab, "rank": rank,
                     "rotate_off": any(a.get("rotate_off") for a in accs.values() if a.get("label") == lab),
                     "cells": cells})

    changes = sum(1 for i in range(1, len(segs)) if segs[i]["acc"] != segs[i - 1]["acc"])
    dwell = [s["end"] - s["start"] for s in segs]
    covered = earliest is not None and earliest <= start
    return {
        "ok": True, "platform": "agy", "generated_at": int(now),
        "window": {"start": start, "end": end, "hours": hours},
        "accounts": accounts, "segments": segs, "markers": [], "events": events,
        "log": [{"t": t, "text": b} for (t, _k, _l, b) in sorted(evs_raw, reverse=True)][:200],
        "daily": {"days": [d[0] for d in days], "rows": rows, "relay": [0] * len(days)},
        "kpi": {"tokens": 0, "requests": len(segs), "avg_tokens": 0, "rotations": changes,
                "avg_dwell": (sum(dwell) / len(dwell)) if dwell else 0, "cool_429": 0,
                "stream_err": 0, "pro_segs": 0, "pro_secs": 0},
        "coverage": {"responses_seen": 0, "responses_with_tokens": 0, "responses_unplaced": unattr,
                     "attributed_pct": None, "undated_lines": 0, "in_window_lines": len(raw),
                     "tail_truncated": False, "window_covered": covered, "tail_bytes": 0,
                     "covers_from": earliest, "log_begins_at": earliest,
                     "log_begins_reason": "ok" if earliest else "unreadable"},
    }


if __name__ == "__main__":
    hrs = 24.0
    if "--hours" in sys.argv:
        hrs = float(sys.argv[sys.argv.index("--hours") + 1])
    sys.stdout.write(json.dumps(collect(hrs), ensure_ascii=False))
