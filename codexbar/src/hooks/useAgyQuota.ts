import type { AgySnapshot } from "../agy";
import { useQuotaSidecar, type QuotaSidecar } from "./useQuotaSidecar";

/**
 * agy 额度的取数 hook。循环体在 `useQuotaSidecar`（与 grok 共用），这里只定策略。
 *
 * ★★ 与 grok 那条**成本结构完全不同**，所以节流也不同：
 *   grok → 联网打 xAI，用别人的配额，10min
 *   agy  → 本机 loopback RPC，不联网、不消耗任何配额、实测毫秒级，**2min**
 *
 * 短是有理由的，不是随手调小：agy 最紧的窗口是 **5h**（300 分钟），每 1% ≈ 3 分钟；
 * 用 grok 那个 10 分钟粒度，用户会看到一个落后三个百分点的数。
 *
 * 唯一的本地成本是起一次 python + `ps` + `lsof`，由 Rust 侧 `AGY_COALESCE_SECS = 60` 兜住。
 */
const FRESH_MS = 2 * 60 * 1000;

export function useAgyQuota(opts: { enabled?: boolean } = {}): QuotaSidecar<AgySnapshot> {
  return useQuotaSidecar<AgySnapshot>({
    readCmd: "read_agy_quota",
    runCmd: "run_agy_quota",
    freshMs: FRESH_MS,
    enabled: opts.enabled,
  });
}
