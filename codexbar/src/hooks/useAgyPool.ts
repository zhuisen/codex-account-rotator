import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
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
}

interface PoolFile {
  accounts?: Record<string, Omit<AgyPoolAccount, "sub">>;
  /** 上次**我们写进去**时看到的当值号。★★★ **绝不能拿它当"当前账号"显示。**
   *  钥匙串是一个被多个常驻 agy 进程并发写的**单槽**：实测 2026-09-13 17:58 我们装进 B，
   *  18:23:17 一个身份为 A 的旧 agy 在它自己 access token 到期（18:23:16）时刷新，
   *  把整份凭证写回钥匙串 —— B 被冲掉，而这个字段毫不知情。用户看到的就是
   *  「界面说 B、agy 里是 A」。真相只能**现读**，见 `live --json`。 */
  live_seen?: string | null;
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
 * 把云端那份按账号的额度，翻成卡片认识的 `AgySnapshot` 形状。
 *
 * ★★ **只造 5h 那一格，绝不补一个假的周格。** 云端 `fetchAvailableModels` 给的
 *   `remainingFraction` 实测就是 5h 窗口（0.9566 与本机 RPC 的 `gemini-5h` 95.66 逐位相同）；
 *   周窗口它根本不返回。补一格「周 100%」会让每张卡都显示满格周额度 ——
 *   而上游那个字段的缺省值恰好也是 1.0，这条链路上「没有」和「满格」只隔一个默认值。
 *   不造那一格，卡片按槽位补一行等高空行，用户看到的是"这里没有数"，那是真话。
 */
function toSnapshot(a: AgyPoolAccount): AgySnapshot {
  const groups = Object.entries(a.quota ?? {}).map(([k, v]) => ({
    name: k === "claude" ? "Claude / GPT" : "Gemini Models",
    buckets: [{
      bucket_id: `${k}-5h`,
      window: "5h",
      remaining_percent: Math.round(v.remaining * 1000) / 10,
      reset_at: Math.round(Date.parse(v.reset) / 1000),
    }],
  }));
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

  const refresh = useCallback(() => {
    if (running.current) return;
    running.current = true;
    setBusy(true); setErr(null);
    void invoke<string>("run_agy_rotate", { args: ["quota"] })
      .then(() => read(true))
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => { running.current = false; setBusy(false); });
  }, [read]);

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
