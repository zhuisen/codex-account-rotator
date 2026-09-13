/**
 * **账号池**的平台清单 —— 主窗总览的分档 Tab 与菜单栏的 logo 芯片行**共用这一份**
 * （菜单栏 v4 交接稿 §9.1：「平台集合单一数据源」）。
 *
 * ★★★ **这不是「AI 用量」那张表。** 两者回答的是不同的问题，用户 2026-09-13 拍板分开：
 *
 *     账号池（本文件，3 家）  = 我有凭证、能管的号     → codex / gemini / grok
 *     AI 用量（scan.py 注册表，8 家）= 本机哪些 CLI 落了盘 → 还含 claude / kimi / deepseek / mimo / …
 *
 *   强行统一会让用量页少掉 Claude（本机占 77.8%），或让账号页多出五个管不了的档。
 *
 * ★ `colorKey` 与 `key` **故意不同名**：账号池这边叫 `gemini`（用户定的叫法），
 *   而取色要去用量注册表里找，那家在 `scan.py` 里的键是 `agy`。
 *   一律走 `colorOf(traffic, colorKey)`，别在组件里写死色值。
 */
export type PoolKey = "codex" | "gemini" | "grok";

export interface PoolPlatform {
  key: PoolKey;
  label: string;
  /** 去 `colorOf(traffic, …)` 取识别色用的键（= `traffic/scan.py` 注册表里的键）。 */
  colorKey: string;
  /** 这一档的账号**是怎么轮换的**。三家机制根本不同，不写就会被当成一样的。 */
  note: string;
  /**
   * 这一档有没有「检查 token / 探针」这两个动作。
   *
   * ★★★ **只有 codex 有，这是与 v4 稿的一处刻意偏离。** 稿 §5 把 Grok 也算进
   *   「刷新全池｜检查 token｜探针」那一组，但那假设 grok 也有自己的账号池与探针；
   *   本机的实测事实是：grok 是**单号只读**，而 `探针` 跑的是 `codex-rotate probe --all`
   *   —— 它扣的是 **codex** 的额度。挂在 Grok 档上就是用户看着 grok 的卡按下去、
   *   花的是另一家的钱，正是本仓判过死刑的那一类。稿与事实冲突时以事实为准。
   */
  codexActions: boolean;
  /** 加号时要用户去终端敲的命令（没有就给一句说明）。 */
  addHint: string;
}

export const POOL_PLATFORMS: readonly PoolPlatform[] = [
  { key: "codex", label: "Codex", colorKey: "codex", codexActions: true,
    note: "账号池 · 经本地代理逐请求换号 · 5h/周双窗口",
    addHint: "加号：终端里跑 `codex-rotate login`" },
  { key: "gemini", label: "Gemini", colorKey: "agy", codexActions: false,
    // ★ 「启动前换凭证」是**设计事实**不是缺陷：agy 只在进程启动时读凭证，
    //   所以换号只对下一次启动生效，已经开着的会话不受影响。
    note: "Antigravity · 启动前换凭证（agy 只在启动时读）",
    addHint: "加号：终端里跑 `agy-rotate login`" },
  { key: "grok", label: "Grok", colorKey: "grok", codexActions: false,
    note: "Grok · 单号只读 · 周窗口",
    addHint: "grok 是单号只读 —— 登录由 grok CLI 自己管" },
] as const;

export const platformOf = (k: PoolKey): PoolPlatform =>
  POOL_PLATFORMS.find(p => p.key === k) ?? POOL_PLATFORMS[0];

const STORE_KEY = "codexbar_provider";

/**
 * 记住的分档。★★ **必须认旧值**：2026-09-13 之前存的是 `google` / `xai`，
 * 不迁移的话，停在 Gemini 档的用户下次打开会**静默跳回 Codex**，
 * 而那看起来就像"我的选择没被记住"。本仓「读不到 ≠ 没有」的另一种形态。
 */
export function loadPoolKey(): PoolKey {
  try {
    const v = localStorage.getItem(STORE_KEY);
    if (v === "google" || v === "gemini") return "gemini";
    if (v === "xai" || v === "grok") return "grok";
  } catch { /* 隐私模式下读不了，落到默认 */ }
  return "codex";
}

export function savePoolKey(k: PoolKey): void {
  try { localStorage.setItem(STORE_KEY, k); } catch { /* 隐私模式下写不了，忽略 */ }
}
