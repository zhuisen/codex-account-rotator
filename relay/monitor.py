"""拉中转站的用量/余额。**只读,零计费。**

## ★★ 三个实测出来的坑,每一个都会让实现「随机地」坏掉

① **Cloudflare 按 User-Agent 封禁。** 不设 UA（Python 默认 `Python-urllib/3.x`）⇒
   **403 `error code: 1010`**;换任何自定义 UA ⇒ 200。2026-09-09 单变量对照:

       [403] 默认 (Python-urllib/3.12)   error code: 1010
       [200] codexbar-probe/1.0
       [200] curl/8.7.1
       [200] OpenAI/Python 1.0

   ⚠️ 这个 403 和「key 失效」长得一样,查错会直奔凭证去。所以 UA 是**前提不是礼貌**。

② **计费端点各家不一样,不许预设。** tokendun 是 `/usage`;one-api / new-api 系
   走 `/dashboard/billing/subscription` + `/dashboard/billing/usage`（本站实测 404）。
   所以要**探测**并把命中的那条记进配置。`usage_path=None` 表示「还没探测过」,
   它和「探测过、就是 /usage」**不是同一个状态**,不许合并。

③ **`cost` 与 `actual_cost` 是两个口径,差 3.85 倍。** 实测本站 2026-08-14→09-08:
   标价 `cost` $62.32 / 实扣 `actual_cost` $16.18。前者是牌价,后者是真金白银扣的。
   CodexBar 现有的「AI用量」页显示的是**按牌价折算的等效成本**,把这两个数堆进
   同一张图会直接骗人。本模块两个都返回,**永不相加、永不互相替代**。

## 为什么不用 requests

本仓的 python 依赖保持零外部包（`traffic/*` 同）。stdlib 的 urllib 够用,
且能显式控制 UA —— 恰好是坑 ① 要的。
"""
import json
import ssl
import time
import urllib.error
import urllib.request

from . import store

# ★ 任何非默认 UA 都能过闸（已实测三种）。带上版本便于对端排障。
# ★ 不写死版本号 —— 本仓刚把三处前端版本串改成运行期取值,这里别又埋一处。
USER_AGENT = "CodexBar (+https://github.com/zhuisen/codex-account-rotator)"
TIMEOUT = 25

# 探测顺序:把最常见的放前面。命中即记，之后直接走记下的那条。
BILLING_PATHS = [
    "/usage",                          # tokendun 系
    "/dashboard/billing/usage",        # one-api / new-api 系
    "/dashboard/billing/subscription",
]


def _get(base_url, path, key):
    """返回 (status, body_text)。网络层异常统一成 (None, 原因) —— 但**保留原因**,
    别把「连不上」和「404」压成同一个值。"""
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
        return None, f"{type(e).__name__}: {e}"


def test_connection(relay):
    """连通性测试 —— 打 `/models`,**不计费**。

    返回三态:`ok` / `auth`（401/403,凭证或 UA 问题）/ `unreachable`。
    ★ 401 和 403 要分开说:401 基本是 key 错;403 在本站实测是 Cloudflare 的 UA 闸,
      而我们已经带了 UA,所以再出 403 多半是对端策略变了 —— 两者的下一步动作不同。
    """
    st, body = _get(relay["base_url"], "/models", relay["key"])
    if st is None:
        return {"state": "unreachable", "detail": body}
    if st == 200:
        try:
            ids = sorted(m["id"] for m in json.loads(body).get("data", []))
        except Exception:
            ids = []
        return {"state": "ok", "models": ids, "model_count": len(ids)}
    if st in (401, 403):
        hint = "key 无效" if st == 401 else "被对端策略拒绝（本站曾是 Cloudflare 的 UA 闸,但我们已带 UA）"
        return {"state": "auth", "http": st, "detail": f"{hint}: {body[:200].strip()}"}
    return {"state": "unreachable", "http": st, "detail": body[:200].strip()}


def probe_billing_path(relay):
    """找出这家中转站的计费端点。返回命中的 path 或 None。

    ★ 只认「200 且能解析成 JSON 对象」。有的站对未知路径返回 200 + HTML,
      光看状态码会认错。"""
    for p in BILLING_PATHS:
        st, body = _get(relay["base_url"], p, relay["key"])
        if st != 200:
            continue
        try:
            d = json.loads(body)
        except Exception:
            continue
        if isinstance(d, dict):
            return p
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _rows(rows, key):
    """把 `daily_usage` / `model_stats` 的行归一化成前端**一定能渲染**的形状。

    ★★ 原来是**原样透传**,而前端直接 `d.date.slice(5)` / `m.total_tokens.toLocaleString()` /
       `d.actual_cost / max`。上游少一个字段就在 render 里抛异常,React 没有 error boundary
       ⇒ **整页白** —— 而白页和"还没有配置中转站"在用户眼里一样。
    ★ 缺 key 的行**丢掉**(它连标签都没有,画出来也没意义);数值缺失填 0 而不是 None,
      因为这两张表是"画出来的量",0 高的柱与不存在的柱视觉上就该一样。
      这与顶层 `balance`/`cost` 的「读不到给 None」不矛盾:那些是**读数**,要区分没读到;
      这些是**明细行**,行本身存在就说明有活动。
    ★ `date` 排序在这里做 —— `runway()` 取 `days[-7:]`,依赖顺序而上游没承诺过有序。
    """
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or not isinstance(r.get(key), str) or not r[key]:
            continue
        # ★★ **四类 token 必须留下**（2026-09-09 补）。原来只取 `total_tokens`，
        #    于是图上只能画一条没有内部结构的带。上游**每天**都给了这四个数
        #    (`input/output/cache_read/cache_write`)，丢掉它们等于自己把唯一可用的
        #    分解维度扔了。默认响应里 `daily_usage` 确实不带模型、`model_stats` 不带日期，
        #    但 **`?start_date=D&end_date=D` 是生效的**（2026-09-09 实测，见 `day_models`），
        #    逐日查一次就拿到「某天 × 某模型」。所以现在两个分解维度都有：
        #    四类 token（总量档）与按模型（分模型档）。
        # ⚠️ `cache_write` 上游的字段名在两张表里**不一样**：
        #    daily 叫 `cache_write_tokens`，models 叫 `cache_creation_tokens`。两个都认。
        out.append({key: r[key],
                    "requests": _num(r.get("requests")),
                    "total_tokens": _num(r.get("total_tokens")),
                    "input_tokens": _num(r.get("input_tokens")),
                    "output_tokens": _num(r.get("output_tokens")),
                    "cache_read_tokens": _num(r.get("cache_read_tokens")),
                    "cache_write_tokens": _num(r.get("cache_write_tokens")
                                               if r.get("cache_write_tokens") is not None
                                               else r.get("cache_creation_tokens")),
                    "cost": _num(r.get("cost")),
                    "actual_cost": _num(r.get("actual_cost"))})
    return sorted(out, key=lambda r: r[key]) if key == "date" else out


def normalize(raw):
    """把各家的响应压成一个稳定形状。**读不到的字段一律 `None`,绝不填 0。**

    「余额读不到」和「余额是 0」在这里是两件事:前者该显示「—」,后者该报警。
    本仓在额度那边栽过同一个坑（`_headroom` 读不到返回 None 而不是 0）。
    """
    g = lambda *ks: next((raw[k] for k in ks if isinstance(raw.get(k), (int, float))), None)
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    total = usage.get("total") if isinstance(usage.get("total"), dict) else {}
    today = usage.get("today") if isinstance(usage.get("today"), dict) else {}
    # ★ 显式按日期排序:`runway()` 取 `days[-7:]`,依赖顺序而上游没承诺过有序。
    days = _rows(raw.get("daily_usage"), "date")
    models = _rows(raw.get("model_stats"), "model")

    def money(d, k):
        v = d.get(k)
        return v if isinstance(v, (int, float)) else None

    return {
        "balance": g("balance", "remaining"),
        # ★ 读不到就 None,**不许默认 USD** —— 国内中转站不少按 CNY 或"额度"计,
        #   编一个 `$` 比留空糟得多(会让用户按错误的币种判断余额)。
        "unit": raw.get("unit") if isinstance(raw.get("unit"), str) else None,
        "plan": raw.get("planName") or raw.get("plan"),
        "valid": raw.get("isValid"),
        "mode": raw.get("mode"),
        # ★ 两个口径并列返回,调用方必须分栏显示。合并即撒谎。
        "today": {"cost": money(today, "cost"), "actual_cost": money(today, "actual_cost"),
                  "requests": today.get("requests"), "total_tokens": today.get("total_tokens")},
        "total": {"cost": money(total, "cost"), "actual_cost": money(total, "actual_cost"),
                  "requests": total.get("requests"), "total_tokens": total.get("total_tokens"),
                  "cache_read_tokens": total.get("cache_read_tokens")},
        "rpm": usage.get("rpm"),
        "tpm": usage.get("tpm"),
        "avg_ms": usage.get("average_duration_ms"),
        "daily": days,
        "models": models,
    }


def runway(norm):
    """「按最近的烧钱速度,余额还能撑几个活跃日」。

    ★ 分母用**有活动的日子**,不是自然日。中转站是「池子撞额度时才切过来」的备胎,
      按自然日平均会把 runway 算得虚高好几倍 —— 那是最不该乐观的一个数。
    ★ 样本 < 2 个活跃日就返回 None:两点才成线,一点连速度都算不出。
      读不到就说读不到,别给一个看着精确的假数。
    """
    bal = norm.get("balance")
    days = [d for d in norm.get("daily") or []
            if isinstance(d.get("actual_cost"), (int, float)) and (d.get("requests") or 0) > 0]
    if bal is None or len(days) < 2:
        return {"days": None, "per_active_day": None, "sample_days": len(days),
                "reason": "余额读不到" if bal is None else "活跃日样本不足 2 天"}
    recent = days[-7:]
    per = sum(d["actual_cost"] for d in recent) / len(recent)
    return {"days": (bal / per) if per > 0 else None, "per_active_day": per,
            "sample_days": len(recent), "reason": None}


# 一次刷新最多补拉多少天的「按模型」明细。★ 上界不是省流量，是**防第一次跑就打 90 个请求**：
# 历史日不可变、拉过一次就进快照，所以稳态下每次只多 1 个请求（今天）。
MAX_DAY_FETCH = 40


def day_models(relay, path, date):
    """某一天的 `model_stats`。-> list | None（None = 这次没拿到，**不是"这天没有模型"**）。

    ★★ 2026-09-09 实测：`/usage?start_date=D&end_date=D` **是生效的**，`model_stats`
       会跟着窗口变。逐日核对过 8 天，其中 7 天与 `daily_usage` 当天的 `total_tokens`
       **逐 token 相等**；唯一不等的是**今天**，两次 HTTP 之间用量还在涨（数值更大），
       是时间差不是数据缺陷。

    ⚠️ 我一度断言「中转站没有『每天 × 每模型』的交叉」并据此把整个按模型上色的图否掉了 ——
       那个结论只看了**默认响应**、没试参数。用一个看不见目标的探针得出"目标不存在"，
       与本仓记过两次的 grep 假阴性同族。留档防再犯。
    """
    st, body = _get(relay["base_url"], f"{path}?start_date={date}&end_date={date}", relay["key"])
    if st != 200:
        return None
    try:
        raw = json.loads(body)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return _rows(raw.get("model_stats"), "model")


def attach_day_models(relay, path, days, prev_days, today):
    """给每个 `daily` 行挂上 `models`。**历史日复用上一份快照，只重取今天。**

    ★ 历史日不可变 —— 拉过一次就永远是那个值。所以稳态每次刷新只多 **1** 个请求。
    ★ 拿不到的那天 `models` 留 **None** 而不是 `[]`：前端据此显示"这天没有按模型明细"，
      而 `[]` 会被画成"这天没用过任何模型"—— 又一次把「没读到」和「确实没有」折叠成一个值。
    """
    budget = MAX_DAY_FETCH
    for d in days:
        date = d.get("date")
        cached = prev_days.get(date)
        # 今天会变，必须重取；历史日有缓存就直接用。
        if cached is not None and date != today:
            d["models"] = cached
            continue
        if budget <= 0:
            d["models"] = cached          # 可能是 None —— 如实留空，不编造
            continue
        budget -= 1
        got = day_models(relay, path, date)
        d["models"] = got if got is not None else cached
    return days


def fetch(relay, remember_path=False, prev=None):
    """拉一次用量。返回 {ok, state, data|detail}。

    `remember_path=True` 时把探测到的计费路径写回配置 —— 下次不用再试三条。
    `prev` = 上一份快照里这个中转站的 `data`，用来复用历史日的按模型明细。
    """
    path = relay.get("usage_path")
    if not path:
        path = probe_billing_path(relay)
        if not path:
            return {"ok": False, "state": "no_billing_endpoint",
                    "detail": f"试过 {', '.join(BILLING_PATHS)},没有一条返回可解析的 JSON"}
        # ★★ **不在读路径里写配置。** monitor 与 UI 的 `set_relay` 是两个进程,
        #    各自 load→save 无锁 ⇒ 用户刚改的 label 会被监控进程用旧快照写回。
        #    原子写只保证文件完整,**不保证不丢更新**。探到的 path 放进返回值,
        #    由调用方(Rust 侧,单点)决定要不要落盘。
    st, body = _get(relay["base_url"], path, relay["key"])
    if st is None:
        return {"ok": False, "state": "unreachable", "detail": body}
    if st != 200:
        return {"ok": False, "state": "auth" if st in (401, 403) else "http_error",
                "http": st, "detail": body[:200].strip()}
    try:
        raw = json.loads(body)
    except Exception as e:
        return {"ok": False, "state": "bad_payload", "detail": str(e)}
    norm = normalize(raw)
    # ★ 逐日「按模型」明细。放在 runway 之前无所谓，但必须在返回之前 ——
    #   前端的图按模型分层就靠它。
    prev_days = {}
    for d in ((prev or {}).get("daily") or []):
        if isinstance(d, dict) and d.get("date") and d.get("models") is not None:
            prev_days[d["date"]] = d["models"]
    norm["daily"] = attach_day_models(
        relay, path, norm.get("daily") or [], prev_days,
        time.strftime("%Y-%m-%d", time.localtime()))
    norm["runway"] = runway(norm)
    norm["fetched_at"] = int(time.time())
    norm["usage_path"] = path
    # 调用方据此决定是否把探测结果落盘(monitor 自己不写,见上)。
    norm["usage_path_discovered"] = (path != relay.get("usage_path"))
    return {"ok": True, "state": "ok", "data": norm}


def merge_daily(prev_days, new_days):
    """把新旧两份 `daily` 按日期**并集**合并，同一天以新的为准。

    ★★ **只增不减。** 上游的窗口会滑动（今天回 8 天、明天可能只回 7 天），
    如果每次都用新结果整块替换，那些滑出窗口的日子就**从此消失** ——
    而用户看到的是"历史没了"，不是"上游这次没给"。
    """
    by_date = {}
    for d in (prev_days or []):
        if isinstance(d, dict) and d.get("date"):
            by_date[d["date"]] = d
    for d in (new_days or []):
        if not isinstance(d, dict) or not d.get("date"):
            continue
        old = by_date.get(d["date"])
        # ★ 新的那天若没取到按模型明细，**沿用旧的**，别把已有的抹成 None。
        if d.get("models") is None and old and old.get("models") is not None:
            d = {**d, "models": old["models"]}
        by_date[d["date"]] = d
    return [by_date[k] for k in sorted(by_date)]


def collect(prev=None):
    """给 UI 的入口:所有启用的中转站各拉一次。**key 绝不出现在返回值里。**

    `prev` = 上一份快照（`.relay-usage.json` 的内容）。两个用途：

    ① **复用历史日的按模型明细** —— 历史日不可变，拉过一次就不必再拉，
       稳态每次刷新只多 1 个请求（今天）。
    ② ★★ **让快照只增不减。** 这一条是用户反复提过的同一类问题：
       一次读不到（网络抖动 / 401 / 对端 5xx）不该把**上一次读到的**抹掉。
       所以取数失败时**保留旧 `data`** 并标 `stale`，`daily` 按日期并集合并。
       「这次没取到」和「确实没有」必须是两个可区分的状态 —— 前者显示旧数据 + 陈旧标记，
       后者才显示空。把它们折叠成一个值，就是用户看到的"用量丢失了"。
    """
    prev_by_id = {}
    for r in ((prev or {}).get("relays") or []):
        if isinstance(r, dict) and r.get("id") and isinstance(r.get("data"), dict):
            prev_by_id[r["id"]] = r["data"]
    out = []
    for r in store.load()["relays"]:
        old = prev_by_id.get(r["id"])
        if not r.get("enabled", True):
            # ★ 停用也别丢历史:用户重新启用时该看到之前的曲线,而不是从零开始。
            row = {"id": r["id"], "label": r.get("label"), "state": "disabled"}
            if old:
                row["data"] = old
            out.append(row)
            continue
        res = fetch(r, prev=old)
        if not res.get("ok") and old:
            # ★★ 失败**不清空**。带上旧数据 + `stale`,让 UI 能同时说
            #   "这是 HH:MM 的数据" 和 "刚才那次没取到,原因是 X"。
            res = {**res, "data": old, "stale": True,
                   "stale_since": old.get("fetched_at")}
        elif res.get("ok") and old:
            res["data"]["daily"] = merge_daily(old.get("daily"), res["data"].get("daily"))
        out.append({"id": r["id"], "label": r.get("label"),
                    "base_url": r["base_url"], "key_fp": store.fingerprint(r["key"]),
                    **res})
    # ★ 键名是 `fetched_at`,**不是** `generated_at` —— 仓库的 `HasFetchedAt`/
    #   `useQuotaSidecar` 认这个名字,Rust 的 `fresh_sidecar` 也用它。
    #   两边不一致时前端会**永远判过期**、每次进页都联网,而且不报错、只是费流量。
    #   **只留一个键**,别为了"兼容"两个都发 —— 那只是把漂移推迟到下一次。
    return {"relays": out, "route": store.route_status(), "fetched_at": int(time.time())}
