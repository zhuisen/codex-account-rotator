import type { Theme } from "../theme";

/**
 * 用量页标题右边那行**数据源副标**（交接稿 §1 主页 / §5 详情页都有）。
 *
 * ★★ 抽成组件的理由与 `KpiStrip` 一字不差：「AI用量信息」与「平台详情」是**同一族的两页**，
 *   两页各写一份渲染，本仓已经漂过两次（§5c 页面统一性）。这一行只有一句话，
 *   但它正是最容易只加在一页上的那种东西 —— 2026-09-13 用户实报「内容和位置不是 1:1」时，
 *   这行在**两页上都不存在**。
 *
 * ★ 它不是装饰：`不消耗额度` 是本仓反复强调的**披露**（数据全部来自本机 CLI 自己落的盘），
 *   而"这个页面会不会花我的钱"恰恰是用户第一次看到它时会问的。
 */
export default function PageSub({ text, t }: { text: string; t: Theme }): React.ReactElement {
  return (
    <span style={{ fontSize: 12, color: t.text2, whiteSpace: "nowrap",
                   overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>
      {text}
    </span>
  );
}
