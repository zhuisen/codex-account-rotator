#!/usr/bin/python3
# SwiftBar plugin — Codex account-rotator (style: 简洁 / minimal).
# SF-symbol status dot (filled=active / hollow=switchable / clock=cooling, colored by remaining)
# + smooth remaining-quota gauges + email subtitle. UUID/plan/expiry/actions live in a submenu.
# Menu-bar title stays system-colored unless quota is low (amber/red). Display reads state.json.
import datetime
import json
import os
import socket
import subprocess
import sys
import time

STORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROT = os.path.join(STORE, "codex-rotate")
STATE = os.path.join(STORE, "state.json")
NOW = time.time()
GRAY = "#8a8a8a"
GREEN = "#3aa856"
AMBER = "#e0a020"
RED = "#e0533a"
MONO = "font=Menlo size=12"
EIGHTHS = "▏▎▍▌▋▊▉"  # 1/8 .. 7/8
VERSION = "v0.8.1"  # bumped on every change — shown in the menu so you can tell it reloaded


def mask(aid):
    if not aid:
        return "?"
    return aid[:6] + "…" + aid[-4:] if len(aid) > 12 else aid


def rem_color(rem):
    return RED if rem <= 10 else AMBER if rem <= 30 else GREEN


# Menu-bar title icon. A fixed emoji (⚡ 🔋 ⛽ 🤖 🧠 ⏱️ 📊 🎚️),
# or "auto" (🟢🟡🔴 by remaining), or "battery" (🔋/🪫 by remaining).
ICON = "⚡"


def title_icon(rem):
    if ICON == "auto":
        return "🔴" if rem <= 10 else "🟡" if rem <= 30 else "🟢"
    if ICON == "battery":
        return "🪫" if rem <= 30 else "🔋"
    return ICON


def smooth_bar(rem, w=10):
    rem = max(0.0, min(100.0, float(rem or 0)))
    units = rem / 100.0 * w
    full = int(units)
    eighth = int(round((units - full) * 8))
    if eighth == 8:
        full += 1
        eighth = 0
    cells = "█" * full
    if eighth:
        cells += EIGHTHS[eighth - 1]
    cells += " " * (w - full - (1 if eighth else 0))
    return "▕" + cells + "▏"


def fmt_eta(ts):
    if not ts:
        return "?"
    d = int(ts - NOW)
    if d <= 0:
        return "已重置"
    h, m = d // 3600, (d % 3600) // 60
    if h >= 24:
        return f"{h // 24}d{h % 24}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


def fmt_age(ts):
    if not ts:
        return "?"
    d = int(NOW - ts)
    if d < 90:
        return "刚刚"
    h = d // 3600
    if h >= 24:
        return f"{h // 24}d前"
    return f"{h}h前" if h else f"{d // 60}m前"


def stale_days(slot):
    lr = slot.get("last_refresh")
    if not lr:
        return None
    try:
        base = str(lr).replace("Z", "").split(".")[0]
        dt = datetime.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return None


def proxy_up(port=8011):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def win_remaining(w):
    """Remaining % for one window; a window whose reset time has passed reads as fully reset (100%)."""
    used = (w or {}).get("used_percent")
    if used is None:
        return None
    ra = (w or {}).get("resets_at")
    if ra and ra <= NOW:
        return 100.0
    return 100 - used


def tightest_remaining(q):
    rems = [r for r in (win_remaining(q.get("primary")), win_remaining(q.get("secondary"))) if r is not None]
    return min(rems) if rems else 100


def effectively_cooling(slot):
    """Single source of truth for 'is this account cooling', matching the proxy's _pick: a cooldown
    that hasn't elapsed BUT whose 5h window already reset is stale → NOT cooling (that was the
    '冷却 1h25m' + '5h 100% 已重置' contradiction: a pre-fix fixed-300m cooldown outliving its window)."""
    cu = slot.get("cooling_until", 0)
    if cu <= NOW:
        return False
    ra = ((slot.get("quota") or {}).get("primary") or {}).get("resets_at")
    return not (ra and ra <= NOW)


def account_block(aid, slot, active):
    """Yield SwiftBar lines for one account."""
    label = slot.get("label", "?")
    who = slot.get("email") or mask(aid)
    q = slot.get("quota")
    dead = slot.get("auth_dead")
    cooling = effectively_cooling(slot)
    sym_color = rem_color(tightest_remaining(q)) if q else GRAY
    lines = []
    if dead:
        lines.append(f"{label} · 失效 | sfimage=exclamationmark.triangle.fill color={RED} size=13")
    elif aid == active:
        lines.append(f"{label} | sfimage=circle.fill color={q and sym_color or GREEN} size=13")
    elif cooling:
        lines.append(f"{label} · 冷却 {fmt_eta(slot.get('cooling_until'))} | sfimage=clock color={GRAY} size=13")
    else:
        age = f" · 快照 {fmt_age((q or {}).get('captured_at'))}" if q else ""
        lines.append(f"{label}{age} | sfimage=circle color={sym_color} size=13 "
                     f"shell={ROT} param1=switch param2={label} terminal=false refresh=true")
    sub = slot.get("sub_until")
    sub_txt = f"  ·  订阅至 {str(sub)[:10]}" if sub else ""
    lines.append(f"   {who}{sub_txt} | color={GRAY} size=12")
    if dead:
        lines.append(f"   ⚠️ token 失效 · 终端跑 \\codex login 登此号即可自动复活 | color={RED} size=11")
        return lines
    if q:
        for key, name in (("primary", "5h"), ("secondary", "周")):
            w = q.get(key) or {}
            rem = win_remaining(w)
            if rem is None:
                continue
            lines.append(f"   {name} {smooth_bar(rem)} {rem:>3.0f}%  ↻{fmt_eta(w.get('resets_at'))} "
                         f"| color={rem_color(rem)} {MONO}")
    elif slot.get("quota_status") == "empty" and aid == active:
        lines.append(f"   ⚠️ 本次会话没拿到额度数据(再跑一次即可) | color={AMBER} size=11")
    else:
        hint = "跑一次 codex 刷新" if aid == active else "切到此并跑一次"
        lines.append(f"   用量未知 · {hint} | color={GRAY} size=11")
    sd = stale_days(slot)
    if sd is not None and sd > 7:
        lines.append(f"   ⚠️ {int(sd)} 天未刷新 · 可能需重新登录 | color={AMBER} size=11")
    return lines


def main():
    up = proxy_up()
    try:  # always refresh; `quota --save` self-skips when the proxy recently owned the rollout (cxp)
        subprocess.run([sys.executable, ROT, "quota", "--save"], timeout=5, capture_output=True)
    except Exception:
        pass

    try:
        with open(STATE) as f:
            st = json.load(f)
    except Exception:
        st = {"slots": {}, "active": None}
    slots = st.get("slots", {})
    active = st.get("active")

    # ---- menu bar title: 额度 of the account currently in use, no label. Track whichever activity is
    # MOST RECENT — a manual switch (active_since), a plain-codex run (last_plain_ts, stamped by
    # quota --save from plain rollout mtime), or a cxp request (last_proxy_ts) — so the title follows
    # plain codex again after cxp use WITHOUT a fixed TTL (a TTL would re-introduce the flip-jitter
    # during cxp sessions with long thinking gaps between requests).
    cxp_recent = up and st.get("last_proxy_ts", 0) >= max(st.get("active_since", 0),
                                                          st.get("last_plain_ts", 0))
    shown = st.get("last_aid") if (cxp_recent and st.get("last_aid") in slots) else active
    # Show the TIGHTEST of the two windows (5h vs weekly), not just 5h. The 5h window resets every 5h,
    # so a few hours after a snapshot its reset time passes and win_remaining reads it as a full 100%
    # — which hid the real binding constraint (e.g. weekly at 42%) and left the title stuck at "100% ·
    # 已重置" whenever the account wasn't being actively driven (no live cxp/codex to refresh the 5h).
    q = (slots.get(shown, {}).get("quota") or {}) if shown in slots else {}
    wins = []
    for w in (q.get("primary"), q.get("secondary")):
        r = win_remaining(w)
        if r is not None:
            wins.append((r, w))
    if wins:
        rem, w = min(wins, key=lambda kv: kv[0])  # the binding constraint = least remaining
        title = f"{title_icon(rem)} {rem:.0f}% · {fmt_eta(w.get('resets_at'))}"
        if rem <= 10:
            title += f" | color={RED}"
        elif rem <= 30:
            title += f" | color={AMBER}"
        print(title)
    else:
        print(f"{title_icon(100)} codex")

    # ---- dropdown ----
    print("---")
    print(f"CODEX · 剩余额度 · {VERSION} | color={GRAY} size=11")
    print(f"{'🔀 代理轮换 开 (cxp)' if up else '⏸ 代理关 · plain codex'} | color={GRAY} size=11")
    print("---")
    if not slots:
        print(f"还没有账号 — 终端跑: codex-rotate add <label> | color={GRAY}")
    for aid, slot in slots.items():
        for line in account_block(aid, slot, active):
            print(line)

    # ---- details / actions submenu ----
    print("---")
    print(f"详情 / 操作 | sfimage=ellipsis.circle color={GRAY}")
    for aid, slot in slots.items():
        lbl = slot.get("label", "?")
        print(f"--{lbl} · {aid} | color={GRAY} size=12 "
              f"shell=/bin/sh param1=-c param2=\"printf %s {aid} | pbcopy\" terminal=false")
        meta = []
        if slot.get("plan"):
            meta.append(slot["plan"])
        if slot.get("sub_until"):
            meta.append("订阅至 " + str(slot["sub_until"])[:10])
        if meta:
            print(f"--{lbl} · {' · '.join(meta)} | color={GRAY} size=12")
    print("-----")
    print(f"--把当前号标记冷却 5h | shell={ROT} param1=cool param2=300 terminal=false refresh=true")
    print(f"--清除所有冷却 | shell={ROT} param1=uncool param2=all terminal=false refresh=true")
    print("--刷新 | refresh=true")
    print(f"--打开工具目录 | shell=/usr/bin/open param1={STORE} terminal=false")


if __name__ == "__main__":
    main()
