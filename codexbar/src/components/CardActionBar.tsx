import { useEffect, useState, type ReactNode, type ReactElement } from "react";
import type { Theme } from "../theme";
import { CARD_ACTIONS_LIFE_MS, CARD_ACTIONS_EXIT_MS } from "../helpers";

/**
 * 卡片底部的**动作条浮层** —— codex 账号卡与 agy 账号卡**共用这一份**。
 *
 * ★★ 为什么抽成组件（2026-09-23）：两张卡原来各写一套，注释里早就写着「两张卡各写一套
 *   迟早只改一边」—— 而收回动画 + 倒计时细线第一版就**只改了 codex 那边**，agy 卡照样受
 *   10 秒收回计时器控制，却一帧消失、也没有预告。§5c 页面统一性：同一类卡必须长得一样，
 *   而「长得一样」唯一靠得住的做法是**只有一份实现**。
 *
 * ## 生命周期：打开 → 停留 → 收回（退场动画）→ 卸载
 *
 * 用户 2026-09-23：「收回的动画设计一下，现在太生硬了」，从 demo 的 A/B/C 里选了
 * **A · 原路退回** + **倒计时细线**。生硬的根因是条件渲染：弹出有 160ms 的 `cbRise`，
 * 收回是组件**直接卸载、0ms**。所以 `open` 变假之后要**先挂着播完 `cbSink` 再卸载**。
 *
 * ★ 用「渲染期调整状态」而不是 effect：effect 在 commit **之后**才跑，于是关闭那一帧
 *   动作条会先被卸载、下一帧再以退场态挂回来 —— 闪一下再沉下去。
 * ★ `gen` 在**每次打开**时加一、作 `key`：收到一半又被点开时重播入场、细线从满格重走，
 *   否则细线接着旧进度走，与 App 那边刚重新开始的计时器对不上。
 * ★ 卸载靠 `setTimeout` 而不是 `animationend`：headless 的虚拟时钟下 CSS 动画时间线
 *   **根本不走**（实测 `currentTime` 恒 0），`animationend` 永远不来 —— 用它的话 harness
 *   里动作条永不卸载；真机上若动画被系统设置禁掉同样不来。定时器两边都成立。
 */
export default function CardActionBar({ open, t, children }: {
  open: boolean; t: Theme; children: ReactNode;
}): ReactElement | null {
  const [prevOpen, setPrevOpen] = useState(open);
  const [leaving, setLeaving] = useState(false);
  const [gen, setGen] = useState(0);
  if (prevOpen !== open) {
    setPrevOpen(open);
    setLeaving(!open);
    if (open) setGen((g) => g + 1);
  }
  useEffect(() => {
    if (!leaving) return;
    // 系统开了「减弱动态效果」⇒ CSS 那边不播退场，这里也就不必等，立即卸载。
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const id = window.setTimeout(() => setLeaving(false), reduce ? 0 : CARD_ACTIONS_EXIT_MS + 40);
    return () => window.clearTimeout(id);
  }, [leaving]);

  if (!open && !leaving) return null;
  return (
    <div data-actions key={gen} data-leaving={leaving ? "" : undefined}
         aria-hidden={leaving || undefined}
         className={leaving ? "cb-actions cb-actions-leaving" : "cb-actions"}
         onClick={(e) => e.stopPropagation()}
         style={{
           position: "absolute", left: 10, right: 10, bottom: 10, zIndex: 3,
           display: "flex", gap: 6, padding: 8, borderRadius: 9,
           /* ★★ **macOS 式半透明磨砂**（用户 2026-09-23：「结合 macOS 的风格，弹出的功能样式
              加个透明度会比较好」）。取的是 NSVisualEffectView 菜单/弹层材质那一套：
              · 底色透明度 .97 → **.66**（深浅两档同一个值）—— 下面那行「到期 / 重置卡」透出轮廓，
                读者知道底下还有东西、不是没了；
              · ★★ 透明度**是实测挑出来的，不是拍的**（真实渲染含模糊，8 张卡取最差像素，
                `scratch/measure_action_bar_material_20260923.py`）。灰色图标（非文字，门槛 3.0）：
                深色 .60/.66/.72/.80 → 4.00/4.08/4.17/4.29（选 .66）；浅色 .55/.60/.66/.72/.80 →
                4.77/4.83/4.93/5.01/5.12（选 .66）。两档都有大量余量。
                ⚠️ 第一轮测出「浅色要 .80 才过线」（.68 只有 2.64）—— **那是量错了**：切主题用的
                  `localStorage.codexbar_theme` 是菜单栏的键，主窗口不认，浅色那列量的是
                  「白色条压在深色界面上」。改成真点太阳图标、并先核实卡片底色变白后重量，
                  浅色反而比深色余量更大。仪器自己撒谎的又一例：测量值合理得让人不去怀疑前提。
              · ★ 底色取**与卡片同色**（深色 `#141a22`），不是更浅的 `28,34,43` ——
                第一版用了后者，底下什么都没有时灰字对比度也从 4.55 掉到 3.83，
                纯粹是挑色挑错了：透明材质只该让「底下有的东西」透出来，不该自己先泛白。
              · 模糊 6px → **20px + saturate(170%)** —— 只降透明度不加大模糊，透出来的是
                清晰的字，与按钮文字打架；饱和度拉高是 macOS 材质的标志（透出来的颜色不发灰）；
              · 顶边一道 1px 内高光 —— 玻璃的边缘感，同 macOS 弹层。
              ⚠️ **必须同时写 `WebkitBackdropFilter`**：CodexBar 跑在 WKWebView（Safari 内核）
                 里，只写标准属性在较老的 macOS 上会被整条忽略 —— 那时「半透明」就退化成
                 「半透明但不模糊」，底下的字清清楚楚地叠在按钮上。harness 用的是 Chrome，
                 两种写法都认，所以这个缺口在 harness 里**看不出来**。
              ★ 对比度按「它盖住了什么」算（本仓规矩），而且是**量真实像素**不是拿色值合成 ——
                合成模型不计模糊（一条 5px 进度条糊开后只剩 ~1/10），会给出毫无意义的 1.92。
                闸：tests/test_card_action_bar.py（真渲染、8 张卡取最差、深浅两档、双向）。 */
           background: t.isDark ? "rgba(20,26,34,.66)" : "rgba(255,255,255,.66)",
           backdropFilter: "blur(20px) saturate(170%)",
           WebkitBackdropFilter: "blur(20px) saturate(170%)",
           /* ★ 边框用**发丝线**不用 accent（用户 2026-09-21：「取消绿色的边框」）。
              青色在本仓专属「激活态 / 推荐项 / 主按钮」，而卡片被选中时
              **本身已经有一圈青边**了 —— 浮层再来一圈是同一个语义说两遍。
              分层交给发丝线 + 阴影，这也是全局 `ui-design.md` 的原话。 */
           border: `1px solid ${t.isDark ? "rgba(255,255,255,.10)" : "rgba(0,0,0,.08)"}`,
           boxShadow: `inset 0 1px 0 ${t.isDark ? "rgba(255,255,255,.06)" : "rgba(255,255,255,.7)"}, ${t.shadow}`,
           // ★ 退场中**点不到**：一个正在消失的按钮被点中，比没点中更让人困惑。
           pointerEvents: leaving ? "none" : undefined,
           // ★ 时长从 TS 常量注入，不写死在 CSS 里 —— 一个数只许有一个家。
           animationDuration: leaving ? `${CARD_ACTIONS_EXIT_MS}ms` : undefined,
           // ★★★ **绝不换行**（用户 2026-09-21：「我不要出现换行的」）。
           //   换行的动作条不只是难看：第二行会把浮层撑高、盖掉更多卡片内容，
           //   而且「最后一个按钮掉下去」看起来像它坏了。
           //   ★ 空间不够时**一起压缩**，不是折行 —— 所以里面每个控件都可收缩，
           //     而卡片本身有 `CARD_MIN_W` 兜底，保证压到极限仍装得下。
           flexWrap: "nowrap",
         }}>
      {children}
      {/* ★ 倒计时细线：底边一条 2px，从满格匀速缩到空，缩完那一刻正好收回
          （用户 2026-09-23 选的）。它回答的是「它为什么突然没了」—— 没有预告的消失
          才叫生硬，动画只是一半。时长与 App 的收回计时器读**同一个常量**。
          实测（真实时钟）：2.5s/5s/9s 时分别剩 75%/50%/10%，10s 时为 0 并开始退场。
          ★ 左右各缩进 9px 避开 9px 圆角，而不是给动作条加 `overflow: hidden`：
            后者会连带裁掉条里任何溢出的浮层。 */}
      <i data-actions-countdown className="cb-actions-tick" aria-hidden
         style={{ background: t.accent, animationDuration: `${CARD_ACTIONS_LIFE_MS}ms` }} />
    </div>
  );
}
