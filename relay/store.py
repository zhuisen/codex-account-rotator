"""中转站（OpenAI 协议 relay）的本地配置与 codex profile 渲染。**纯模块,不发网络请求。**

## 它解决什么

账号池是订阅制:免费,但撞了额度要等重置。中转站是按量付费:随时能用,但烧余额。
两者是**同一件事的两条路由**,用户要能在 CodexBar 里新增/改 key+base_url 并一键切过去。

## ★★ 三条必须守住的不变量

① **绝不重写 `~/.codex/config.toml`。** 那份文件有大量中文注释、oh-my-codex 段、
   `[hooks.state]` 与 `[projects]` 等由 codex 自己回写的块。任何 TOML 库的
   load→dump 都会丢注释、重排键。
   实测（2026-09-09，codex 0.154.0-alpha.6，三方对照）:
     `--profile X` + 存在 `~/.codex/X.config.toml` → **文件被读**
       （文件里写个不存在的 provider ⇒ `Error: failed to load configuration`）
     不带 `--profile`                              → 该文件被完全无视
     `--profile X` + **文件不存在**                 → **不报错,静默退回 base 配置**
   所以新增路由 = 新增一个独立的 `<id>.config.toml`,**config.toml 一个字节都不用动**。

② ★ **profile 文件缺失是静默失败,必须自己加闸。** 由上面第三条对照:名字对不上时
   codex 不吭声,直接用 base 配置跑 —— 对 `cxp` 而言就是「直连单号、不轮换、WS 全开」,
   和正常运行**长得一模一样**。本仓的老教训:写入侧标志会撒谎,判据要从被作用对象自证。
   `active_profile()` 因此返回三态,`profile_missing` 不许和 `ok` 合并。

③ **key 只出指纹,不出明文。** 任何面向 UI / 日志 / 报错的路径都走 `fingerprint()`。
   落盘文件权限 0600,与仓库现有 `auth/` 同级。

## 为什么不用 Keychain

仓库已经把 OAuth refresh_token（比 relay key 敏感得多）明文存在 `auth/`。再引入
Keychain 会 ① 与现有范式不一致 ② Windows 要另写一套（本仓是双平台）。
统一走「0600 本地文件 + gitignore」,一种做法守到底。
"""
import json
try:
    import fcntl                       # POSIX
except ModuleNotFoundError:            # Windows —— 语义等价的 LockFileEx 兼容层,见 portalock.py
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    import portalock as fcntl          # noqa: N813
# ★ 裸 `import fcntl` 是**回归**:Windows 上会让 relay-ctl 的每个子命令 ImportError,
#   Rust 收到空 stdout、报"relay-ctl 无输出",而页面同时渲染"还没有配置中转站" ——
#   一句关于事实的假陈述。本仓 `codex-rotate:23` 与 `proxy.py:22` 早就是这个写法。
import os
import re
import sys
import stat
import time
import urllib.parse
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

SCHEMA_V = 1
STORE_NAME = "relays.local.json"
ROUTE_NAME = "route.local.json"

# 账号池那条路由的 profile 名。它是既有的,不由本模块创建。
POOL_PROFILE = "rotateproxy"

# id 直接当文件名用（`~/.codex/<id>.config.toml`）也当 codex 的 provider id 用,
# 所以字符集要卡死:既防路径穿越,也防 TOML 里需要转义的字符。
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _is_loopback(url):
    """host 是不是回环。★ 用 `urlsplit().hostname` 而不是切字符串:
    它会正确剥掉端口和 IPv6 的方括号（`http://[::1]:3000` → `::1`）。"""
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower() in _LOOPBACK
    except ValueError:                      # 畸形 URL —— 当成非回环,从严
        return False
# codex 的内置 provider id 不可覆盖（0.154 仍硬报
# `model_providers contains reserved built-in provider IDs:`）,而 `rotateproxy`
# 是账号池自己的,被中转站占用会把两条路由搅在一起。
RESERVED_IDS = {"openai", "codex", "azure", "bedrock", "oss", POOL_PROFILE}


def data_root():
    """与 Rust 侧 `data_dir()` 同一个约定:环境变量优先,否则仓库根。"""
    return os.environ.get("CODEX_ROTATE_STORE") or str(Path(__file__).resolve().parent.parent)


def store_path():
    return Path(data_root()) / "relay" / STORE_NAME


def route_path():
    return Path(data_root()) / "relay" / ROUTE_NAME


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def fingerprint(key):
    """★ 给 UI / 日志用的**唯一**表示形式。永远不要把完整 key 递出去。

    形如 `sk-73a1… (0f39111c7caf)` —— 前缀够认人,sha256 前 12 位既区分同前缀的两把,
    又能在两台机器之间比对「是不是同一把」而不用传原文。

    ## ⚠️ 为什么**不再**露出明文尾巴（2026-09-10 修）

    原来是 `head(7) + "…" + tail(3) + sha256[:12]`。那 12 位哈希是一个 **48 bit 的
    验证预言机**:拿一个猜测算 sha256 前 12 位比一下就知道对不对。露出首尾共 10 个明文
    字符之后,一把 18 字符的 key 只剩 8 个未知位 —— base62^8 ≈ 2.2e14,离线可暴力。
    而指纹会进 **0644 的快照文件**、进日志、进截图。
    去掉尾巴后未知位回到 11 个（62^11 ≈ 5e19),同时哈希仍然承担「区分」与「跨机比对」
    两个职责 —— 尾巴本来就是多余的那一份。

    ★ 前缀也跟着 key 长度收缩:短 key 上固定露 7 位等于露掉大半。
    """
    if not key:
        return ""
    # 至多 7 位,且不超过全长的三分之一 —— 短 key 上自动收敛。
    head = key[:max(1, min(7, len(key) // 3))]
    return f"{head}… ({sha256(key.encode()).hexdigest()[:12]})"


def _atomic_write(path, text, mode=0o600):
    """★ 原子写 + 权限。照 `set_scan_source` 的做法（tmp + rename）——
    监控进程随时可能在读这份配置,直接覆写会让它读到半截 JSON。

    ★★ **权限必须在 `open` 的那一刻就定下来**（2026-09-10 修）。
       原来是 `tmp.write_text(...)` 再 `os.chmod(tmp, mode)` —— `write_text` 按 umask
       建文件（通常 022 ⇒ **0644**),于是从建立到 chmod 之间存在一个窗口,
       期间这份**含明文 api key** 的临时文件是全局可读的。
       原 docstring 只说「chmod 要在 rename 之前」,那一半是对的、也确实做到了,
       但它挡的是 rename 之后的窗口,挡不住**创建时**的窗口 —— 一条只覆盖一半的规则
       读起来和覆盖全部一样。
    ★ 同时带 `O_EXCL`:临时文件名含 pid,但同一进程重入或残留符号链接都会让
      「写进一个别人指定的路径」变得可能。`O_EXCL` 让这种情况直接失败而不是跟随。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    # 残留的同名文件（上次崩在中途）会让 O_EXCL 失败 —— 先清掉,那是我们自己的文件。
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    # ★ umask 会**削**掉 open 的 mode 位（0600 & ~umask 通常仍是 0600,但不保证),
    #   所以再显式 chmod 一次把它钉死。此时文件从未有过更宽的权限。
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load():
    """读不到 / 坏了都返回空表 —— 但**不吞掉区别**:坏文件会被改名留档,
    否则「配置丢了」和「从来没配过」看起来一样。"""
    p = store_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"v": SCHEMA_V, "relays": []}
    except OSError as e:
        raise RuntimeError(f"读取中转站配置失败: {e}") from e
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        kept = p.with_name(f"{p.name}.corrupt-{int(time.time())}")
        p.rename(kept)
        # ★ 文件系统层区分了「坏了」和「没配过」,**但不能到 UI 层又折回去**:
        #   两者都返回空表的话,页面会画"还没有配置中转站" —— 一句关于事实的假陈述,
        #   而同一刻 `relay-key` 已经在报"配置不存在"。带上标记,让 status 能说实话。
        return {"v": SCHEMA_V, "relays": [], "store_corrupt": str(kept)}
    if not isinstance(cfg, dict) or not isinstance(cfg.get("relays"), list):
        return {"v": SCHEMA_V, "relays": []}
    cfg.setdefault("v", SCHEMA_V)
    return cfg


@contextmanager
def _store_lock():
    """★ 跨进程写锁。照本仓 `codex-rotate::_cred_lock` 的范式(`fcntl.flock` on a lockfile)。

    原子写只保证**文件完整**,不保证**不丢更新**:`relay-ctl usage`（落盘探到的计费端点）
    与 UI 的 `set` 是两个进程,各自 load→save,后写的会把先写的盖掉。
    锁要加在**数据这一层** —— Rust 侧那把 `Mutex` 只管得住 app 自己,
    命令行里跑一次 `relay-ctl set` 它一点都不知道。

    ⚠️ 拿不到锁时**照常继续**:丢一次更新远好过让整个功能不可用。
       但要在 stderr 留一行 —— 否则「为什么我的改动没保存」永远查不出来。
    """
    lock_dir = store_path().parent
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        lf = open(lock_dir / ".relays.lock", "w")
    except OSError as e:
        sys.stderr.write(f"relay store: 建不了锁文件({e}),本次写入无并发保护\n")
        yield
        return
    try:
        fcntl.flock(lf, fcntl.LOCK_EX)
        yield
    finally:
        lf.close()


def save(cfg):
    _atomic_write(store_path(), json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def validate(relay):
    """返回错误列表;空表示通过。**在这里挡住,别等到发请求才发现。**"""
    errs = []
    rid = (relay.get("id") or "").strip()
    if not ID_RE.match(rid):
        errs.append("id 只能是小写字母/数字/下划线/连字符,2-31 位,且以字母数字开头")
    elif rid in RESERVED_IDS:
        errs.append(f"id `{rid}` 是保留名（codex 内置 provider 或账号池自用）")
    url = (relay.get("base_url") or "").strip()
    if not url.startswith(("http://", "https://")):
        errs.append("base_url 必须以 http:// 或 https:// 开头")
    # ★★ 远端明文 http 在这里就挡掉。中转站 key 是**按量扣钱的凭证**,明文发一次,
    #    沿途任何一跳都能拿去刷余额。此前这条只校验"是不是 http(s) 开头",
    #    远端 http 一路放行到 `monitor._get()` 才有人管 —— 而 `proxy.py` 那侧一直要求
    #    https。同一条规则三处实现,这里曾是最宽的那处。
    #    回环仍然放行:自建 one-api 跑 `http://127.0.0.1:3000` 是正常用法,流量不出网卡。
    elif url.startswith("http://") and not _is_loopback(url):
        errs.append("base_url 用明文 http 只允许指向回环地址（localhost / 127.0.0.1 / ::1）;"
                    "远端请改成 https:// —— 否则 api key 会明文上网")
    elif url.rstrip("/").endswith("/chat/completions"):
        # 很常见的粘贴错误:把完整端点当 base_url 填进来。
        errs.append("base_url 填的是完整端点,应该只到 /v1")
    if not (relay.get("key") or "").strip():
        errs.append("api key 不能为空")
    return errs


def patch(rid, **fields):
    """★★ **锁内**的 read-modify-write。给「只改一两个字段」的调用方用。

    `upsert` 是**整行重建**:调用方给什么就是什么。于是
    `row = get(rid); upsert({**row, "usage_path": p})` 这种写法里,
    `get` 与 `upsert` 之间落进来的另一进程的修改(改 label / base_url / **key**)
    会被那份旧快照原样盖回去 —— flock 只序列化了两次 `save()`,RMW 跨在锁外,
    等于没锁。`relay-ctl usage` 正是这么写的,而它与 UI 的 `set` 走两把不同的 Rust 锁、
    可以并发,且中转站不可达时它最长跑 100s —— 正是用户最想改配置的时刻。
    """
    with _store_lock():
        cfg = load()
        for r in cfg["relays"]:
            if r.get("id") == rid:
                r.update(fields)
                save(cfg)
                return r
    return None


def upsert(relay):
    """新增或按 id 覆盖。返回 (cfg, errors)。**errors 非空时不写盘。**"""
    errs = validate({k: v for k, v in relay.items() if k != "_keep_key"})
    if errs:
        return None, errs
    with _store_lock():
        return _upsert_locked(relay)


def _upsert_locked(relay):
    """★ **持锁调用,自己绝不再取锁。** `fcntl.flock` 在同进程用第二个 fd 取会**阻塞**,
    将来谁在锁内调 `upsert()` 就是静默堵住 UI —— 而"卡住"和"在算"看起来一样。"""
    cfg = load()
    rid = relay["id"].strip()
    row = {
        "id": rid,
        "label": (relay.get("label") or rid).strip(),
        "base_url": relay["base_url"].strip().rstrip("/"),
        "key": relay["key"].strip(),
        "enabled": bool(relay.get("enabled", True)),   # 缺席时下面会沿用旧值
        # None = 还没探测过。**不要预设成 "/usage"** —— 各家中转站不一样
        # （one-api / new-api 走 /dashboard/billing/…）,预设会把「没探测」
        # 伪装成「已知是这个」。
        "usage_path": relay.get("usage_path"),
        "model": (relay.get("model") or "").strip() or None,
    }
    olds = [r for r in cfg["relays"] if r.get("id") == rid]
    # ★★ **key 的"沿用旧值"也必须在锁内。** 调用方原来在锁外 `get()` 再 `upsert()`,
    #    CLI `set` 与 app `set` 并发时会把旧 key 盖回去 —— 正是这次要堵的那一类。
    #    `_keep_key` 由调用方置位:它只表达"这次没给新 key",具体沿用哪个由这里决定。
    if relay.get("_keep_key") and olds:
        row["key"] = olds[0].get("key") or row["key"]
    # ★★ **payload 里缺席的字段沿用旧值。** 前端编辑表单只送 id/label/base_url/key/model,
    #    整行重建会把 `usage_path` 清回 None（下次白跑 3 个探测）、把 CLI 里停用的中转站
    #    **静默重新启用** —— 后者是"用户明确关掉的东西自己回来了",最不该发生的一类。
    if olds:
        for k in ("usage_path", "enabled"):
            if k not in relay:
                row[k] = olds[0].get(k, row[k])
    row["added_at"] = olds[0].get("added_at") if olds else time.strftime("%Y-%m-%dT%H:%M:%S%z")
    cfg["relays"] = [r for r in cfg["relays"] if r.get("id") != rid] + [row]
    save(cfg)
    return cfg, []


def remove(rid):
    """删除一个中转站。★ 连它的 codex profile 一起删,否则会留下一个
    「切过去就静默退回 base 配置」的孤儿路由（见模块 docstring 不变量 ②）。

    ★★ **只删我们自己的东西。** 2026-09-09 Fable 复核抓到:原实现不查所有权,
       `remove("rotateproxy")` 会删掉**账号池的** overlay(里面有 12 行 codex 回写的
       hooks 信任哈希 + 项目信任),而返回值还是 `False`(「没删到中转站」)——
       删了最要紧的东西,却报告"什么也没删"。之后所有运行时 `cxp` 直接 exit 78。
       `remove("mine")` 同样会删掉用户手写的 profile。
       三道校验:保留名 / 必须是已登记的中转站 / 文件必须带托管标记。
    """
    if rid in RESERVED_IDS:
        raise KeyError(f"拒绝:`{rid}` 是保留名(codex 内置 provider 或账号池自用),不归本模块管")
    if not get(rid):
        raise KeyError(f"没有这个中转站: {rid}")
    with _store_lock():
        cfg = load()
        before = len(cfg["relays"])
        cfg["relays"] = [r for r in cfg["relays"] if r.get("id") != rid]
        save(cfg)
    # ★ **顺序不能反。** 先删文件再复位路由的话,中间任何一次 cxp 启动都会撞上
    #   `profile_missing` —— 而 codex 对它**不报错**,直接静默退回 base 配置
    #   (单号直连、不轮换、WS 全开)。先把路由挪回账号池,再删文件。
    if active_route() == rid:
        set_route(POOL_PROFILE)
    prof = codex_home() / f"{rid}.config.toml"
    if prof.exists():
        # ★ 只动带托管标记的那一段。没标记 = 用户或别的工具的文件,一律不碰。
        drop_managed_profile(prof)
    return before != len(cfg["relays"])


def get(rid):
    for r in load()["relays"]:
        if r.get("id") == rid:
            return r
    return None


def redacted(cfg=None):
    """给 UI 的形式:key 换成指纹。**这是唯一允许跨进程边界的形状。**"""
    cfg = cfg or load()
    out = []
    for r in cfg["relays"]:
        row = dict(r)
        row["key_fp"] = fingerprint(row.pop("key", ""))
        out.append(row)
    return {"v": cfg.get("v", SCHEMA_V), "relays": out}


# ── codex profile 渲染 ────────────────────────────────────────────────────────

# ★★ **托管区标记 —— 这套方案能与 codex 共存的全部依据。**
# codex 会往 **profile overlay 文件本身**回写运行时状态,不只是往 config.toml。
# 所以我们只拥有这两个标记之间的行。现在只用来**识别**遗留文件的归属(见 `remove` / cleanup)。
MARK_BEGIN = "# >>> codexbar-relay managed — 本区由 CodexBar 重写,标记之外的内容原样保留 >>>"
MARK_END = "# <<< codexbar-relay managed <<<"


def _tstr(v):
    """渲染成合法的 TOML basic string。

    ★ label 里一个引号就能让整份配置解析失败 —— codex 报
      `failed to load configuration`,而用户只是给中转站起了个带引号的名字。
      JSON 的字符串转义与 TOML basic string 兼容,直接借用。
    """
    return json.dumps(str(v), ensure_ascii=False)


# ── 已删除:每中转站一份 codex profile ────────────────────────────────────────
#
# 2026-09-09 定稿「一个 provider,两种上游」之后,`profile_toml` / `write_profile` /
# `key_helper_path` / `managed_values` 以及 `relay/relay-key` 全部**删除**,不是保留待用。
# codex 只认 `rotateproxy` 一个 provider,中转站的 key 由**代理**直接从
# `relays.local.json` 读并放进 Authorization 头 —— 没有第二份 profile 要渲染,
# 也就没有"渲染得对不对"可判(整个 `profile_stale` 分支随之消失)。
#
# ★ 留着一份没人调用、测试还在跑的 `write_profile`,会让套件绿着测一条**永不执行**
#   的代码路径 —— 本仓记过两次的"空守卫"形状。要恢复请从 git 历史取,别在这里留骨架。
#
# `split_managed` / `MARK_*` **保留**:`remove()` 与 `relay-ctl cleanup` 靠它判断
# 一个遗留文件是不是我们写的(只删自己的东西)。


def split_managed(text):
    """切成 (托管区之前, 托管区, 托管区之后)。没有标记时托管区为 None。"""
    if MARK_BEGIN not in text or MARK_END not in text:
        return text, None, ""
    a = text.index(MARK_BEGIN)
    b = text.index(MARK_END) + len(MARK_END)
    return text[:a], text[a:b], text[b:].lstrip("\n")


def drop_managed_profile(path):
    """把一份 codex profile 里**属于本工具**的那一段拿掉。返回三态：

    · `"removed"` —— 整份都是我们写的，文件已删；
    · `"stripped"` —— 文件里还有用户自己的内容，只剥掉了托管区，文件保留；
    · `"kept"` —— 没有托管标记 / 读不出来，一个字节都没动。

    ★★ **绝不因为"文件里出现过托管标记"就删掉整份**（2026-09-10 修）。
       `split_managed` 一直把 `before` / `after` 切出来 —— 那两段就是用户自己加在
       我们那段前后的内容（自定义 effort、注释、别的 provider）。原来两处调用点
       （`remove()` 与 `relay-ctl cleanup`）都是命中标记就 `unlink()` 整份,
       而返回值只说「删掉了这个孤儿」,读起来像只清掉了我们自己的东西。

    ★ 这个判据以前是**两份实现**（各写各的 `split_managed(...)[1] is not None`),
      所以两边同时错。本仓铁律：同一条规则的两份实现必然分叉,合成一份。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "kept"
    before, managed, after = split_managed(text)
    if managed is None:
        return "kept"
    if before.strip() or after.strip():
        # ★ profile 不含密钥（key 走 `relay-key` 脚本/环境),所以 0644 ——
        #   与 `write_profile` 当初写它时同一档权限,别悄悄收紧用户能读的文件。
        _atomic_write(path, (before + after).rstrip("\n") + "\n", mode=0o644)
        return "stripped"
    path.unlink()
    return "removed"


# ── 路由开关 ──────────────────────────────────────────────────────────────────

def read_route():
    """读路由文件 → `{"profile": str|None, "error": str|None}`。

    ★★ **绝不把「文件坏了」折叠成「用户选了账号池」。** 2026-09-09 Fable 复核抓到:
       原实现 `except Exception: return POOL_PROFILE`,于是 `{"profile": null}` / 半截 JSON /
       `[]` 全都报告"账号池"。
       ⚠️ 2026-09-10 更正这条的**理由**:原文写的是"而 `cxp` 对同样的输入是 exit 78" ——
       那在「一个 provider,两种上游」定稿之后**已经不成立**,`cxp` 根本不读这个文件
       (它恒用 `rotateproxy`,只检查 `rotateproxy.config.toml` 在不在)。
       真正的后果换成了:`proxy.py::_relay_upstream()` 读不出来就**退回账号池**,
       于是用户明明选了按量付费的中转站,却在**不知情地扣订阅额度**,
       而工具绿着说"路由:账号池" —— 那句话字面上还成了"对的",这才是最坏的形状:
       **它把一次静默改道说成了一次正常配置。**
       结论不变(坏 ≠ 账号池),但**理由必须是真的** —— 照着一条过期理由做判断,
       下一次同类问题就会被诊断到错误的组件上。

    ★ 还要**校验字符集**。profile 名同时是文件名,不校验就是路径穿越:
      实测原实现对 `{"profile": "../evil"}` 直接返回 `../evil`,
      而 `codex_home() / f"{rid}.config.toml"` 会把它拼成 `~/.codex/../evil.config.toml`。
      cxp 那半早就校验了,Python 这半漏了。
    """
    p = route_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"profile": POOL_PROFILE, "error": None}     # 没配过 = 账号池,这才是真的默认
    except OSError as e:
        return {"profile": None, "error": f"路由文件读不出来: {e}"}
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"profile": None, "error": f"路由文件不是合法 JSON: {e}"}
    if not isinstance(d, dict):
        return {"profile": None, "error": f"路由文件顶层不是对象(是 {type(d).__name__})"}
    prof = d.get("profile")
    if not isinstance(prof, str) or not prof:
        return {"profile": None, "error": f"路由文件里的 profile 不是非空字符串: {prof!r}"}
    if prof != POOL_PROFILE and not ID_RE.match(prof):
        return {"profile": None,
                "error": f"profile 名 {prof!r} 不符合 ^[a-z0-9][a-z0-9_-]{{1,30}}$ "
                         f"—— 它同时是文件名,放行等于路径穿越"}
    return {"profile": prof, "error": None}


def active_route():
    """当前该用哪个 profile。**坏文件时返回 None** —— 调用方必须自己决定怎么办,
    不许在这里替它折叠成账号池(见 `read_route`)。"""
    return read_route()["profile"]


def set_route(profile):
    if profile != POOL_PROFILE and not get(profile):
        raise KeyError(f"没有这个中转站: {profile}")
    _atomic_write(route_path(),
                  json.dumps({"profile": profile}, ensure_ascii=False) + "\n",
                  mode=0o644)   # 不含密钥,cxp 每次启动都要读
    return profile


def route_status():
    """路由的**五态**判定。

    ## 2026-09-09 定稿：一个 provider，两种上游

    中转站不再有自己的 codex profile。codex 永远只看见 `rotateproxy` 一个
    `model_provider`；账号池 ↔ 中转站的切换发生在**代理内部**
    （`proxy.py::_relay_upstream` 读同一个路由文件决定往哪转发）。

    这一改消掉了整个 `profile_stale` 分支 —— 它的每一条都在检查"第二份 profile 文件
    是否与登记表同步"，而现在没有第二份文件了。同时 `codex resume` 的会话列表不再分裂
    （picker 按 `model_provider` 过滤，且 0.154 里没有任何配置键能放宽它）。

    ## 剩下的每一态都对应一种「看起来正常、其实不是」

    - `route_corrupt` —— 路由文件坏了。代理会**退回账号池**（`_relay_upstream` 判不准时
      往免费那档倒），所以 codex 照常能跑 —— 坏的是**你选的那条路由被无声忽略了**。
      ⚠️ 这里原来写的是「`cxp` 对同样的输入 exit 78，codex 一条都跑不起来」，
      那是上一版架构（中转站各有一份 profile）的事实，定稿之后 `cxp` 已经不读这个文件。
    - `profile_missing` —— `rotateproxy.config.toml` 没了。**codex 对此不报错**，
      直接静默退回 base 配置（直连单号、不轮换、WS 全开），和正常运行长得一模一样。
    - `orphan` / `relay_disabled` —— 路由指着一个已删除 / 已停用的中转站。
      代理会**退回账号池**（那是刻意的：判不准时往免费那档倒），于是用户以为在按量付费、
      实际扣的是订阅额度。**两种分开报**，因为修法不同：一个要重新登记，一个只要启用。
    """
    rr = read_route()
    if rr["error"]:
        return {"state": "route_corrupt", "profile": None, "path": str(route_path()),
                "detail": rr["error"] + "。codex 照常能跑,但代理会**退回账号池** ——"
                                        "你选的中转站被无声忽略,扣的是订阅额度不是余额。"}
    prof = rr["profile"]
    # ★ 现在只有一份 profile 需要存在 —— 账号池那份。中转站档也走它。
    path = codex_home() / f"{POOL_PROFILE}.config.toml"
    if not path.exists():
        return {
            "state": "profile_missing",
            "profile": prof,
            "path": str(path),
            "detail": "rotateproxy.config.toml 不存在 ⇒ codex 会**静默**退回 base 配置"
                      "（直连单号、不轮换、WS 全开）。这不会报错,只能靠这条闸发现。",
        }
    if prof == POOL_PROFILE:
        return {"state": "pool", "profile": prof, "path": str(path)}
    r = get(prof)
    if not r:
        return {"state": "orphan", "profile": prof, "path": str(path),
                "detail": f"路由指向 {prof!r},但它已不在登记表里 ⇒ 代理**退回账号池**。"
                          f"你以为在按量付费,实际扣的是订阅额度。"}
    if not r.get("enabled"):
        return {"state": "relay_disabled", "profile": prof, "path": str(path),
                "label": r.get("label"),
                "detail": f"{r.get('label') or prof} 已停用 ⇒ 代理**退回账号池**。"
                          f"你以为在按量付费,实际扣的是订阅额度。"}
    return {"state": "relay", "profile": prof, "path": str(path),
            "label": r.get("label"), "key_fp": fingerprint(r.get("key", ""))}
