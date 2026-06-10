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
REFRESH_LOCK = STORE / ".refresh.lock"   # cross-process: shared with codex-rotate keepalive/manual refresh

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
    prevents lost updates; the UNIQUE mkstemp temp keeps even cross-process writes from sharing a path."""
    with _state_lock:
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


def _exp(jwt):
    try:
        p = jwt.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
    except Exception:
        return 0


def _slot_token(aid, slot, force=False):
    """Return a FRESH access_token (+account_id), OAuth-refreshing if expired (or force=True, used on a
    401 to retry with a brand-new token). The ACTIVE account is read/written via the live
    ~/.codex/auth.json (shared with plain codex) so a refresh here never leaves codex's live copy stale
    (avoids 'session ended' divergence). Inactive → slot file."""
    use_live = (aid == _load(STATE).get("active") and LIVE.exists()
                and (_load(LIVE).get("tokens") or {}).get("account_id") == aid)
    sf = LIVE if use_live else (AUTH_DIR / slot["file"])
    tok = (_load(sf).get("tokens") or {})
    if not force and _exp(tok.get("access_token", "")) - time.time() > 60:
        return tok.get("access_token", ""), tok.get("account_id")
    # token expired → refresh under BOTH an in-process lock (proxy threads) and a cross-process file
    # lock (codex-rotate keepalive/manual refresh), each with a re-check: the refresh_token is
    # single-use, so any two refreshers racing the SAME account invalidate it = dead account.
    with _refresh_lock, open(REFRESH_LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
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
            tmp = sf.with_suffix(".tmp")
            tmp.write_text(json.dumps(auth))
            os.chmod(tmp, 0o600)
            os.replace(tmp, sf)
            sys.stderr.write(f"[proxy] refreshed {slot.get('label')} via {'live' if use_live else 'slot'}\n")
            return d["access_token"], tok.get("account_id")
        return at, tok.get("account_id")


def _used(slot):
    p = (slot.get("quota") or {}).get("primary") or {}
    ra = p.get("resets_at")
    if ra and ra <= time.time():
        return 0  # 5h window already reset → full headroom; prefer this account in _pick
    u = p.get("used_percent")
    return u if u is not None else 0


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
            until = time.time() + minutes * 60
            ra = ((sl.get("quota") or {}).get("primary") or {}).get("resets_at")
            if ra:
                until = min(until, ra + 60)  # never cool past the real 5h-window reset (was: fixed 300m)
            sl["cooling_until"] = until
    _mutate_state(f)


def _mark_dead(aid):
    """Flag an account whose token the server rejected even after a forced refresh (token invalidated /
    session terminated) so the picker skips it until the user re-logs in (\\codex login → autosync
    writes a fresh token and clears the flag)."""
    def f(s):
        if aid in s.get("slots", {}):
            s["slots"][aid]["auth_dead"] = True
            s["slots"][aid]["auth_dead_at"] = time.time()
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _open(self, body, token, account_id, label, reason, prev_id):
        """Send the request upstream under one account's token; return (conn, resp). Caller closes conn."""
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
        conn = http.client.HTTPSConnection(UPSTREAM_HOST, 443,
                                           context=ssl.create_default_context(), timeout=180)
        conn.request(self.command, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        sys.stderr.write(f"[proxy] ← {resp.status} [{label}]\n")
        sys.stderr.flush()
        return conn, resp

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
        # next; first usable account wins. One dead/exhausted account never blocks the whole request.
        tried = set()
        pool_n = len(_load(STATE).get("slots", {}))
        for _ in range(max(1, pool_n)):
            aid, slot, reason = _pick(prev_id, exclude=tried)
            if not aid:
                self.send_error(503, "no usable accounts in pool (all dead or excluded)")
                return
            tried.add(aid)
            label = slot.get("label", aid[:6])
            token, account_id = _slot_token(aid, slot)
            conn = None
            try:
                conn, resp = self._open(body, token, account_id, label, reason, prev_id)
                if resp.status == 401:
                    conn.close()  # stored token rejected → one forced refresh, retry SAME account once
                    conn = None
                    token2, account_id2 = _slot_token(aid, slot, force=True)
                    if token2 and token2 != token:
                        conn, resp = self._open(body, token2, account_id2, label, "retry-refresh", prev_id)
                        if resp.status != 401:
                            self._finish(conn, resp, aid, label)
                            return
                    _mark_dead(aid)
                    sys.stderr.write(f"[proxy] 401 invalidated → marked dead [{label}], failing over\n")
                    continue
                if resp.status == 429:
                    _record_quota(aid, resp.getheaders())
                    _cool(aid)
                    sys.stderr.write(f"[proxy] 429 → cooled [{label}] 300m, failing over\n")
                    continue
                self._finish(conn, resp, aid, label)
                return
            except Exception as e:
                sys.stderr.write(f"[proxy] upstream err [{label}]: {e}\n")
                try:
                    self.send_error(502, str(e))
                except Exception:
                    pass
                return
            finally:
                if conn is not None:
                    conn.close()
        try:
            self.send_error(503, "all accounts rate-limited or dead — re-login a dead one: \\codex login")
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
