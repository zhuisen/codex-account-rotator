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

用法（需要先起 harness 静态服务，见 §4）:
    python3 codexbar/uishot/sweep.py [--base http://127.0.0.1:3304]

退出码:发现任何折行/溢出 → 1；干净 → 0。
"""
import argparse
import json
import re
import subprocess
import sys

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 每一项 = (名字, 相对 URL, 窗口宽)。
# ★ 菜单栏是**固定 352px**,不随窗口变 —— 它的窗口宽只是为了绕开 Chrome 最小窗宽 500 的坑,
#   真正钉宽的是 `?w=352`。所以"窗口小就缩字体"这类方案对它天然无效。
VIEWS = [
    # ★ 900 是**窗口的 minWidth**(2026-08-24 加进 tauri.conf.json)。此前没有下限,
    #   窗口能被拖到任意窄,于是"小尺寸下排版乱"根本没有一个可以宣称干净的宽度。
    #   实测:900 干净、880 起账号九宫格挤不下(三列各 ~184px,卡片内容要 188)。
    #   **不扫 900 以下** —— 那已经不是支持范围,报了只会制造永远修不完的噪音。
    # ★ 两个下限,都是实测:侧栏**展开** ≥860 干净(840 起单卡溢出);**折叠** ≥740 干净(720 起)。
    #   差 120px = 侧栏宽度差(176-52)。窗口 <860 时侧栏自动折叠,所以 860 以下必须用折叠态扫。
    #   `minWidth=740` 就钉在折叠态的下限上 —— 两个数一起改,闸在 test_narrow_window_nowrap.py。
    ("总览·侧栏展开",    "/harness.html?nav=home&rail=open&grok=ok",                  [1200, 1000, 900, 860]),
    ("总览·侧栏折叠",    "/harness.html?nav=home&grok=ok",                            [850, 800, 740]),
    ("总览·动作条",      "/harness.html?nav=home&rail=open&grok=ok&click=Pro1",       [1200, 1000, 900]),
    ("总览·grok降级",    "/harness.html?nav=home&rail=open&grok=stale",               [1000, 900]),
    ("用量总览",         "/harness.html?nav=traffic&rail=open",                       [1200, 1000, 900]),
    ("平台详情",         "/harness.html?nav=platform:claude&rail=open",               [1200, 1000, 900]),
    ("设置",            "/harness.html?nav=settings&rail=open",                      [1200, 1000, 900]),
    ("菜单栏·账号",      "/harness-menubar.html?w=352&grok=ok",                       [520]),
    ("菜单栏·今日",      "/harness-menubar.html?w=352&tab=today&grok=ok",             [520]),
    ("菜单栏·grok降级",  "/harness-menubar.html?w=352&grok=stale",                    [520]),
]


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

    bad = 0
    for name, path, widths in VIEWS:
        for w in widths:
            d = probe(args.base + path, w)
            if d.get("_fatal"):
                print("  ✗ {:<14} {:<5} {}".format(name, w, d["_fatal"]))
                bad += 1
                continue
            wrapped = d.get("wrapped") or []
            over = d.get("overflow") or []
            squeezed = d.get("squeezed") or []
            if not (wrapped or over or squeezed):
                print("  ✓ {:<14} {:<5} 干净".format(name, w))
                continue
            bad += 1
            print("  ✗ {:<14} {:<5} 折行{} 溢出{} 压扁{}".format(
                name, w, len(wrapped), len(over), len(squeezed)))
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
