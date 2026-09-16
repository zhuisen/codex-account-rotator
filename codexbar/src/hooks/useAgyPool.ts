import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import { getSettings } from "../pages/SettingsPage";
import type { AgyQuota, AgySnapshot } from "../agy";

/**
 * 「现在钥匙串里是谁」的**跨 webview 广播**。
 *
 * ★★★ 主窗与菜单栏是**两个独立的 webview**，各自 `useAgyPool()` 一份，
 *   而且 `enabled` 的条件还不一样（主窗要 `总览 + Gemini 档`，菜单栏要 `账号 Tab + Gemini 芯片`）。
 *   于是两边在**不同时刻**各自跑 `agy-rotate live --json` —— 而这台机器上钥匙串正被
 *   4 个常驻 agy 进程反复抢（实测最久的跑了 6 天 23 小时，`drifted: true`）。
 *   两次探测落在不同时刻，就会得到不同的号。
 *
 * ⚠️ **这个缺口是 2026-09-14 用户实报的**：同一屏上菜单栏说当前是 `sam`、
 *   主窗总览说当前是 `dbk`（实际 `live --json` = sam，主窗停在陈旧的 `live_seen`）。
 *
 * ★★ 而 B45 引入的 `verified` 位让这件事**从瞬态变成永久** —— 在那之前两边至少每次
 *   进档都会重读一次、有机会收敛；之后各自锁死在自己那次探测的结果上。
 *   所以这条广播不是锦上添花，是 `verified` 的**必要配套**。
 *
 * 范式照抄 `usePrivacy`（两个 webview 的 localStorage 不互通，只能走 Tauri 事件）；
 * 采纳规则照抄 `useQuotaSidecar.adopt`：**按时间戳单调采纳**，只认更新的。
 * 这样自己 `emit` 出去又被自己收到（Tauri 会广播给所有 webview，包括发送方）是无害的空操作。
 */
const LIVE_EVT = "agy-live-changed";

interface LivePayload { sub: string; drifted: boolean; at: number }

/** 池里一个号（`.agy-pool.json` 的一条）。 */
export interface AgyPoolAccount {
  sub: string;
  label: string;
  email?: string | null;
  /** 云端按账号读到的额度。★ **只有 5h 窗口** —— 周窗口只有本机 RPC 有，
   *  而那条只看得到当值那个号（见 `toSnapshot`）。 */
  quota?: Record<string, { remaining: number; reset: string; models?: string[] }> | null;
  quota_err?: string | null;
  quota_at?: number | null;
  /** 反向：`true` = 这个号被摘出自动轮换。**缺省（没有这个键）= 参与轮换**。 */
  rotate_off?: boolean;
  /**
   * ★★★ **上次看到这个号的周窗口时，它是多少**（由 `agy-quota` 在归属明确时写）。
   *
   * 周窗口只有本机 loopback RPC 有，而那条只看得到当前登录的号；云端按账号那条
   * **结构上就没有周**（2026-09-15 实测：两个号各 27 模型、各只有 2 个桶，没有周桶）。
   * 所以非当值号的周额度不可能现取 —— 但它当值时读到过，那个数字是真的。
   * §7.0b：「这次读不到」不许覆盖「上次读到过」。
   */
  /**
   * ★★★ **完整额度摘要**（含周窗口），由 `agy-rotate quota` 走
   * `/v1internal:retrieveUserQuotaSummary` 按账号取回（2026-09-15 起）。
   *
   * 形状与本机 loopback RPC 的快照**同形同源**，所以 `toSnapshot` 基本是直译。
   * ⚠️ 在此之前本仓写着「周窗口只有当值号读得到」——**那是错的**，
   *   它建立在 `fetchAvailableModels` 只回 5h 这一个观测上，而从没找过第二个端点。
   */
  quota_summary?: { displayName?: string; buckets?: {
    bucketId?: string; window?: string; resetTime?: string; remainingFraction?: number;
  }[] }[] | null;
}

interface PoolFile {
  accounts?: Record<string, Omit<AgyPoolAccount, "sub">>;
  /** 上次**我们写进去**时看到的当值号。★★★ **绝不能拿它当"当前账号"显示。**
   *  钥匙串是一个被多个常驻 agy 进程并发写的**单槽**：实测 2026-09-13 17:58 我们装进 B，
   *  18:23:17 一个身份为 A 的旧 agy 在它自己 access token 到期（18:23:16）时刷新，
   *  把整份凭证写回钥匙串 —— B 被冲掉，而这个字段毫不知情。用户看到的就是
   *  「界面说 B、agy 里是 A」。真相只能**现读**，见 `live --json`。 */
  live_seen?: string | null;
  /**
   * 上次**跑过** `agy-rotate quota` 的时刻（epoch 秒），**成败都写**。
   *
   * ★★★ 自动保鲜的判据只能是它，**绝不能用各号的 `quota_at`**：取数失败那条分支
   *   不写 `quota_at`，于是一个坏掉的号会让"最旧的读数过期了吗"**永远为真** ⇒
   *   30s 心跳变成每 30s 起一次 18.6s 的子进程猛打云端。
   *   与 B46 的 `_reset_crossed` 同形：拿**成功的副作用**当**尝试过**的判据，
   *   失败时自我锁死成放大器，且没有任何症状。
   *
   * ★ 它落在**盘上**而不是 hook 的 ref 里，所以两个 webview 与重启之间共享同一个事实 ——
   *   各存一份 ref 的话，主窗和菜单栏会各跑各的。
   */
  quota_ran_at?: number | null;
}

/** `agy-rotate live --json` 的回答：**现在**钥匙串里是谁。 */
interface LiveProbe {
  sub: string | null;
  email: string | null;
  live_seen: string | null;
  /** 现读的和我们上次装进去的不是同一个号 —— 有别的 agy 进程把槽抢回去了。 */
  drifted: boolean;
}

/**
 * 把按账号取回的**完整额度摘要**翻成卡片认识的 `AgySnapshot` 形状。
 *
 * ★★★ 2026-09-15 起走 `retrieveUserQuotaSummary` —— 每个号都带自己的 5h **与周**，
 *   所以这里基本是直译（两边同形同源）。
 *
 * ⚠️ **此前这里造的是"只有 5h"的残缺快照**，因为老端点 `fetchAvailableModels`
 *   只回 5h。当时还写了一大段"绝不补一个假的周格"的注释 —— 那条判断本身没错
 *   （不许拿默认值 1.0 冒充满额），错的是**前提**：以为周窗口根本取不到。
 *   `CLAUDE.md` §6：**只看默认响应就断言"接口没有这个能力" = 假阴性。**
 *
 * ★ 失败时 `quota` 恒 `null`（不是空对象）—— 卡片据此走降级态，而不是画一条满格的条。
 *   上游 `remainingFraction` 的缺省恰好是 1.0，这条链路上「没有」和「满格」只隔一个默认值。
 */
function toSnapshot(a: AgyPoolAccount): AgySnapshot {
  // ★★★ 优先用**完整摘要**：每个号都带自己的 5h + 周，非当值号不再缺一格。
  //   （2026-09-15：`retrieveUserQuotaSummary` 按账号返回，实测两个号都 200。）
  const groups = (a.quota_summary ?? []).map((g) => ({
    name: g.displayName || "?",
    buckets: (g.buckets ?? [])
      .filter((b) => typeof b.remainingFraction === "number")
      .map((b) => ({
        bucket_id: b.bucketId ?? null,
        window: b.window ?? null,
        // ★ 上游是 0~1 的 fraction，我们对外一律 0~100 的百分比。
        //   这层换算丢了会画出一条 0.99% 的条 —— 看着像"快用光了"，方向还挺合理，肉眼极难发现。
        remaining_percent: Math.round((b.remainingFraction as number) * 1000) / 10,
        reset_at: b.resetTime ? Math.round(Date.parse(b.resetTime) / 1000) : null,
      })),
  })).filter((g) => g.buckets.length > 0);
  const ok = groups.length > 0 && !a.quota_err;
  return {
    schema: 1, fetched_at: a.quota_at ?? 0, available: ok,
    // ★ 失败时 `quota` 恒 `null`（不是空对象）—— 卡片据此走降级态而不是画一条满格的条。
    reason: ok ? null : "network_error", detail: a.quota_err ?? null, pid: null,
    quota: ok ? ({ groups } as unknown as AgyQuota) : null,
    last_good: null,
  };
}


/**
 * 重进 Gemini 档时，多新的 `live` 探测还算数。
 *
 * ★ 这个节流**不是为了省 CPU**（`live --json` 实测 80ms、不联网、不消耗任何配额）。
 *   它挡的是「来回点分档」叠起来的子进程：每次进档要起两个 python，各自抢 Rust 侧的
 *   `AGY_LOCK`，而 `run_agy_quota` 抢的是同一把锁。
 * ★ 安全性判据：`drifted` 的成因是别的常驻 agy 在**自己 token 到期时**（小时级）把凭证
 *   写回钥匙串，所以 8 秒内不重探不可能错过一次真实漂移。
 *   ⚠️ 写操作（switch / rename / remove / rotate / …）一律 `read(true)` 绕过它 ——
 *   那些路径重读的正是它们刚改掉的东西。
 */
const PROBE_FRESH_MS = 8000;

/**
 * 云端每账号额度的保鲜阀（用户 2026-09-16：「刷新情况太慢了，都要我手动去刷新」）。
 *
 * ★★★ **真因不是阈值调得太松，是这条链路上根本没有自动刷新。**
 *   在此之前 `agy-rotate quota` 的**唯一**调用方是 ↻ 按钮：挂载只 `readPool()` 读盘，
 *   `probeLive()` 只查身份不查额度。实测本机三个号的 `quota_at` 全停在 **18.2 小时前**，
 *   而同机 `.agy-quota.json`（本机 RPC，有采样器）是 **0.4 分钟前** —— 一冷一热。
 *   所以这里加的是**缺失的那一半**，不是把某个数字改小（§7.1：先问信息是不是被丢掉了）。
 *
 * ★ 10 分钟的来历是**实测成本**：一次 `agy-rotate quota` = **18.6s / 3 个号**
 *   （34% CPU，几乎全是网络等待），占空比 18.6s ÷ 10min ≈ 3%。
 *   而 agy 的 5h 窗口每 1% ≈ 3 分钟、周窗口更慢 —— 10 分钟丢不掉任何用户看得见的精度。
 *   ⚠️ 别照抄 `useAgyQuota` 的 2 分钟：那条是**本机 loopback**，零网络零额度，成本差两个量级。
 *
 * ★★ 零额度消耗、**不写钥匙串**（`cmd_quota` 用每个号自己存的 token 逐个取，不切号），
 *   所以后台跑它不会和用户当值的号抢槽 —— 这是它敢自动化的前提，不是顺带的好处。
 */
const QUOTA_FRESH_MS = 10 * 60 * 1000;

/** 心跳只是"到点看一眼岁数"，不过期什么都不做 —— 所以 30s 节拍 ≠ 30s 取一次。 */
const TICK_MS = 30 * 1000;

/** 池文件被重写了（额度刚取完）⇒ 另一个 webview **读盘**即可，别也去起一个子进程。 */
const POOL_EVT = "agy-pool-updated";

/** 与 `useTraffic` / `useQuotaSidecar` 共用设置页那一个「后台自动刷新」开关。
 *  ★ 每次 tick 现读：两个 webview 的 localStorage **不互通**，建立 effect 时读一次会漂。 */
function autoRefreshEnabled(): boolean {
  try { return getSettings().autoRefresh !== false; } catch { return true; }
}

/**
 * agy 账号池。→ 每个号一张卡所需的一切。
 *
 * ★ 只读盘，不主动联网：`refresh()` 才会跑 `agy-rotate quota`（零消耗，但要往云端发请求）。
 *   与 grok/agy 额度同一条纪律 —— 总览一打开就联网不是这个 app 的做法。
 *
 * ★★★ **这一档的"缓存"就是这个 hook 自己的状态，所以它只增不减**（2026-09-14，用户实报
 *   「gemini 没有对应的缓存，因此在总览里切换导致跳来跳去」）。三条，缺一条就会再跳：
 *
 *   ① **池文件在挂载时就读**，不等进档。它是一次 `read_sidecar` 文件读 ——
 *      不起子进程、不联网、不消耗任何配额，与"总览一打开就联网"那条纪律不同族。
 *      不预读的代价是可见的：分档条上的「Gemini N」在没进过这一档时恒显示兜底的
 *      `Math.max(1, …)` = **1**，进档那一刻才变成真实号数，整条 pill 跟着重排。
 *   ② **`live_seen` 只能当种子，不能覆盖已验证的现读值**（本仓 §7.0b：
 *      「读不到 ≠ 没有」的另一种形态）。这两个值**本来就常常不同** ——
 *      实测 2026-09-14 本机 `live_seen=103986…`(dbk) 而现读是 `100990…`(sam)、`drifted:true`。
 *      原来每次进档都先把 `liveSub` 打回 `live_seen`、约 160ms 后再被现读改回来，
 *      于是 Hero 的名字/邮箱/环形百分比/5h·周两行 **每切一次档就整块闪一次**，
 *      而「当前」徽章在两张卡之间来回跳。**这就是用户说的"跳来跳去"。**
 *   ③ **探测失败不许写成"没有漂移"**。原来 `catch { setDrifted(false) }` 把
 *      「这次没探到」折叠成「确实没漂移」，那条琥珀告警会因为一次子进程失败而消失。
 */
export function useAgyPool(enabled: boolean): {
  accounts: AgyPoolAccount[];
  /** **现在**钥匙串里是谁（现读，不是 `live_seen`）。 */
  liveSub: string | null;
  /** 现读的号 ≠ 我们上次装进去的号 ⇒ 有别的 agy 进程把槽抢回去了。 */
  drifted: boolean;
  /** 当值号的那张 `AgySnapshot`（含**周**窗口）——它只能来自本机 RPC。 */
  snapshotOf: (a: AgyPoolAccount, liveSnap: AgySnapshot | null) => AgySnapshot;
  busy: boolean;
  err: string | null;
  refresh: () => void;
  switchTo: (label: string) => void;
  /** 改显示名。★ 与 codex 同款：label 只是昵称，身份始终是 `sub`。 */
  renameTo: (label: string, next: string) => void;
  /** 从池里移除。★ **不可逆** —— 卡片上有两段确认，CLI 侧另有一道拒绝删当值号的守卫。 */
  removeIt: (label: string) => void;
  /** 逐号验凭证还有效吗。**零消耗**（刷 token + 打 `fetchAvailableModels`）。 */
  health: () => void;
  /** ★★★ **计费探针 —— 花的是 agy 自己的额度**（起一次 `agy -p`，实测约 15k token）。
   *  回答 `health` 回答不了的那个问题：这个号**真的还能干活吗**。 */
  probe: (label?: string) => void;
  /** 按号开关自动轮换。 */
  setRotate: (label: string, on: boolean) => void;
  /** 全局自动切号开关。`null` = 还没读到。 */
  autoOn: boolean | null;
  setAuto: (on: boolean) => void;
  /** 正在跑的那条写操作的 id（`probe:<label>` / `health` / …），给按钮转圈用。 */
  running: string | null;
  switching: string | null;
} {
  const [accounts, setAccounts] = useState<AgyPoolAccount[]>([]);
  const [liveSub, setLiveSub] = useState<string | null>(null);
  const [drifted, setDrifted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [autoOn, setAutoOn] = useState<boolean | null>(null);
  /** 正在跑的那条写操作的 id。★ 与下面那个 `running` ref 是两回事：
   *  那个管「refresh 在途、别起第二个子进程」，这个管**按钮转圈**。 */
  const [runningId, setRunningId] = useState<string | null>(null);
  const running = useRef(false);
  /** ★★ `liveSub` 现在这个值**是现读探回来的**吗？`false` = 它还只是 `live_seen` 那个种子。
   *  这一位就是 ② 的全部实现：只有它为假时，`live_seen` 才有资格写 `liveSub`。 */
  const verified = useRef(false);
  /** 上次**成功**跑完现读探测的时刻。0 = 还没成功过（于是永远算过期，必探）。
   *  ★ 也用作跨 webview 广播的单调时间戳（见 `LIVE_EVT`）。 */
  const probedAt = useRef(0);
  /** `read()` 在途 —— 来回点分档不该把子进程叠起来。 */
  const readingRef = useRef(false);
  /** 盘上那条「上次跑过 `agy-rotate quota`」的时刻（毫秒）。0 = 从没跑过 ⇒ 必取一次。
   *  ★ 每次 `readPool()` 现读，不自己累加 —— 另一个 webview 跑完时我们靠读盘知道。 */
  const quotaRanAt = useRef(0);

  /**
   * 读池文件。**只读盘**：不起子进程、不联网、不消耗配额，所以它在挂载时就跑（见 ①）。
   *
   * ★ `raw` 为空 = 池文件不存在（从没建过池），这是**真话**，照写空。
   *   而读失败会 `throw` 落进 `catch`，那里一个字都不动已有的 `accounts` ——
   *   「这次没读到」不许把已经画出来的号抹掉（§7.0b）。
   */
  const readPool = useCallback(async () => {
    try {
      const raw = await invoke<string | null>("read_agy_pool");
      if (!raw) {
        setAccounts([]);
        // ★ 没有池 ⇒ 也没有"上次装进去的号"可当种子。但**已验证的现读值仍然有效**：
        //   钥匙串里登录着谁，与我们有没有建过池是两件独立的事。
        if (!verified.current) setLiveSub(null);
        setErr(null);
        return;
      }
      const p = JSON.parse(raw) as PoolFile;
      // ★ 现读「上次尝试过」的时刻。另一个 webview 刚跑完时，我们靠这一行知道，
      //   于是两边不会各跑一次同样的 18.6s 子进程。
      quotaRanAt.current = (p.quota_ran_at ?? 0) * 1000;
      setAccounts(Object.entries(p.accounts ?? {})
        .map(([sub, a]) => ({ sub, ...a }))
        // ★ 按 label 排，不按额度：位置一变，用户就得重新找他的号。
        //   "该用哪个"由「当前」徽章回答，不由顺序回答（同账号卡那条）。
        .sort((x, y) => (x.label || "").localeCompare(y.label || "")));
      // ★★★ **`live_seen` 只是种子。** 只用它就是 2026-09-13 用户报的那个 bug
      //   （界面说 B、agy 里是 A）；只用现读则会在 `live` 还没回来的那一帧丢掉「当前」徽章。
      //   ★ 而**现读一旦回来过，就再也不许退回这个种子** —— 退回去正是"跳来跳去"（见 ②）。
      if (!verified.current) setLiveSub(p.live_seen ?? null);
      setErr(null);
    } catch (e: unknown) {
      // ★ 只记错，**不动 `accounts` / `liveSub`**：保留上一次读到的，UI 才不会闪回空态。
      setErr(String(e).slice(0, 200));
    }
  }, []);

  /**
   * 现读探测：全局自动切号开关 + **现在钥匙串里到底是谁**。这两条各起一个 python 子进程。
   *
   * @param force 写操作之后必须为 `true` —— 它们改的就是这里要读的东西。
   */
  const probeLive = useCallback(async (force: boolean) => {
    if (!force && Date.now() - probedAt.current < PROBE_FRESH_MS) return;
    // ★ `live` **排在 `auto-switch` 前面**，顺序是有理由的：本会话第一次进档时
    //   `liveSub` 还只是 `live_seen` 这个种子，Hero 在它被现读改正之前都可能画着另一个号。
    //   两条各起一个 python（实测各约 80ms），串在它后面就把那个窗口白白翻倍。
    //   开关那条只影响一个 pill 的文字，先后都不显眼。
    try {
      const out = await invoke<string>("run_agy_rotate", { args: ["live", "--json"] });
      const probe = JSON.parse(out) as LiveProbe;
      // ★ 读不到（`sub` 为 null）时**不要**把它写成 null 覆盖掉种子值：
      //   「这次没探到」和「确实没人登录」是两件事（本仓 §7.0b）。
      if (probe.sub) { verified.current = true; setLiveSub(probe.sub); }
      setDrifted(!!probe.drifted);
      probedAt.current = Date.now();
      // ★★ 告诉**另一个 webview**。不广播的话，主窗与菜单栏会各自锁死在自己那次
      //   探测的结果上（`verified` 让它变成永久分歧）—— 就是用户 2026-09-14 报的
      //   「菜单栏说 sam、总览说 dbk」。见 `LIVE_EVT` 的说明。
      if (probe.sub) {
        void emit(LIVE_EVT, { sub: probe.sub, drifted: !!probe.drifted,
                              at: probedAt.current } satisfies LivePayload);
      }
    } catch {
      // ★★ 探不到当前号不该让整块卡片失败 —— 上面的池数据已经可用了。
      //   ★ 尤其**不许写 `setDrifted(false)`**：那是把「这次没探到」说成「确实没漂移」，
      //     一次子进程失败就会让那条琥珀告警消失（见 ③）。保持上次的判断。
      //   ★ 也不推进 `probedAt`：失败不算"刚探过"，下次进档要立刻重试。
    }
    try {
      // 全局自动切号开关的真源在池里（wrapper 在 app 没开时也要读它）。
      const j = await invoke<string>("run_agy_rotate", { args: ["auto-switch", "--json"] });
      setAutoOn(!!(JSON.parse(j) as { enabled: boolean }).enabled);
    } catch { /* 读不到就保持 null —— 「没探到」不写成「关着」 */ }
  }, []);

  /**
   * 池 + 现读，一次进档要的全部。`force` 透传给现读那半（池文件读本来就免费，不节流）。
   *
   * ★★ 在途守卫**只挡不 force 的那种**（来回点分档）。写操作之后那次重读必须放行 ——
   *   它读的正是刚被改掉的东西，丢掉它 = 用户点了「切换」而界面纹丝不动，
   *   而"丢了一次重读"和"切换没生效"在界面上长得一模一样（本仓反复记的那个形状）。
   */
  const read = useCallback(async (force = false) => {
    if (!force && readingRef.current) return;
    readingRef.current = true;
    try {
      await readPool();
      await probeLive(force);
    } finally {
      readingRef.current = false;
    }
  }, [readPool, probeLive]);

  // ① 挂载即读池文件 —— 不等用户进 Gemini 档。见文件头 ①。
  useEffect(() => { void readPool(); }, [readPool]);

  /**
   * ★★★ 收另一个 webview 的现读结果。**不受 `enabled` 约束** ——
   *   同 `useQuotaSidecar` 的推送通道那条理由：这是别人**已经取好**的数据，
   *   收下它零成本，而受约束就会退回「只有正在看这一档时才收敛」，
   *   那正是「菜单栏说 sam、总览说 dbk」的成因。
   * ★ 按 `at` **严格更新**才采纳：自己 emit 又被自己收到时 `at` 相等 ⇒ 空操作。
   */
  useEffect(() => {
    let un: (() => void) | undefined;
    let dead = false;
    void listen<LivePayload>(LIVE_EVT, (e) => {
      const p = e.payload;
      if (!p || !p.sub || !(p.at > probedAt.current)) return;
      probedAt.current = p.at;
      verified.current = true;
      setLiveSub(p.sub);
      setDrifted(!!p.drifted);
    }).then((f) => { if (dead) f(); else un = f; });
    return () => { dead = true; un?.(); };
  }, []);
  useEffect(() => { if (enabled) void read(); }, [enabled, read]);

  /**
   * 取一次云端每账号额度。`refresh()`（手动 ↻）与自动保鲜**共用这一条** ——
   * 两条各写一份的话，迟早只有一条带上了 `running` 守卫或广播。
   *
   * ★ `silent`：自动那次**不点亮按钮转圈**。后台保鲜让整排卡每 10 分钟转一次圈，
   *   用户会以为自己碰了什么；而手动点 ↻ 必须立刻有反馈。
   *   ⚠️ 但**失败仍然照常写 `err`** —— 静默的是"忙"，不是"坏了"。
   */
  const runQuota = useCallback((silent: boolean) => {
    if (running.current) return;
    running.current = true;
    if (!silent) setBusy(true);
    setErr(null);
    void invoke<string>("run_agy_rotate", { args: ["quota"] })
      .then(() => read(true))
      // ★ 广播「池文件变了」：另一个 webview 收到后**只读盘**（~1ms），
      //   而不是也起一个 18.6s 的子进程。同 `useTraffic` 的 `traffic-updated`。
      .then(() => emit(POOL_EVT))
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => { running.current = false; if (!silent) setBusy(false); });
  }, [read]);

  const refresh = useCallback(() => { runQuota(false); }, [runQuota]);

  /**
   * 过期才取。**判据是盘上的 `quota_ran_at`（尝试过没有），不是各号的 `quota_at`（取成没有）** ——
   * 理由写在 `PoolFile.quota_ran_at` 上，那是这次改动里唯一会自我锁死成放大器的地方。
   */
  const refreshQuotaIfStale = useCallback(() => {
    if (running.current) return;
    if (Date.now() - quotaRanAt.current < QUOTA_FRESH_MS) return;
    runQuota(true);
  }, [runQuota]);

  /**
   * ★★★ 云端额度的**自动保鲜**，三个触发点共用同一条 `QUOTA_FRESH_MS`
   *   （用户 2026-09-16：「刷新情况太慢了，都要我手动去刷新，额度才更新上去」）。
   *
   * 形状照抄 `useTraffic`，**不另发明**：
   *   ① 进到这一档时看一眼岁数；② 可见时 30s 心跳；③ 托盘弹出。
   * ★ 三处**必须是同一个阀**。曾经挂载用 10 分钟、心跳用 2 分钟，结果启动 30s 后必定多取一次
   *   （`useTraffic` 实测过）——「新鲜」只能有一套标准。
   *
   * ⚠️ **不受 `enabled` 之外的条件放宽**：没人在看 Gemini 档时不该往云端发请求。
   *   这与 ① 那条「池文件挂载就读」不冲突 —— 那是读盘，这是联网。
   */
  useEffect(() => {
    if (!enabled) return;
    // ① 进档即看一眼（岁数没过阀就什么都不做）。手动 ↻ 仍然随时可用。
    if (autoRefreshEnabled()) refreshQuotaIfStale();
    // ② 心跳。★ `visibilityState` 与开关都**每 tick 现读** —— 窗口藏起来时零开销。
    const id = setInterval(() => {
      if (!autoRefreshEnabled()) return;
      if (document.visibilityState === "visible") refreshQuotaIfStale();
    }, TICK_MS);
    return () => clearInterval(id);
  }, [enabled, refreshQuotaIfStale]);

  /**
   * ③ 托盘弹出 —— 菜单栏 webview **只在 app 启动时挂载一次**（show/hide 不重建），
   * 所以初始化 effect 之后再不会跑。少了这条，菜单栏里的额度会冻在开机那一刻
   * （`useTraffic` 实测踩过，用户报「过了几十分钟还没刷新」）。
   */
  useEffect(() => {
    if (!enabled) return;
    let un: (() => void) | undefined;
    let dead = false;
    void listen("menubar-shown", () => {
      if (autoRefreshEnabled()) refreshQuotaIfStale();
    }).then((f) => { if (dead) f(); else un = f; });
    return () => { dead = true; un?.(); };
  }, [enabled, refreshQuotaIfStale]);

  /**
   * 另一个 webview 取完了 ⇒ **只读盘**，不重取。
   * ★ 不受 `enabled` 约束：这是别人已经取好的数据，收下它零成本（同 `LIVE_EVT` 那条理由）。
   */
  useEffect(() => {
    let un: (() => void) | undefined;
    let dead = false;
    void listen(POOL_EVT, () => { void readPool(); })
      .then((f) => { if (dead) f(); else un = f; });
    return () => { dead = true; un?.(); };
  }, [readPool]);

  const switchTo = useCallback((label: string) => {
    setSwitching(label);
    void invoke<string>("run_agy_rotate", { args: ["switch", label] })
      .then(() => read(true))
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => setSwitching(null));
  }, [read]);

  /** `switch` 之外的写操作。都要重读池 —— 改完名字/删完号，卡片得跟着变。 */
  const runThen = useCallback((args: string[]) => {
    void invoke<string>("run_agy_rotate", { args })
      .then(() => read(true))
      .catch((e: unknown) => setErr(String(e).slice(0, 200)));
  }, [read]);
  const renameTo = useCallback((label: string, next: string) =>
    runThen(["rename", label, next]), [runThen]);
  /** 带"正在跑"标记的写操作 —— 探针要 30s+，按钮必须能转圈。 */
  const runTagged = useCallback((id: string, args: string[]) => {
    setRunningId(id);
    void invoke<string>("run_agy_rotate", { args })
      .then(() => read(true))
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => setRunningId(null));
  }, [read]);
  const health = useCallback(() => runTagged("health", ["health"]), [runTagged]);
  const probe = useCallback((label?: string) =>
    runTagged(`probe:${label ?? ""}`, label ? ["probe", label] : ["probe", "--all"]),
    [runTagged]);
  const setRotate = useCallback((label: string, on: boolean) =>
    runThen(["rotate", label, on ? "--on" : "--off"]), [runThen]);
  const setAuto = useCallback((on: boolean) => {
    setAutoOn(on);                       // 乐观更新：开关点下去要立刻有反馈
    runThen(["auto-switch", on ? "--on" : "--off"]);
  }, [runThen]);
  const removeIt = useCallback((label: string) => runThen(["remove", label]), [runThen]);

  const snapshotOf = useCallback((a: AgyPoolAccount, liveSnap: AgySnapshot | null) => {
    // ★★★ **本机 RPC 那份只在能证明归属时才用。**（2026-09-13 三方评审共同指出）
    //   `agy-quota` 打的是「第一个应答的 agy 进程」，而本机常有多个长期存活的进程、
    //   身份各不相同 —— 那份周额度属于**那个进程**，不属于"当前登录的号"。
    //   实测：卡上 `user-b` 的「周 99%」实际来自 pid 24433（`user-a`，起于 09-07）。
    //   ⚠️ 旧判据是 `a.sub === liveSub`，它问的是"这张卡是不是当值号"，
    //     而该问的是"这份读数是不是这张卡的"。**归属要有证据，没证据就不归属** ——
    //     宁可少一行（卡上显示 `—` 并说明原因），也不把 A 的数字画在 B 的卡上。
    const mine = !!liveSnap?.available && !!liveSnap.pid_email && !!a.email
      && liveSnap.pid_email === a.email;
    return mine ? liveSnap : toSnapshot(a);
  }, []);

  return { accounts, liveSub, drifted, snapshotOf, busy, err, refresh, switchTo,
           renameTo, removeIt, switching, health, probe, setRotate,
           autoOn, setAuto, running: runningId };
}
