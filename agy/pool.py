"""Antigravity(agy) 账号池 —— 凭证、额度、选号。

## 为什么是独立的一池，不并进 `state.json` 的 `slots`

★★★ `slots` 里的**每一个 key 都会被 codex 的刷新器遍历**（`_pick` / `cmd_keepalive` /
  `cmd_refresh_all`），而 `cmd_keepalive` 就是拿 `refresh_token` 去打 OpenAI 的端点。
  把 Google 的凭证放进去 = 进了那台刷新器的射程。本仓对 grok 的处置是同一条理由
  （见 `.claude/rules/traffic.md`：「不进 `state.json` 的 `slots`，走独立 sidecar」）。

## 与 codex 池的**结构性**差异（决定了整套机制长什么样）

| | codex | agy |
|---|---|---|
| 请求路径 | 经本地代理 → **每请求**都能换号 | CLI 直连 Google，**没有代理** |
| 换号时机 | 代理里挑 | **启动前**换凭证文件 —— agy 只在启动时读它 |
| 额度来源 | 免费 GET `/usage`，每账号 | `fetchAvailableModels`，每账号（本文件） |
| 计费探针 | 需要（5h 窗口**用过才锚定**） | **不需要**：额度是 `remainingFraction`，随时可读 |

★ 「运行中换文件对已开的会话无效」是**设计事实不是缺陷**，文案与行为都要按它来：
  自动切只承诺「下一次启动 agy 生效」，不承诺打断当前会话。

## 实测记录（2026-09-13，全部可复现）

- `POST https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels`
  带 `Authorization: Bearer <该账号 access_token>` + 下面那三个头 → **200**，
  27 个模型各带 `quotaInfo{remainingFraction, resetTime}`，聚成 3 组
  （gemini 一组、claude 一组、`tab_*` 那类无 `resetTime` 的一组）。
- ★★ **那三个头是必需的**：只带 Bearer → **403**。第一次探测时我既用了过期 token
  又没带头，拿到 401 —— 差一点写下「拿不到」这个错结论。
- ★★ **刷新 access_token 不会轮换 refresh_token**（返回里没有 `refresh_token` 字段）⇒
  我们刷新**不会**作废 agy 自己那份。这一条必须实测：本仓对 grok 的铁律正好相反
  （「绝不刷，它单次有效」），两家行为是反的，照搬任何一边都会出事。
- 第二个额度池（gemini-cli 头）→ **403**，上游要先 `loadCodeAssist` 拿 `projectId`。
  这是「还没打通」不是「不存在」—— 别把它记成后者。

## ★★★ OAuth client 从**本机 agy 二进制**里现取，绝不写进仓库

  刷新 token 需要 agy 那套 client_id + client_secret。它们**本来就印在用户机器上**
  （`~/.local/bin/agy`，实测各找到 1 个），而这个仓库是公开的 —— 把 secret 提交进来
  既是泄漏，也让仓库看起来在分发凭证。提交时 `secrets-scan` 钩子直接拦下了第一版，
  那一拦是对的。
  现取的额外好处：agy 自动更新换了 client 也能自愈；代价是要扫一遍 180MB，
  所以按 `(mtime_ns, size)` 缓存进**已 gitignore** 的池文件。
"""
import json
import os
import re
import time
import urllib.parse
from http.client import HTTPSConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: agy 自己的登录态。**这是用户唯一的凭证，写它必须原子且先备份** ——
#: 写坏 = 用户要重新走一遍浏览器登录。
LIVE = Path(os.environ.get(
    "AGY_TOKEN_FILE", str(Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token")))

#: 池的落点。`AGY_POOL_STORE` 让测试整体换目录（同 `CODEX_ROTATE_STORE` 的角色）。
STORE = Path(os.environ.get("AGY_POOL_STORE", str(ROOT)))
POOL = STORE / ".agy-pool.json"
CRED_DIR = STORE / "auth" / "agy"

#: agy 真身。wrapper 在 PATH 更前面，所以这里不能用 `which agy`。
AGY_BIN = Path(os.environ.get("AGY_REAL", str(Path.home() / ".local" / "bin" / "agy")))

TOKEN_HOST, TOKEN_PATH = "oauth2.googleapis.com", "/token"
API_HOST = "cloudcode-pa.googleapis.com"
MODELS_PATH = "/v1internal:fetchAvailableModels"
#: ★★ 这三个头是**必需**的，不是装饰：只带 Bearer 会 403（2026-09-13 实测）。
ANTIGRAVITY_HEADERS = {
    "User-Agent": "antigravity/1.11.5 windows/amd64",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
}
TIMEOUT = 25

#: 低于这个剩余比例就该换号（自动切的阈值）。
#: 0.15 而不是 0：额度是**滚动窗口**，跌到 0 才换意味着那一次请求已经被拒了。
LOW_WATER = float(os.environ.get("AGY_LOW_WATER", "0.15"))

_CID_RE = re.compile(rb"[0-9]{10,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com")
#: ★★ **定长 28，不能写 `{20,40}`。** agy 的二进制里两个 secret 是**首尾相连、无分隔符**
#:   存放的（实测 `…qDAfGOCSPX-9YQ…`），贪婪匹配会把它俩粘成一个 47 字符的串，
#:   拿去刷新得到 `invalid_client` —— 而那个报错与「凭证坏了」长得一模一样。
_SEC_RE = re.compile(rb"GOCSPX-[A-Za-z0-9_\-]{28}")


# ── 状态读写 ──────────────────────────────────────────────────────────
def _lock(path):
    """跨进程写锁。★ **fail-open**：拿不到锁就照常写下去。
    与 `quota_anchors._ledger_lock` 同一条理由 —— 丢一次更新远好过把调用方卡死。"""
    try:
        import fcntl
    except ModuleNotFoundError:                      # Windows
        import sys
        sys.path.insert(0, str(ROOT))
        import portalock as fcntl                    # noqa: N813

    class _L:
        def __enter__(self):
            self.fh = None
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                self.fh = open(str(path) + ".lock", "a+")
                fcntl.flock(self.fh, fcntl.LOCK_EX)
            except Exception:                        # noqa: BLE001
                self.fh = None
            return self

        def __exit__(self, *a):
            if self.fh is not None:
                try:
                    self.fh.close()
                except Exception:                    # noqa: BLE001
                    pass
            return False
    return _L()


def load():
    """→ `{"accounts": {sub: {...}}, ...}`。读不到/坏了一律返回空池，**不抛**。"""
    try:
        with open(POOL, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("accounts"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"accounts": {}}


def save(pool):
    """原子落盘。★ 带 pid 的临时名：多个进程可能同时写，共用一个临时名会互相截断。"""
    POOL.parent.mkdir(parents=True, exist_ok=True)
    tmp = "%s.tmp%d" % (POOL, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(pool, ensure_ascii=False, indent=1))
    os.replace(tmp, POOL)


# ── OAuth client（现取 + 缓存） ────────────────────────────────────────
def _bin_sig():
    try:
        st = AGY_BIN.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return ""


def oauth_candidates(pool=None):
    """→ (候选 `[(client_id, secret), …]`, 错误说明)。从本机 agy 二进制里现取。

    ★★ **不按出现顺序配对，返回所有组合让调用方逐对试。** 实测 agy 二进制里有
      2 个 client_id 和 2 个 secret，而能用的那一对是**交叉**的（按顺序配会 `invalid_client`）。
      "位置相邻/顺序相同"是个看起来很合理的假设，它在这里是错的；
      而错了的症状是 401，与「凭证坏了」长得一模一样。
    ★ 已验证过的那一对缓存在池里，键是二进制的 `(mtime_ns, size)` ——
      agy **自带自动更新**，换了二进制就要重试。用 `mtime_ns` 不是 `int(mtime)`：
      本仓在秒级签名上栽过（同一秒内改写判不出来）。
    """
    pool = load() if pool is None else pool
    sig = _bin_sig()
    if not sig:
        return [], "找不到 agy 二进制（%s）—— 装了 agy 才能刷新凭证" % AGY_BIN
    c = pool.get("oauth_client") or {}
    cached = [(c["id"], c["secret"])] if (c.get("sig") == sig and c.get("id") and c.get("secret")) else []
    try:
        blob = AGY_BIN.read_bytes()
    except OSError as e:
        return cached, ("" if cached else "读不了 agy 二进制: %s" % e)
    ids = [x.decode() for x in dict.fromkeys(_CID_RE.findall(blob))]
    secs = [x.decode() for x in dict.fromkeys(_SEC_RE.findall(blob))]
    if not ids or not secs:
        return cached, ("" if cached else "agy 二进制里没找到 OAuth client（agy 换实现了？）")
    # 当前登录态的 `aud` 排最前 —— 它多半就是对的，能让第一次就命中。
    aud = (claims(read_live()) or {}).get("aud") or ""
    ids.sort(key=lambda i: 0 if i == aud else 1)
    out = list(cached)
    for i in ids:
        for s in secs:
            if (i, s) not in out:
                out.append((i, s))
    return out, ""


def remember_client(pool, cid, secret):
    """把**验证成功**的那一对记下来，下次直接用。"""
    pool["oauth_client"] = {"sig": _bin_sig(), "id": cid, "secret": secret}


# ── 凭证 ──────────────────────────────────────────────────────────────
def claims(cred):
    """从 `id_token` 里解出 `{sub, email, aud, exp}`。★ **只解不验签** ——
    我们不是在鉴权，只是要一个稳定的账号身份；签名由 Google 在用它的时候验。"""
    import base64
    idt = (cred or {}).get("id_token") or ""
    if idt.count(".") != 2:
        return {}
    p = idt.split(".")[1]
    p += "=" * (-len(p) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:                                # noqa: BLE001
        return {}


def read_live():
    """当前 agy 登录态。读不到返回 None。"""
    try:
        with open(LIVE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def cred_path(sub):
    return CRED_DIR / ("%s.json" % sub)


def read_cred(sub):
    try:
        with open(cred_path(sub), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_cred(sub, cred):
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    p = cred_path(sub)
    tmp = "%s.tmp%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(cred, ensure_ascii=False))
    os.chmod(tmp, 0o600)        # 与 agy 自己那份同权限
    os.replace(tmp, p)


def install_live(cred):
    """把某个号的凭证装回 agy 的登录态。

    ★★★ **先备份再原子替换。** 这是用户唯一的 agy 登录凭证 ——
      写坏的代价是重新走一遍浏览器 OAuth，而那不是我们能替他做的。
      `os.replace` 保证读者要么看到旧的、要么看到新的，不会看到半截。
    """
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    if LIVE.exists():
        try:
            bak = Path(str(LIVE) + ".codexbar-bak")
            bak.write_bytes(LIVE.read_bytes())
            os.chmod(bak, 0o600)
        except OSError:
            pass                # 备份失败不挡换号，但下面的写仍是原子的
    tmp = "%s.tmp%d" % (LIVE, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(cred, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    os.replace(tmp, LIVE)


# ── token 刷新 ────────────────────────────────────────────────────────
def refresh(cred, pool=None):
    """用 `refresh_token` 换一个新的 `access_token` -> (新 cred, 错误说明)。

    ★★ **Google 默认不轮换 refresh_token**（2026-09-13 实测：响应里没有 `refresh_token`），
      所以刷新我们池里的凭证**不会**作废 agy 自己那份。
      ⚠️ 这一条与本仓对 grok 的铁律**正好相反**（grok 的 refresh_token 单次有效，
      一刷就把 grok CLI 手里那份作废）。两家行为是反的，照搬任何一边都会出事 ——
      所以这里写的是「实测过的 Google 行为」，不是「刷新一般是安全的」。
    """
    rt = ((cred or {}).get("token") or {}).get("refresh_token")
    if not rt:
        return None, "凭证里没有 refresh_token"
    pool = load() if pool is None else pool
    cands, err = oauth_candidates(pool)
    if err:
        return None, err
    j, status, last = None, 0, ""
    for cid, sec in cands:
        body = urllib.parse.urlencode({
            "client_id": cid, "client_secret": sec,
            "refresh_token": rt, "grant_type": "refresh_token"})
        try:
            c = HTTPSConnection(TOKEN_HOST, timeout=TIMEOUT)
            c.request("POST", TOKEN_PATH, body=body,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
            r = c.getresponse()
            j = json.loads(r.read())
            status = r.status
            c.close()
        except Exception as e:                        # noqa: BLE001
            return None, "刷新失败: %s" % e
        if status == 200 and j.get("access_token"):
            remember_client(pool, cid, sec)
            break
        last = "HTTP %s: %s" % (status, str(j)[:100])
        # ★ 只有「这对 client 不对」才值得换一对再试。凭证本身失效（invalid_grant）
        #   换几对都一样，继续试只是把同一个错误问四遍。
        if j.get("error") != "invalid_client":
            return None, "刷新 %s" % last
    else:
        return None, "刷新失败（试完 %d 对 client 都不行）：%s" % (len(cands), last)
    out = json.loads(json.dumps(cred))                # 深拷贝，不就地改调用方的对象
    out.setdefault("token", {})["access_token"] = j["access_token"]
    # ★ 只有响应真带了新的才覆盖 —— 没带就说明没轮换，原样保留。
    if j.get("refresh_token"):
        out["token"]["refresh_token"] = j["refresh_token"]
    if j.get("id_token"):
        out["id_token"] = j["id_token"]
    exp = int(time.time()) + int(j.get("expires_in") or 3600)
    out["token"]["expiry"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(exp))
    out["_expiry_epoch"] = exp                        # 我们自己用的，agy 不看
    return out, ""


def expired(cred, skew=120):
    """access_token 是不是（快）过期了。★ 留 120s 余量：卡着过期时刻用会拿到 401，
    而那个 401 与「凭证坏了」长得一模一样。"""
    e = (cred or {}).get("_expiry_epoch")
    if isinstance(e, (int, float)):
        return time.time() + skew >= e
    s = ((cred or {}).get("token") or {}).get("expiry") or ""
    try:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).timestamp() + skew >= \
            datetime.datetime.fromisoformat(s).timestamp()
    except Exception:                                # noqa: BLE001
        return True                                   # 判不出就当过期 —— 刷新是零成本的


# ── 额度 ──────────────────────────────────────────────────────────────
def fetch_quota(access_token):
    """-> (`{"gemini"|"claude": {remaining, reset, models:[…]}}`, 错误说明)。

    ★ 分组判据是 **(remainingFraction, resetTime) 这一对**，不是模型名：
      服务端不下发组名，而同一个池里的模型这两个值**逐字相同**。
      按模型名前缀猜分组会在下一次改名时静默错位。
    ★ 没有 `resetTime` 的那一组（`tab_*` 之类）**不是额度池，是不限量** ——
      把它算进"剩余最少"的比较里，选号会永远挑不中真正空闲的号。
    """
    try:
        c = HTTPSConnection(API_HOST, timeout=TIMEOUT)
        c.request("POST", MODELS_PATH, body="{}",
                  headers={"Authorization": "Bearer " + access_token,
                           "Content-Type": "application/json", **ANTIGRAVITY_HEADERS})
        r = c.getresponse()
        raw = r.read()
        c.close()
    except Exception as e:                            # noqa: BLE001
        return None, "取额度失败: %s" % e
    if r.status != 200:
        return None, "额度 HTTP %s: %s" % (r.status, raw[:120].decode("utf-8", "replace"))
    try:
        models = (json.loads(raw).get("models") or {})
    except ValueError:
        return None, "额度响应不是 JSON"
    buckets = {}
    for name, m in models.items():
        q = (m or {}).get("quotaInfo") if isinstance(m, dict) else None
        if not q or q.get("resetTime") is None:
            continue
        k = "%s|%s" % (q.get("remainingFraction"), q.get("resetTime"))
        b = buckets.setdefault(k, {"remaining": q.get("remainingFraction"),
                                   "reset": q.get("resetTime"), "models": []})
        b["models"].append(name)
    # ★ 成员最多的那组是 gemini（实测 20 vs 3）。**按成员数判，不按模型名** ——
    #   模型名每隔几周就换一批，而"哪一组更大"是结构性的。
    ordered = sorted(buckets.values(), key=lambda b: -len(b["models"]))
    names = ["gemini", "claude", "other"]
    return {names[i] if i < len(names) else "g%d" % i: b
            for i, b in enumerate(ordered)}, ""
