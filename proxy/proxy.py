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
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("CRP_PORT", "8011"))
UPSTREAM_HOST = "chatgpt.com"
UPSTREAM_BASE = "/backend-api/codex"
# ★★ **`CODEX_ROTATE_STORE` 是全仓统一的数据目录变量,这里必须跟着认**（2026-09-10 修）。
#    此前只有本文件硬写 `__file__` 推算,而 `codex-rotate` / `relay/store.py` /
#    `traffic/{scan,rotation,quota_anchors,agy_quota_sampler}.py` / `cxp` / `cxd`
#    **八处全都认这个变量** —— 代理是唯一的例外。
#    后果不是报错,是**脑裂**:安装目录与数据目录分开时(Windows 上 CodexBar 每次更新
#    整个替换安装目录,所以必须分开),`relay-ctl` 把 `route.local.json` 写进数据目录,
#    而代理去读安装目录里的那份 —— **切了路由代理毫不知情**,而两边都不报错。
#    `auth/` / `state.json` / `relays.local.json` / 两把跨进程锁同理:锁在不同路径上
#    等于没有锁,`codex-rotate` 与代理会同时刷同一个号的 token。
#    不设该变量时行为**逐字不变**(默认值就是原来的表达式)。
STORE = Path(os.environ.get("CODEX_ROTATE_STORE")
             or Path(__file__).resolve().parent.parent)   # codex-account-rotator/
# ★★ 中转站上游(2026-09-09 定稿:**一个 provider，两种上游**)。
#    以前的做法是给每个中转站单独生成一份 `~/.codex/<id>.config.toml`，靠 cxp 换 profile 切换。
#    那样做 codex 会看到两个不同的 `model_provider` id，而 `codex resume` 的 picker
#    **按 provider 过滤且无配置可绕** ⇒ 会话列表必然分裂成两份。
#    改成由代理自己决定往哪转发之后：provider 恒为 `rotateproxy`，会话列表只有一份；
#    并且 `profile_missing` / `profile_stale` / `orphan` 这三种**静默失败态直接不再可能发生**
#    (它们全部源于"第二份 profile 文件与登记不同步")。
RELAY_DIR = STORE / "relay"
RELAY_ROUTE = RELAY_DIR / "route.local.json"
RELAY_STORE = RELAY_DIR / "relays.local.json"
POOL_PROFILE = "rotateproxy"            # 账号池档的保留名，绝不可用作中转站 id
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


def _plan_tier(slot):
    """选号的**第一优先级**:Plus 排在 Pro 前面(用户 2026-09-07 定策略 C)。

    ★★ **这是产品策略,不是排序 bug 的修复**,两者这次一起做:
      · 策略:Plus 号平时承担轮换,**Pro 号保底** —— 只在没有任何可用 Plus 时才动它。
      · 顺带修掉的 bug 见 `_tightest_used`。

    ★ 按 `plan` 判,不按 label —— **老号从 Plus 升级到 Pro 时 label 一个字都不会变**。
    ★ 读不到 plan 的号归到 Plus 档:它**大概率就是 Plus**(本池 6 个号 5 个是),
      而把未知归到保底档会让一个刚加进来、还没解出 plan 的号永远排在最后、拿不到流量。
    """
    plan = (slot.get("plan") or (slot.get("quota") or {}).get("plan_type") or "").lower()
    return 1 if plan == "pro" else 0


def _tightest_used(slot):
    """这个号**最紧**窗口的已用百分比;读不到返回 `(1, 0.0)` 排在有读数的之后。

    ★★ **替掉了原来的 `_used()`**(已删,`git show v1.3.0:proxy/proxy.py` 可查)。
      它按 `(primary, secondary)` 字典序排,
      而 `primary` 是**槽位名不是窗口时长** —— Plus 的 primary 是 5h、Pro 的是周。
      于是一个「周额度 100% 烧光、但 5h 窗口刚重置回 0%」的号,按 primary 看是**全池最空的**。
      2026-09-07 用实况跑生产函数确认:plus3(周 100%)被排到**全池第一**,
      每次 5h 窗口重置都会重新排第一、白撞一次 429。
    ★ 本仓 8 月已在 UI 层定过这条(`helpers.ts`「单个汇总数字一律取最紧的窗口」);
      `codex-rotate::_headroom` 也是同一口径。这里是第三处,三处终于一致。
    ★ 「未知」仍排在「有读数」之后 —— 拿没发生的观测当成最有利的观测,是本仓反复栽的那类。
    """
    worst = None
    for key in ("primary", "secondary"):
        u = _win_used(slot, key)
        if u is None:
            continue
        if worst is None or u > worst:
            worst = u
    return (1, 0.0) if worst is None else (0, worst)


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

# ── 中转站上游解析 ────────────────────────────────────────────────────────────
# ★★ **一个键，存一个元组。** 原来是 `{"sig": ..., "up": ...}` 两次独立赋值 ——
#    而这是 `ThreadingHTTPServer`：线程 A 写完 `sig`、还没写 `up` 时，线程 B 读到的是
#    **新签名配旧上游**。后果是钱去了用户没选的地方：刚切到中转站却发去账号池，
#    或刚切回账号池却还在扣中转站余额。两者都不报错。
#    单个 dict 赋值在 GIL 下是原子的，所以把这一对绑成一个值就消掉了这个窗口。
_relay_cache = {"v": (None, None)}


def _route_sig():
    """两个文件的 (mtime, size)。**必须两个都看** —— 只看 route.local.json 的话，
    改了 key/base_url 却不切路由时，代理会一直用着旧凭证往旧地址发。"""
    out = []
    for p in (RELAY_ROUTE, RELAY_STORE):
        try:
            st = p.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _relay_upstream():
    """-> None(走账号池) | dict(走中转站)。**每请求调用，靠 mtime 签名避免读盘。**

    ★ 解析失败一律**退回账号池**（返回 None），绝不 fail-closed 成"谁也不通"。
      理由：账号池是零边际成本的那一档，而中转站是花钱的那一档 —— 判不准时
      往免费那边倒，最坏结果是"没按预期扣费"，反过来则是"用户不知情地在花钱"。
    ★ 同样绝不 fail-**open** 成中转站：路由文件读不到 ≠ 用户选了中转站。
    """
    sig = _route_sig()
    cached_sig, cached_up = _relay_cache["v"]
    if cached_sig == sig:
        return cached_up
    up = None
    try:
        route = json.loads(RELAY_ROUTE.read_text(encoding="utf-8"))
        rid = route.get("profile") if isinstance(route, dict) else None
        # `rotateproxy` = 账号池档的保留名；任何读不出 id 的形状都按账号池处理。
        if isinstance(rid, str) and rid and rid != POOL_PROFILE:
            reg = json.loads(RELAY_STORE.read_text(encoding="utf-8"))
            row = next((r for r in (reg.get("relays") or [])
                        if isinstance(r, dict) and r.get("id") == rid), None)
            if row and row.get("enabled") and row.get("key") and row.get("base_url"):
                u = urllib.parse.urlsplit(str(row["base_url"]))
                if u.scheme == "https" and u.hostname:
                    up = {
                        "id": rid,
                        "label": str(row.get("label") or rid),
                        "host": u.hostname,
                        "port": u.port or 443,
                        # base_url 到 `/v1` 为止；请求路径(`/responses`)由 codex 给出。
                        "base": u.path.rstrip("/"),
                        "key": str(row["key"]),
                        "model": row.get("model") or None,
                    }
    except Exception as e:
        _plog(f"relay route unreadable ({e}) — 退回账号池")
        up = None
    # ★★ **读完再取一次签名，两次不一致就不缓存。** 签名是在**读文件之前**取的，
    #    两者之间文件被改写的话，缓存里就会固化「新签名 + 旧内容」—— 而新签名等于
    #    最新文件状态，于是**直到下一次再改动为止**，代理都在用旧上游。
    #    这一版：只在"读的前后文件没变过"时才缓存；变过就这次用新读到的值、不写缓存，
    #    下次请求重来一遍。
    if _route_sig() == sig:
        _relay_cache["v"] = (sig, up)
    return up


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

    # ★★ 用户手动停用轮换的号(`codex-rotate rotate <label> --off`,总览页那个开关)。
    #    用户 2026-09-07:「A 账号我不想轮换,就禁掉」。
    #    ★ 存的是 `rotate_off` 而不是 `rotate_enabled` —— **缺省必须等于「参与轮换」**:
    #      autosync 新入池的号和所有存量号都没有这个键,用正向命名就得写迁移,
    #      而漏迁移的号会**静默退出轮换池**(症状:代理只用那两三个号,零报错)。
    #    ⚠️ 会话粘性(`conv`/`affinity`)**也要过这道闸** —— 否则一段已经粘在 A 上的对话
    #      会在 A 被停用之后继续用 A,而用户以为自己已经把它摘出去了。
    def rotatable(sl):
        return not sl.get("rotate_off")

    def ok(aid, sl):
        return (aid not in exclude and not sl.get("auth_dead")
                and not cooling(sl) and rotatable(sl))

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
                 if aid not in exclude and not sl.get("auth_dead") and rotatable(sl)]
    if not avail:
        # ★★ **最后一层兜底:全被停用时忽略这个开关,并把它记进日志。**
        #    CLI 已经拒绝关掉最后一个,所以走到这里只可能是手改 state.json 或多进程竞态。
        #    在「codex 整个不能用」与「多用了一个用户不想用的号」之间选后者 ——
        #    前者会让每个请求都失败,而 502 实测会被 codex 重试 30 次,越修越糟。
        #    ⚠️ 但**绝不能静默**:这一行是用户唯一能看出"设置被绕过了"的地方,
        #    而日志页的轮换事件流会把它显示出来。
        relaxed = [(aid, sl) for aid, sl in slots.items()
                   if aid not in exclude and not sl.get("auth_dead")]
        if relaxed:
            _plog("⚠️ 所有号都被停用了自动轮换 —— 本次忽略该设置,否则无号可用。"
                  "用 `codex-rotate rotate <label> --on` 恢复至少一个。")
            avail = relaxed
    if not avail:
        return None, None, "exhausted"
    avail.sort(key=lambda kv: (_plan_tier(kv[1]), _tightest_used(kv[1])))

    # ★ 迟滞:上一次真正服务过的号(`last_aid` 由 _record_quota 在成功响应后写入 —— 用它而不是
    # 「上次被挑中的号」,因为挑中但 401/429 失败的那个不该被粘住)如果仍可用、且没比最省的号贵出
    # PICK_HYSTERESIS 个百分点,就继续用它。exclude 里的(本轮已试过的)绝不粘 —— 那会把 failover
    # 变成死循环。
    if PICK_HYSTERESIS > 0:
        last = s.get("last_aid")
        if last and last not in exclude and last in slots and ok(last, slots[last]):
            # ★ 任一侧未知就**不粘**。迟滞的意思是"贵不了多少就继续用它",
            #   而"贵多少"在缺少读数时**无从谈起** —— 拿 None 当 0 正是上面刚修掉的那个错。
            # ★★ **迟滞不得跨套餐档**(2026-09-07 策略 C)。原来这里只比 `primary` 百分比,
            #    于是一个粘在 Pro 上的会话会因为"Pro 没比最省的 Plus 贵多少"而**一直粘在 Pro 上**,
            #    把「Pro 保底」直接绕过去。档位不同就不粘,让它回到上面那个 Plus 优先的排序。
            # ★ 口径同样换成**最紧窗口**:拿 Pro 的周% 和 Plus 的 5h% 比大小本就不成立。
            lt, lu = _plan_tier(slots[last]), _tightest_used(slots[last])
            bt, bu = _plan_tier(avail[0][1]), _tightest_used(avail[0][1])
            if lt == bt and lu[0] == 0 and bu[0] == 0 and lu[1] <= bu[1] + PICK_HYSTERESIS:
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


# ★ 具名附加限额的头形如 `x-codex-bengalfox-primary-used-percent`。
#   中间那段是**上游控制的短名**,所以:① 必须有界(见 _MAX_ADDL);② 只收白名单后缀;
#   ③ 短名本身要过滤控制字符 —— 它会进 state.json,而那个文件被轮换器和 UI 读。
_ADDL_RE = re.compile(
    r"^x-codex-(?P<name>[a-z0-9][a-z0-9-]*?)-(?P<win>primary|secondary)"
    r"-(?P<field>used-percent|window-minutes|reset-at)$")
# 上游一次能塞多少个具名限额没有契约。不设上界的话,`state.json` 每个请求都写一次,
# 一个异常上游就能把它撑爆 —— 而那是轮换器的活文件。CLIProxyAPI 同样取 8。
_MAX_ADDL = 8


def _codex_bool(v):
    """→ True/False/None。★ 取不到就是 `None`,**不默认 False** ——

    「上游没说」和「上游说不允许」是两件事,折叠成一个值,UI 就没法把
    「不知道能不能用」和「确定用不了」分开(本仓贯穿始终的那条铁律)。
    """
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def _codex_credits(h, num):
    """订阅之外的付费余额。→ dict,一个字段都没有时 None(而不是空壳)。

    ★ `unlimited` 为真时 `balance` 没有意义(上游可能回 0 或干脆不发)。
      调用方**不许**在 unlimited 时把 balance 画成"余额为 0" —— 那正是把
      「不适用」显示成「用光了」。
    """
    out = {
        "balance": num("x-codex-credits-balance"),
        "has_credits": _codex_bool(h.get("x-codex-credits-has-credits")),
        "unlimited": _codex_bool(h.get("x-codex-credits-unlimited")),
    }
    return out if any(v is not None for v in out.values()) else None


def _codex_additional(h):
    """具名附加限额 → {短名: {primary/secondary: {...}, "limit_name": str}},没有则 None。

    ★★ **`bengalfox` 就是这一族。** 本仓 v0.12.9 那次「Pro 号上冒出 5h 窗口」正是
    这类具名限额被混进了 primary/secondary 主窗口。所以它们在这里**单独成键**,
    绝不并入 `primary`/`secondary` —— 主窗口是套餐的,具名限额是某个模型的,
    混在一起会让 UI 画出一个该账号根本没有的窗口。
    """
    out = {}
    for k, v in h.items():
        m = _ADDL_RE.match(k)
        if not m:
            continue
        name = m.group("name")
        # `code-review` 是官方的具名限额,与 bengalfox 同族,一起收。
        if name in out or len(out) < _MAX_ADDL:
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            slot = out.setdefault(name, {})
            slot.setdefault(m.group("win"), {})[m.group("field").replace("-", "_")] = val
    for k, v in h.items():
        m = re.match(r"^x-codex-([a-z0-9][a-z0-9-]*?)-limit-name$", k)
        if m and m.group(1) in out:
            s = str(v)
            # 上游控制的文本会进 state.json 并被日志/UI 读到,控制字符一律丢弃。
            printable = all(0x20 <= ord(c) and ord(c) != 0x7F for c in s)
            if s and printable and len(s) <= 64:
                out[m.group(1)]["limit_name"] = s
    return out or None


# 上一次见到的 `x-codex-*` 头名集合。★ 只在**集合变化时**记一行 —— 每请求一行会把
# proxy.log 淹掉(现已 67k 行),而变化点才是有信息量的那一刻。
_seen_codex_hdrs = set()


def _log_codex_header_set(h):
    """服务端**实际发了哪些** `x-codex-*` 头,集合一变就记一行。

    ★★ 这条存在的理由是本仓记了很久的一笔债:`proxy.log` 对额度写入**零留痕**,
    于是事后无法回答「当时到底写进去了什么」。更要命的是它让另一个问题也无解 ——
    某个字段读不到时,**分不清是「服务端没发」还是「我的解析没打中」**,
    而这两者在本仓是必须分开的两件事。
    记下来之后,下次只要看一眼日志就能判定,不用再猜。
    """
    global _seen_codex_hdrs
    names = {k for k in h if k.startswith("x-codex-")}
    if names and names != _seen_codex_hdrs:
        added = sorted(names - _seen_codex_hdrs)
        gone = sorted(_seen_codex_hdrs - names)
        _seen_codex_hdrs = names
        _plog("x-codex 头集合变化 +{} -{} (共{})".format(added or "无", gone or "无", len(names)))


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
    # ★ 放在下面那个早退**之前** —— 没有窗口头的响应同样值得记:
    #   「这次一个 x-codex 头都没有」本身就是要回答的问题之一。
    _log_codex_header_set(h)

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
    # ★★ **代理独有的那些头单独成键,不并进 `quota`** —— 这是实测逼出来的结构(2026-09-05)。
    #    第一版把它们塞进 `q`,真机上活不过几分钟:`quota_daemon` 走 `/backend-api/codex/usage`
    #    **整体替换** `slot["quota"]`(codex-rotate:1321),而那条路径拿不到这些响应头,
    #    于是每轮轮询都把它们抹掉。测试全绿、字段也确实写进去了 —— 只是转瞬即逝。
    #
    #    两条来源就该是两个对象,各带自己的时间戳:
    #      · `quota`         窗口水位,proxy 与 usage-api 都能给,谁新用谁;
    #      · `codex_headers` **只有代理路径能看到**的响应头,usage-api 不覆盖它。
    #    合并是不行的:`captured_at` 挂在对象上,混源会让陈旧值蹭到新时间戳被认成现值 ——
    #    与 agy 那两本账不可相加是同一条理由。
    #
    #    ⚠️ **命名避让**:`slot["credits"]` 已被 usage-api 占用,存的是 `rate_limit_reset_credits`
    #    (重置限流用的额度数);这里的 `credits_balance` 是**付费余额**,完全不同的东西。
    #    同名会让两个概念在 UI 上混成一个,所以这里刻意不叫 credits。
    extra = {
        "active_limit": h.get("x-codex-active-limit"),
        "credits_balance": _codex_credits(h, num),
        # 布尔三态:上游明说「这次允许/已触顶」。与 used_percent 是两回事 ——
        # 100% 已用不等于被拒,limit_reached 是上游的结论而不是我们的推断。
        # 实测(2026-09-05):本机这几个号的响应里**根本没有**这两个头,所以恒 None。
        "allowed": _codex_bool(h.get("x-codex-allowed")),
        "limit_reached": _codex_bool(h.get("x-codex-limit-reached")),
        # 具名附加限额(`x-codex-bengalfox-*` 那一族)+ code-review。实测本机也没有。
        "additional": _codex_additional(h),
        # ★ 相对重置秒数。与 `resets_at` **性质不同**:后者是绝对纪元、依赖两边对"现在"的共识,
        #   时钟一偏就错;前者免疫。本仓在"窗口是否已重置"上栽过(v0.12.9),两个量并存可互校:
        #   `resets_at - captured_at` 与它大幅不符 = 有一边不可信。
        #   ⚠️ 目前**只采集不判定** —— 没有跨时钟样本前,不拿它去改选号逻辑。
        "primary_reset_after_seconds": num("x-codex-primary-reset-after-seconds"),
        "secondary_reset_after_seconds": num("x-codex-secondary-reset-after-seconds"),
        # 服务端算好的两窗口关系,我们原来只能自己推。
        "primary_over_secondary_limit_percent": num("x-codex-primary-over-secondary-limit-percent"),
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
                # 同样只在 2xx 替换:非 2xx 可能只带一部分头,整体替换会把已知的写成 null。
                s["slots"][aid]["codex_headers"] = extra
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

    def _open(self, body, token, account_id, label, reason, prev_id, rid=None, up=None):
        """Send the request upstream under one account's token; return (conn, resp). Caller closes conn.

        两阶段分开抛异常,让调用方**无法**再把「没送出去」和「送出去了但没读到回应」当成一回事。

        ★ `up` = 中转站上游描述（见 `_relay_upstream`）。给了就换 host/base/鉴权，
          **并且必须去掉 `chatgpt-account-id`** —— 那是 ChatGPT 订阅端点的私有头，
          原样发给第三方中转站等于把本机账号 id 泄露给一个无关服务。"""
        host = up["host"] if up else UPSTREAM_HOST
        port = up["port"] if up else 443
        path = (up["base"] if up else UPSTREAM_BASE) + self.path
        skip = {"host", "authorization", "chatgpt-account-id", "content-length", "connection"}
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in skip}
        hdrs["Authorization"] = f"Bearer {token}"
        if account_id and not up:
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
            conn = http.client.HTTPSConnection(host, port,
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

    def _open_or_fail(self, body, token, account_id, label, reason, prev_id, rid=None, up=None):
        """包住 _open,把结局压成 (conn, resp) | "NEXT" | "ABORT"。

        返回 "ABORT" 时**响应已经发出去了**,调用方只需 `return`。

        ★ 两个调用点(首发 + 401 强刷后重发)必须共用这段。评审在初版里抓到:我只改了首发那个,
        401 那条仍是 bare `except Exception: continue` —— 同一个双计费 bug 原封不动地活着。

        ⚠️ 中转站档下 `"NEXT"` **没有下一个可试** —— 那一档只有一个上游。调用方
        (`_proxy_relay`)必须把 `"NEXT"` 当成终局，不能像账号池那样继续循环。"""
        try:
            return self._open(body, token, account_id, label, reason, prev_id, rid, up=up)
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
        """Relay the chosen upstream response back to codex, recording quota + session affinity.

        ★ `aid=None` = 中转站档。**不记额度、不记粘性** —— 中转站不回 ChatGPT 的额度头，
          硬记会把一个账号的额度写成中转站的响应；而粘性在只有一个上游时没有意义。
          把它们做成 `if aid:` 而不是"反正写进去也没人看"，因为额度账本是被 UI 直接消费的。"""
        if aid:
            _record_quota(aid, resp.getheaders(), resp.status)
        # ★ 只在**真正成功服务过**之后才登记会话归属 —— 挑中但 401/429 失败的号不该被粘住。
        conv = getattr(self, "_conv_key", None)
        if conv and aid:
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
            # ★ `aid` 为空(中转站档)时整段跳过:粘性表存 `None` 会让 `_pick` 把
            #   "没有归属"读成"归属于一个叫 None 的号"。跳过后 scanbuf 也不再增长。
            if aid and not got:
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
        # ★★ 路由分叉。中转站档走一条**完全独立**的路径，不碰账号池的任何机制
        #    (挑号 / failover / OAuth 刷新 / dead 标记 / 冷却 / 额度记账)。
        #    合流写在一个循环里试过一次就该知道不行：那些机制的每一条都以
        #    "还有别的号可以换"为前提，而中转站档只有一个上游。
        up = _relay_upstream()
        if up is not None:
            return self._proxy_relay(body, up, rid)
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

    def _proxy_relay(self, body, up, rid):
        """中转站档的转发：**单上游、零 failover**。

        ★ 与账号池档的根本区别：那边"换个号重试"既免费又正确，这边**没有第二个上游** ——
          `"NEXT"`（可证明未送达、未计费）只能变成一个错误码，绝不能变成重试循环。

        ★★ **401 在这里不是"号死了"。** 它是 key 无效或余额耗尽。所以这条路径
          绝不 `_mark_dead`、绝不 `_cool`、绝不碰 `auth.json`、绝不刷任何 token ——
          账号池与中转站是两套互不相干的凭证。（Fable 复核在 `env_key` 那版抓到过同形状的真 bug：
          中转站回 401 会让 codex 去刷账号池当值号的 refresh_token 并喊"log out and sign in
          again"，而 `codex logout` 在本仓是**杀号**操作。）

        ★ 同理**不把 401 原样转给 codex**：本仓既有不变量是"401 永不出现在 codex 面前"
          （账号池档也从不转发它，全部内部消化）。转过去会触发 codex 的重新登录流程，
          而那正是上面那条要防的事。改回一个不可重试的 400 + 一句人话。
        """
        label = up["label"]
        conn = None
        streamed = False
        try:
            got = self._open_or_fail(body, up["key"], None, label, "relay", None, rid, up=up)
            if got == "ABORT":
                return                      # 响应已由 _abort() 发出
            if got == "NEXT":
                # 可证明未送达 ⇒ 未计费。但没有下一个上游可试，如实回错而不是静默换回账号池
                # ——"以为在用中转站、其实扣的是订阅额度"是这条链路最不该出现的谎。
                _plog(f"relay send failed [{label}] — 无第二上游可切", rid)
                try:
                    self.send_error(502, "relay upstream unreachable")
                except Exception:
                    pass
                return
            conn, resp = got
            if resp.status == 401:
                _plog(f"relay 401 [{label}] — key 无效或余额耗尽（**未触碰账号池凭证**）", rid)
                try:
                    self.send_error(self.ABORT_STATUS,
                                    "relay rejected the API key (401): check the key or the balance "
                                    "on the relay page; the account pool was NOT touched")
                except Exception:
                    pass
                return
            streamed = True
            self._finish(conn, resp, None, label)
            return
        except Exception as e:
            if self._billable():
                # ★★ **中转站泳道用自己的计数器**（2026-09-10 改）。
                #    `stream_aborts` / `committed_aborts` 的**存在理由**是量化账号池那条
                #    路径上的**双计费**风险：那条路有 failover，一次断流之后可能重试到
                #    另一个号，于是同一次生成被两个号各计一次费。
                #    中转站这条路**没有 failover**（单上游、`"NEXT"` 是终态），
                #    一次断流的含义完全不同：钱已经从余额扣了、不会再扣第二次。
                #    混进同一个键有两个后果，都不出声：
                #      ① 账号池的双计费指标被中转站的噪音稀释，"这个月发生了多少次"不再可信；
                #      ② 中转站自己的失败率没有任何地方汇总。
                #    ⚠️ 键名带 `relay_` 前缀，**不要**改成嵌套结构 —— `state.json` 的
                #      `proxy_counters` 是扁平表，嵌套会让既有读者拿到 dict 而不是 int。
                _bump("relay_stream_aborts")
            _plog(f"relay stream err [{label}]: {e}", rid)
            if not streamed:
                try:
                    if self._billable():
                        self.send_error(self.ABORT_STATUS,
                                        "relay failed; not retried to avoid double-billing")
                    else:
                        self.send_error(502, "relay failed")
                except Exception:
                    pass
            return
        finally:
            if conn is not None:
                conn.close()

    def do_POST(self):
        self._proxy()

    def do_GET(self):
        self._proxy()


if __name__ == "__main__":
    # ★★ **数据目录先落地、并印出来**（2026-09-10 四方评审）。
    #    自从 STORE 认了 `CODEX_ROTATE_STORE`，一个写错的值会被**照单全收** ——
    #    而本文件是全仓唯一从不 mkdir 的入口（`relay/store.py` 和 `codex-rotate` 都建）。
    #    不建的话第一次写 state 才炸 FileNotFoundError，而它落在 handler 线程里，
    #    `_mutate_state` 的 `except (OSError, ValueError): return` 会把它咽掉 ——
    #    症状变成「池子是空的」，指不到真因。
    #    印出来是因为：这个进程可能连着好几天，事后想知道它当时在哪个目录上跑，
    #    除了日志没有第二个来源。
    try:
        STORE.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _plog(f"⛔ 数据目录建不出来 {STORE}: {e}")
        raise SystemExit(78)
    _plog(f"store={STORE}" + ("" if os.environ.get("CODEX_ROTATE_STORE")
                              else " (按 __file__ 推算 —— 没有 CODEX_ROTATE_STORE)"))
    if not STATE.exists():
        # ★ 「state.json 不在」与「池子里没有号」必须分开。后者是合法状态，前者是装错了。
        #   服务化跑法下 launchd/schtasks 会重拉，理由留在日志里。
        _plog(f"⛔ state.json 不存在: {STATE} —— 数据目录多半指错了，拒绝以空池提供服务")
        raise SystemExit(78)
    # ★ 起手就把**当前路由**印出来。这个进程可能连着好几天，而"钱扣在哪里"是排查时
    #   第一个要回答的问题 —— 只印一个写死的 chatgpt.com 会让日志在中转站档下说谎。
    _up0 = _relay_upstream()
    _dest = (f"https://{_up0['host']}{_up0['base']} (中转站 {_up0['id']} · 按量付费)"
             if _up0 else f"https://{UPSTREAM_HOST}{UPSTREAM_BASE} (账号池轮换)")
    _plog(f"rotating proxy on 127.0.0.1:{PORT} → {_dest}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
