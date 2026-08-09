#!/usr/bin/env python3
"""Claude Code 的 token 消耗按天统计 —— 读本机 transcript,不联网、不消耗任何额度。

与 `codex-rotate tokens` 是同一类工具、同一套输出形状(所以 GUI 侧能复用面积图),但数据模型完全
不同,不共用代码。用法:

    claude_tokens.py [--days N] [--json] [--no-cache]

数据源 `~/.claude/projects/**/*.jsonl`(可用 CLAUDE_CONFIG_DIR 改根目录)。Claude Code 把每次
assistant 响应连同服务端返回的 `usage` 一起落盘,所以这里读到的就是账单口径的原始数字。

★★ 去重是这个脚本存在的全部理由 —— 朴素求和虚高 2.23x(实测 2026-08-09,84 天/1.97GB/5090 文件):

      usage 行 211,717  →  唯一响应 94,807

   两种重复,成因不同,必须都处理:

   1) **文件内重复 115,413 条**:Claude Code 把**一次** API 响应按 content block 拆成多行 JSONL
      (thinking 一行、tool_use 一行……),**每行都带完整且相同的 usage**。实证:9,254 个重复组里
      组内 usage 不一致的有 **0 个**。所以同一 `message.id` 只能计一次。

   2) **跨文件重复 1,497 条(占 1.6%)**:会话 resume / fork 会把历史复制进新文件,同一个
      `message.id` 因此出现在多个 .jsonl 里。**per-file 去重挡不住这类**,必须全局去重。
      ——这条直接决定了下面的缓存形状:缓存里存的是 per-file 的**逐条明细**而不是聚合值,因为
      聚合值一旦算出来就没法再把跨文件的那份减掉了。

★ 时区:transcript 的 timestamp 是 **UTC**(`2026-05-15T07:55:51.306Z`),本机是 +0800。直接切
  `ts[:10]` 会把本地 00:00–08:00 的活记到前一天。这里一律转**本地日期**再分桶。

★ `total` = input + output + cache_creation + cache_read。**cache_read 通常占大头**(Claude Code
  每轮重发完整历史,命中缓存后按 0.1x 计价)。所以这张图是「token 吞吐量」不是「等价成本」——
  不要拿 total 直接乘单价。分项都保留了,要算钱自己按各自费率加权。

★ subagent 计入总量(那是真花的钱),但单独拆出 `sub` 一项。实测占 46%,混在一起看不出主线消耗。
"""

import json
import os
import re
import sys
import tempfile
import time
from calendar import timegm
from pathlib import Path

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
PROJECTS = CLAUDE_HOME / "projects"
CACHE = Path(__file__).resolve().parent.parent / ".claude-tokens-cache.json"

# claude-haiku-4-5-20251001 -> claude-haiku-4-5。带日期后缀的和不带的是同一个模型,不归一就会在
# 图例里裂成两条带、两种颜色。
_DATED = re.compile(r"-\d{8}$")

# ★ 改这个函数(改变 rows 里存什么/怎么算)必须 +1,否则 5000+ 个此生不会再变 mtime 的文件会永远
#   沿用旧逻辑的结果,产出一份新旧混血、无法察觉的数据集。
PARSER_V = 1
CACHE_V = 2


def _epoch(ts):
    """UTC ISO 时间戳 -> epoch 秒。**不做时区换算** —— 见 scan() 里 _day() 的说明。"""
    try:
        return timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]),
                       int(ts[11:13]), int(ts[14:16]), int(ts[17:19]), 0, 0, 0))
    except (ValueError, IndexError):
        return None


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return {}
    # 形状不对当 cache miss —— 只 catch OSError/ValueError 挡不住「语法合法但结构异常」的文件
    # (半截写入、别的工具写进来、格式演进)。让它整份作废重扫,而不是在 156 行 AttributeError 崩掉。
    if not isinstance(c, dict) or c.get("v") != CACHE_V or c.get("pv") != PARSER_V:
        return {}
    f = c.get("files")
    return f if isinstance(f, dict) else {}


def _save_cache(files):
    # 紧凑写(约 12MB;带 indent 会涨到 40MB+ 且拖慢启动)。原子替换,避免半截文件被下次读到。
    tmp = None
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(CACHE.parent), prefix=f".{CACHE.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"v": CACHE_V, "pv": PARSER_V, "files": files}, f,
                      ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, CACHE)
    except Exception:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        # 缓存只是加速手段,写不进去不该让统计失败。


def _parse_file(path):
    """-> {msg_id: [epoch, model, is_sidechain, input, output, cache_creation, cache_read]}

    ★ 存 **epoch 而不是已换算的本地日期**。缓存键只有 (mtime, size),不含时区 —— 一旦以别的 TZ
    跑过一次(launchd 默认环境 / CI / 脚本里 export TZ),那批文件就永久保留旧时区的日期,而 5000+
    个此生不会再变 mtime 的文件永远不会被纠正,两种口径混进同一张图且不自愈。缓存里只放原始事实,
    派生值一律在聚合层现算。

    只对含 `"usage"` 的行做 json.loads —— transcript 里绝大多数行是 user/attachment/system,
    预过滤把全量扫描从分钟级压到 11s。"""
    rows = {}
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
            # ★ 逐层 isinstance 守卫,不能用 `or {}` —— 那只挡 None/假值,挡不住非 dict 的真值。
            #   一行 `{"type":"assistant","message":"unexpected","usage":{}}` 就能让 .get 抛
            #   AttributeError 把整次扫描打死,前端只剩一行 traceback,整页永久打不开。
            if not isinstance(o, dict) or o.get("type") != "assistant":
                continue
            m = o.get("message")
            if not isinstance(m, dict):
                continue
            u = m.get("usage")
            mid = m.get("id")
            ts = o.get("timestamp")
            if not isinstance(u, dict) or not isinstance(mid, str) or not isinstance(ts, str):
                continue

            def _n(key):
                v = u.get(key)
                return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0

            i, out = _n("input_tokens"), _n("output_tokens")
            cc, cr = _n("cache_creation_input_tokens"), _n("cache_read_input_tokens")
            if not (i or out or cc or cr):
                continue          # `<synthetic>` 等本地占位消息,四项全 0,不是 API 调用
            ep = _epoch(ts)
            if ep is None:
                continue
            model = m.get("model")
            rows[mid] = [ep, _DATED.sub("", model if isinstance(model, str) else "unknown"),
                         1 if o.get("isSidechain") else 0, i, out, cc, cr]
    return rows


def scan(days=90, use_cache=True):
    """-> (per_day, stat)。per_day[YYYY-MM-DD] = 各分项 + models + main/sub 拆分。"""
    cached = _load_cache() if use_cache else {}
    cut = time.time() - max(days, 90) * 86400
    fresh, merged = {}, {}
    scanned = reused = 0

    for f in sorted(PROJECTS.rglob("*.jsonl")):
        try:
            st = f.stat()
        except OSError:
            continue
        if st.st_mtime < cut:
            continue
        key = str(f)
        sig = [int(st.st_mtime), st.st_size]
        hit = cached.get(key)
        if hit and hit.get("sig") == sig:
            rows = hit.get("r") or {}
            reused += 1
        else:
            rows = _parse_file(f)
            scanned += 1
        fresh[key] = {"sig": sig, "r": rows}
        # ★ 全局按 message.id 合并,跨文件重复(1,497 条 / 1.6%)在这里消掉。
        #   **冲突时取 token 总量大的那份,而不是后来者覆盖**——实测 1,497 条里有 16 条两边不一致,
        #   形态全是「一份四项全 0 / 一份是真实值」(fork 出来的副本没带上 usage)。零值那份会被
        #   _parse_file 的零值过滤挡掉,所以 `update` 覆盖此刻也能得到对的数;但那是**碰巧**——
        #   那道过滤本是为 `<synthetic>` 写的,一旦格式变化就会退化成"按文件名字典序赌一个"。
        #   显式取大值让结果与遍历顺序无关,格式变了也不会静默选错。
        for mid, row in rows.items():
            prev = merged.get(mid)
            if prev is None or sum(row[3:]) > sum(prev[3:]):
                merged[mid] = row

    # 一个文件都没重新解析、且没有需要淘汰的旧条目 ⇒ 缓存内容与磁盘上那份逐字节相同,重写 8.6MB
    # 纯属白烧 ~350ms(实测热路径的最大单项)。`len` 相等即可判定:scanned==0 已保证 fresh 的每个
    # key 都在 cached 里且 sig 一致,那么只剩「cached 里有已删除文件的残留」这一种差异。
    if use_cache and not (scanned == 0 and len(fresh) == len(cached)):
        _save_cache(fresh)

    # ★ 日期在这里现算,而且**逐条算、不按小时记忆化**。原来按 `ts[:13]`(UTC 整小时)做 memo,
    #   在整点偏移时区成立,在 **+05:30 这类半小时偏移**下不成立:Asia/Kolkata 的本地午夜落在
    #   18:30Z,正好在 UTC 小时 18:00–18:59 的中间,同一个 memo 键里的两条记录分属两个本地日期,
    #   却会被折叠成先到的那一个 —— 结果还依赖文件遍历顺序。(三方评审在这条上分歧,codex 判对,
    #   已用 TZ=Asia/Kolkata + 18:20Z/18:40Z 实跑复现。)
    per_day = {}
    localtime, strftime = time.localtime, time.strftime
    for ep, model, sc, i, out, cc, cr in merged.values():
        day = strftime("%Y-%m-%d", localtime(ep))
        b = per_day.get(day)
        if b is None:
            b = per_day[day] = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0,
                                "total": 0, "turns": 0, "main": 0, "sub": 0, "models": {}}
        tot = i + out + cc + cr
        b["input"] += i
        b["output"] += out
        b["cache_creation"] += cc
        b["cache_read"] += cr
        b["total"] += tot
        b["turns"] += 1
        b["sub" if sc else "main"] += tot
        mb = b["models"].get(model)
        if mb is None:
            mb = b["models"][model] = {"total": 0, "turns": 0}
        mb["total"] += tot
        mb["turns"] += 1

    return per_day, {"scanned": scanned, "reused": reused,
                     "files": scanned + reused, "responses": len(merged)}


def _fmt(n):
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.2f}{unit}" if div == 1e9 else f"{n / div:.1f}{unit}"
    return str(int(n))


def main(argv):
    days, use_cache, as_json = 30, True, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--days":
            if i + 1 >= len(argv):
                sys.exit("--days 后面要跟天数")
            days = max(1, int(argv[i + 1]))
            i += 1
        elif a == "--json":
            as_json = True
        elif a == "--no-cache":
            use_cache = False
        else:
            sys.exit(f"未知参数: {a}")
        i += 1

    if not PROJECTS.is_dir():
        msg = f"找不到 {PROJECTS}(设 CLAUDE_CONFIG_DIR 可改根目录)"
        # scan 必须给全字段:前端把 scanned/reused 当必填读,给 {} 会渲染成「解析 undefined」。
        empty = {"scanned": 0, "reused": 0, "files": 0, "responses": 0, "elapsed_ms": 0}
        print(json.dumps({"days": {}, "scan": empty, "error": msg}, ensure_ascii=False)
              if as_json else msg)
        return 0 if as_json else 1

    t0 = time.time()
    per_day, stat = scan(days=days, use_cache=use_cache)
    stat["elapsed_ms"] = int((time.time() - t0) * 1000)
    picked = dict(sorted(per_day.items())[-days:])

    if as_json:
        print(json.dumps({"days": picked, "scan": stat}, ensure_ascii=False))
        return 0

    if not picked:
        print(f"没有 token 记录(检查 {PROJECTS})")
        return 0
    total = sum(v["total"] for v in picked.values())
    turns = sum(v["turns"] for v in picked.values())
    peak = max(v["total"] for v in picked.values()) or 1
    print(f"Claude Code token 消耗 · 近 {len(picked)} 天 · 合计 {total:,} · {turns:,} 轮 "
          f"(解析 {stat['scanned']} / 缓存 {stat['reused']} 文件, {stat['elapsed_ms']}ms)")
    for d, v in picked.items():
        bar = "█" * max(1, round(v["total"] / peak * 42))
        print(f"  {d}  {v['total']:>14,}  {bar}")
    cr = sum(v["cache_read"] for v in picked.values())
    cc = sum(v["cache_creation"] for v in picked.values())
    inp = sum(v["input"] for v in picked.values())
    out = sum(v["output"] for v in picked.values())
    sub = sum(v["sub"] for v in picked.values())
    print(f"  构成: 缓存读 {_fmt(cr)} ({cr / max(1, total) * 100:.0f}%) · "
          f"缓存写 {_fmt(cc)} · 输入 {_fmt(inp)} · 输出 {_fmt(out)}")
    print(f"  subagent {_fmt(sub)} ({sub / max(1, total) * 100:.0f}%) · "
          f"日均 {_fmt(total / max(1, len(picked)))} · 单轮均 {_fmt(total / max(1, turns))}")
    agg = {}
    for v in picked.values():
        for m, mv in v["models"].items():
            agg[m] = agg.get(m, 0) + mv["total"]
    print("  模型:")
    for m, val in sorted(agg.items(), key=lambda kv: -kv[1]):
        print(f"    {m:<24} {_fmt(val):>9}  {val / max(1, total) * 100:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
