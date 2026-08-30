#!/usr/bin/env python3
"""Phase-1b rotating proxy for the Codex ChatGPT-subscription backend.

Codex (custom model_provider, base_url=http://127.0.0.1:PORT) → this proxy → chatgpt.com, with:
  • pool-based account selection (least-used WEEKLY quota, skip cooling) from codex-rotate slots
  • on-expiry OAuth refresh of the selected account's token (reuses the proven refresh flow)
  • 429 → mark the account cooling in state.json
  • billing safety: a request that reached the upstream is NEVER re-sent to another account
stdlib-only; streams the SSE response back close-delimited.

★ 两处曾经写在这里、现已被实测推翻的说法,留下以免有人照着旧描述推理:
  • "session affinity: previous_response_id sticks the whole conversation to one account" ——
    **从未生效**。实测 2291 次请求 100% 不带 previous_response_id,选号原因全是 `new`,
    `_affinity` 一次都没命中。每一轮都重新挑用量最少的号,所以一次会话必然跨号。
    (轮换本身不浪费:同一 prompt 发同号两次 vs 发两个号,input_tokens 一致;cached_tokens
     恒为 0,`store:true` 被端点 400 拒 —— 没有 prompt cache 可失去。)
  • "least-used 5h quota" —— Codex 于 2026-07 废掉 5h 窗口,现在只有周/月。
"""
import base64
import datetime
try:
    import fcntl                       # POSIX
except ModuleNotFoundError:            # Windows —— 语义等价的 LockFileEx 兼容层,见 portalock.py
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    import portalock as fcntl          # noqa: F401  (drop-in: flock / LOCK_EX / LOCK_NB)
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("CRP_PORT", "8011"))
UPSTREAM_HOST = "chatgpt.com"
UPSTREAM_BASE = "/backend-api/codex"
STORE = Path(__file__).resolve().parent.parent          # codex-account-rotator/
AUTH_DIR = STORE / "auth"
STATE = STORE / "state.json"
LIVE = Path(os.environ.get("CODEX_LIVE_AUTH", str(Path.home() / ".codex" / "auth.json")))
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_LOCK = STORE / ".refresh.lock"   # cross-process: shared with codex-rotate (refresh + cred copies)
STATE_LOCK = STORE / ".state.lock"       # cross-process state.json RMW mutex (codex-rotate takes the same)

_affinity = {}            # previous_response_id → account_id
# ★ 会话粘性的**真正**key。codex 每个 POST /responses 都带 `prompt_cache_key`(实测 2026-08-09
# 的 body 键:client_metadata,include,input,model,parallel_tool_calls,**prompt_cache_key**,
# reasoning,service_tier,store,stream,text,tool_choice) —— 那是 OpenAI 用来标识 prompt cache
# 血缘的字段,同一会话恒定。以前用 `previous_response_id` 做 key 是选错了字段:codex 从不发它
# (实测 2291/2291),所以 `_affinity` 从未命中过一次,每轮都在重新挑号。
# 换号的代价不是"多一次请求",而是**整段历史在新号上冷缓存全价重算**(实测冷启动单次 17~24 万
# input,占未命中 input 的 29.7%)。所以这条粘性是省钱的主力,迟滞只是它的兜底。
_conv = {}                # prompt_cache_key → account_id
_lock = threading.Lock()
_state_lock = threading.Lock()     # serialize state.json read-modify-write across ThreadingHTTPServer threads
_refresh_lock = threading.Lock()   # serialize refreshes — concurrent refresh of ONE account kills its single-use refresh_token
_RESP_ID = re.compile(rb'"id"\s*:\s*"(resp_[A-Za-z0-9_-]+)"')


def _load(p):
    return json.loads(Path(p).read_text())


def _mutate_state(fn):
    """Serialized read-modify-write of state.json. ThreadingHTTPServer runs many request threads; a
    fixed `state.tmp` + unsynchronized writes interleave bytes → corrupt JSON (observed: stray '}').
    Holding _state_lock for the whole load→modify→atomic-write makes the proxy a single writer and
    prevents lost updates; the UNIQUE mkstemp temp keeps even cross-process writes from sharing a path.
    The STATE_LOCK flock extends the same guarantee across processes (codex-rotate holds it for its own
    load→mutate→save), so CLI and proxy can no longer silently revert each other's fields."""
    with _state_lock, open(STATE_LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            s = _load(STATE)
        except (OSError, ValueError):
            return
        fn(s)
        fd, tmp = tempfile.mkstemp(dir=str(STORE), prefix=".state.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(s, f, indent=2)
            os.replace(tmp, STATE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _plog(msg, rid=None):
    """代理日志的唯一出口:时间戳 + 请求 ID。

    ★ 为什么必须有这两样:proxy 跑在 ThreadingHTTPServer 上,并发请求的日志行天然交错。没有请求 ID
    时,连续两行 `→ POST [plus5]` 到底是「同一轮被重发」(=双计费)还是「两个并发请求」(=正常),
    **物理上无法区分** —— 排查「一次对话是不是打了两个号」时就卡死在这里,只能靠重跑实验。
    rid 让每一轮的生命周期可以被 grep 出来。"""
    ts = time.strftime("%m-%d %H:%M:%S")
    tag = f" #{rid}" if rid else ""
    sys.stderr.write(f"[proxy {ts}{tag}] {msg}\n")
    sys.stderr.flush()


def _bump(key):
    """把一类事件累加到 state.json 的 `proxy_counters`。

    ★ 存在的理由:双计费这个 bug 之所以拖到用户自己发现,是因为它只在日志里留下一行看不出严重性的
    `upstream err`,没有任何地方汇总"这个月发生了多少次"。计数器让下次同类问题在被问起之前就能量化。
    失败必须静默 —— 计数是可观测性,不能反过来拖垮它要观测的那条请求路径。"""
    def f(s):
        c = s.setdefault("proxy_counters", {})
        c[key] = c.get(key, 0) + 1
        c[key + "_last"] = time.time()
    try:
        _mutate_state(f)
    except Exception:
        pass


def _exp(jwt):
    try:
        p = jwt.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
    except Exception:
        return 0


def _slot_token(aid, slot, force=False):
    """Return (access_token, account_id), or (None, None) when this account is unusable RIGHT NOW.
    LIVE (active) account: READ-ONLY. Its refresh_token is owned by codex's native refresher, which
    does not take our flock — refreshing here can consume the same single-use token concurrently
    (= dead account, the last open death path of the B9 class). A valid live access token is used
    as-is (re-read every call, so codex's own rotation is picked up); expired/rejected → (None, None)
    and the caller fails over to another account instead of refreshing.
    Inactive slot: refresh on expiry (or force=True after a 401) under in-process + cross-process locks."""
    use_live = (aid == _load(STATE).get("active") and LIVE.exists()
                and (_load(LIVE).get("tokens") or {}).get("account_id") == aid)
    if use_live:
        tok = (_load(LIVE).get("tokens") or {})
        at = tok.get("access_token", "")
        if _exp(at) - time.time() > 60:
            return at, tok.get("account_id")
        return None, None
    sf = AUTH_DIR / slot["file"]
    tok = (_load(sf).get("tokens") or {})
    if not force and _exp(tok.get("access_token", "")) - time.time() > 60:
        return tok.get("access_token", ""), tok.get("account_id")
    # token expired → refresh under BOTH an in-process lock (proxy threads) and a cross-process file
    # lock (codex-rotate keepalive/manual refresh/switch), each with a re-check: the refresh_token is
    # single-use, so any two refreshers racing the SAME account invalidate it = dead account.
    with _refresh_lock, open(REFRESH_LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        if _load(STATE).get("active") == aid:
            return None, None  # a switch raced us: account just became live → codex owns it, never refresh
        auth = _load(sf)
        tok = auth.get("tokens") or {}
        at = tok.get("access_token", "")
        if not force and _exp(at) - time.time() > 60:
            return at, tok.get("account_id")            # another thread already refreshed it
        rt = tok.get("refresh_token")
        if not rt:
            return at, tok.get("account_id")
        body = json.dumps({"grant_type": "refresh_token", "client_id": OAUTH_CLIENT_ID,
                           "refresh_token": rt}).encode()
        try:
            req = urllib.request.Request(OAUTH_TOKEN_URL, data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
        except Exception as e:
            _plog(f"refresh {slot.get('label')} FAILED: {e}")
            return at, tok.get("account_id")
        if d.get("access_token"):
            tok["access_token"] = d["access_token"]
            if d.get("id_token"):
                tok["id_token"] = d["id_token"]
            if d.get("refresh_token"):
                tok["refresh_token"] = d["refresh_token"]
            auth["last_refresh"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            fd, tmp = tempfile.mkstemp(dir=str(sf.parent), prefix=f".{sf.name}.", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(auth))
            os.chmod(tmp, 0o600)
            os.replace(tmp, sf)
            _plog(f"refreshed {slot.get('label')} (slot)")
            return d["access_token"], tok.get("account_id")
        return at, tok.get("account_id")


def _win_used(slot, key):
    """This window's used_percent, or **None when we have no confirmed reading for it**.

    ★★ `None` means "not observed", NOT "0% used". The old version returned 0 for both
    "the reset time passed" and "there is no reading at all", so an account we knew nothing
    about sorted as completely idle and **out-ranked every account with a real measurement**.
    That is not a display bug — `_used` feeds `_pick`, so it changed where traffic went.

    ★ 过了重置点分两种，别一律作废（grok 2026-08-28 的判据）:
      · 快照 `captured_at` **晚于** `resets_at` ⇒ 读数本来就是重置之后拍的,`used_percent`
        属于新窗口,照常采信 —— 一律作废会把真实数据白白丢掉;
      · 快照更旧 ⇒ 窗口重置了但**还没有任何新读数**确认 ⇒ 未知。
    """
    q = slot.get("quota") or {}
    w = q.get(key) or {}
    u = w.get("used_percent")
    if u is None:
        return None
    ra = w.get("resets_at")
    if ra and ra <= time.time():
        cap = q.get("captured_at")
        return u if (cap is not None and cap > ra) else None
    return u


def _used(slot):
    """Sort key for _pick: primary (5h) first, weekly as tie-break. Without the weekly component, five
    accounts whose 5h windows all reset sort in dict-insertion order and every request lands on the
    first one — even if its weekly quota is nearly exhausted (observed: main at 9% weekly picked first)."""
    # ★★ 每个窗口是 `(未知?, 已用)` 两级键:**有读数的一律排在未知之前**,层内按已用升序。
    #    把"未知"塞进同一条百分比轴,就是拿一个**没有发生的观测**当成最有利的观测。
    #    数据完整时排序与改动前完全一致;全都未知时并列,退回原有顺序。
    def k(key):
        u = _win_used(slot, key)
        return (1, 0.0) if u is None else (0, u)
    return (k("primary"), k("secondary"))


# ★ 选号迟滞(百分点)。0 = 旧行为「谁低选谁」。
#
# 为什么需要它:`_affinity` 依赖 `previous_response_id`,而 codex 从不发(实测 2291/2291),所以粘性
# 从未生效,每轮都重新挑号。服务端只回**整数** used_percent,于是多个号打平后会来回横跳,而**每一次
# 换号 = 该轮整段历史在新号上冷缓存全价重算**。
#
# 代价有多大:实测全量 rollout,`cached_input_tokens/input_tokens` 逐月 95%~99%(推翻了项目里
# 「cached_tokens 恒 0、没有 prompt cache 可失去」的旧结论)。定义冷大请求=`cached==0 且 input>50k`,
# 它占**未命中 input**(真正贵的那部分)的比例逐月为 9.2/6.0/13.1/0/18.7/**27.2%(8月)**,在恶化。
#
# 迟滞只放弃「百分比完全拉平」这个**本来就不是目标**的性质:只要当前号没比最省的号贵出 N 个百分点
# 就继续用它。耗尽/冷却/dead 的判断完全不变 —— 那几条是安全性,不参与迟滞。
# 取 5:仿真 A/B(scratch/picker_ab_20260809.py,跑的就是本函数)在 30~300 轮 × 4 档消耗速率下,
# 合计换号 H=0→78 · H=3→13 · H=5→6 · H=10→3,5 之后收益递减。它同时把池内不平衡的上界钉在
# 5 个百分点(超过即换号),不会出现「一个号跑到 100% 而别人闲着」。
# 回退:`CRP_PICK_HYSTERESIS=0` 即逐字节回到旧行为(已单测覆盖)。
PICK_HYSTERESIS = float(os.environ.get("CRP_PICK_HYSTERESIS", "5"))


def _pick(prev_id, exclude=None, conv=None):
    """(aid, slot, reason). 优先级:会话粘性(conv) > previous_response_id 粘性 > 迟滞 > 最少使用者。
    每一层都先过 `ok()`(排除 dead / 冷却 / 本轮已试过),所以粘性永远不会挡住 failover。"""
    exclude = exclude or set()
    s = _load(STATE)
    slots = s.get("slots", {})
    now = time.time()
    if not slots:
        return None, None, "empty"

    def cooling(sl):
        cu = sl.get("cooling_until", 0)
        if cu <= now:
            return False
        ra = ((sl.get("quota") or {}).get("primary") or {}).get("resets_at")
        return not (ra and ra <= now)  # window already reset → stale cooldown, treat as free

    def ok(aid, sl):
        return aid not in exclude and not sl.get("auth_dead") and not cooling(sl)

    with _lock:
        # ★ 会话粘性优先:同一个 prompt_cache_key = 同一段对话 = 同一份 prompt cache。
        # 只要该号还能用就绝不换 —— 换了就等于把这段对话的缓存扔掉重建。
        if conv and conv in _conv:
            aid = _conv[conv]
            if aid not in exclude and aid in slots and ok(aid, slots[aid]):
                return aid, slots[aid], "conv"
        if prev_id and prev_id in _affinity:
            aid = _affinity[prev_id]
            if aid not in exclude and aid in slots and ok(aid, slots[aid]):
                return aid, slots[aid], "affinity"
    avail = [(aid, sl) for aid, sl in slots.items() if ok(aid, sl)]
    if not avail:  # nothing cleanly available → relax cooling, but never a dead or already-tried one
        avail = [(aid, sl) for aid, sl in slots.items()
                 if aid not in exclude and not sl.get("auth_dead")]
    if not avail:
        return None, None, "exhausted"
    avail.sort(key=lambda kv: _used(kv[1]))

    # ★ 迟滞:上一次真正服务过的号(`last_aid` 由 _record_quota 在成功响应后写入 —— 用它而不是
    # 「上次被挑中的号」,因为挑中但 401/429 失败的那个不该被粘住)如果仍可用、且没比最省的号贵出
    # PICK_HYSTERESIS 个百分点,就继续用它。exclude 里的(本轮已试过的)绝不粘 —— 那会把 failover
    # 变成死循环。
    if PICK_HYSTERESIS > 0:
        last = s.get("last_aid")
        if last and last not in exclude and last in slots and ok(last, slots[last]):
            # ★ 任一侧未知就**不粘**。迟滞的意思是"贵不了多少就继续用它",
            #   而"贵多少"在缺少读数时**无从谈起** —— 拿 None 当 0 正是上面刚修掉的那个错。
            lu = _win_used(slots[last], "primary")
            bu = _win_used(avail[0][1], "primary")
            if lu is not None and bu is not None and lu <= bu + PICK_HYSTERESIS:
                return last, slots[last], "sticky"

    return avail[0][0], avail[0][1], "new"


def _cool(aid, minutes=300):
    def f(s):
        sl = s.get("slots", {}).get(aid)
        if sl:
            now = time.time()
            until = now + minutes * 60
            ra = ((sl.get("quota") or {}).get("primary") or {}).get("resets_at")
            if ra and ra > now:
                until = min(until, ra + 60)  # never cool past the real 5h-window reset
            elif ra:
                # snapshot is STALE (its reset already passed — e.g. a 429 that carried no x-codex
                # headers): capping with it would set cooling_until in the PAST = no cooldown at all,
                # and the next request re-picks this account in a 429 loop. Short fallback instead.
                until = now + 600
            sl["cooling_until"] = until
    _mutate_state(f)


def _mark_dead(aid, token_fp=None):
    """Flag an account whose token the server rejected even after a forced refresh (token invalidated /
    session terminated) so the picker skips it. token_fp = tail of the REJECTED access token: autosync
    only clears the flag when it sees a DIFFERENT token (re-login / codex-native refresh), so the 10s
    quota--save tick can no longer false-revive a dead account with the very token that was rejected."""
    def f(s):
        if aid in s.get("slots", {}):
            sl = s["slots"][aid]
            sl["auth_dead"] = True
            sl["auth_dead_at"] = time.time()
            if token_fp:
                sl["auth_dead_fp"] = token_fp
    _mutate_state(f)


def _record_quota(aid, headers, status=None):
    # ★★ 默认值必须是**安全**的那一侧，不是最宽松的那一侧。
    #    第一版写 `status=200` —— 调用点一旦漏传，就默认落进「完整清单」档、
    #    恢复整体替换，而**没有任何测试会经过调用点**（单测直接调函数）。
    #    这与今天刚修掉的「没有读数 → 当 0% 已用」是同一个形态：
    #    **把"不知道"默认成最有利/最宽松的取值**。现在漏传 = 不替换。
    #    调用点是否真的传了，由 tests/test_quota_never_fabricated.py 的 AST 闸盯着。
    """Per-request quota accounting: parse the x-codex-* rate-limit response headers and write the
    SERVED account's real quota to its slot — accurate, since the proxy knows exactly which account
    served this request (no rollout time-window guessing). Also records last_aid for the UI."""
    h = {k.lower(): v for k, v in headers}

    def num(key):
        try:
            return float(h[key])
        except (KeyError, ValueError, TypeError):
            return None

    pu = num("x-codex-primary-used-percent")
    su = num("x-codex-secondary-used-percent")
    if pu is None and su is None:
        return
    q = {
        "primary": {"used_percent": pu, "window_minutes": num("x-codex-primary-window-minutes"),
                    "resets_at": num("x-codex-primary-reset-at")},
        "secondary": {"used_percent": su, "window_minutes": num("x-codex-secondary-window-minutes"),
                      "resets_at": num("x-codex-secondary-reset-at")},
        "plan_type": h.get("x-codex-plan-type"),
        "captured_at": time.time(),
        "source": "proxy",
    }
    # ★★ **只有 2xx 才是完整清单**（grok 2026-08-28 定的绑法：完整性跟**响应类型**走，
    #    不跟**写入方身份**走）。`_finish` 对任何非 401 都调这里，429 另有两处专门调用；
    #    而限流/错误响应**可能只带一个窗口的头**，整体替换就会把另一个真实窗口写成 null。
    #    「零个头的 429」是本仓库记录过的事实（CHANGELOG B16），上面的早退已挡住；
    #    未知的是「恰好一个头」—— 无从证实也无从证伪，所以这里锁**不变量**而不是等证据。
    #
    #    ★ **不要改成「非 2xx 时逐窗口保留」**：`captured_at` 挂在 quota **对象**上，
    #      保留下来的窗口会蹭到兄弟窗刚刷新的时间戳，于是 `helpers.ts::winRem` 的
    #      「快照晚于重置点才采信」会把幽灵窗**认证成真实读数**，永远画一条绿色 100%。
    #      按 2xx 绑则没有这个问题：`/usage` 恒 403 的机器上，下一次成功的 2xx 就会清掉它。
    complete = 200 <= (status or 0) < 300

    def f(s):
        if aid in s.get("slots", {}):
            prev = (((s["slots"][aid].get("quota") or {}).get("primary") or {}).get("used_percent"))
            if complete:
                s["slots"][aid]["quota"] = q
                s["slots"][aid]["quota_status"] = "ok"
            s["last_aid"] = aid
            s["last_proxy_ts"] = time.time()  # lets codex-rotate/plugin tell "via cxp" from "plain codex"
            # ★ 只在**跨过整数百分点**时记一行:服务端只回整数,所以这就是能拿到的最细粒度。
            # 目的是攒「每 1% 对应多少 token」的样本,判定额度计量到底算不算缓存命中的部分 ——
            # 这一条决定了会话粘性/迟滞是省额度还是只省钱(订阅制下后者=什么也没省)。
            # 现有证据只有 n=3、Δ% 只有 2~3(整数量化 ±50%),不足以下结论。
            if complete and prev is not None and pu is not None and pu != prev:
                s.setdefault("quota_marks", []).append(
                    {"aid": aid, "t": round(time.time(), 1), "from": prev, "to": pu})
                del s["quota_marks"][:-400]      # 上界,避免 state.json 无限长
    _mutate_state(f)


class SendFailed(Exception):
    """连接/发送阶段就失败了 —— 请求**没有**到达上游,该号不会被计费,换号重发是安全的。"""


class UpstreamCommitted(Exception):
    """★ 请求已经完整发出,但读响应时失败(超时 / TLS EOF / 对端关闭)。

    此时上游**很可能已经开始生成并计费**,而我们拿不到任何回执来确认。原实现把这一类和 SendFailed
    混在同一个 `except Exception` 里 `continue` 换号,注释还断言 "nothing reached codex yet" ——
    那句话只对连接/发送阶段成立。结果:一次用户请求被两个号各计一次费,成本翻倍。

    ★ 证据不足以判定它到底计没计费(日志从不记录异常发生在哪个阶段,这本身就是缺陷的一部分;
    实测 218 次 `EOF occurred in violation of protocol` 无法归相位)。所以这里选**在两种假说下
    都不更差**的做法:只要请求已送出就绝不换号重发 —— 最坏情况是白丢一次请求(客户端本来就会重试),
    而绝不会变成双倍扣费。流式阶段早已是这个策略(见下面 `stream err` 分支),这里只是把同一条不变量
    补到它本该覆盖的位置。"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _open(self, body, token, account_id, label, reason, prev_id, rid=None):
        """Send the request upstream under one account's token; return (conn, resp). Caller closes conn.

        两阶段分开抛异常,让调用方**无法**再把「没送出去」和「送出去了但没读到回应」当成一回事。"""
        path = UPSTREAM_BASE + self.path
        skip = {"host", "authorization", "chatgpt-account-id", "content-length", "connection"}
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in skip}
        hdrs["Authorization"] = f"Bearer {token}"
        if account_id:
            hdrs["chatgpt-account-id"] = account_id
        hdrs.setdefault("originator", "codex_cli_rs")
        hdrs["Content-Length"] = str(len(body))
        # ★ body 指纹。三方评审(codex/grok/kimi)收敛到同一个残余双计费机制:上游已 200 并计费 →
        # SSE 在 completed 前断掉 → codex 把**整轮当成全新 POST 重发** → 代理重新挑号 → 第二个号
        # 再计一次。代理的 400-abort 拦不住它(那是一个新的 HTTP 请求,与首发无任何关联标识)。
        # 闭环证据只差一件:两次 POST 的 body 是否同一个。rid 证明不了 —— 它只标识一次 handler 调用。
        # 只记 sha256 前 12 位:单向摘要,不含任何明文/凭证,足以判等。
        bh = hashlib.sha256(body).hexdigest()[:12] if body else "-"
        ck = getattr(self, "_conv_key", None)
        _plog(f"→ {self.command} {self.path} [{label}] {reason}"
              f" conv={ck[:12] if ck else '-'} body={bh}", rid)
        # ★ 相位分界 = request() vs getresponse(),不是 connect() vs 其后。
        # 依据:`sendall` 是循环写,**当且仅当仍有尾段没写进去时才抛异常** —— 尾段没出去,上游拿到的
        # 就是不完整的 body,Content-Length 框架下这种请求永远不会被 dispatch,也就不可能计费。
        # 所以 request() 抛错 = 可证明未计费 = 换号安全;只有 getresponse() 抛错才是「已完整交给内核、
        # 到没到不可知」。(上一版我按「connect 之后一律算已提交」画界,依据是"sendall 可能已送出完整帧",
        # 那个前提是错的 —— 四方评审里 Fable 指出并驳倒了它。)
        # 连接构造/TLS ctx 也放进这一段:它们抛错时零字节送出,同属 SendFailed。
        conn = None
        try:
            conn = http.client.HTTPSConnection(UPSTREAM_HOST, 443,
                                               context=ssl.create_default_context(), timeout=180)
            conn.request(self.command, path, body=body, headers=hdrs)
        except Exception as e:
            if conn is not None:
                conn.close()
            raise SendFailed(e) from e
        try:
            resp = conn.getresponse()
        except Exception as e:
            conn.close()
            raise UpstreamCommitted(e) from e
        _plog(f"← {resp.status} [{label}]", rid)
        return conn, resp

    def _billable(self):
        """这次请求失败会不会烧钱。

        ★ 判据是「不是 GET/HEAD」,而**不是**白名单 `POST /responses`。方向很重要:白名单一旦漏掉
        某个计费端点(上游新增路由、absolute-form 请求行、路径前缀变化),漏网的那个会被当成非计费 →
        照旧换号重发 → **原双计费 bug 静默复活,而计数器对它零感知**。反过来用黑名单,误判方向是
        「多 abort 一个本可重试的请求」,代价是一次请求而不是一次静默扣费。
        与全部观测数据兼容:实测 228 次 upstream err 中的 212 次非计费请求**全部是 GET**。"""
        return self.command not in ("GET", "HEAD")

    # ★ ABORT 用 400 而不是 502 —— 实测出来的,不是猜的。
    # 拿一个恒定返回指定状态码的假上游顶掉真代理,让 cxp 打它,数 POST /responses 的次数:
    #     502 → 30 次    409 → 6 次    429 → 1 次    400 → 1 次
    # 502 是可重试码,codex 会带退避猛重发;而每一次重发在真代理里都会重新挑号转发上去。也就是说
    # 上一版返 502 的"修复"把「可能两个号各计一次」放大成了「最多 N 个号轮着计费」——比它要修的
    # bug 更糟。400 让 codex 一次就停,这是唯一能让 abort 策略真正成立的前提。
    ABORT_STATUS = 400

    def _abort(self, label, exc, rid=None):
        """计费请求已提交但读不到回应 → 终止本轮,绝不换号重发。响应体只给固定文案。

        单独成 helper 是因为评审指出:上一版把 send_error 那段在两个调用点手抄了一遍,
        "第三个调用点不可能退化"并没达成 —— 退化点只是从 except 块挪到了 if 块。"""
        _bump("committed_aborts")
        _plog(f"⚠️ committed [{label}]: {exc} — 计费请求已送出,中止而非换号(防双计费)", rid)
        try:
            # 不回显 str(exc):它含本地路径 / TLS / 系统错误文本,没有理由暴露给客户端。
            self.send_error(self.ABORT_STATUS,
                            "upstream committed but unreadable; not retried to avoid double-billing")
        except Exception:
            pass

    def _open_or_fail(self, body, token, account_id, label, reason, prev_id, rid=None):
        """包住 _open,把结局压成 (conn, resp) | "NEXT" | "ABORT"。

        返回 "ABORT" 时**响应已经发出去了**,调用方只需 `return`。

        ★ 两个调用点(首发 + 401 强刷后重发)必须共用这段。评审在初版里抓到:我只改了首发那个,
        401 那条仍是 bare `except Exception: continue` —— 同一个双计费 bug 原封不动地活着。"""
        try:
            return self._open(body, token, account_id, label, reason, prev_id, rid)
        except SendFailed as e:
            _plog(f"send err [{label}]: {e} — 未完整送达,安全换号", rid)
            return "NEXT"
        except UpstreamCommitted as e:
            if not self._billable():
                _plog(f"committed [{label}] (非计费 {self.command}): {e} — 换号重试", rid)
                return "NEXT"
            self._abort(label, e, rid)
            return "ABORT"

    def _finish(self, conn, resp, aid, label):
        """Relay the chosen upstream response back to codex, recording quota + session affinity."""
        _record_quota(aid, resp.getheaders(), resp.status)
        # ★ 只在**真正成功服务过**之后才登记会话归属 —— 挑中但 401/429 失败的号不该被粘住。
        conv = getattr(self, "_conv_key", None)
        if conv:
            with _lock:
                _conv[conv] = aid
                while len(_conv) > 512:          # FIFO 上界:长跑的代理不能无限攒会话
                    _conv.pop(next(iter(_conv)))
        self.send_response(resp.status)
        hop = {"connection", "transfer-encoding", "content-length", "keep-alive"}
        for k, v in resp.getheaders():
            if k.lower() not in hop:
                self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        scanbuf, got = b"", False
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
            if not got:
                scanbuf += chunk
                m = _RESP_ID.search(scanbuf)
                if m:
                    rid = m.group(1).decode()
                    with _lock:
                        _affinity[rid] = aid
                        while len(_affinity) > 256:  # FIFO cap — codex never sends previous_response_id
                            _affinity.pop(next(iter(_affinity)))  # today, so entries only accumulate
                    got = True
                    _plog(f"affinity {rid[:18]} → [{label}]", rid)
                elif len(scanbuf) > 65536:
                    scanbuf = scanbuf[-4096:]

    def _proxy(self):
        # 每轮一个短 ID:ThreadingHTTPServer 下并发请求的日志行会交错,没有它就分不清
        # 「同一轮被重发」和「两个并发请求」—— 而这正是排查双计费时唯一要回答的问题。
        rid = f"{threading.get_ident() % 0x1000:03x}{int(time.time() * 1000) % 0x1000:03x}"
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        prev_id = conv = None
        if body:
            try:
                _b = json.loads(body)
                if isinstance(_b, dict):
                    prev_id = _b.get("previous_response_id")
                    c = _b.get("prompt_cache_key")
                    conv = c if isinstance(c, str) and c else None
            except Exception:
                pass
        # 放到实例上而不是往 _finish 传参:_finish 有两个调用点(首发 + 401 强刷后重发),
        # 靠参数传递意味着漏掉一处就静默失去粘性。Handler 每请求一个实例,这样存是安全的。
        self._conv_key = conv
        # failover loop: pick least-used → on 401 (dead token) mark dead + try next; on 429 cool + try
        # next; on a network error before any bytes reach codex, try next. First usable account wins.
        # One dead/exhausted/unreachable attempt never blocks the whole request.
        tried = set()
        pool_n = len(_load(STATE).get("slots", {}))
        for _ in range(max(1, pool_n)):
            aid, slot, reason = _pick(prev_id, exclude=tried, conv=conv)
            if not aid:
                break
            tried.add(aid)
            label = slot.get("label", aid[:6])
            token, account_id = _slot_token(aid, slot)
            if not token:
                _plog(f"skip [{label}]: live token expired (codex owns its refresh)", rid)
                continue
            conn = None
            streamed = False
            try:
                got = self._open_or_fail(body, token, account_id, label, reason, prev_id, rid)
                if got == "NEXT":
                    continue
                if got == "ABORT":
                    return          # 响应已由 _abort() 发出
                conn, resp = got
                if resp.status == 401:
                    conn.close()  # stored token rejected → one forced refresh, retry SAME account once
                    conn = None
                    token2, account_id2 = _slot_token(aid, slot, force=True)
                    if token2 and token2 != token:
                        # ★ 评审抓到的 blocker:这里原本是 bare `except Exception: continue`,
                        # 与首发路径同一个双计费 bug。第一发 401 说明没计费,但这一发是真 billable POST。
                        got = self._open_or_fail(body, token2, account_id2, label, "retry-refresh", prev_id, rid)
                        if got == "NEXT":
                            continue
                        if got == "ABORT":
                            return          # 响应已由 _abort() 发出
                        conn, resp = got
                        if resp.status == 429:
                            # 评审指出:强刷后拿到 429 原本被当成功直接转发,绕过了下面的冷却+换号,
                            # 该号不进冷却,codex 退避后大概率再次选中它。
                            _record_quota(aid, resp.getheaders(), resp.status)
                            _cool(aid)
                            _plog(f"429 (retry-refresh) → cooled [{label}], failing over", rid)
                            continue
                        if resp.status != 401:
                            streamed = True
                            self._finish(conn, resp, aid, label)
                            return
                    _mark_dead(aid, (token2 or token)[-16:])
                    _plog(f"401 invalidated → marked dead [{label}], failing over", rid)
                    continue
                if resp.status == 429:
                    _record_quota(aid, resp.getheaders(), resp.status)
                    _cool(aid)
                    _plog(f"429 → cooled [{label}], failing over", rid)
                    continue
                streamed = True
                self._finish(conn, resp, aid, label)
                return
            except Exception as e:
                # response already partially relayed (or client hung up) — a retry on another account
                # would double-send; abort. send_error only if no headers went out yet.
                # ★ 计费请求的断流是**最大的一类真实浪费**:上游已 200 并计费,流却断了,codex 会把
                # 整轮重发到另一个号(实测 85 次紧跟新请求)。代理侧无解 —— 响应已部分转发,abort 是唯一
                # 正确动作(伪造 response.completed 收尾更糟)。但必须可量化。
                # ★ 只数计费的:实测 545 次 stream err 里 **491 次(90%)是 GET /models** —— 客户端拿完
                # 模型列表就关连接,完全无害。无条件累加会让这个指标 9 成是噪音,看着吓人却没有信息量,
                # 正是它要取代的那种"没人看得懂的日志"。
                if self._billable():
                    _bump("stream_aborts")
                _plog(f"stream err [{label}]: {e}", rid)
                if not streamed:
                    # ★ 这里原本是 `send_error(502, str(e))`,两处都不对:
                    #   ① 502 是可重试码 —— 实测 codex 对 502 会重发 30 次,每次在代理里重新挑号。
                    #      能走到这儿(streamed 尚未置位)说明异常出在 _slot_token/_pick/_record_quota
                    #      这类地方;若本次是计费请求,那 30 次重试就是 30 次挑号扣费的机会。
                    #   ② str(e) 会把本地路径、TLS/系统错误原文回显给客户端,没有理由暴露。
                    # 计费请求一律用不可重试的 400 掐断;非计费的保留 502(重试免费,能自愈更好)。
                    try:
                        if self._billable():
                            self.send_error(self.ABORT_STATUS, "upstream relay failed; not retried to avoid double-billing")
                        else:
                            self.send_error(502, "upstream relay failed")
                    except Exception:
                        pass
                return
            finally:
                if conn is not None:
                    conn.close()
        try:
            self.send_error(503, "no usable account (dead / rate-limited / live-expired) — \\codex login or wait")
        except Exception:
            pass

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        self._proxy()


if __name__ == "__main__":
    _plog(f"rotating proxy on 127.0.0.1:{PORT} → https://{UPSTREAM_HOST}{UPSTREAM_BASE}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
