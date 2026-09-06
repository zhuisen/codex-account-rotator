import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

/**
 * 每日清晨探针的**补跑**路径（用户 2026-09-06 要的「早上 6 点给 Plus 号探针，
 * 让 5h 额度走动」）。
 *
 * ## 为什么定时器之外还要这一条
 *
 * 主触发是 launchd 的 `com.doushutangmu.codex-rotate.dawnprobe`（06:00
 * `StartCalendarInterval`）。但**本项目的日历定时有前科**：keepalive / refreshquota 的
 * `StartCalendarInterval` 曾被 `install-launchd.sh` 以外的东西改写掉，`runs = 0`、
 * **从未运行过**，而没有任何一处会为此报红（改写者至今未查明，CLAUDE.md §3）。
 * 所以那个 plist **不能是唯一触发路径** —— 这里补一条不依赖 plist 的。
 *
 * ## 三条护栏（全在 CLI 侧，这里只是尽量少调它）
 *
 * ① **默认关闭**：`state.json` 的 `dawn_probe.enabled` 缺省为假。仓库已公开，
 *    一个默认开启的自动计费定时器会在别人机器上悄悄花钱。
 * ② ★★ **先占天再探**：`cmd_dawn_probe` 在**发请求之前**就把当天日期写进 state
 *    （持跨进程互斥锁）。没有它，launchd 与本补跑几乎同时触发就是**双重计费**。
 *    已用 3 进程并发实测：恰好 1 个进到探测阶段。
 * ③ **每次运行落痕**，成功失败都写，UI 读它 —— 「从未运行过」必须看得见。
 *
 * ## 只在菜单栏 webview 跑
 *
 * 两个 webview 都常驻，都跑就是每天多起一个 python（虽然被②挡住不会重复计费，
 * 但那是靠护栏兜底，不是设计）。菜单栏 webview 在 app 启动时创建且**从不卸载**，
 * 是更稳的那个宿主。
 *
 * ★ 判据是「今天过了 6 点、而 state 里记的日期不是今天」，**不是**「现在正好 6 点」——
 *   Mac 凌晨多半在睡觉，卡点判定等于永远不触发。睡醒后补跑才是真实场景。
 */

/** 到点后多久检查一次。只是读一次 state，不起 python。 */
const TICK_MS = 10 * 60 * 1000;
/** 当天几点之后才允许补跑。与 launchd 的 `Hour=6` 同源，改一处要改两处。 */
const DAWN_HOUR = 6;

interface DawnRec { enabled?: boolean; date?: string; state?: string }

function todayLocal(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function useDawnProbe(): void {
  const running = useRef(false);

  useEffect(() => {
    let label = "";
    try { label = getCurrentWindow().label; } catch { return; }
    if (label !== "menubar") return;      // 见上：只在常驻的那个 webview 跑

    const check = async () => {
      if (running.current) return;
      if (new Date().getHours() < DAWN_HOUR) return;
      try {
        const raw = await invoke<string>("run_rotate", { args: ["dawn-probe", "--status"] });
        const rec = JSON.parse(raw.trim().split("\n").pop() || "{}") as DawnRec;
        // ★ 关掉了就什么都不做 —— 这是用户对一个**会花钱**的功能的显式选择，
        //   补跑路径没有资格绕过它。
        if (!rec.enabled) return;
        if (rec.date === todayLocal()) return;      // launchd 已经跑过了，正常路径
        running.current = true;
        await invoke("run_rotate", { args: ["dawn-probe"] });
      } catch {
        // 读不到就下个 tick 再说。★ 不弹 toast：这是后台补救，
        //   失败本身不是用户此刻需要处理的事；真正该看的是设置页里那条「上次运行」。
      } finally {
        running.current = false;
      }
    };

    void check();
    const id = setInterval(() => { void check(); }, TICK_MS);
    return () => clearInterval(id);
  }, []);
}
