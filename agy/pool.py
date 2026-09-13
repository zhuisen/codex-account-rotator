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
import base64
import json
import os
import re
import subprocess
import time
import urllib.parse
from http.client import HTTPSConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: agy 登录态的**文件**落点。★★★ 这**不是**主存储，见下面 `KEYRING_SVC`。
#: **这是用户唯一的凭证，写它必须原子且先备份** —— 写坏 = 用户要重新走一遍浏览器登录。
LIVE = Path(os.environ.get(
    "AGY_TOKEN_FILE", str(Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token")))

#: ★★★ **agy 1.2.2 的真登录态在 macOS 钥匙串里，不在上面那个文件里。**（2026-09-13 实测）
#:
#: 用户报 `agy-rotate login` 走完浏览器登录、回来却说「读不到登录态」。查 agy 自己的日志：
#:
#:     auth.go:148]  ChainedAuth: authenticated via keyring (effective: keyring)
#:     keyring.go:64] keyringAuth: loaded token, expiry=…
#:     composite_token_storage.go:237] Failed to save token to keyring, falling back to file: exit status 45
#:
#: 最后那行是关键：文件只是**钥匙串写失败时的兜底**。本机之所以一直有那个文件，
#: 就是 09-13 11:23 发生过一次那种失败 —— 我们把兜底路径当成了主路径。
#:
#: ★★ **判别实验（已跑，别再推理）**：把 A 号写进文件、钥匙串里留 B 号，
#:   跑 `agy models` 看日志 ⇒ `applyAuthResult: email=B`。**文件被完全忽略。**
#:   也就是说在这之前 `agy-rotate switch` 一直是**静默空操作** ——
#:   它写的那份 agy 根本不读，而界面、日志、退出码全都显示成功。
#:   这正是本仓记了无数次的那一条：**写入侧的标志会撒谎，判据要由被作用对象自证**。
#:
#: go-keyring（agy 用的库）也是 shell 出 `/usr/bin/security`，所以我们用同一个命令读写，
#: 格式完全一致：`go-keyring-base64:` + base64(JSON)。
KEYRING_SVC = os.environ.get("AGY_KEYRING_SERVICE", "gemini")
KEYRING_ACCT = os.environ.get("AGY_KEYRING_ACCOUNT", "antigravity")
_KR_PREFIX = "go-keyring-base64:"

#: `AGY_KEYRING=0` 完全关掉钥匙串通路。**测试必须设它** —— 否则一条用例就能把
#: 用户真实的 agy 登录态覆盖掉（同 `CODEXBAR_QUOTA_ANCHORS` 那次事故的形状：
#: 夹具数据写进了真账本）。闸在 `tests/test_isolation_bootstrap.py`。
def _keyring_on():
    return os.environ.get("AGY_KEYRING", "1") != "0"

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
    idt = (cred or {}).get("id_token") or ""
    if idt.count(".") != 2:
        return {}
    p = idt.split(".")[1]
    p += "=" * (-len(p) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:                                # noqa: BLE001
        return {}


def keyring_read():
    """从钥匙串读 agy 的登录态。读不到/没装/被拒一律 None。"""
    if not _keyring_on():
        return None
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", KEYRING_SVC, "-a", KEYRING_ACCT, "-w"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    raw = (r.stdout or "").strip()
    if raw.startswith(_KR_PREFIX):
        try:
            raw = base64.b64decode(raw[len(_KR_PREFIX):]).decode("utf-8")
        except Exception:                            # noqa: BLE001
            return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def keyring_write(cred):
    """写回钥匙串。返回 **True 才表示真的写进去了** —— 调用方据此决定要不要走文件兜底。

    ★★★ **密文只能走 argv，stdin 那条路会静默截断到 128 字节。**（2026-09-13 实测）
      `security -w` 不带值时会在 TTY 上问两遍，喂两行也确实能写成功、退出码 0 ——
      但存进去的只有 **128 字节**（`readpassphrase` 的缓冲区），而我们的凭证约 2.2 KB。
      症状是 agy 报 `You are not logged into Antigravity`，**写入侧一切正常**：
      命令成功、退出码 0、读回来还有正确的 `go-keyring-base64:` 前缀。
      我第一版就是这么写的，当场把用户的登录态截没了（靠池里的备份复原）。
      这条正是本仓那句「写入侧标志会撒谎，判据要由被作用对象自证」的第二次实证 ——
      同一轮里踩了两次，第二次是我为了避开第一次的教训而引入的。

    ⚠️ **已知代价**：`refresh_token` 在这次调用期间对 `ps` 可见。没有别的路
      （`security` 只有 argv 与那个 128 字节的 prompt 两种入口），而 agy 自己用的
      go-keyring 也是 argv —— 我们没有扩大暴露面，只是没有缩小它。
    """
    if not _keyring_on():
        return False
    blob = _KR_PREFIX + base64.b64encode(
        json.dumps(cred, ensure_ascii=False).encode("utf-8")).decode("ascii")
    try:
        r = subprocess.run(
            ["security", "add-generic-password", "-U",
             "-s", KEYRING_SVC, "-a", KEYRING_ACCT, "-w", blob],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0:
        return False
    # ★★ **写完必须读回来核长度。** 上面那次截断的全部症状就是"写成功了"，
    #    只有把存进去的东西再取出来比一遍才发现得了。不核 = 把一个已经发生过的
    #    静默损坏留在原地。
    try:
        chk = subprocess.run(
            ["security", "find-generic-password", "-s", KEYRING_SVC, "-a", KEYRING_ACCT, "-w"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return chk.returncode == 0 and (chk.stdout or "").strip() == blob


def read_live():
    """当前 agy 登录态。读不到返回 None。

    ★★ **钥匙串优先，文件兜底** —— 与 agy 自己的 `ChainedAuth` 同序（实测 13/13 次
      日志都是 `effective: keyring`）。反过来读会在两边不一致时报出一个
      **agy 并不在用**的账号，而那看起来完全正常。
    """
    cred = keyring_read()
    if cred:
        return cred
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
    """把某个号的凭证装回 agy 的登录态。返回 `"keyring"` / `"file"` —— **落在哪儿**。

    ★★★ **先备份再原子替换。** 这是用户唯一的 agy 登录凭证 ——
      写坏的代价是重新走一遍浏览器 OAuth，而那不是我们能替他做的。
      `os.replace` 保证读者要么看到旧的、要么看到新的，不会看到半截。

    ★★★ **必须写钥匙串，只写文件等于什么都没做**（实测，见文件头 `KEYRING_SVC`）。
      返回值不是装饰：调用方要把"到底换没换成"说给用户听。全仓最贵的一课就是
      「写入侧说成功 ≠ 被作用对象真的变了」，所以这里**不返回 bool**，
      而是返回落点本身 —— `"file"` 时 agy 极可能仍在用原来那个号。
    """
    # ★ 换号前把**当前**这份收进池：钥匙串里只有一格，覆盖就没了。
    #   `_adopt` 也做这件事，但那是 CLI 层；低层自己兜一道，手工调用同样安全。
    cur = read_live()
    cur_sub = (claims(cur) or {}).get("sub")
    if cur and cur_sub and not cred_path(cur_sub).exists():
        try:
            write_cred(cur_sub, cur)
        except OSError:
            pass

    if keyring_write(cred):
        # 钥匙串写成功：顺手把**已存在**的兜底文件也同步过去。
        # 不新建文件 —— agy 只在钥匙串写失败时才建它，我们凭空造一份
        # 等于给未来的读者留一个"它是主存储"的假象（正是这次踩的坑）。
        if LIVE.exists():
            try:
                _write_live_file(cred)
            except OSError:
                pass
        return "keyring"

    _write_live_file(cred)
    return "file"


def _write_live_file(cred):
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
