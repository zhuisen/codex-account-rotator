#!/usr/bin/env python3
"""把 `agy-quota-ledger/samples.jsonl` 的**水位**样本差分成**消耗**序列。

纯函数模块:不落盘、不起进程、不读环境。采样在 `agy_quota_sampler.py`,编排在 `scan.py`。
(项目规则:纯计算放普通模块,框架接线反过来 import 它,别让测试为了 import 一个函数去 stub 一堆东西。)

## ★★ agy 的额度是**滚动窗口**,不是固定窗口 —— 这是这个文件最重要的一条

2026-09-05 真机实测,两处 `remaining` 在 `resetTime` **完全没变**的情况下**上涨**:

    01:31:51  gemini-5h  rem=98.740   →  01:37:15  rem=98.870   (+0.13%, reset 均为 05:59:25)
    01:46:39  gemini-周  rem=97.600   →  09:30:22  rem=98.400   (+0.80%, reset 均为 09-11 16:17)

固定窗口下这不可能发生。**滚动窗口下这是常态**:旧消耗随时间老化退出 trailing 5h / trailing 7d,
额度就"长回来"了。接口自己的措辞也一致 —— `description` 写的是
"it will **fully refresh** in 6 days, 15 hours",是"逐渐补满"不是"到点清零"。

⚠️ **这个结论是从 5 个样本、2 次上涨得出的**,不是从文档。另一个仍能解释同样数据的假说是
「服务端最终一致性 / 计量回补」。两者的差别在长期形状上才看得出来。
**所以现行口径刻意选了在两种假说下都成立的算法**(只累加下降),而不是押注滚动窗口。
判别实验:连续采样一整个 5h 窗口,看恢复曲线是平滑连续的(滚动)还是集中在某一刻(固定重置)。

## 由此而来的四条口径

① ★★ **只有下降算消耗;上升是恢复,不是异常、不是重置。**
   最初的版本把上升当异常报出来,在真机上立刻误报了 2 次 —— 而那 2 次都是正常的额度恢复。
   `recovered_pct` 单独记账,不与消耗相抵。

② ★★ **绝不凭一个读数造消耗。** 每笔消耗都必须由**相邻两点的下降**支撑。
   历史上试过"跨重置时把旧窗口剩余当消耗",那会把一个剩 98% 的窗口记成消耗了 98% —— 凭空造数。

③ ★★ **采样越稀,漏得越多,而且漏掉的永远补不回来。** 滚动窗口下,一笔消耗若在两次采样之间
   **完全老化退出**,水位差就看不见它。所以采样间隔超过窗口长度的
   `GAP_LOWER_BOUND_RATIO` 时,结果标 `lower_bound` —— 它是**下界**,不是准确值。
   ★ 这是水位量测的固有上限:**它是水位计,不是流量计。**

④ ★★ **没有样本的时间段 = 没有观测,不是零消耗。** 心跳样本(采样器静默期也打点)
   正是用来把「确实没动」与「没在看」分开的。

## 一条与本机数据无关的已知前提

额度是**账号级**的:同一账号在别处消耗(另一台机器、Antigravity IDE)也会让水位下降,
而我们会把它记成本机消耗。**无法从本机数据判断这件事有没有发生。**
"""

# 变动超过这个幅度才当真;以下视为浮点/服务端舍入噪声。
# 实测 `remainingFraction` 有 7 位小数,而一次调用的量级是 ~1%,所以 0.01% 的门槛
# 既滤得掉噪声,又远小于任何真实消耗。
NOISE_PCT = 0.01

# 各窗口的长度。用来判断「采样间隔相对窗口是不是太长」。
_WINDOW_SECS = {"5h": 5 * 3600, "weekly": 7 * 86400}
# 采样间隔超过窗口的这个比例,就认为可能有消耗完全老化掉了 ⇒ 结果标为下界。
GAP_LOWER_BOUND_RATIO = 0.5


def dt_gap(prev, cur):
    return cur["ts"] - prev["ts"]


def read_samples(path):
    """读 jsonl → 按 ts 升序的样本列表。坏行跳过(采集侧 fail-open,读取侧也不能被一行毒死)。"""
    import json
    out = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict) and isinstance(o.get("ts"), int) and o.get("buckets"):
                out.append(o)
    out.sort(key=lambda r: r["ts"])
    return out


def _index(sample):
    return {b["id"]: b for b in sample.get("buckets") or [] if b.get("id")}


def derive(samples, since=None):
    """样本序列 → 每个桶的消耗区间。

    → {bucket_id: {"group","window","spans":[...],"consumed_pct","lower_bound","anomalies"}}
      `spans` 每项 = {"t0","t1","pct","crossed_reset"}。
    """
    result = {}
    for prev, cur in zip(samples, samples[1:]):
        pi, ci = _index(prev), _index(cur)
        for bid, cb in ci.items():
            pb = pi.get(bid)
            if pb is None:
                continue                      # 这个桶是新出现的,没有前一点可差分
            r = result.setdefault(bid, {
                "group": cb.get("group"), "window": cb.get("window"),
                "spans": [], "consumed_pct": 0.0, "recovered_pct": 0.0,
                "lower_bound": False, "anomalies": [],
            })
            p_rem, c_rem = pb.get("rem"), cb.get("rem")
            if not isinstance(p_rem, (int, float)) or not isinstance(c_rem, (int, float)):
                continue

            # ★★ **滚动窗口模型**(2026-09-05 实测推翻了原来的固定窗口假设,见文件头口径 ④)。
            #    只有**下降**算消耗;**上升是恢复**(旧消耗老化退出窗口),不是异常也不是重置。
            d = p_rem - c_rem
            if d > NOISE_PCT:
                r["spans"].append({"t0": prev["ts"], "t1": cur["ts"],
                                   "pct": round(d, 4), "crossed_reset": False})
                r["consumed_pct"] += d
            elif d < -NOISE_PCT:
                r["recovered_pct"] += -d

            # ★★ 采样间隔相对窗口越长,漏掉的消耗越多 —— 滚动窗口下,一笔消耗若在两次采样
            #    之间**完全老化退出**,就永久看不见了。所以间隔超过窗口的一个比例就标下界。
            #    这不是保守,是这个量测方式的固有上限:它测的是**水位**,不是流量计。
            win = _WINDOW_SECS.get((cb.get("window") or "").lower())
            if win and dt_gap(prev, cur) > win * GAP_LOWER_BOUND_RATIO:
                r["lower_bound"] = True

    for r in result.values():
        r["consumed_pct"] = round(r["consumed_pct"], 4)
        r["recovered_pct"] = round(r["recovered_pct"], 4)
        if since is not None:
            r["spans"] = [s for s in r["spans"] if s["t1"] >= since]
    return result


def daily(samples, tz_offset_secs=0):
    """→ {"YYYY-MM-DD": {bucket_id: pct}}。跨天的区间**按时间比例摊分**。

    ★ 摊分是近似,而且是**刻意选的**近似:一个区间横跨午夜时,把它整段记到任一天
    都会造出一个假的尖峰。比例摊分至少让总量守恒、形状不失真。
    区间越短误差越小,而采样间隔默认 60s —— 只有 agy 跨午夜连续跑时才可能出现长区间。
    """
    import datetime
    out = {}

    def day(ts):
        return datetime.datetime.fromtimestamp(ts + tz_offset_secs).strftime("%Y-%m-%d")

    for bid, r in derive(samples).items():
        for s in r["spans"]:
            t0, t1, pct = s["t0"], s["t1"], s["pct"]
            d0, d1 = day(t0), day(t1)
            if d0 == d1 or t1 <= t0:
                out.setdefault(d0, {}).setdefault(bid, 0.0)
                out[d0][bid] += pct
                continue
            # 跨天:按每天占的秒数摊
            span = t1 - t0
            cur = t0
            while cur < t1:
                d = day(cur)
                nxt_midnight = int(
                    datetime.datetime.strptime(d, "%Y-%m-%d").timestamp()
                ) - tz_offset_secs + 86400
                seg_end = min(nxt_midnight, t1)
                out.setdefault(d, {}).setdefault(bid, 0.0)
                out[d][bid] += pct * (seg_end - cur) / span
                cur = seg_end
    for d in out:
        for b in out[d]:
            out[d][b] = round(out[d][b], 4)
    return out


def coverage(samples):
    """采样覆盖:第一条/最后一条样本的时间,以及样本数。

    ★ UI 必须能说出「这条序列从什么时候开始有观测」—— 与 token 账本那条
    「采集自 08/19 起」同一个理由:一个偏小的数会被读成"用得少",而不是"还没看到那么早"。
    """
    if not samples:
        return None
    return {"first": samples[0]["ts"], "last": samples[-1]["ts"], "n": len(samples)}
