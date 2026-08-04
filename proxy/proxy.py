#!/usr/bin/env python3
"""Phase-1b rotating proxy for the Codex ChatGPT-subscription backend.

Codex (custom model_provider, base_url=http://127.0.0.1:PORT) → this proxy → chatgpt.com, with:
  • pool-based account selection (least-used 5h quota, skip cooling) from codex-rotate slots
  • session affinity: previous_response_id sticks the whole conversation to one account (solves the
    cross-account context break); only NEW conversations pick a fresh account
  • on-expiry OAuth refresh of the selected account's token (reuses the proven refresh flow)
  • 429 → mark the account cooling in state.json
stdlib-only; streams the SSE response back close-delimited.
"""
import base64
import datetime
import fcntl
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
            sys.stderr.write(f"[proxy] refresh {slot.get('label')} FAILED: {e}\n")
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
            sys.stderr.write(f"[proxy] refreshed {slot.get('label')} (slot)\n")
            return d["access_token"], tok.get("account_id")
        return at, tok.get("account_id")


def _win_used(slot, key):
    w = (slot.get("quota") or {}).get(key) or {}
    ra = w.get("resets_at")
    if ra and ra <= time.time():
        return 0  # window already reset → full headroom
    u = w.get("used_percent")
    return u if u is not None else 0


def _used(slot):
    """Sort key for _pick: primary (5h) first, weekly as tie-break. Without the weekly component, five
    accounts whose 5h windows all reset sort in dict-insertion order and every request lands on the
    first one — even if its weekly quota is nearly exhausted (observed: main at 9% weekly picked first)."""
    return (_win_used(slot, "primary"), _win_used(slot, "secondary"))


def _pick(prev_id, exclude=None):
    """(aid, slot, reason). Affinity: stick to prev_id's account; else least-used, skipping cooling,
    auth-dead, and already-tried (exclude) accounts."""
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
        if prev_id and prev_id in _affinity:
            aid = _affinity[prev_id]
            if aid in slots and ok(aid, slots[aid]):
                return aid, slots[aid], "affinity"
    avail = [(aid, sl) for aid, sl in slots.items() if ok(aid, sl)]
    if not avail:  # nothing cleanly available → relax cooling, but never a dead or already-tried one
        avail = [(aid, sl) for aid, sl in slots.items()
                 if aid not in exclude and not sl.get("auth_dead")]
    if not avail:
        return None, None, "exhausted"
    avail.sort(key=lambda kv: _used(kv[1]))
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


def _record_quota(aid, headers):
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
    def f(s):
        if aid in s.get("slots", {}):
            s["slots"][aid]["quota"] = q
            s["slots"][aid]["quota_status"] = "ok"
            s["last_aid"] = aid
            s["last_proxy_ts"] = time.time()  # lets codex-rotate/plugin tell "via cxp" from "plain codex"
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

    def _open(self, body, token, account_id, label, reason, prev_id):
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
        sys.stderr.write(f"[proxy] → {self.command} {self.path} [{label}] {reason}"
                         f" prev={prev_id[:18] if prev_id else '-'}\n")
        sys.stderr.flush()
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
        sys.stderr.write(f"[proxy] ← {resp.status} [{label}]\n")
        sys.stderr.flush()
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

    def _abort(self, label, exc):
        """计费请求已提交但读不到回应 → 终止本轮,绝不换号重发。响应体只给固定文案。

        单独成 helper 是因为评审指出:上一版把 send_error 那段在两个调用点手抄了一遍,
        "第三个调用点不可能退化"并没达成 —— 退化点只是从 except 块挪到了 if 块。"""
        _bump("committed_aborts")
        sys.stderr.write(f"[proxy] ⚠️ committed [{label}]: {exc} — 计费请求已送出,中止而非换号(防双计费)\n")
        sys.stderr.flush()
        try:
            # 不回显 str(exc):它含本地路径 / TLS / 系统错误文本,没有理由暴露给客户端。
            self.send_error(self.ABORT_STATUS,
                            "upstream committed but unreadable; not retried to avoid double-billing")
        except Exception:
            pass

    def _open_or_fail(self, body, token, account_id, label, reason, prev_id):
        """包住 _open,把结局压成 (conn, resp) | "NEXT" | "ABORT"。

        返回 "ABORT" 时**响应已经发出去了**,调用方只需 `return`。

        ★ 两个调用点(首发 + 401 强刷后重发)必须共用这段。评审在初版里抓到:我只改了首发那个,
        401 那条仍是 bare `except Exception: continue` —— 同一个双计费 bug 原封不动地活着。"""
        try:
            return self._open(body, token, account_id, label, reason, prev_id)
        except SendFailed as e:
            sys.stderr.write(f"[proxy] send err [{label}]: {e} — 未完整送达,安全换号\n")
            sys.stderr.flush()
            return "NEXT"
        except UpstreamCommitted as e:
            if not self._billable():
                sys.stderr.write(f"[proxy] committed [{label}] (非计费 {self.command}): {e} — 换号重试\n")
                sys.stderr.flush()
                return "NEXT"
            self._abort(label, e)
            return "ABORT"

    def _finish(self, conn, resp, aid, label):
        """Relay the chosen upstream response back to codex, recording quota + session affinity."""
        _record_quota(aid, resp.getheaders())
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
                    sys.stderr.write(f"[proxy] affinity {rid[:18]} → [{label}]\n")
                elif len(scanbuf) > 65536:
                    scanbuf = scanbuf[-4096:]

    def _proxy(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        prev_id = None
        if body:
            try:
                prev_id = json.loads(body).get("previous_response_id")
            except Exception:
                pass
        # failover loop: pick least-used → on 401 (dead token) mark dead + try next; on 429 cool + try
        # next; on a network error before any bytes reach codex, try next. First usable account wins.
        # One dead/exhausted/unreachable attempt never blocks the whole request.
        tried = set()
        pool_n = len(_load(STATE).get("slots", {}))
        for _ in range(max(1, pool_n)):
            aid, slot, reason = _pick(prev_id, exclude=tried)
            if not aid:
                break
            tried.add(aid)
            label = slot.get("label", aid[:6])
            token, account_id = _slot_token(aid, slot)
            if not token:
                sys.stderr.write(f"[proxy] skip [{label}]: live token expired (codex owns its refresh)\n")
                continue
            conn = None
            streamed = False
            try:
                got = self._open_or_fail(body, token, account_id, label, reason, prev_id)
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
                        got = self._open_or_fail(body, token2, account_id2, label, "retry-refresh", prev_id)
                        if got == "NEXT":
                            continue
                        if got == "ABORT":
                            return          # 响应已由 _abort() 发出
                        conn, resp = got
                        if resp.status == 429:
                            # 评审指出:强刷后拿到 429 原本被当成功直接转发,绕过了下面的冷却+换号,
                            # 该号不进冷却,codex 退避后大概率再次选中它。
                            _record_quota(aid, resp.getheaders())
                            _cool(aid)
                            sys.stderr.write(f"[proxy] 429 (retry-refresh) → cooled [{label}], failing over\n")
                            continue
                        if resp.status != 401:
                            streamed = True
                            self._finish(conn, resp, aid, label)
                            return
                    _mark_dead(aid, (token2 or token)[-16:])
                    sys.stderr.write(f"[proxy] 401 invalidated → marked dead [{label}], failing over\n")
                    continue
                if resp.status == 429:
                    _record_quota(aid, resp.getheaders())
                    _cool(aid)
                    sys.stderr.write(f"[proxy] 429 → cooled [{label}], failing over\n")
                    continue
                streamed = True
                self._finish(conn, resp, aid, label)
                return
            except Exception as e:
                # response already partially relayed (or client hung up) — a retry on another account
                # would double-send; abort. send_error only if no headers went out yet.
                # ★ 这是**频率最高**的一类双计费源(实测 542 次,其中 85 次紧跟客户端重试):上游已 200
                # 并计费,流却断了,codex 会把整轮重发到另一个号。代理侧无解(响应已部分转发,abort 是
                # 唯一正确动作),但必须可量化 —— 本 commit 声讨的正是"只留一行没人聚合的日志"。
                _bump("stream_aborts")
                sys.stderr.write(f"[proxy] stream err [{label}]: {e}\n")
                if not streamed:
                    try:
                        self.send_error(502, str(e))
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
    sys.stderr.write(f"[proxy] rotating proxy on 127.0.0.1:{PORT} → https://{UPSTREAM_HOST}{UPSTREAM_BASE}\n")
    sys.stderr.flush()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
