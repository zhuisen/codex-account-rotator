import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { AgyQuota, AgySnapshot } from "../agy";

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
 * agy 账号池。→ 每个号一张卡所需的一切。
 *
 * ★ 只读盘，不主动联网：`refresh()` 才会跑 `agy-rotate quota`（零消耗，但要往云端发请求）。
 *   与 grok/agy 额度同一条纪律 —— 总览一打开就联网不是这个 app 的做法。
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
  switching: string | null;
} {
  const [accounts, setAccounts] = useState<AgyPoolAccount[]>([]);
  const [liveSub, setLiveSub] = useState<string | null>(null);
  const [drifted, setDrifted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const running = useRef(false);

  const read = useCallback(async () => {
    try {
      const raw = await invoke<string | null>("read_agy_pool");
      if (!raw) { setAccounts([]); setLiveSub(null); return; }
      const p = JSON.parse(raw) as PoolFile;
      setAccounts(Object.entries(p.accounts ?? {})
        .map(([sub, a]) => ({ sub, ...a }))
        // ★ 按 label 排，不按额度：位置一变，用户就得重新找他的号。
        //   "该用哪个"由「当前」徽章回答，不由顺序回答（同账号卡那条）。
        .sort((x, y) => (x.label || "").localeCompare(y.label || "")));
      // ★★★ **先用 `live_seen` 兜底，再立刻用现读覆盖。** 只用 `live_seen` 就是这次
      //   用户报的那个 bug；只用现读则会在 `live` 还没回来的那一帧丢掉「当前」徽章。
      setLiveSub(p.live_seen ?? null);
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    }
    try {
      const out = await invoke<string>("run_agy_rotate", { args: ["live", "--json"] });
      const probe = JSON.parse(out) as LiveProbe;
      // ★ 读不到（`sub` 为 null）时**不要**把它写成 null 覆盖掉兜底值：
      //   「这次没探到」和「确实没人登录」是两件事（本仓 §7.0b）。
      if (probe.sub) setLiveSub(probe.sub);
      setDrifted(!!probe.drifted);
    } catch {
      // 探不到当前号不该让整块卡片失败 —— 上面的池数据已经可用了。
      setDrifted(false);
    }
  }, []);

  useEffect(() => { if (enabled) void read(); }, [enabled, read]);

  const refresh = useCallback(() => {
    if (running.current) return;
    running.current = true;
    setBusy(true); setErr(null);
    void invoke<string>("run_agy_rotate", { args: ["quota"] })
      .then(() => read())
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => { running.current = false; setBusy(false); });
  }, [read]);

  const switchTo = useCallback((label: string) => {
    setSwitching(label);
    void invoke<string>("run_agy_rotate", { args: ["switch", label] })
      .then(() => read())
      .catch((e: unknown) => setErr(String(e).slice(0, 200)))
      .finally(() => setSwitching(null));
  }, [read]);

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

  return { accounts, liveSub, drifted, snapshotOf, busy, err, refresh, switchTo, switching };
}
