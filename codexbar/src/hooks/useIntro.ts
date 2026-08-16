import { useEffect, useRef, useState } from "react";
import { getSettings } from "../pages/SettingsPage";

/** 入场时长。C 档（左到右擦除）用户 2026-08-16 从四方案里选的，配 KPI 数字同步滚动。 */
export const INTRO_MS = 700;

/**
 * 要不要播入场动效。**两个门任一为「关」就不播**：
 * ① 设置页的「入场动效」开关（用户 2026-08-16 加的 —— 不是所有人都想看）；
 * ② 系统的 `prefers-reduced-motion`。
 *
 * ★ 这两者都是「不播」而不是「播快一点」。把它做成缩短时长，等于没听懂人家为什么关掉。
 * ★ 单一真源：`.cb-wipe` 这个 class 该不该加也读它，不许在页面里各写一份 `getSettings().intro`。
 */
export function introEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return false;
  try { return getSettings().intro !== false; } catch { return true; }
}

/** easeOutCubic —— 起步快、收尾稳。**不要回弹**：仪表类 UI 里弹跳显得轻浮。 */
const ease = (t: number): number => 1 - Math.pow(1 - t, 3);

/**
 * 入场进度 0→1。`dep` 变化时重头播一次。
 *
 * ★★ **`dep` 必须是「数据集身份」，绝不能是数据本身。**
 * `useTraffic` 每 2 分钟自动刷新一次（可见时），数据对象每次都是新引用。若拿数据当依赖，
 * 页面会**每 2 分钟自己重播一次动画** —— 你正在读的时候数字突然滚回 0，比「突然出现」糟得多。
 * 所以调用方传的是 `range` / 平台 key 这类身份，跟图表 `key` 用的是同一套判据。
 *
 * ★ 尊重 `prefers-reduced-motion`：直接返回 1（无动画），不是播得快一点。
 *   系统里关掉动效的人要的是「没有」，不是「短一点」。
 */
export function useIntro(dep: string): number {
  const [p, setP] = useState(1);
  const raf = useRef(0);

  useEffect(() => {
    if (!introEnabled()) { setP(1); return; }

    const t0 = performance.now();
    setP(0);
    const step = (now: number): void => {
      // ★★ **下界必须钳**。只钳上界时，一旦 `now < t0`（rAF 时间戳与 `performance.now()` 的
      //   原点错位、或 headless 的 virtual time）就会得到负的 t，而 easeOutCubic 对负数是
      //   `1-(1-t)³` → 大负数 ⇒ KPI 直接显示 **-76,424,735 / $-61.182**（实测截到）。
      //   动画进度天然是 [0,1]，两端都钳才是完整的。
      const t = Math.max(0, Math.min(1, (now - t0) / INTRO_MS));
      setP(ease(t));
      if (t < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);

    /**
     * ★★ 看门狗：无论时钟怎么走，到点**强制归位到 1**。
     *
     * 不是保险起见 —— 实测踩到了：headless 的 virtual time 下 `now` 始终不超过 `t0`，
     * `t` 恒为 0，rAF 无限自我调度，**KPI 永久停在 0**（截图为证：总 token 0 / 总费用 $0.000）。
     * 一个入场动效把真实数据盖成 0，比「突然出现」严重得多。
     * 动效可以不播，**数字不能是错的** —— 所以最终值由定时器兜底，不由动画负责。
     */
    const wd = setTimeout(() => { cancelAnimationFrame(raf.current); setP(1); }, INTRO_MS + 250);
    return () => { cancelAnimationFrame(raf.current); clearTimeout(wd); };
  }, [dep]);

  return p;
}
