import type { Theme } from "../theme";
import type { PoolKey, PoolPlatform } from "../platforms";
import logoOpenAI from "../assets/logo-openai.png";
import logoGrok from "../assets/logo-grok.png";

/**
 * 菜单栏的**平台 logo 芯片行**（v4 交接稿 §2，1:1 复刻）。
 *
 * 它替换的是 v3 那条闲置的「可用账号」标题行 —— 那一行只重复了 Tab 上已经有的数字。
 *
 * ★★ **logo 用蒙版着色，不备两套彩色图**（稿 §2）：同一张白色 glyph + 透明底的 PNG，
 *   通过 `mask-image` 上色，选中/未选中自动跟着芯片状态变。备两套图的话，
 *   下次调品牌色会漏掉其中一套，而那**不会报任何错**。
 *
 * ★★ **资产必须内置**（稿 §9.2）：运行时远程加载等于离线就没有 logo，
 *   而这个 app 的全部卖点就是本机可用。
 */

/** Gemini 没有现成蒙版图，用内联四角星（稿 §2 末）。`currentColor` 让它跟着芯片状态走。 */
const IconGemini = ({ size = 13 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 1.8c.9 4.9 4.3 8.3 9.2 9.2v2c-4.9.9-8.3 4.3-9.2 9.2h-2c-.9-4.9-4.3-8.3-9.2-9.2v-2c4.9-.9 8.3-4.3 9.2-9.2h2z" />
  </svg>
);

const MASKS: Partial<Record<PoolKey, string>> = { codex: logoOpenAI, grok: logoGrok };

export interface ChipItem extends PoolPlatform {
  /** 这一档**渲染出来**几个号。写"池里有几个"就是在说界面上看不到的事。 */
  count: number;
  /** 这一档有没有失效账号 —— 数字后跟一颗红点（稿 §2）。 */
  hasDead?: boolean;
  /** 平台识别色，走 `colorOf(traffic, colorKey)` 取。 */
  color: string;
}

export default function PlatformChips({ items, cur, on, right, t }: {
  items: ChipItem[];
  cur: PoolKey;
  on: (k: PoolKey) => void;
  /** 右侧小字 `{当前平台名} · ↻ {时间}` —— **只有 logo 时用来防认错**（稿 §2）。 */
  right?: React.ReactNode;
  t: Theme;
}): React.ReactElement {
  return (
    <div className="mb-chips">
      {items.map((p) => {
        const on_ = p.key === cur;
        const mask = MASKS[p.key];
        return (
          <span key={p.key} className={`mb-chip${on_ ? " on" : ""}`} onClick={() => on(p.key)}
                title={`${p.label} · ${p.count} 号`}
                style={{
                  // 选中：品牌色 50% 描边 + 10% 底；未选中：中性描边、透明底（稿 §2 表）
                  borderColor: on_ ? `${p.color}80` : t.ghostBorder,
                  background: on_ ? `${p.color}1a` : "transparent",
                }}>
            <span className="mb-chip-logo"
                  style={{ background: on_ ? p.color : "rgba(255,255,255,.08)",
                           color: on_ ? t.appBg : p.color }}>
              {mask ? (
                <span className="mb-chip-mask"
                      style={{
                        // ★ 蒙版着色：选中反白成底色、未选中用品牌色。一张图两态。
                        background: on_ ? t.appBg : p.color,
                        WebkitMaskImage: `url(${mask})`,
                        maskImage: `url(${mask})`,
                      }} />
              ) : <IconGemini />}
            </span>
            <span className="mb-chip-n" style={{ color: on_ ? p.color : t.muted }}>{p.count}</span>
            {/* 死号提示：数字后紧跟一颗红点（稿 §2）。★ 只在真有死号时出现 ——
                常亮的灯会被学会忽略，这是本仓判过死刑的形态。 */}
            {p.hasDead && <span className="mb-chip-dead" />}
          </span>
        );
      })}
      {right && <span className="mb-chips-right" style={{ color: t.muted }}>{right}</span>}
    </div>
  );
}
