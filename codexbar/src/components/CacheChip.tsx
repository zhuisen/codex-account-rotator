import { cacheModeLabel, cacheModeDesc, type CacheMode } from "../traffic";

const AMBER = "#E0A21C";

/**
 * 「当前不是原始口径」的披露标签。开关在设置页,但**被它改变的数字在这一页** ——
 * 不在数字旁边说一声,页面就会在毫无提示的情况下把 34.2B 显示成 0.46B(相差 25 倍),
 * 那是误导而不是筛选。
 *
 * ★ 它只是**口径名**,不带任何数字 —— 缓存指标本身在非默认口径下要从页面上消失
 * (用户 2026-08-11 定稿),连「已排除 32.9B」也不留,否则等于换个说法把它请回来。
 * 具体排除了什么放在 `title` 里,鼠标停上去才看得到,不占版面。
 *
 * `full` 时返回 `null`:默认口径下不该有任何多余像素(设计规范「一屏密排,靠层级不靠装饰」)。
 * 用琥珀而不是品牌青 —— 青色在本产品里是「激活/推荐」,而这里要表达的是「这个数被限定了」。
 * 琥珀是固定语义色(两套主题只改明度不改色相),所以不需要 `Theme`。
 */
export default function CacheChip({ mode }: { mode: CacheMode }): React.ReactElement | null {
  if (mode === "full") return null;
  return (
    <span
      title={`${cacheModeDesc(mode)}\n口径在「设置 › 缓存计入口径」里改。`}
      style={{
        fontSize: 10, fontWeight: 700, fontFamily: "'JetBrains Mono'", letterSpacing: ".03em",
        color: AMBER, background: `${AMBER}1A`, border: `1px solid ${AMBER}40`,
        padding: "3px 8px", borderRadius: 7, whiteSpace: "nowrap", flexShrink: 0,
      }}
    >
      {cacheModeLabel(mode)}
    </span>
  );
}
