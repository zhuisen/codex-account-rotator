#!/usr/bin/env python3
"""扫描本机还有哪些地方存着 AI token 用量 —— 给 CodexBar 设置页的「扫描新数据源」按钮用。

用法:discover.py [--json]

★ **它只产出体检报告,不会自动启用任何东西。**
   新增一家 = 在 `scan.py` 的 `SOURCES` 里写一个 `_scan_*` 解析器。这里做的是把「值不值得写、
   要按什么口径写」先测出来,把人从"翻目录猜字段"里解放出来 —— 而不是替人做那个判断。

★ 核心主张:**不猜字段含义,去验算术关系**。
   枚举字段子集,留下"在所有记录里都恰好等于 total"的那些:
     只有 {input, output} 成立   ⇒ 缓存**含在** input 里(codex/Grok/DeepSeek 族)→ 要减
     四类一起才成立              ⇒ 互不相交(Claude/Kimi/OpenClaw 族)          → 不减
     多组同时成立                ⇒ 差集字段在样本里恒为 0,**判不了**,如实报告
     一组都不成立                ⇒ 拒绝,报反例数

   这不是"通用适配器"(拿一套字段名去套所有家),而是**每家现场解一次方程**。
   `scan.py` 顶部那条禁令禁的是猜,不是测。

这一轮踩过、已固化进代码的三个采样偏差(每个都会让口径被误判):
  1. 按**大小**取样 → 取到老会话,缓存冷、cached 恒 0
  2. 读文件**头部**  → 取到对话开头,同样冷
  3. 只取**最近**的  → 早期用过、现在不用的模型整个消失(deepseek 就是这么被漏掉的)
现在:按 mtime 排序后**跨时间分层**取样,每个文件读**尾部**。
"""
import json
import os
import pathlib
import re
import sqlite3
import sys
from collections import Counter
from itertools import combinations

HOME = pathlib.Path.home()
MAX_FILES = 60           # 每个候选根目录采样的文件数
MAX_BYTES = 2_000_000    # 每个文件最多读尾部这么多
MIN_RECORDS = 20         # 少于这么多条不下结论

# 已注册的根目录 —— 报告里标"已注册",免得把自己已经在扫的东西当成新发现。
# ★ 光有 KNOWN 不够:一个源可能**已注册却被停用**,那它报「已注册」而实际根本没在扫,
#   用户没有第二个办法分辨。所以再带上 key 与 enabled —— 「已停用」正是唯一能安全自动启用的那类。
KNOWN_BY_ROOT = {}          # root -> key
ENABLED_KEYS = set()
try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from scan import SOURCES, _enabled_sources                 # noqa: E402
    KNOWN_BY_ROOT = {str(s["root"]): s["key"] for s in SOURCES}
    ENABLED_KEYS = {s["key"] for s in _enabled_sources()}
    KNOWN = set(KNOWN_BY_ROOT)
except Exception:                                              # 独立运行也要能用
    KNOWN = set()

# 备份/快照目录:和本体给出一模一样的判定,列出来只是噪音,还会诱导人把备份当成新平台。
BACKUPISH = re.compile(r"(backup|bak|rebuilt|snapshot|copy|old|archive|-\d{8})", re.I)
# 长得像 token 计数的键。**只用来"找到候选对象",不参与含义判定**。
#
# ★ 必须覆盖**两种词序**:后缀式 `input_tokens`(Claude/codex)与前缀式 `tokens_input`(opencode)。
#   早先只写了后缀式,于是 opencode 的 `tokens_input/tokens_cache_read` 一个都不匹配,
#   整个数据源被判成"没有用量"(用户 2026-08-12 指出它没被扫到)。
#   同时不能太松:`access_token` / `refresh_token` 是凭证,绝不能当成用量列。
_TOK_PART = (r"(input|output|total|prompt|completion|cached?|cache_?read|cache_?write|"
             r"cache_?creation|reasoning|thoughts?)")
# 字段名是**多段拼接**的:Claude 的 `cache_read_input_tokens` = cache_read + input + tokens。
# 所以规则是「由若干个已知语义段拼成,可选以 tokens 结尾」,而不是枚举完整名字。
# 反面例子:`access_token` 的 "access" 不是语义段 ⇒ 不匹配(它是凭证,绝不能当用量列)。
TOKENISH = re.compile(
    rf"^({_TOK_PART}_?)+(tokens?)?$|^tokens?_({_TOK_PART}_?)+$|^tokens?$", re.I)


# 这几个是**容器**,不是某个工具的家 —— 必须展开成各自独立的候选。
# ★ 之前把它们当成单个根去 walk,4000 文件的上限在走到 `share/opencode` 之前就用完了,
#   于是 `~/.local/share/` 下的 opencode / mimocode / tirith 一个都没被发现(用户 2026-08-12 指出)。
#   每个工具一个独立候选,才各有各的采样预算。
CONTAINERS = (".local/share", ".local/state", ".config", ".cache")


def candidate_roots():
    """候选根 = `~/.*` 一层 + XDG 容器展开 + Application Support 全部子目录。

    ★ **不硬编码工具名**。早先只列了 CherryStudio/Chatbox 那几个,等于把"猜"从字段名换到目录名 ——
    换个工具就漏。改成枚举标准位置下的所有子目录,新装的 AI CLI 自动进候选。
    """
    seen, roots = set(), []
    def add(p):
        if p.is_dir() and str(p) not in seen and not BACKUPISH.search(p.name):
            seen.add(str(p)); roots.append(p)

    for p in sorted(HOME.glob(".*")):
        if p.is_dir() and not p.name.startswith(".Trash"):
            # 容器本身不做候选,展开它的子目录。
            # ★ 取 CONTAINERS 的**首段**:`.local/share` 的首段是 `.local`,漏掉它的话
            #   `~/.local` 与 `~/.local/share/opencode` 会同时成为候选,同一个库被报两遍。
            if p.name in {c.split("/")[0] for c in CONTAINERS}:
                continue
            add(p)
    for c in CONTAINERS:
        base = HOME / c
        if base.is_dir():
            for q in sorted(base.iterdir()):
                add(q)
    aps = HOME / "Library/Application Support"
    if aps.is_dir():
        for q in sorted(aps.iterdir()):
            add(q)
    return roots


def _usage_like(o):
    if not isinstance(o, dict) or not (3 <= len(o) <= 12):
        return False
    nums = [k for k, v in o.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return len(nums) >= 3 and all(TOKENISH.search(k) for k in nums)


def _harvest(o, out, models, depth=0, model=None):
    """收集 usage 对象,并带回**最近的 model 字段**。

    只按目录报会漏掉最要紧的事:DeepSeek 是 API 不是 CLI,本机没有 `~/.deepseek`,它的用量藏在
    别的宿主里当一个模型。报告只说"发现某目录"等于没说 —— 宿主 × 模型是两个维度。
    """
    if depth > 8:
        return
    if isinstance(o, dict):
        m = o.get("model") or o.get("modelId") or o.get("model_id") or model
        if _usage_like(o):
            rec = {k: v for k, v in o.items() if isinstance(v, (int, float))}
            out.append(rec)
            if m:
                tot = next((v for k, v in rec.items() if re.search(r"total", k, re.I)), 0)
                models[str(m)] += tot or 0
        for v in o.values():
            _harvest(v, out, models, depth + 1, m)
    elif isinstance(o, list):
        for v in o[:200]:
            _harvest(v, out, models, depth + 1, model)


def _reg_state(shown):
    """这个根对应哪个已注册的源、它此刻**是否真的在扫**。

    ★ 「已注册」与「在扫」是两件事:`sources.local.json` 的 `disabled` 会让一个有解析器的源
      整个不被解析,而报告只说「已注册」——用户会以为它的数据已经在图里了。
    """
    for root, key in KNOWN_BY_ROOT.items():
        if root == shown or root.startswith(shown + "/") or shown.startswith(root + "/"):
            return {"key": key, "enabled": key in ENABLED_KEYS}
    return {"key": None, "enabled": None}


def classify(recs):
    """实测口径。返回 (判定文本, 状态)。状态 ∈ ok | ambiguous | reject | unknown。"""
    shape = Counter(tuple(sorted(r)) for r in recs).most_common(1)[0][0]
    rows = [r for r in recs if tuple(sorted(r)) == shape]
    tot_keys = [k for k in shape if re.search(r"total", k, re.I)]
    if not tot_keys:
        return "没有 total 字段,无法用算术验证口径", "unknown"
    total = tot_keys[0]
    parts = [k for k in shape if k != total]
    if len(parts) > 8:
        return f"字段过多({len(parts)} 个),不做组合搜索", "unknown"
    usable = [r for r in rows if r.get(total)]
    if len(usable) < MIN_RECORDS:
        return f"样本不足({len(usable)} 条非零)", "unknown"

    winners = [c for n in range(1, len(parts) + 1) for c in combinations(parts, n)
               if all(sum(r.get(k, 0) for k in c) == r[total] for r in usable)]
    if not winners:
        return f"没有任何字段子集恒等于 {total}({len(usable)} 条)", "reject"

    # ★ 多组同时成立 ⇒ 差集字段在样本里恒为 0,数据没告诉我们它们属于哪边。**不许挑一个**。
    #   早先取了最小的那组,于是把"恒为 0 的 cacheWrite"说成"已含在 input 里,要减" —— 凭空造结论。
    if len(winners) > 1:
        amb = sorted(set().union(*map(set, winners)) - set.intersection(*map(set, winners)))
        return (f"歧义:{len(winners)} 组子集都恒等于 {total},差别只在 {', '.join(amb)}"
                f"(样本里恒为 0),需要含非零 {amb[0]} 的样本才能判"), "ambiguous"

    base = set(winners[0])
    inside = [k for k in parts if k not in base]
    txt = f"{total} = {' + '.join(sorted(base))}({len(usable)} 条全中,0 反例)"
    txt += f" ⇒ 要减:{', '.join(inside)} 已含在其中" if inside else " ⇒ 不减:各字段互不相交"
    return txt, "ok"


def probe_sqlite(root):
    """探 SQLite。**opencode 就是这么被漏掉的**(用户 2026-08-12 指出):它的用量在
    `~/.local/share/opencode/opencode.db` 的 `session` 表里,而扫描器只看 json/jsonl,
    结构上就够不着。

    ★ 一律 `mode=ro` 只读打开:这些库可能正被 CLI 开着(有 -wal/-shm),写模式会动它的日志。
    ★ 只挑**列名像 token 计数**的表,再跑与 JSON 侧**同一个**子集搜索 —— 口径判定不分格式。
    """
    hits = []
    try:
        dbs = [q for q in root.rglob("*") if q.is_file()
               and q.suffix in (".db", ".sqlite", ".sqlite3") and q.stat().st_size > 4096][:12]
    except OSError:
        return hits
    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            # 后缀是 .db 不代表就是 SQLite(本机实测撞到过非 SQLite 的 .db)。
            # 连接是惰性的,第一次查询才报错 —— 所以整段都得裹住,不能只裹 connect。
            tabs = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tabs:
                try:
                    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
                except sqlite3.Error:
                    continue
                # 只要"像 token 计数"的列;access_token 那种凭证列不能算进来
                tok = [c for c in cols
                       if TOKENISH.search(c) and not re.search(r"access|refresh|secret|expiry", c, re.I)]
                if len(tok) < 3:
                    continue
                try:
                    rows = con.execute(
                        f'SELECT {", ".join(chr(34)+c+chr(34) for c in tok)} FROM "{t}" LIMIT 5000'
                    ).fetchall()
                except sqlite3.Error:
                    continue
                recs = [{c: (v or 0) for c, v in zip(tok, r) if isinstance(v, (int, float))}
                        for r in rows]
                recs = [r for r in recs if sum(r.values())]
                if not recs:
                    continue
                verdict, state = classify(recs)
                hits.append({"root": f"{str(db).replace(str(HOME), '~')} :: {t}",
                             "known": False, "files": 1, "records": len(recs),
                             "verdict": verdict, "state": state, "models": []})
        except sqlite3.DatabaseError:
            continue                       # 不是 SQLite / 加密 / 损坏 —— 跳过,不是错误
        finally:
            con.close()
    return hits


def probe(root):
    files = []
    try:
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in ("node_modules", ".git", "Caches")][:20]
            for f in fn:
                if f.endswith((".jsonl", ".json")) and ".bak-" not in f:
                    q = pathlib.Path(dp) / f
                    try:
                        st = q.stat()
                    except OSError:
                        continue
                    if st.st_size > 200:
                        files.append((st.st_mtime, st.st_size, q))
            if len(files) > 4000:
                break
    except OSError:
        return None
    if not files:
        return None
    total_files = len(files)
    files.sort(reverse=True)
    if len(files) > MAX_FILES:              # 跨时间分层,见模块 docstring
        step = len(files) / MAX_FILES
        files = [files[int(i * step)] for i in range(MAX_FILES)]

    recs, models, hit_paths = [], Counter(), []
    for _, sz, q in files:
        try:
            with q.open("rb") as fh:
                if sz > MAX_BYTES:
                    fh.seek(sz - MAX_BYTES)
                    fh.readline()           # 丢掉被切断的半行
                txt = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        for line in txt.splitlines():
            line = line.strip()
            if not line or line[0] not in "{[":
                continue
            try:
                before = len(recs)
                _harvest(json.loads(line), recs, models)
                if len(recs) > before:
                    hit_paths.append(q)
            except ValueError:
                pass
        if len(recs) > 8000:
            break
    if len(recs) < MIN_RECORDS:
        return None
    verdict, state = classify(recs)
    # ★ 报出**真正出数据的那一层**,不是候选根:说"发现 ~/.local"等于没说,
    #   得说 "~/.local/share/opencode" 才有用。取所有命中文件的公共祖先。
    try:
        common = pathlib.Path(os.path.commonpath([str(x) for x in set(hit_paths)]))
        if common.is_file():
            common = common.parent
        # 别退到比候选根还浅
        shown = common if str(common).startswith(str(root)) else root
    except (ValueError, OSError):
        shown = root
    return {"root": str(shown).replace(str(HOME), "~"),
            # 注册的根往往比候选根**更深**(候选 `~/.claude` ↔ 注册 `~/.claude/projects`),
            # 所以要双向判包含 —— 只写一个方向会把已注册的全标成"新发现"。
            "known": any(k == str(shown) or k.startswith(str(shown) + "/")
                         or str(shown).startswith(k + "/") for k in KNOWN),
            **_reg_state(str(shown)),
            "files": total_files, "records": len(recs), "verdict": verdict, "state": state,
            "models": [{"model": m, "total": v} for m, v in models.most_common(10)]}


def main():
    roots = candidate_roots()
    hits = [h for h in (probe(r) for r in roots) if h]
    for r in roots:                       # SQLite 侧:一个库可能贡献多张表
        hits.extend(probe_sqlite(r))
    # 同一个库可能被多个候选根覆盖到(嵌套目录),按展示路径去重
    seen, uniq = set(), []
    for h in hits:
        if h["root"] not in seen:
            seen.add(h["root"]); uniq.append(h)
    hits = uniq
    hits.sort(key=lambda h: (h["known"], -h["records"]))
    if "--json" in sys.argv:
        json.dump({"candidates": hits, "roots": len(roots)},
                  sys.stdout, ensure_ascii=False)
        return
    print(f"\n扫了 {len(roots)} 个候选根目录,{len(hits)} 个含 token 用量记录\n")
    for h in hits:
        tag = ("★ 新发现" if not h["known"]
               else "已注册" if h.get("enabled") else "已注册·**已停用**")
        print(f"  [{tag}] {h['root']}  "
              f"({h['files']} 个文件 · {h['records']} 条 usage)")
        print(f"      口径: {h['verdict']}")
        if h["models"]:
            print("      模型: " + " · ".join(f"{m['model']} {m['total']/1e6:.1f}M"
                                              for m in h["models"][:6]))
        print()


if __name__ == "__main__":
    main()
