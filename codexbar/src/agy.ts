/**
 * Antigravity(agy) 额度的类型与**文案单一真源**。
 *
 * 数据来自仓库根的 `agy-quota`（本机 agy 进程监听的 loopback Connect RPC，
 * `RetrieveUserQuotaSummary`，无鉴权）。**不联网、不消耗任何配额。**
 *
 * 与本页 token 统计**不同源**，且这次的差距比 grok 那边更大：
 * token 那边是 `traffic/agy-ledger/`（只有经 wrapper 的 print 模式会被记账，
 * 交互式会话一个字都进不来，所以那是**下界**）；这边是 Google 那侧的真实额度水位。
 * 两个数不可加、不可互推 —— 尤其**不能**拿账本去解释额度掉了多少。
 *
 * ★★ 与 grok 的方向**相反**，这是全 app 最容易写反的一处：
 *
 *        grok-quota  → `used_percent`      已用
 *        agy-quota   → `remaining_percent` 剩余
 *
 * 两条链路的卡片长得几乎一样、变量名也都叫 `pct`。所以这里的取数函数**名字里都带方向**，
 * 且不导出裸数字 —— 同 `grok.ts` 的纪律，理由见那份文件里那段「颜色完全反相且不报错」。
 */

/** ★ 闭集，必须与 `agy-quota` 里的 `REASONS` 逐字相等。
 *  闸在 `tests/test_agy_reason_copy.py`：两边都从源解析，新增一个只改一边就红。 */
export type AgyReason =
  | "not_installed"
  | "no_process"
  | "not_ready"
  | "no_ports"
  | "bad_payload"
  | "rpc_error"
  | "network_error";

export interface AgyBucket {
  bucket_id: string | null;
  /** 上游原词：`"weekly"` / `"5h"`。转展示标签走 `agyWinLabel`，别在调用点写 switch。 */
  window: string | null;
  /** ★★ 0–100 的**剩余**百分比。与 grok 的 `used_percent` 方向相反。 */
  remaining_percent: number;
  reset_at: number | null;
}

export interface AgyGroup {
  /** 上游 `displayName`，实测两组：`"Gemini Models"` / `"Claude and GPT models"`。 */
  name: string | null;
  buckets: AgyBucket[];
}

export interface AgyQuota {
  groups: AgyGroup[];
}

export interface AgySnapshot {
  schema: number;
  fetched_at: number;
  available: boolean;
  reason: AgyReason | null;
  detail: string | null;
  pid: number | null;
  /** ★ `available === false` 时恒 `null`。
   *  绝不是空对象、更不是满额 —— 上游 `remainingFraction` 缺省值就是 1.0，
   *  这条链路上「失败」与「满格」只隔一个默认值。 */
  quota: AgyQuota | null;
  last_good: { quota: AgyQuota; fetched_at: number | null } | null;
}

/** 上游窗口原词 → 展示标签。与账号卡的 `winLabel` 输出对齐，靠它对上同一条槽位。 */
export function agyWinLabel(window: string | null): string {
  if (window === "weekly") return "周";
  if (window === "5h") return "5h";
  return window || "?";
}

/**
 * 当前该看哪份额度：活数据优先，没有就用降级时搬运的上次读数。
 *
 * ★ 返回值里带 `stale`，**调用点不许自己判断** —— 「这个数是不是现在的」必须跟着数一起走，
 * 分开传迟早有一处只取了数、忘了取那个标志，于是陈旧读数被画成实时值。
 */
export function agyShown(s: AgySnapshot | null | undefined):
  { quota: AgyQuota; stale: boolean; at: number | null } | null {
  if (s?.available && s.quota) return { quota: s.quota, stale: false, at: s.fetched_at };
  if (s?.last_good?.quota) return { quota: s.last_good.quota, stale: true, at: s.last_good.fetched_at };
  return null;
}

/** 全部桶摊平。顺序保持上游给的顺序（Gemini 在前），不排序 —— 排序会让 UI 里的行跳来跳去。 */
export function agyBuckets(q: AgyQuota | null | undefined): { group: string | null; b: AgyBucket }[] {
  return (q?.groups ?? []).flatMap(g => g.buckets.map(b => ({ group: g.name, b })));
}

/**
 * **约束最紧**的那个桶 —— 剩余最少的那个。
 *
 * 这是环里该显示的数：4 个桶里任何一个见底，agy 就用不了了，所以"还剩多少"的答案
 * 只能是最小的那个，不是平均值。★ 与托盘挑窗口的口径一致（`lib.rs` 取 used 最大者）。
 */
export function agyTightest(q: AgyQuota | null | undefined): { group: string | null; b: AgyBucket } | null {
  const all = agyBuckets(q);
  if (!all.length) return null;
  return all.reduce((a, x) => (x.b.remaining_percent < a.b.remaining_percent ? x : a));
}

/**
 * 按窗口聚合成卡片上的条形行：每个窗口标签一行，取该窗口下**最紧**的那组。
 *
 * agy 是 2 组 × 2 窗口 = 4 个数，而卡片只有账号卡那两行的高度。**刻意做减法**：
 * 行上显示的是"这个窗口最紧的是谁、剩多少"，具体哪一组写在 `group` 里由调用点放进 title。
 * 全 4 行铺开会把卡片撑高，破坏九宫格里与账号卡的对齐（那个对齐是像素级调过的）。
 */
export function agyWinRows(q: AgyQuota | null | undefined):
  { label: string; remaining: number; group: string | null; reset_at: number | null }[] {
  const byWin = new Map<string, { label: string; remaining: number; group: string | null; reset_at: number | null }>();
  for (const { group, b } of agyBuckets(q)) {
    const label = agyWinLabel(b.window);
    const cur = byWin.get(label);
    if (!cur || b.remaining_percent < cur.remaining) {
      byWin.set(label, { label, remaining: b.remaining_percent, group, reset_at: b.reset_at });
    }
  }
  // 短窗在前（5h 比周更常变），与账号卡的行序一致。
  return [...byWin.values()].sort((a, b) => (a.label === "5h" ? -1 : b.label === "5h" ? 1 : 0));
}

export type AgyTone = "amber" | "red" | "muted";

/**
 * 降级态的色调。
 *
 * ★ `no_process` 给 `muted` 而不是琥珀：agy **不常驻**，没在跑是**常态**不是故障。
 * 把常态染成警告色，就是又造一盏长亮的灯 —— 本仓判过死刑的形态。
 */
export function agyReasonTone(s: AgySnapshot): AgyTone {
  switch (s.reason) {
    case "not_installed":
    case "no_process": return "muted";
    case "bad_payload": return "red";   // 接口变了，要人去看
    default: return "amber";            // 会自愈的
  }
}

/**
 * 降级文案的**唯一出处**（同 `grok.ts` 的 `grokReasonNote` 纪律）。
 *
 * 每条都必须做到两件事：
 * ① **明说这不是「额度耗尽」** —— 满格与读不到在这条链路上只隔一个默认值，
 *    用户没有别的办法分辨；
 * ② **给出下一步动作，且那个动作要真能修** —— 反例是 erp-v3 那条让用户"重试"的提示，
 *    而重试根本修不了它指的那个状态。所以 `no_process` 这条写的是"起一次 agy"，
 *    `not_ready` 写的是"等几秒"，两者不能都写成"稍后重试"。
 */
export function agyReasonNote(s: AgySnapshot): string {
  switch (s.reason) {
    case "not_installed":
      return `本机没有 agy。装了 Antigravity CLI 之后才有额度可读。`;
    case "no_process":
      return `agy 现在没在运行。额度服务随 agy 进程存在，所以这**不是「额度耗尽」**——`
        + `在终端起一次 agy（或跑一次 omc ask antigravity）就能读到。`;
    case "not_ready":
      // ★ 这条是实测出来的,不是猜的:同一个进程 0s 返 500、10s 返 200。
      //   我曾经因为在端口刚出现时就调,把这个预热窗口误判成"结构性拿不到"。
      return `agy 刚起来，额度服务还在预热（实测约 10 秒）。这不是「额度耗尽」，`
        + `过几秒再刷新就有了。`;
    case "no_ports":
      return `agy 在运行，但还没开监听端口。这不是「额度耗尽」，下次刷新会自动重试。`;
    case "bad_payload":
      return `agy 返回了 200，但响应里没有额度字段（接口可能改了）。这不是「额度耗尽」。`;
    case "rpc_error":
      return `agy 的额度接口返回错误${s.detail ? `（${s.detail.slice(0, 60)}）` : ""}。`
        + `这不是「额度耗尽」，下次刷新会自动重试。`;
    case "network_error":
      return `连不上 agy 的本地端口${s.detail ? `（${s.detail.slice(0, 60)}）` : ""}。`
        + `这不是「额度耗尽」，下次刷新会自动重试。`;
    default:
      return `额度暂时读不到。这不是「额度耗尽」，下次刷新会自动重试。`;
  }
}

/**
 * 这台机器上**该不该显示 agy 额度**。总览卡与菜单栏行必须用同一个判据。
 *
 * 只有两种情况不画：
 * ① 用户在设置页停用了 agy（复用既有的平台开关，不新造第二套）；
 * ② `not_installed` —— **确定的否定**，隐藏是诚实的。
 *
 * ★★ `no_process` **要画**。它和 `not_installed` 的区别就是这个函数存在的理由：
 * agy 不常驻，"没在跑"是常态；此时卡上还能显示上次读数（`last_good`），
 * 那是关于一份真实额度的真实数字。把它一起藏掉，等于让用户永远看不见 agy 的额度。
 *
 * ★ `snap == null`（还没取过）返回 false：宁可晚 1 秒出现，也不要让没装 agy 的人
 * 先闪一下「未探测」再消失。
 */
export function agyQuotaVisible(
  snap: AgySnapshot | null | undefined,
  opts: { disabled?: boolean } = {},
): boolean {
  if (opts.disabled) return false;
  if (!snap) return false;
  return snap.reason !== "not_installed";
}
