#!/usr/bin/env python3
"""代理轮换泳道的数据引擎:**什么时间 · 哪个号在岗 · 烧了多少 token(哪些模型) · 为什么切换**。

设计稿:`~/Downloads/design_handoff_codexbar 5/代理轮换-交接说明.md`(用户 2026-09-07 定稿,要求 1:1)。

## 为什么在 Python 而不是 Rust

需要**把 codex rollout 的 token 记账接进来**,而 rollout 解析的基建(以及那一堆口径坑)已经在
`traffic/scan.py` 里。在 Rust 里再写一份 codex 解析器,正是本仓 `.claude/rules/traffic.md` 明令禁止的
「别再按平台各写一份扫描器」。Rust 侧只负责起进程 + 缓存。

## ★★ token 归属靠 `response_id` **精确 join**,不是按时间推断

这是本模块的地基,所以先写清楚它是怎么被证实的(2026-09-07 实测):

* `proxy.log` 的 affinity 行形如 `[proxy 09-07 16:28:22 #resp_<完整id>] affinity resp_xxx → [plus5]`
  —— `#` 后面那个就是**完整的 response_id**,并且它旁边就写着是哪个号服务的。
* codex rollout 的 `token_usage_record.payload` 里有**同一个 `response_id`**,外加
  `usage`(该次响应的四类 token,**非累计**)与 `turn_id`。
* 实测:2026/09 的 942 条 rollout token 记录里 **727 条(77%)** 能精确命中一个账号;
  **对照实验**:300 个随机生成的同形 `resp_...` id 命中 **0** 条 ⇒ 这个 join 不是碰运气。

★ 没命中的 23% 是**没走代理**的请求(直连 `codex`、或请求早于当前 proxy.log 尾部)。
  这个数字必须原样报给 UI(`coverage`) —— 稿子里「612M token」是当完整值写的,
  而真实数据天然不完整。**把一个下界当成总量画出来,和编造没有区别。**

## 时间口径

* `proxy.log` 的时间戳是**本地时区、不带年份**(`time.strftime("%m-%d %H:%M:%S")`)。
  跨年时 `12-31` 按今年算会落在未来 ⇒ 整段历史被判出窗,所以要回退年份。
* rollout 的 `timestamp` 是 **UTC ISO**。两者必须都折成 epoch 再比。

本模块是**纯模块**:顶层只有常量,无副作用,可被测试按路径 import。
"""
import bisect
import calendar
import glob
import json
import os
import re
import time

# ── 常量 ───────────────────────────────────────────────────────────────
TAIL_BYTES = 6 * 1024 * 1024      # proxy.log 尾读上限(全量 5.5MB,窗口最长 7d)
MAX_SEGMENTS = 400                # 泳道上限,防病态数据把前端画爆
MAX_EVENTS = 200
SEG_GAP_SECS = 900                # 同一个号连续两次请求间隔超过它 ⇒ 断成两段"在岗"
MIN_SEG_SECS = 60                 # 单点请求也给一个最小可见时长(前端另有 min-width:3px)

# ── 缓存 ───────────────────────────────────────────────────────────────
# 实测(2026-09-07,本机 4188 个 rollout):**扫 rollout 是压倒性的大头** ——
#   1h 0.47s · 6h 0.51s · 24h 1.29s · 7d 2.78s,而解析 proxy.log 恒 0.42s、切段与归属都是毫秒级。
# 所以缓存只需要盖住 rollout 这一段:按文件签名记住"这个文件里有哪些 response_id 的用量",
# 没变过的文件下次直接取。签名用 **`st_mtime_ns`** —— 秒级会漏掉"同一秒内、长度不变的改写",
# 那种情况下缓存会沿用旧结果且**没有任何症状**(本仓 `scan.py` 上栽过一次)。
CACHE_V = 1
CACHE_NAME = ".rotation-cache.json"
SNAP_NAME = ".rotation-latest.json"          # 成品快照:UI 先画它,再后台重扫
CACHE_MAX_FILES = 4000                       # 超出按最后命中时间淘汰,防无限增长

# 设计稿指定的 6 个账号识别色。★ 稿子里写的是「plus5=#2dd4bf」这种**具体 label 的映射**,
# 但 label 是用户可改名的(`codex-rotate rename`),把映射写死等于把一次快照当成规则。
# 所以按 label 做**确定性散列**取色:同一个号永远同一个色,改名才会变。
# 调色板逐字取自稿子,不含灰 —— 灰是"其余"桶的颜色,不给有身份的东西用(全局 ui-design 规则)。
ACC_PALETTE = ["#2dd4bf", "#4d9fff", "#8b7cf6", "#E0A21C", "#27B26B", "#E0784F"]
# 模型色:稿子的三档青(主模型 → 次 → 第三)。同样按序取,不按名字散列 ——
# 这里要表达的是"同一族里的主次",不是"这是哪个模型"。
MODEL_SHADES = ["#2dd4bf", "#7fe8da", "#158f80", "#4d9fff", "#8b7cf6", "#E0A21C"]

_TS_RE = re.compile(r"^\[proxy (\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)(?: #(\S+))?\] (.*)$")
_ROLLOUT_RE = re.compile(r"rollout-\d{4}-\d\d-\d\dT[\d-]+-([0-9a-f-]{36})\.jsonl$")


def store_dir():
    return os.environ.get("CODEX_ROTATE_STORE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


# ── 时间 ───────────────────────────────────────────────────────────────
def _local_epoch(y, mo, da, h, mi, se):
    try:
        return time.mktime((y, mo, da, h, mi, se, 0, 0, -1))
    except (ValueError, OverflowError):
        return None


def parse_proxy_ts(mo, da, h, mi, se, now):
    """`MM-DD HH:MM:SS`(本地、无年份)→ epoch。

    ★ 取「不在未来的候选里**最近**的那个」。写成"第一个满足下限的"会把**今天**的行判成去年
      (365 天前也满足任何合理下限),症状是整页空白而日志完全正常。
    """
    year = time.localtime(now).tm_year
    best = None
    for y in (year - 1, year, year + 1):
        t = _local_epoch(y, mo, da, h, mi, se)
        if t is not None and t <= now + 86400 and (best is None or t > best):
            best = t
    return best


def _iso_utc_epoch(s):
    """rollout 的 `2026-09-07T08:52:34.129Z` → epoch。**不用 fromisoformat** ——
    Python 3.9 不认结尾的 `Z`,而本机 launchd 会解析到 3.9(见 devport 里同款注记)。"""
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)", s or "")
    if not m:
        return None
    return calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0))


# ── 第一段:proxy.log → 在岗时间线 + 事件 + response_id→账号 ─────────────
def _tail(path, max_bytes):
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, False
    truncated = size > max_bytes
    try:
        with open(path, "rb") as fh:
            if truncated:
                fh.seek(size - max_bytes)
            raw = fh.read()
    except OSError:
        return None, False
    text = raw.decode("utf-8", "replace")
    if truncated:
        # 从中间切进去必然切断一行,而半行会解析出一条形状怪异却看着像真的记录。
        i = text.find("\n")
        text = text[i + 1:] if i >= 0 else ""
    return text, truncated


def scan_proxy_log(text, now, start, end):
    """返回 (requests, resp_owner, markers, log_lines, undated, in_window)。

    * requests: [(ts, acc, billed)] —— 只有 billed=True 的用来切在岗段
    * resp_owner: {response_id: acc} —— token 归属的 join 键
    * markers:   [(ts, acc, kind)] kind ∈ stream_err | cool_429
    """
    requests, resp_owner, markers, log_lines = [], {}, [], []
    undated = in_window = 0
    for line in text.splitlines():
        if not line.startswith("[proxy"):
            continue                       # Python traceback 等,静默跳过
        m = _TS_RE.match(line)
        if not m:
            # ★ 老 `[proxy]` 前缀**完全没有时间戳**(实测占全库 27%)。它进不了任何时间窗,
            #   但**绝不能悄悄丢掉** —— 丢了就是把「我们没看到」伪装成「确实没有」。
            if line.startswith("[proxy]"):
                undated += 1
            continue
        mo, da, h, mi, se, rid, body = m.groups()
        ts = parse_proxy_ts(int(mo), int(da), int(h), int(mi), int(se), now)
        if ts is None or ts < start or ts > end:
            continue
        in_window += 1
        acc = _first_label(body)

        if body.startswith("→ "):
            if acc:
                requests.append((ts, acc, body[2:].startswith("POST")))
        elif body.startswith("affinity"):
            # `#` 后面是完整 response_id,消息里那个是截断的 —— 用前者。
            if rid and rid.startswith("resp_") and acc:
                resp_owner[rid] = acc
        elif body.startswith("← "):
            pass                            # 状态码这里用不到,泳道只关心时间与归属
        else:
            # ★★ 三类失败的**计费含义完全不同**,不可合并成一个「错误」:
            #   · `send err`  → 请求没送完 ⇒ 上游未 dispatch ⇒ **没计费**,换号安全
            #   · `stream err`→ 已 200、流中途断 ⇒ **已计费**
            #   · `committed` → 已交出去、到没到**不可知** ⇒ **可能已计费**(最贵的一类)
            #   这是 `CLAUDE.md` §8「计费相位分界」在展示层的投影。稿子只画了断流与 429,
            #   但把 `committed` 一起丢掉等于**唯一能告诉用户"这次可能白花了钱"的信号消失** ——
            #   所以它进事件流(不进泳道标记:泳道那两种是位置标注,这一类要的是文字说明)。
            kind = None
            if body.startswith("stream err"):
                kind = "stream_err"
            elif "→ cooled" in body:
                kind = "cool_429"
            elif "committed" in body:
                kind = "billed_unknown"
            elif body.startswith("send err"):
                kind = "safe_switch"
            if kind and acc:
                # ★ 泳道上只画 `stream_err`(琥珀点)与 `cool_429`(蓝环) —— 稿子 §1 只定义了这两种
                #   位置标注。另两类要的是**文字说明**("可能已计费"/"未送达,安全换号"),
                #   画成点分辨不出来,所以只进事件流。
                markers.append((ts, acc, kind))
            log_lines.append((ts, body))
    return requests, resp_owner, markers, log_lines, undated, in_window


def _first_label(body):
    """一行里 `[label]` 形式的账号名。★ 只取**第一个**方括号组:
    `stream err [plus5]: [Errno 32] Broken pipe` 里第二组是 errno 不是账号 ——
    取错会造出一个叫 `Errno 32` 的幽灵账号,而它在泳道里长得和真账号一模一样。"""
    i = body.find("[")
    if i < 0:
        return None
    j = body.find("]", i + 1)
    if j < 0:
        return None
    s = body[i + 1:j]
    return s if s and len(s) <= 40 and "\n" not in s else None


def _sig(path):
    """(mtime_ns, size)。★ 必须 `st_mtime_ns` 不是 `int(st_mtime)`。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size]


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    """原子落盘:先写 `.tmp<pid>` 再 rename。★ 直接覆写会让并发读者读到半截 JSON ——
    主窗口在扫、用户同时点开菜单栏,是每天都会发生的时序(同 `.traffic-latest.json`)。"""
    tmp = "{}.tmp{}".format(path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False))
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ── 第二段:rollout → response_id → (tokens, model, ts) ─────────────────
def scan_rollouts(start, end, want_ids, cache=None, now=None):
    """只解析 mtime 落在窗口内的 rollout,且只取 `want_ids` 里的响应。

    ★ 两层剪枝都必要:全量是 4183 个文件,而 24h 窗口通常只碰得到几十个。
    ★ `usage` 是**该次响应**的量,不是累计 —— rollout 里同时有 `turn_token_usage` 与
      `thread_token_usage` 两个**累计**字段,取错会让 token 随轮次平方级虚高。
    """
    out = {}
    files = cache.setdefault("files", {}) if cache is not None else {}
    now = now or time.time()
    pat = os.path.join(codex_home(), "sessions", "**", "rollout-*.jsonl")
    for path in glob.iglob(pat, recursive=True):
        try:
            st = os.stat(path)
        except OSError:
            continue
        # 会话文件在窗口结束前就没再写过 ⇒ 里面不可能有窗口内的响应。
        if st.st_mtime < start:
            continue
        # ★ 缓存的是**整份文件解出来的 response_id → 用量**,不是"窗口内的那部分" ——
        #   存后者的话换个窗口就全部失效,而窗口是用户随手切的。
        sig = [st.st_mtime_ns, st.st_size]
        hit = files.get(path)
        if hit and hit.get("sig") == sig:
            hit["seen"] = now
            for rid, u in hit["resp"].items():
                if rid in want_ids and start <= u["ts"] <= end:
                    out[rid] = u
            continue
        parsed = {}
        models = {}          # turn_id → model
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"turn_context"' in line:
                        try:
                            p = json.loads(line).get("payload") or {}
                        except ValueError:
                            continue
                        if p.get("turn_id") and p.get("model"):
                            models[p["turn_id"]] = p["model"]
                    elif '"token_usage_record"' in line:
                        try:
                            o = json.loads(line)
                        except ValueError:
                            continue
                        p = o.get("payload") or {}
                        rid = p.get("response_id")
                        if not rid:
                            continue
                        u = p.get("usage") or {}
                        ts = _iso_utc_epoch(o.get("timestamp"))
                        if ts is None:
                            continue
                        # ★ 解析时**不按窗口过滤**:整份存进缓存,窗口过滤放到取用那一步。
                        parsed[rid] = {
                            "ts": ts,
                            "tokens": int(u.get("total_tokens") or 0),
                            "model": models.get(p.get("turn_id")) or "unknown",
                        }
        except OSError:
            continue
        if cache is not None:
            files[path] = {"sig": sig, "seen": now, "resp": parsed}
        for rid, u in parsed.items():
            if rid in want_ids and start <= u["ts"] <= end:
                out[rid] = u
    return out


# ── 第三段:切在岗段 ────────────────────────────────────────────────────
def build_segments(requests, now):
    """连续由同一个号服务的计费请求 = 一段「在岗」。

    ★ 只用 **POST /responses** 切段。把 `GET /models` 也算进来的话,一次纯探活就会在
      泳道上画出一段假的「在岗」—— 那个号其实一个 token 都没烧。
    ★ 同号但间隔 > `SEG_GAP_SECS` 也要断开:否则整夜没人用会被画成一条 8 小时的在岗块,
      看上去像"它扛了一整夜",而实际上那段时间根本没有流量。
    """
    posts = [(t, a) for (t, a, billed) in requests if billed]
    posts.sort()
    segs = []
    for ts, acc in posts:
        if segs and segs[-1]["acc"] == acc and ts - segs[-1]["end"] <= SEG_GAP_SECS:
            segs[-1]["end"] = ts
            segs[-1]["requests"] += 1
        else:
            segs.append({"acc": acc, "start": ts, "end": ts, "requests": 1})
    for s in segs:
        if s["end"] - s["start"] < MIN_SEG_SECS:
            s["end"] = s["start"] + MIN_SEG_SECS
    if segs:
        segs[-1]["current"] = True
    return segs[-MAX_SEGMENTS:]


def classify_enter(segs, markers, plans=None):
    """为什么切到这个号。★ 判据是**切入时刻之前 120s 内**发生了什么,不是猜。
    分不出来时说「额度轮换」—— 那是代理的默认行为(每请求都重新挑号)。"""
    ms = sorted(markers)
    times = [t for (t, _a, _k) in ms]
    plans = plans or {}
    for i, s in enumerate(segs):
        # ★★ **Pro 在岗 ⇒ 当时没有任何可用的 Plus。** 这是 `_pick` 的策略 C 直接推出来的:
        #   Pro 排在所有 Plus 之后,只有 Plus 全部耗尽/冷却/停用时才轮得到它。
        #   所以把它单独归一类,而不是和普通轮换混在「额度轮换」里 ——
        #   「Plus 池干了」是**唯一需要用户做点什么**的状态(等重置 / 用重置卡 / 加号),
        #   混进普通轮换里就等于把它藏起来了。用户 2026-09-07 是**自己肉眼**发现切到 Pro 的。
        if (plans.get(s["acc"]) or "").lower() == "pro":
            s["enter_reason"] = "pro_fallback"
            continue
        if i == 0:
            s["enter_reason"] = "window_start"
            continue
        prev = segs[i - 1]["acc"]
        lo = bisect.bisect_left(times, s["start"] - 120)
        hi = bisect.bisect_right(times, s["start"])
        recent = [k for (_t, a, k) in ms[lo:hi] if a == prev]
        if "cool_429" in recent:
            s["enter_reason"] = "cool_429"
        elif "stream_err" in recent:
            s["enter_reason"] = "stream_err"
        else:
            s["enter_reason"] = "quota_rotate"
    return segs


# ── 第四段:把 token 灌进段里 ───────────────────────────────────────────
def attribute(segs, resp_owner, resp_usage):
    """按 `response_id` 把 token 与模型落到对应的在岗段。

    ★ 归属键是**账号 + 时间**双重匹配:先由 `resp_owner` 拿到账号(精确),再在该号的段里
      按时间落位。只按时间落位会在两个号交替的边界上归错;只按账号不落位则画不出时段构成。
    ★ 落不进任何段的(如响应发生在窗口边缘)计入 `orphan`,**不静默丢弃**。
    """
    by_acc = {}
    for i, s in enumerate(segs):
        s.setdefault("tokens", 0)
        s.setdefault("by_model", {})
        by_acc.setdefault(s["acc"], []).append((s["start"], s["end"], i))
    for lst in by_acc.values():
        lst.sort()

    matched = orphan = 0
    for rid, u in resp_usage.items():
        acc = resp_owner.get(rid)
        if not acc:
            continue
        # ★ 取**距离最近**的那一段,不是第一个落进容差的。容差有 SEG_GAP_SECS 那么宽,
        #   而同一个号在窗口里通常有好几段 —— 取第一个会在两段都够得着时**落错段**。
        #   账号总量不受影响(还是那个号),但泳道上"这一段烧了多少"会张冠李戴,
        #   而两段的颜色深浅都还是正常的,看不出来。
        best_i, best_d = None, None
        for st, en, i in by_acc.get(acc, ()):
            d = 0 if st <= u["ts"] <= en else min(abs(u["ts"] - st), abs(u["ts"] - en))
            if d <= SEG_GAP_SECS and (best_d is None or d < best_d):
                best_i, best_d = i, d
        placed = best_i is not None
        if placed:
            segs[best_i]["tokens"] += u["tokens"]
            segs[best_i]["by_model"][u["model"]] = \
                segs[best_i]["by_model"].get(u["model"], 0) + u["tokens"]
        matched += placed
        orphan += not placed
    for s in segs:
        s["by_model"] = sorted(
            ({"model": k, "tokens": v} for k, v in s["by_model"].items()),
            key=lambda x: -x["tokens"])
    return matched, orphan


# ── 组装 ───────────────────────────────────────────────────────────────
def assign_colors(labels):
    """给每个号一个**互不相同**的识别色。

    ★ 稿子写的是「plus5=#2dd4bf」这类**具体 label 的映射**,但 label 用户可改名
      (`codex-rotate rename`),把它写死就是把一次快照当成规则。所以复刻的是**调色板本身
      与「每个号一个专属色、不含灰」这条不变量**,不是那六条具体映射。

    ★★ **纯散列不够 —— 实测当场撞车**:6 个号散列进 6 色板,`Pro1` 与 `plus6` 都落到
      `#8b7cf6`(生日问题下这是大概率事件)。两条泳道同色,正是这个设计要避免的东西,
      而它不会报任何错。所以在散列偏好之上做**线性探测**,保证互不相同。
    ★ 代价说清楚:池子里增删账号可能让其余号换色(探测顺序变了)。这个代价换的是
      「任何时刻都不会有两个号同色」—— 后者是会看错的,前者只是要重新认一次。
    """
    out, taken = {}, set()
    for label in sorted(labels):
        h = 0
        for ch in label:
            h = (h * 131 + ord(ch)) & 0xFFFFFFFF
        start = h % len(ACC_PALETTE)
        for k in range(len(ACC_PALETTE)):
            c = ACC_PALETTE[(start + k) % len(ACC_PALETTE)]
            if c not in taken:
                break
        else:                       # 号比色多 —— 只能允许复用,但至少是确定性的
            c = ACC_PALETTE[start]
        taken.add(c)
        out[label] = c
    return out


def _quota_pct(slot):
    """剩余百分比,取**最紧**的窗口。读不到返回 None(绝不当成满额)。"""
    q = (slot or {}).get("quota") or {}
    cap = q.get("captured_at")
    worst = None
    for key in ("primary", "secondary"):
        w = q.get(key) or {}
        if not (w.get("window_minutes") or 0):
            continue
        u = w.get("used_percent")
        if u is None:
            continue
        ra = w.get("resets_at")
        if ra and ra <= time.time() and not (cap is not None and cap > ra):
            continue                      # 过了重置点却没有新读数 ⇒ 未知,不采信
        rem = max(0.0, 100.0 - float(u))
        worst = rem if worst is None else min(worst, rem)
    return worst


def collect(hours=24.0, now=None, store=None, use_cache=True):
    now = time.time() if now is None else now
    hours = max(0.1, float(hours))
    start, end = now - hours * 3600, now
    store = store or store_dir()
    cache_path = os.path.join(store, CACHE_NAME)
    cache = _load_json(cache_path, {}) if use_cache else {}
    if cache.get("v") != CACHE_V:
        cache = {"v": CACHE_V, "files": {}}

    text, truncated = _tail(os.path.join(store, "proxy", "proxy.log"), TAIL_BYTES)
    if text is None:
        return {"ok": False, "reason": "no_log", "detail": "读不到 proxy/proxy.log"}

    # 账号 → 套餐。★ 必须在切段**之前**读:切入原因要靠它区分「Pro 保底」与普通轮换。
    slots = {}
    try:
        with open(os.path.join(store, "state.json"), encoding="utf-8") as fh:
            slots = {v.get("label"): v for v in (json.load(fh).get("slots") or {}).values()}
    except (OSError, ValueError):
        pass
    plans = {k: (v.get("plan") or "") for k, v in slots.items()}

    requests, resp_owner, markers, log_lines, undated, in_window = scan_proxy_log(text, now, start, end)
    segs = classify_enter(build_segments(requests, now), markers, plans)
    usage = scan_rollouts(start, end, set(resp_owner), cache if use_cache else None, now) if resp_owner else {}
    matched, orphan = attribute(segs, resp_owner, usage)

    # 账号汇总
    accs = {}
    for s in segs:
        a = accs.setdefault(s["acc"], {"acc": s["acc"], "tokens": 0, "requests": 0, "models": {}})
        a["tokens"] += s["tokens"]
        a["requests"] += s["requests"]
        for m in s["by_model"]:
            a["models"][m["model"]] = a["models"].get(m["model"], 0) + m["tokens"]
    for m_ts, m_acc, m_kind in markers:
        accs.setdefault(m_acc, {"acc": m_acc, "tokens": 0, "requests": 0, "models": {}})

    colors = assign_colors(accs.keys())
    accounts = []
    for a in accs.values():
        top = max(a["models"].items(), key=lambda kv: kv[1], default=None)
        accounts.append({
            "acc": a["acc"],
            # ★ 套餐看 `plan` 不看 label —— 老号从 Plus 升 Pro 时 label 一个字都不变。
            "plan": (plans.get(a["acc"]) or "").lower(),
            "color": colors[a["acc"]],
            "tokens": a["tokens"],
            "requests": a["requests"],
            # ★ 主模型份额的分母是**已归属的 token**,不是该号的全部消耗 ——
            #   没归属上的那部分我们不知道它是什么模型,不能替它假设。
            "top_model": ({"model": top[0], "share": top[1] / a["tokens"]} if top and a["tokens"] else None),
            "quota_pct": _quota_pct(slots.get(a["acc"])),
        })
    accounts.sort(key=lambda x: -x["tokens"])

    if use_cache:
        files = cache.get("files") or {}
        if len(files) > CACHE_MAX_FILES:
            # 按最后命中时间淘汰。★ 不按 mtime —— 老会话文件永远不再变,但只要还落在
            #   用户看的窗口里就仍会被读到,按 mtime 淘汰会把最该缓存的那些先扔掉。
            keep = sorted(files.items(), key=lambda kv: -(kv[1].get("seen") or 0))[:CACHE_MAX_FILES]
            cache["files"] = dict(keep)
        _save_json(cache_path, cache)

    tot_tok = sum(a["tokens"] for a in accounts)
    tot_req = sum(a["requests"] for a in accounts)
    dwell = [s["end"] - s["start"] for s in segs]
    out = {
        "ok": True,
        "generated_at": now,
        "window": {"start": start, "end": end, "hours": hours},
        "accounts": accounts,
        "segments": segs,
        "markers": [{"acc": a, "t": t, "kind": k} for (t, a, k) in markers],
        "events": _events(segs, markers)[:MAX_EVENTS],
        "log": [{"t": t, "text": b} for (t, b) in sorted(log_lines, reverse=True)[:200]],
        "kpi": {
            "tokens": tot_tok,
            "requests": tot_req,
            "avg_tokens": (tot_tok / tot_req) if tot_req else 0,
            "rotations": max(0, len(segs) - 1),
            "avg_dwell": (sum(dwell) / len(dwell)) if dwell else 0,
            "cool_429": sum(1 for (_t, _a, k) in markers if k == "cool_429"),
            # ★ 「Pro 保底接管」单独成一个 KPI:它等价于「Plus 池干了多久」,
            #   而那是这一页唯一需要用户采取行动的信号。
            "pro_segs": sum(1 for x in segs if x["enter_reason"] == "pro_fallback"),
            "pro_secs": sum(x["end"] - x["start"] for x in segs if x["enter_reason"] == "pro_fallback"),
            "stream_err": sum(1 for (_t, _a, k) in markers if k == "stream_err"),
        },
        # ★★ 诚实度。UI **必须**据此区分「这段时间没流量」「我们没看到」「只归属到了一部分」。
        #    `attributed_pct` 尤其重要:合计 token 是**下界**不是总量,直连 codex 的请求
        #    根本不经过代理,永远不会出现在这里。
        "coverage": {
            "responses_seen": len(resp_owner),
            "responses_with_tokens": matched,
            "responses_unplaced": orphan,
            "attributed_pct": (matched / len(resp_owner)) if resp_owner else None,
            "undated_lines": undated,
            "in_window_lines": in_window,
            "tail_truncated": truncated,
        },
    }
    if use_cache:
        # ★ 成品快照按窗口分键:UI 打开时先画它(读盘 ~1ms),再后台重扫。
        #   用户报的「太卡」就是没有这一步 —— 每次进页面都同步等 0.9~3.3s。
        snap = _load_json(os.path.join(store, SNAP_NAME), {})
        snap[str(int(hours)) if float(hours).is_integer() else str(hours)] = out
        _save_json(os.path.join(store, SNAP_NAME), snap)
    return out


def _events(segs, markers):
    """轮换事件 = 切换/故障转移 + 冷却 + 断流,新→旧。

    ★ 文案里带上一个号的**驻留时长 / token / 请求数**(稿子 §4)——「为什么切」离开
      「切之前它干了多少活」就没法判断轮换是不是合理。
    """
    REASON = {"cool_429": "429 冷却 → 故障转移", "stream_err": "断流 → 轮换",
              "quota_rotate": "额度轮换", "window_start": "窗口起点",
              "pro_fallback": "**Plus 全部不可用 → Pro 保底接管**"}
    MARK_TEXT = {
        "cool_429": "429 → cooled [{}], failing over",
        "stream_err": "stream err [{}] · 已 200 后断流,**已计费**",
        # ★ 最贵的一类:请求已交给上游、到没到不可知 ⇒ 可能已经计过费。
        "billed_unknown": "committed [{}] · 已送出、结果不可知 ⇒ **可能已计费**",
        "safe_switch": "send err [{}] · 未完整送达 ⇒ 未计费,换号安全",
    }
    evs = []
    for i, s in enumerate(segs):
        if i == 0:
            continue
        p = segs[i - 1]
        is429 = s["enter_reason"] == "cool_429"
        evs.append({
            "t": s["start"],
            "type": "failover" if is429 else "switch",
            "from": p["acc"], "to": s["acc"],
            "reason": s["enter_reason"],
            "text": "{} → {} · {} · 上号 {} / {} / {} 次".format(
                p["acc"], s["acc"], REASON.get(s["enter_reason"], s["enter_reason"]),
                _dur(p["end"] - p["start"]), _fmt_tok(p["tokens"]), p["requests"]),
            "accs": [p["acc"], s["acc"]],
        })
    for t, a, k in markers:
        evs.append({
            "t": t, "type": k, "from": a, "to": None, "reason": k, "accs": [a],
            "text": MARK_TEXT.get(k, "{} [{}]".format(k, "{}")).format(a),
        })
    evs.sort(key=lambda e: -e["t"])
    return evs


def _dur(secs):
    m = int(secs // 60)
    h, mm = divmod(m, 60)
    return ("{}h".format(h) if h else "") + ("{}m".format(mm) if mm or not h else "")


def _fmt_tok(n):
    if n >= 1e9:
        return "{:.2f}B".format(n / 1e9)
    if n >= 1e8:
        return "{:.0f}M".format(n / 1e6)
    if n >= 1e6:
        return "{:.1f}M".format(n / 1e6)
    if n >= 1e3:
        return "{:.0f}K".format(n / 1e3)
    return str(int(n))


if __name__ == "__main__":
    import sys
    hrs = 24.0
    for i, a in enumerate(sys.argv[1:]):
        if a == "--hours" and i + 2 <= len(sys.argv) - 1:
            hrs = float(sys.argv[i + 2])
    sys.stdout.write(json.dumps(collect(hrs), ensure_ascii=False))
