import type { GrokSnapshot } from "../grok";
import { useQuotaSidecar, type QuotaSidecar } from "./useQuotaSidecar";

/**
 * grok 周额度的取数 hook。循环体在 `useQuotaSidecar`（与 agy 共用），这里只定策略。
 *
 * ★★ 这条链路的关键事实：**它会联网。** 抓取者分成两条，别合成一个轮询：
 *   · grok CLI **活着**时：`grok-quota-sampler` 是唯一 GET 账单的人（约 15s），
 *     写完 sidecar，Rust 1s 内 `emit("grok-quota-updated")`，这里只读。
 *   · grok **没在跑**时：采样器自己退出。下面的 10min 轮询是兜底，
 *     周窗口每 1% ≈ 100 分钟，闲置时不需要更密。
 *
 * `enabled` 仍白名单（总览 / 菜单栏）：那只挡**主动** `run_grok_quota`。
 * 推送通道不受 `enabled` 约束（见 `useQuotaSidecar`），收下别人已经取好的数没有成本。
 */
const FRESH_MS = 10 * 60 * 1000;

export function useGrokQuota(opts: { enabled?: boolean } = {}): QuotaSidecar<GrokSnapshot> {
  return useQuotaSidecar<GrokSnapshot>({
    readCmd: "read_grok_quota",
    runCmd: "run_grok_quota",
    freshMs: FRESH_MS,
    enabled: opts.enabled,
    updateEvent: "grok-quota-updated",
  });
}
