#!/usr/bin/env python3
"""窄宽度**折行/溢出/压扁**全景扫描（CLAUDE.md §4 的一部分）。

为什么需要它:2026-08-24 用户连报三处排版缺陷（总览头部按钮断字、菜单栏刷新时间被裁、
卡片动作条压成竖排），**全部靠肉眼截图发现**。而当时三个自动探针一个都没报:

  · `overflow`(scrollWidth > clientWidth)—— flex 空间不够时**压缩子项**而不是溢出,不成立;
  · `squeezed`(渲染宽 ≤ 4px)—— 「切换到此号」被压到 ~20px 竖排,正好漏过;
  · `--dump-dom` —— 拿的是**源文本**,浏览器在哪断的行它根本不知道。

真正的判据是 **content box 高 vs 单行高**（`wrapped` 探针，2026-08-24 加）。
第一版拿 border box 比,`padding: 7px 11px` 的按钮单行就判成折行 —— 一次扫描 4 个假阳性,
真缺陷淹在里面。**必须减掉 padding。**

2026-08-26 又加了**跨卡对齐**探针（`align_defects`），起因同样是用户截图指出的缺陷。

用法（需要先起 harness 静态服务，见 §4）:
    CODEXBAR_CARD_EXPIRING=1 python3 codexbar/uishot/make_harness.py
    python3 codexbar/uishot/sweep.py [--base http://127.0.0.1:3304]

★ **harness 必须带 `CODEXBAR_CARD_EXPIRING=1` 生成**：真实数据里两个号的重置卡徽章
  恰好一样长，不制造长短差就证伪不了对齐闸里那条 ③，跑出来的绿是假绿。

退出码:折行/溢出/压扁/错位 → 1；服务没起来 → 2；干净 → 0。
"""
import argparse
import collections
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 同排卡片之间允许的最大错位。1px 是给亚像素取整留的，不是给"差一点点"留的。
ALIGN_TOL = 1

# ★ 展开动作条那个视图**不再用放宽阈值**处理:改成把展开态的卡排出比较集合
#   （见 align_defects 的说明）。兄弟卡之间照旧 1px 严格比。

# 每一项 = (名字, 相对 URL, 窗口宽)。
# ★ 菜单栏是**固定 352px**,不随窗口变 —— 它的窗口宽只是为了绕开 Chrome 最小窗宽 500 的坑,
#   真正钉宽的是 `?w=352`。所以"窗口小就缩字体"这类方案对它天然无效。
VIEWS = [
    # ★ 900 是**窗口的 minWidth**(2026-08-24 加进 tauri.conf.json)。此前没有下限,
    #   窗口能被拖到任意窄,于是"小尺寸下排版乱"根本没有一个可以宣称干净的宽度。
    #   实测(D 档字号,2026-08-26):卡宽 ≥240 干净、≤235 页脚内折行 ⇒ 展开 ≥960、折叠 ≥840。
    #   **不扫 900 以下** —— 那已经不是支持范围,报了只会制造永远修不完的噪音。
    # ★ 两个下限,都是实测:侧栏**展开** ≥960;**折叠** ≥840。字号一改这两个数就要重测。
    #   差 120px = 侧栏宽度差(176-52)。窗口 <860 时侧栏自动折叠,所以 860 以下必须用折叠态扫。
    #   `minWidth=740` 就钉在折叠态的下限上 —— 两个数一起改,闸在 test_narrow_window_nowrap.py。
    # ★ 1120/1080/1040 是**对齐闸的危险区**，不是随手加的采样点：卡片页脚在这一段
    #   「一张折行、另一张不折」，两头（1000 与 1160）都是干净的。只挑整百宽度截图必漏。
    ("总览·侧栏展开",    "/harness.html?nav=home&rail=open&grok=ok",                  [1200, 1120, 1080, 1040, 1000, 960]),
    ("总览·侧栏折叠",    "/harness.html?nav=home&grok=ok",                            [940, 900, 860]),
    # ★★ 这一行被改过两次,两次都是因为**它在假装测东西**:
    #    · 2026-08-26:点的是 hero 卡(名字有两份),hero 没有 onSelect ⇒ 动作条不展开 ⇒ 恒绿空测;
    #    · 2026-09-05:`Pro1` 已变成死号 —— 死号只在折叠的「失效账号」区渲染,同样没有 onSelect
    #      ⇒ `click` 恒匹配 0 个 ⇒ **恒红**,而要验的布局仍然没被验过。
    #    现在点**活号**、序号 1(名字在当前布局里只出现一次,`~2` 那条理由已过时)。
    #    ★ 定这个目标前**正面验过它真的展开**:点击后动作词从 14 处涨到 22 处。
    #      「点中了」≠「展开了」—— 只看 click 不报错,就会退回上面那两种假装。
    ("总览·动作条",      "/harness.html?nav=home&rail=open&grok=ok&click=plus3~1",    [1200, 1000, 960]),
    ("总览·grok降级",    "/harness.html?nav=home&rail=open&grok=stale",               [1000, 960]),
    # ★ agy 卡让总览的格子从 4 张变 5 张 —— 换行位置整个变了,所以这几行不是"再验一遍",
    #   而是验一个**新的**布局。`agy=tight` 让数字进红区(位数与颜色都变),
    #   `agy=noproc` 验"没在跑"仍然显示上次读数且**不染警告色**(它是常态不是故障)。
    ("总览·agy低额度",   "/harness.html?nav=home&rail=open&grok=ok&agy=tight",        [1200, 1080, 1000, 960]),
    ("总览·agy没在跑",   "/harness.html?nav=home&rail=open&grok=ok&agy=noproc",       [1000, 960]),
    ("总览·agy折叠",     "/harness.html?nav=home&grok=ok&agy=tight",                  [940, 900, 860]),
    # ★ 需要 `CODEXBAR_UNPROBED=1` 生成的 harness 才有第 3 个号（见 make_harness 同名夹具）。
    #   没有它时这一行等价于「总览·侧栏展开」,不会假红,只是少测两件事。
    ("总览·未探测号",    "/harness.html?nav=home&rail=open&grok=ok",                  [1200, 1000, 960]),
    # ★ 1037 / 913 是**紧凑区列宽的“谷底”**（发版前评审算出来的）：
    #   `auto-fill` 的格宽随窗宽呈锯齿波，谷底处每格只剩 264px、名字仅余 68px，
    #   `Antigravity`（注册表里最长）余量近零。**整百宽度全落在舒适段，只挑整百必漏**。
    #   另：`make_harness.py` 的探针对 `textOverflow: ellipsis` 直接跳过，
    #   所以“名字被截断”这类缺陷**结构上抢不到**，只能靠宽度采样 + 人看。
    ("用量总览",         "/harness.html?nav=traffic&rail=open",                       [1200, 1037, 1000, 960]),
    ("用量总览·谷底",     "/harness.html?nav=traffic",                                 [940, 913, 880]),
    ("平台详情",         "/harness.html?nav=platform:claude&rail=open",               [1200, 1000, 900]),
    # ★ agy 详情页是唯一有**两本账**的页面（token 图 + 额度消耗条）。它比 claude 那页多一整块，
    #   窄宽下是新的换行风险；而且那块里有「≥」前缀和一段较长的披露文案，都是折行的常见诱因。
    ("平台详情·agy",     "/harness.html?nav=platform:agy&rail=open",                  [1200, 1000, 900]),
    ("平台详情·agy折叠",  "/harness.html?nav=platform:agy",                            [940, 860]),
    ("设置",            "/harness.html?nav=settings&rail=open",                      [1200, 1000, 900]),
    ("菜单栏·账号",      "/harness-menubar.html?w=352&grok=ok",                       [520]),
    ("菜单栏·今日",      "/harness-menubar.html?w=352&tab=today&grok=ok",             [520]),
    ("菜单栏·grok降级",  "/harness-menubar.html?w=352&grok=stale",                    [520]),
    ("菜单栏·agy",       "/harness-menubar.html?w=352&grok=ok&agy=tight",             [520]),
    ("菜单栏·agy没在跑", "/harness-menubar.html?w=352&grok=ok&agy=noproc",            [520]),
]


def align_defects(d, tol=ALIGN_TOL):
    """★★ 同排卡片的**水平线**闸（用户 2026-08-26 报的缺陷，同日加）。

    守的不变量：**同一种额度窗口（5h / 周）在一排卡里必须落在同一条线上**，
    「到期」行与**圆环的圆心**同理。这不是审美 —— 一排卡片横着读就是在比同一个量，
    错开半行会让人把 Plus 的 5h 和 Pro 的周读成同一行。

    为什么必须做成闸而不是再写一条规范：这条线**至少有五个独立的破法**，
    每一个都不报错、只是看起来歪了一点：
      ① 窗口数不同（Plus 5h+周 / Pro 只有周）—— 原始症状；
      ② 徽章行折不折行随**窗宽**变（1000px 折、1280px 不折）；
      ③ 页脚折不折行随**文案长短**变（一个号的重置卡快到期、另一个不快 ⇒ 差 19px，
         只在 1040~1120px 这一段出现，两头都是干净的）；
      ④ 行内占位盒的 strut 随**容器字号**变（差 2px）；
      ⑤ 圆环的垂直对齐方式（顶对齐 vs 居中）—— 修 ①~④ 时我把环改成顶对齐，
         用户当场指出难看；改回居中后它必须仍然跨卡对齐，否则是拿一个缺陷换另一个。
    ①②⑤ 靠肉眼截图发现，③④ 是这条闸量出来的 —— 而 ③ 有边界区间，靠挑宽度截图必然漏。

    ★★ **只比较处于同一状态的卡**：某张卡展开动作条后结构本就不同（多一排按钮），
       把它和兄弟卡比是拿两种东西比。所以展开态的卡**排除在比较之外**，
       但**必须打印出来**（下面的 `已排除` 一行）—— 静默排除会让"覆盖了"变成谎话。
       这不是放宽阈值：兄弟卡之间仍按 1px 严格比。
       ⚠️ 残留仍在：展开的卡与兄弟卡之间条形差 ≤28px、环心差 ~41px，
       真解法是 CSS `subgrid`（三张卡共享同一组行轨道），未混进本批。

    ★ 夹具要用 `CODEXBAR_CARD_EXPIRING=1` 生成：真实数据里两个号的徽章恰好一样长，
      不制造长短差就**证伪不了** ③，跑出来的绿是假绿。
    """
    a = d.get("alignY") or {}
    out, notes = [], []
    dropped = set()

    def split(items):
        """items 形如 ['plus5#r281/周@319', 'Pro1(展开)#r281/周@302'] → [(who, row, key, y)]。

        展开态的卡剔除（结构不同，不可比）；`#r<top>` 是**网格行**——卡片超过 3 张时
        网格会换行，跨行比 y 等于把两排东西放一起比，必然误报。
        """
        keep = []
        for it in items or []:
            wl, y = it.rsplit("@", 1)
            who_row, _, key = wl.partition("/")
            who, _, row = who_row.partition("#r")
            if who.endswith("(展开)"):
                dropped.add(who)
                continue
            keep.append((who, row, key.replace("(空)", ""), int(y)))
        return keep

    groups = collections.defaultdict(list)
    rows = set()
    for who, row, key, y in split(a.get("bars")):
        rows.add(row); groups[(row, "窗口「{}」".format(key))].append((who, y))
    for who, row, _k, y in split(a.get("expiry")):
        rows.add(row); groups[(row, "「到期」行")].append((who, y))
    for who, row, _k, y in split(a.get("rings")):
        rows.add(row); groups[(row, "环的圆心")].append((who, y))

    for (row, name), items in sorted(groups.items()):
        ys = [y for _, y in items]
        if len(ys) > 1 and max(ys) - min(ys) > tol:
            out.append("{}跨卡错开 {}px:{}".format(
                name, max(ys) - min(ys), ", ".join("{}@{}".format(w, y) for w, y in items)))
    if len(rows) > 1:
        notes.append("网格有 {} 排卡片,已**按排**比较(跨排比 y 必然误报)".format(len(rows)))
    if dropped:
        notes.append("已排除展开态的卡:{}(结构不同,与兄弟卡不可比;兄弟卡之间仍按 {}px 严格比)"
                     .format(",".join(sorted(dropped)), tol))
    return out, notes


def server_alive(base):
    """★ 先证明静态服务活着。

    2026-08-26 我把一次**服务已死**（HTTP 000）读成了「24 个视图探针缺失 / 页面没渲染」，
    顺着那句话查了一轮排版。探针缺失有两种成因，而原文案只描述了其中一种 ——
    **「这一枪没打中」和「确实有问题」不能返回同一句话**（本仓库的老规矩）。
    """
    try:
        with urllib.request.urlopen(base + "/harness.html", timeout=5) as r:
            return r.status == 200, "HTTP {}".format(r.status)
    except urllib.error.HTTPError as e:
        return False, "HTTP {}".format(e.code)
    except OSError as e:
        return False, "连不上({})".format(e)


def probe(url, width):
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--window-size={},900".format(width),
         "--virtual-time-budget=3000", "--dump-dom", url],
        capture_output=True, text=True, timeout=120).stdout
    m = re.search(r"<title>__PROBE__(.*?)</title>", out, re.S)
    if not m:
        return {"_fatal": "探针缺失(页面可能没跑到 2.2s 的探针时刻)"}
    d = json.loads(m.group(1))
    # ★ 先看 mounted。**零渲染的页面量出来正好是「零折行、零溢出」** —— 那是假阴性,
    #   比没测更糟(本仓库 2026-08-11 中过两次)。
    if not d.get("mounted"):
        return {"_fatal": "整页零渲染 —— 下面的『干净』是假阴性"}
    if d.get("errors"):
        d["_fatal"] = "页面报错:{}".format(d["errors"][:2])
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3304")
    args = ap.parse_args()

    ok, how = server_alive(args.base)
    if not ok:
        print("  ✗ harness 静态服务没起来({}) —— 先按 CLAUDE.md §4 起服务再跑。".format(how))
        print("    下面一个视图都不会扫;这不是排版问题。")
        return 2

    bad = 0
    for view in VIEWS:
        name, path, widths = view[0], view[1], view[2]
        tol = view[3] if len(view) > 3 else ALIGN_TOL
        for w in widths:
            d = probe(args.base + path, w)
            if d.get("_fatal"):
                print("  ✗ {:<14} {:<5} {}".format(name, w, d["_fatal"]))
                bad += 1
                continue
            wrapped = d.get("wrapped") or []
            over = d.get("overflow") or []
            squeezed = d.get("squeezed") or []
            misalign, align_notes = align_defects(d, tol)
            if not (wrapped or over or squeezed or misalign):
                print("  ✓ {:<14} {:<5} 干净{}".format(
                    name, w, "  ·" + align_notes[0] if align_notes else ""))
                continue
            bad += 1
            print("  ✗ {:<14} {:<5} 折行{} 溢出{} 压扁{} 错位{}".format(
                name, w, len(wrapped), len(over), len(squeezed), len(misalign)))
            for item in misalign:
                print("        错位 · {}".format(item))
            for item in wrapped[:6]:
                print("        折行 · {}".format(item))
            for item in squeezed[:4]:
                print("        压扁 · {}".format(item))
            for item in (over[:4] if isinstance(over, list) else []):
                print("        溢出 · {}".format(item))

    print("\n  {} 个视图×宽度组合有问题".format(bad) if bad else "\n  全部干净")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
