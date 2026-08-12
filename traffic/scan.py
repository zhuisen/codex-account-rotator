#!/usr/bin/env python3
"""多 AI 流量总览的统一扫描器 —— Claude / Codex / Grok / Kimi 四家 + OpenClaw **宿主源**
(宿主自己不是平台:按模型名把每条记录回流到真正的平台,可再分出 DeepSeek / MiMo),读本机 CLI 落盘记录。

    scan.py [--days N] [--json] [--no-cache] [--only k1,k2] [--exclude k1]

**全部本地只读、不联网、不消耗任何额度。**各家的 transcript 都是它们自己写在硬盘上的。

★★ 三家的 token 语义**不一样**,不归一就是整块数字错位(实测 2026-08-09):

      codex :  total_tokens = input + output,  cached_input_tokens **⊆** input
      Grok  :  totalTokens  = input + output,  cachedReadTokens    **⊆** input
      Claude:  无 total 字段;input / cache_read / cache_creation **三者并列**(实测
               input=1 而 cache_read=27,086 —— input 本就只是未命中那部分)

   所以统一归到**四个不相交的类**再相加,四类之和才可跨平台比较:

      uncached_in | cache_read | cache_write | output

   归一后 codex/Grok 的 Σ四类 == 它们原生的 total_tokens(恒等,已验),与旧
   `codex-rotate tokens` 的数字不产生断层。

★ Claude **必须全局按 `message.id` 去重**,朴素求和虚高 2.23x:一次响应按 content block 拆成多行、
  每行带同一份 usage(文件内);会话 resume/fork 复制历史(跨文件 1.6%,per-file 去重挡不住)。
  ★ 「codex 无重复」**已作废**(2026-08-12):codex 把同一个 `token_count` 事件写两遍,现按累计值
  `total_token_usage.total_tokens` 去重,详见 `_scan_codex_file`。Grok 按 `prompt_id` 实测无重复
  (64/64 唯一);OpenClaw 按 `responseId`(虚高 4.08x)。

★ 缓存只存**原始 epoch**,日期/小时一律在聚合层现算。缓存键是 (mtime,size) 不含时区 —— 存派生日期
  的话,换一次 TZ(launchd 默认环境 / CI / export TZ)就会让不再变动的文件永久保留旧时区的桶,
  两种口径混进同一张图且不自愈。同理日期换算**不按 UTC 整小时记忆化**:+05:30 这类半小时偏移的
  本地午夜落在整点小时中间,会把两天折叠成一天。
"""

import json
import os
import re
import sys
import tempfile
import time
from calendar import timegm
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

HOME = Path.home()
CLAUDE_ROOT = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (HOME / ".claude")) / "projects"
CODEX_ROOT = Path(os.environ.get("CODEX_HOME") or (HOME / ".codex")) / "sessions"
GROK_ROOT = Path(os.environ.get("GROK_HOME") or (HOME / ".grok")) / "sessions"
KIMI_ROOT = Path(os.environ.get("KIMI_HOME") or (HOME / ".kimi-code")) / "sessions"
CACHE = Path(__file__).resolve().parent.parent / ".traffic-cache.json"

CACHE_V = 1
# ★ 改任何 _scan_* 的解析逻辑(改变 rows 里存什么/怎么算)必须 +1,否则那些此生不再变 mtime 的文件
#   会永远沿用旧结果,产出一份新旧混血、无法察觉的数据集。
PARSER_V = 3          # +1 于 2026-08-12:codex 累计值去重;接入 OpenClaw 并按 AI 平台路由(row 多一位)

_DATED = re.compile(r"-\d{8}$")          # claude-haiku-4-5-20251001 -> claude-haiku-4-5

# rows 元素: [epoch, model, uncached_in, cache_read, cache_write, output]
IDX_EPOCH, IDX_MODEL, IDX_IN, IDX_CR, IDX_CW, IDX_OUT = range(6)


# ---------------------------------------------------------------- 缓存

def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return {}
    # 形状不对当 cache miss:只 catch OSError/ValueError 挡不住「语法合法但结构异常」的文件
    # (半截写入 / 别的工具写进来 / 格式演进),那会在下面 .get 时 AttributeError 打死整次扫描。
    if not isinstance(c, dict) or c.get("v") != CACHE_V or c.get("pv") != PARSER_V:
        return {}
    f = c.get("files")
    return f if isinstance(f, dict) else {}


def _save_cache(files):
    tmp = None
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(CACHE.parent), prefix=f".{CACHE.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"v": CACHE_V, "pv": PARSER_V, "files": files}, fh,
                      ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, CACHE)
    except Exception:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        # 缓存只是加速手段,写不进去不该让统计失败。


def _iso_epoch(ts):
    """`2026-08-09T01:23:45.678Z` -> epoch 秒。不做时区换算(见模块 docstring)。"""
    try:
        return timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]),
                       int(ts[11:13]), int(ts[14:16]), int(ts[17:19]), 0, 0, 0))
    except (ValueError, IndexError):
        return None


def _num(d, key):
    v = d.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


# ---------------------------------------------------------------- 各平台解析

def _scan_claude_file(path):
    """-> {message_id: row}。用 dict 是因为 Claude **必须**全局按 message.id 去重。"""
    rows = {}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return rows
    with fh:
        for line in fh:
            if '"usage"' not in line:          # 预过滤:绝大多数行是 user/attachment/system
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            # 逐层 isinstance,不能用 `or {}` —— 那只挡 None/假值,挡不住非 dict 的真值,
            # 一行 {"message":"unexpected"} 就能 AttributeError 打死整次扫描。
            if not isinstance(o, dict) or o.get("type") != "assistant":
                continue
            m = o.get("message")
            if not isinstance(m, dict):
                continue
            u, mid, ts = m.get("usage"), m.get("id"), o.get("timestamp")
            if not isinstance(u, dict) or not isinstance(mid, str) or not isinstance(ts, str):
                continue
            i = _num(u, "input_tokens")                    # Anthropic:本就只是未命中部分
            cr = _num(u, "cache_read_input_tokens")
            cw = _num(u, "cache_creation_input_tokens")
            out = _num(u, "output_tokens")
            if not (i or cr or cw or out):
                continue                                   # `<synthetic>` 等本地占位,四项全 0
            ep = _iso_epoch(ts)
            if ep is None:
                continue
            model = m.get("model")
            rows[mid] = [ep, _DATED.sub("", model if isinstance(model, str) else "unknown"),
                         i, cr, cw, out]
    return rows


def _scan_codex_file(path):
    """-> [row]。

    ★ **同一个 `token_count` 事件会被写两遍**(2026-08-12 实测):形态是 `(last, total)` 成对重复,
    而累计值单调不降 —— 所以是重复写入,不是会话续接。旧注释"codex 无重复"据此作废,
    `SOURCES` 的 `dedup: False` 也仅指**跨文件**(3618 个文件 ↔ 3618 个会话 uuid,一文件一会话)。

    ⚠️ **别引用单一的"虚高 N 倍" —— 重复是重尾的,倍数完全取决于窗口**。测法必须是拿 git 里的
    旧解析器与新解析器**各跑一遍真代码**(自己另写一个"朴素求和"来对比会得到 2.73x,是错的):
      · 全量 3619 个 rollout(含历史)  旧/新 = **1.421**,下调 29.6% —— 单个文件贡献了 38% 的重复量
      · **90 天窗口(app 实际显示的档)  旧/新 = 1.069,下调 6.5%** ← 用户看到的变化是这个
      · 早先按 300 个抽样报过 12.4%,那只是第三个窗口,不是"真值"

    去重键是 **`total_token_usage.total_tokens`**(单调递增的累计值,每个值只该出现一次),
    不是内容哈希 —— 两轮恰好用掉一样多 token 是常事,按内容去重会误删真实记录。
    验证:300 个 rollout 抽样,去重后「Σ增量 == 最终累计」**181/181 零例外**。
    拿不到累计值时**保留该条**(fail-open):宁可偏高,不可静默丢数据。

    模型按 **ordinal 顺序**归属到最近一次 `turn_context` —— 实测 310 个文件里有 5 个中途换过模型,
    按会话整体归会错。"""
    rows, cur = [], None
    seen_cum = set()          # 本文件内已记过的累计值 —— 见 docstring
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return rows
    with fh:
        for line in fh:
            if '"turn_context"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("type") == "turn_context":
                    m = (d.get("payload") or {}).get("model")
                    if isinstance(m, str) and m:
                        cur = m
                continue
            if '"token_count"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            pl = d.get("payload")
            if not isinstance(pl, dict) or pl.get("type") != "token_count":
                continue
            info = pl.get("info")
            lt = (info or {}).get("last_token_usage") if isinstance(info, dict) else None
            if not isinstance(lt, dict) or not _num(lt, "total_tokens"):
                continue
            ep = _iso_epoch(d.get("timestamp") or "")
            if ep is None:
                continue
            # ★ 按累计值去重。`None` 时不去重(fail-open),见 docstring。
            tt = info.get("total_token_usage") if isinstance(info, dict) else None
            cum = tt.get("total_tokens") if isinstance(tt, dict) else None
            if cum is not None:
                if cum in seen_cum:
                    continue
                seen_cum.add(cum)
            raw_in = _num(lt, "input_tokens")
            cr = _num(lt, "cached_input_tokens")           # ⊆ input(OpenAI 语义)
            cw = _num(lt, "cache_write_input_tokens")      # 实测该端点恒 0
            rows.append([ep, cur or "unknown",
                         max(0, raw_in - cr - cw), cr, cw, _num(lt, "output_tokens")])
    return rows


def _scan_grok_file(path):
    """-> [row]。每条 usage = 一个 prompt(自带 modelUsage 分模型拆分),实测 prompt_id 全唯一。"""
    rows = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return rows
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            ep = o.get("timestamp")                        # Grok 直接给 epoch 秒
            if not isinstance(ep, (int, float)):
                continue
            upd = (o.get("params") or {}).get("update") if isinstance(o.get("params"), dict) else None
            u = upd.get("usage") if isinstance(upd, dict) else None
            if not isinstance(u, dict):
                continue
            mu = u.get("modelUsage")
            # 有 modelUsage 就按模型拆开记,拿不到就整条归 unknown
            per = mu if isinstance(mu, dict) and mu else {"unknown": u}
            for model, mv in per.items():
                if not isinstance(mv, dict):
                    continue
                raw_in = _num(mv, "inputTokens")
                cr = _num(mv, "cachedReadTokens")          # ⊆ input(同 OpenAI 语义)
                out = _num(mv, "outputTokens")
                if not (raw_in or out):
                    continue
                rows.append([int(ep), model if isinstance(model, str) else "unknown",
                             max(0, raw_in - cr), cr, 0, out])
    return rows



def _scan_kimi_file(path):
    """-> [row]。kimi 的 wire 日志,一个 `agents/<agent>/wire.jsonl` 一个代理。

    ★★ **只认 `type == "usage.record"` 且 `usageScope == "turn"`**,三条都是实测定的
    (2026-08-09,75 个 wire.jsonl / 1745 条):

    1. **同一笔账记了两遍**。`usage.record`(1746 条)与 `event.type == "step.end"` 里的
       `event.usage`(1745 条)是同一批调用,四类逐项**零差**。两个都加 = 虚高一倍。选
       `usage.record` 是因为它多带 `model` 和 `usageScope`,`step.end` 里没有模型名。
       (与 codex 那边「取 `last_token_usage` 不取 `total_token_usage`」是同一个形状的坑。)
    2. **`usageScope` 里混着累计口径**:1745 条 `turn` + **1 条 `session`**。那条 session 是
       整个会话的累计,不滤掉就把它重复计一遍 —— 滤掉之后与 `step.end` 四类逐项对上,零差。
    3. **四个字段本来就互不相交**(`inputOther | inputCacheRead | inputCacheCreation | output`),
       与 Claude 同族、与 codex/Grok 相反(那两家的缓存读**含在** input 里要减)。**别在这里做减法。**

    另外两条实测结论:
    - `main` 与 `agent-N` 的 wire 日志 **uuid 零交集**(1388 / 357),主代理日志不含子代理的步骤,
      所有文件直接相加即可,不会重复。
    - `time` 是 epoch **毫秒**,不是秒。
    """
    rows = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return rows
    with fh:
        for line in fh:
            if '"usage.record"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("type") != "usage.record":
                continue
            # 累计口径的那条必须丢。将来若出现新的 scope 取值,一律按"不是 turn 就不认"处理 ——
            # 宁可漏记也不能把累计值混进逐笔求和。
            if o.get("usageScope") != "turn":
                continue
            ms = o.get("time")
            u = o.get("usage")
            if not isinstance(ms, (int, float)) or not isinstance(u, dict):
                continue
            i = _num(u, "inputOther")
            cr = _num(u, "inputCacheRead")
            cw = _num(u, "inputCacheCreation")
            out = _num(u, "output")
            if not (i or cr or cw or out):
                continue
            model = o.get("model")
            rows.append([int(ms / 1000), model if isinstance(model, str) else "unknown",
                         i, cr, cw, out])
    return rows


# ---------------------------------------------------------------- 平台注册表
#
# ★ **加一家 = 写一个 `_scan_*` + 在这里加一行**,前端不用动:平台名、配色、是否可用都从这份
#   注册表随扫描结果一起输出,UI 照着渲染(`theme.ts` 只留兜底色)。
#
# ⚠️ **解析器必须一家一写,这部分不该自动化**。实测四家是四种完全不同的形状:Claude 三个 input
#   字段互不相交、codex/Grok 的缓存读**含在** input 里、kimi 自带四类还混着一条累计记录。
#   写个"通用适配器"去猜字段名,正是会静默算错数的做法 —— 宁可每家多写 30 行。
#
# 停用某家:`--exclude grok`,或在 `traffic/sources.local.json` 写 {"disabled": ["grok"]}
# (该文件 gitignored,是本机偏好不是仓库配置)。停用后它不出现在输出里,UI 上自然消失。
OPENCLAW_ROOT = Path(os.environ.get("OPENCLAW_HOME") or (HOME / ".openclaw")) / "agents"

# 宿主内**路由出来**的平台。OpenClaw 自己不是平台(用户 2026-08-12 定稿:「openclaw 不算平台,
# 但是涉及的对应 ai 平台也要纳入计算」)—— 它是宿主,里面跑的 AI 各归各家。
ROUTED = {
    "deepseek": {"name": "DeepSeek", "color": "#4d6bfe"},
    "mimo":     {"name": "MiMo",     "color": "#ff6a00"},
}


def _openclaw_platform(provider, model):
    """把一条 OpenClaw 记录归到它真正的 AI 平台。

    ★ **按模型名判,不按 provider 判**。本机的 provider 是 `xiaomi` / `huohuo` / `deepseek` ——
    `huohuo` 跑的是 gpt-5.4/5.5(那是账号昵称,不是厂商),按 provider 归会造出一个叫 huohuo 的
    假平台。模型名才带厂商信息。
    认不出时回落到 provider 名:**宁可多一个名字奇怪的平台,也不静默丢数据**。
    """
    m = (model or "").lower()
    if "deepseek" in m:                          return "deepseek"
    if "mimo" in m:                              return "mimo"
    if m.startswith(("gpt", "o1", "o3", "o4")):  return "codex"     # 并入 Codex 平台
    if "claude" in m:                            return "claude"
    if "grok" in m:                              return "grok"
    if "kimi" in m:                              return "kimi"
    return (provider or "unknown").lower()


def _scan_openclaw_file(path):
    """-> {responseId: row}。row 末尾多带一个**平台键**,聚合层据此路由。

    ★ **去重键是 `responseId`**(2026-08-12 全量实测):29506 条 usage 记录只有 4203 个不同的
    responseId,朴素求和虚高 **4.08x** —— trajectory/checkpoint 存的是 `messagesSnapshot`,
    每一步把之前所有消息连同 usage 重发一遍,一条最多重复 306 次。零缺失,同 id 的 total
    100% 一致,所以合并无歧义。故本源 `dedup: True`(跨文件全局按 id 合并)。

    ★ 口径:`totalTokens == input + output + cacheRead + cacheWrite`,**4203/4203 零反例**
    ⇒ 四类互不相交,**不做减法**(与 Claude/Kimi 同族,与 codex/Grok 相反)。

    ⚠️ **必须排除 `*.jsonl.bak-*`**:本机 2663 个滚动备份共 14.4GB。抽样 60 个/350MB 实测
    「备份里独有的 responseId = 0」⇒ 跳过不丢数据,但**加进来会把同一笔账算上百遍**。
    glob 用 `*/sessions/*.jsonl`,备份名以 `.bak-<num>` 结尾,天然不匹配。
    """
    rows = {}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return rows

    def walk(o, model=None, provider=None, ts=None):
        if isinstance(o, dict):
            m = o.get("model") or model
            pv = o.get("provider") or provider
            t = o.get("timestamp") or ts
            u = o.get("usage")
            rid = o.get("responseId")
            if isinstance(u, dict) and u.get("totalTokens") and rid:
                ep = None
                if isinstance(t, str):
                    ep = _iso_epoch(t)
                elif isinstance(t, (int, float)):
                    ep = t / 1000.0 if t > 1e11 else float(t)     # 毫秒 → 秒
                if ep is not None:
                    rows[rid] = [ep, str(m or "unknown"),
                                 u.get("input") or 0, u.get("cacheRead") or 0,
                                 u.get("cacheWrite") or 0, u.get("output") or 0,
                                 _openclaw_platform(pv, m)]
            for v in o.values():
                walk(v, m, pv, t)
        elif isinstance(o, list):
            for v in o:
                walk(v, model, provider, ts)

    with fh:
        for line in fh:
            line = line.strip()
            if not line or '"usage"' not in line:
                continue
            try:
                walk(json.loads(line))
            except ValueError:
                continue
    return rows


SOURCES = (
    {"key": "claude", "name": "Claude", "root": CLAUDE_ROOT, "color": "#E0784F",
     "glob": "**/*.jsonl",         "parse": _scan_claude_file, "dedup": True},
    {"key": "codex",  "name": "Codex",  "root": CODEX_ROOT,  "color": "#2dd4bf",
     "glob": "**/rollout-*.jsonl", "parse": _scan_codex_file,  "dedup": False},
    {"key": "grok",   "name": "Grok",   "root": GROK_ROOT,   "color": "#8b7cf6",
     "glob": "*/*/updates.jsonl",  "parse": _scan_grok_file,   "dedup": False},
    {"key": "kimi",   "name": "Kimi",   "root": KIMI_ROOT,   "color": "#f472b6",
     "glob": "**/wire.jsonl",      "parse": _scan_kimi_file,   "dedup": False},
    # ★ OpenClaw 是**宿主**,不是平台:它 parse 出来的每条 row 末尾自带平台键,聚合层据此路由。
    #   `key` 只用于 enabled/registered 列表,不会作为平台出现在输出里。
    {"key": "openclaw", "name": "OpenClaw", "root": OPENCLAW_ROOT, "color": "#8b8b8b",
     "glob": "*/sessions/*.jsonl", "parse": _scan_openclaw_file, "dedup": True, "host": True},
)

SRC_META = {s["key"]: {"name": s["name"], "color": s["color"]} for s in SOURCES}

LOCAL_CFG = Path(__file__).resolve().parent / "sources.local.json"


def _enabled_sources(only=None, exclude=None):
    """按 CLI 参数 + 本机配置过滤注册表。三者取交集,CLI 优先级最高。"""
    disabled = set(exclude or ())
    if not only:
        try:
            cfg = json.loads(LOCAL_CFG.read_text(encoding="utf-8"))
            disabled |= set(cfg.get("disabled") or ())
        except (OSError, ValueError):
            pass          # 没有配置文件是常态,不是错误
    picked = [s for s in SOURCES if s["key"] not in disabled]
    if only:
        picked = [s for s in picked if s["key"] in set(only)]
    return picked


# ---------------------------------------------------------------- 聚合

def _blank():
    return {"uncached_in": 0, "cache_read": 0, "cache_write": 0, "output": 0,
            "total": 0, "rounds": 0, "models": {}}


def _add(b, model, i, cr, cw, out):
    t = i + cr + cw + out
    b["uncached_in"] += i; b["cache_read"] += cr; b["cache_write"] += cw
    b["output"] += out; b["total"] += t; b["rounds"] += 1
    m = b["models"].get(model)
    if m is None:
        m = b["models"][model] = {"uncached_in": 0, "cache_read": 0, "cache_write": 0,
                                  "output": 0, "total": 0, "rounds": 0}
    m["uncached_in"] += i; m["cache_read"] += cr; m["cache_write"] += cw
    m["output"] += out; m["total"] += t; m["rounds"] += 1


def scan(days=90, use_cache=True, only=None, exclude=None):
    cached = _load_cache() if use_cache else {}
    cut = time.time() - max(days, 90) * 86400
    fresh = {}
    scanned = reused = 0
    out = {}
    acc = {}            # 平台键 -> (days_b, hours_b);跨源累积
    seen_roots = {}
    now_ts = time.time()
    localtime, strftime = time.localtime, time.strftime
    # 用 date 做日期回退,不是 now-off*86400 —— 跨 DST 的地区一天不等于 86400 秒,
    # 那样算会漏掉或重复一天(本机 +08 无 DST,但这条不该依赖部署地)。
    end_date = _date.fromtimestamp(now_ts)
    today = end_date.isoformat()

    for src in _enabled_sources(only, exclude):
        key, name, root = src["key"], src["name"], src["root"]
        pattern, parse, dedup = src["glob"], src["parse"], src["dedup"]
        merged, seq = {}, []
        if root.is_dir():
            for f in sorted(root.rglob(pattern) if "**" in pattern else root.glob(pattern)):
                try:
                    st = f.stat()
                except OSError:
                    continue
                if st.st_mtime < cut:
                    continue
                ck = str(f)
                sig = [int(st.st_mtime), st.st_size]
                hit = cached.get(ck)
                if hit and hit.get("sig") == sig:
                    data = hit.get("r"); reused += 1
                else:
                    data = parse(f); scanned += 1
                fresh[ck] = {"sig": sig, "r": data}
                if dedup:
                    if isinstance(data, dict):
                        # 全局按 id 合并。冲突取 token 总量大者而非后来者覆盖 —— 实测跨文件重复里
                        # 有一类是「一份四项全 0 / 一份真实值」(fork 副本没带上 usage),靠字典序
                        # 赌一个会随遍历顺序变。
                        for mid, row in data.items():
                            prev = merged.get(mid)
                            if prev is None or sum(row[IDX_IN:IDX_OUT + 1]) > sum(prev[IDX_IN:IDX_OUT + 1]):
                                merged[mid] = row
                elif isinstance(data, list):
                    seq.extend(data)

        for row in (merged.values() if dedup else seq):
            ep, model, i, cr, cw, o = row[:6]
            # ★ row 可带第 7 位 = **平台键**。宿主型源(OpenClaw)靠它把每条记录路由到真正的
            #   AI 平台 —— 宿主自己不作为平台出现。普通源没这一位,就归自己。
            pk = row[6] if len(row) > 6 else key
            days_b, hours_b = acc.setdefault(pk, ({}, {}))
            lt = localtime(ep)
            d = strftime("%Y-%m-%d", lt)
            b = days_b.get(d)
            if b is None:
                b = days_b[d] = _blank()
            _add(b, model, i, cr, cw, o)
            if d == today:                                  # 今日视图按小时,只需当天
                h = strftime("%Y-%m-%dT%H", lt)
                hb = hours_b.get(h)
                if hb is None:
                    hb = hours_b[h] = _blank()
                _add(hb, model, i, cr, cw, o)

        # ★ 按**自然日窗口**切,不是「最后 N 个有数据的日期」。后者是新旧扫描器共有的缺陷:
        # 实测 mtime 窗口内 codex 有 113(UTC)/116(本地) 个不同日期、最早回到 2026-04-07,
        # `[-90:]` 切掉的是 4 月那 20 多天(约 10 亿 token);而 UTC 与本地的"日期个数"不同,
        # 切掉的天数就不同 —— 同一批数据的总量会随时区变(实测差 3.2%)。
        # 缺数据的日期**补零**:面积图按下标等距布点,不补零会把 3 天空档画成相邻两点,
        # 把"那几天没跑"抹成一段平滑上升,同时让"日均"的分母偏小。
        seen_roots[key] = root.is_dir()

    # 出表放在**所有源之后**:一个平台可能由多个源汇入(OpenClaw 里的 gpt 并进 Codex),
    # 边扫边写 `out[key]` 会让后写的覆盖先写的。
    cur_h = int(strftime("%H", localtime(now_ts)))
    for pk, (days_b, hours_b) in acc.items():
        picked = {}
        for off in range(days - 1, -1, -1):
            d = (end_date - _timedelta(days=off)).isoformat()
            picked[d] = days_b.get(d) or _blank()
        hours = {f"{today}T{h:02d}": (hours_b.get(f"{today}T{h:02d}") or _blank())
                 for h in range(cur_h + 1)}
        meta = SRC_META.get(pk) or ROUTED.get(pk) or {"name": pk, "color": None}
        out[pk] = {"name": meta["name"], "color": meta.get("color"),
                   "days": picked, "hours": hours,
                   "available": seen_roots.get(pk, True)}

    if use_cache and not (scanned == 0 and len(fresh) == len(cached)):
        _save_cache(fresh)
    # ★ 把"这一次实际启用了哪些源"记进结果。快照是会被落盘复用的成品,不记这个的话,
    #   一旦某次扫描少了一家(临时 --exclude、sources.local.json 没删干净、根目录暂时不可读),
    #   事后完全无法判断是"当时被停用了"还是"解析器坏了"—— 2026-08-09 就吃过一次这个哑巴亏。
    return out, {"scanned": scanned, "reused": reused, "files": scanned + reused,
                 "enabled": [s["key"] for s in _enabled_sources(only, exclude)],
                 "registered": [s["key"] for s in SOURCES]}


# ---------------------------------------------------------------- CLI

def _fmt(n):
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.2f}{unit}"
    return str(int(n))


def main(argv):
    days, use_cache, as_json = 14, True, False
    only = exclude = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--days":
            if i + 1 >= len(argv):
                sys.exit("--days 后面要跟天数")
            days = max(1, int(argv[i + 1])); i += 1
        elif a == "--json":
            as_json = True
        elif a == "--no-cache":
            use_cache = False
        elif a in ("--only", "--exclude"):
            if i + 1 >= len(argv):
                sys.exit(f"{a} 后面要跟平台 key(逗号分隔): {','.join(x['key'] for x in SOURCES)}")
            vals = [x.strip() for x in argv[i + 1].split(",") if x.strip()]
            bad = [v for v in vals if v not in {x["key"] for x in SOURCES}]
            if bad:
                sys.exit(f"未知平台 {bad};已注册: {','.join(x['key'] for x in SOURCES)}")
            if a == "--only":
                only = vals
            else:
                exclude = vals
            i += 1
        else:
            sys.exit(f"未知参数: {a}")
        i += 1

    t0 = time.time()
    platforms, stat = scan(days=days, use_cache=use_cache, only=only, exclude=exclude)
    stat["elapsed_ms"] = int((time.time() - t0) * 1000)

    if as_json:
        print(json.dumps({"platforms": platforms, "scan": stat,
                          "generated_at": int(time.time())}, ensure_ascii=False))
        return 0

    print(f"全部 AI 消耗 · 近 {days} 天  (解析 {stat['scanned']} / 缓存 {stat['reused']} 文件, "
          f"{stat['elapsed_ms']}ms)\n")
    grand = 0
    for k, p in platforms.items():
        tot = sum(v["total"] for v in p["days"].values())
        rounds = sum(v["rounds"] for v in p["days"].values())
        grand += tot
        if not p["available"]:
            print(f"  {p['name']:<8} (未找到本地数据目录)")
            continue
        agg = {}
        for v in p["days"].values():
            for m, mv in v["models"].items():
                agg[m] = agg.get(m, 0) + mv["total"]
        top = sorted(agg.items(), key=lambda kv: -kv[1])[:3]
        print(f"  {p['name']:<8} {_fmt(tot):>9}  {rounds:>7,} 轮  "
              f"{len(p['days'])} 天  今日小时桶 {len(p['hours'])}")
        for m, v in top:
            print(f"      {m:<26} {_fmt(v):>9}  {v / max(1, tot) * 100:5.1f}%")
    print(f"\n  合计 {_fmt(grand)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
