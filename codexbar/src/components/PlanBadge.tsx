import type { Theme } from "../theme";

/**
 * 套餐徽章。数据源是 `plan`(id_token / usage API),**不是** node 名。
 *
 * 曾经的问题:新增 Pro 号被自动命名成 `plus8`,界面上就一直读作 Plus。命名已修,但 label 终究只是
 * 昵称 —— 老号从 Plus 升级到 Pro 时 label 一个字都不会变,只有这个徽章会跟着变。所以判套餐永远看它。
 *
 * Plus 是绝大多数,画出来只是噪音,故只在 Pro(及未来其它非 plus 档)显示。
 */
export default function PlanBadge({ plan, t, size = 8 }: { plan: string; t: Theme; size?: number }) {
  if (!plan || plan === "plus" || plan === "free") return null;
  return (
    <span title={`套餐:${plan}`} style={{
      flexShrink: 0, fontSize: size, fontWeight: 700, letterSpacing: ".06em",
      padding: "1px 5px", borderRadius: 4, textTransform: "uppercase",
      color: t.accentText, background: "#8b5cf6",
    }}>{plan}</span>
  );
}
