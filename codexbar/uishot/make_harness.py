#!/usr/bin/env python3
"""
生成 UI 验证 harness(CLAUDE.md §4 的方法固化版)。

思路:**加载和 app 完全同一份 bundle**,只在它之前注入一个 `window.__TAURI_INTERNALS__` 打桩,
所以量到的是真实构建产物的像素,而不是另写一遍组件的近似。

两条安全线:
- `read_state` 只返回**脱敏空桩**。真实 `state.json` 含 OAuth token,**绝不放进 HTTP 伺服目录**。
- 流量快照是 token 计数、无凭证,内联进 HTML(不是 fetch)——fetch 是异步的,
  app 挂载时就会调 `read_traffic_snapshot`,竞态会让首屏画成空。

用法:python3 make_harness.py  → 生成 app/harness.html
      然后 ?mode=full|noRead|none&nav=traffic|settings|platform:claude
"""
import json
import os
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE / "app"
# 快照可覆盖:`CODEXBAR_SNAPSHOT=<path>` 用来渲染**退化态**(只有 1 个小时桶、空数据…)。
# 真实快照是 app 在写的活文件,**只读不改** —— 要造夹具就另写一份再用这个变量指过去。
REPO = HERE.parent.parent                       # 仓库根:state.json 夹具的来源,**与快照路径解耦**
SNAP = pathlib.Path(os.environ.get("CODEXBAR_SNAPSHOT") or (REPO / ".traffic-latest.json"))

index = (APP / "index.html").read_text()
snapshot = SNAP.read_text()          # 只传递,不打印

STUB = """
<script>
(function () {
  var p = new URLSearchParams(location.search);
  try {
    localStorage.setItem('codexbar_cache_mode', p.get('mode') || 'full');
    // `?intro=off` 关掉入场动效(设置页那个开关)。默认开 —— 与真实默认值一致。
    localStorage.setItem('codexbar_settings', JSON.stringify({
      dockVisible: false, intro: p.get('intro') !== 'off',
      // `?autorefresh=off` 关掉后台心跳(设置页那个开关)。默认开 —— 与真实默认值一致。
      autoRefresh: p.get('autorefresh') !== 'off',
      // `?nav=open` 展开侧栏。默认折叠 —— 与真实默认值一致。
      navOpen: p.get('rail') === 'open',
    }));
    localStorage.setItem('codexbar_privacy', '0');
    // 菜单栏停留页:`?tab=today` 直接渲染今日 Tab(默认账号页)
    localStorage.setItem('codexbar_mb_tab', p.get('tab') === 'today' ? 'today' : 'acc');
    // 平台偏好:`?plat=demo` 套一组示范偏好(停用一家 + 改名改色 + 换顺序),用来验设置面板与总览
    if (p.get('plat') === 'demo') {
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: ['grok', 'claude', 'codex', 'kimi'],
        by: { kimi: { off: true }, grok: { name: 'DeepSeek', color: '#7fd1ff' } },
      }));
    } else {
      localStorage.removeItem('codexbar_platform_prefs');
    }
  } catch (e) { /* 无痕模式:本次渲染仍走默认值 */ }

  var SNAPSHOT = __SNAPSHOT__;
  var STATE = __STATE__;

  // ★ 菜单栏宽 412,而 **Chrome 最小窗宽是 500** —— 直接传 --window-size=412 会按 500 布局、
  //   按 412 裁图,伪装成"横向溢出"(CLAUDE.md §4 记过这个坑)。所以窗口开 500,用 CSS 把
  //   文档钉死在 412,量到的才是真实的紧凑布局。
  if (p.get('w')) {
    var st = document.createElement('style');
    st.textContent = 'html,body{width:' + p.get('w') + 'px;overflow-x:hidden;margin:0}';
    document.head.appendChild(st);
  }
  // hover 态无法在 headless 里靠鼠标触发,用 CSS 强制展开来量**几何与遮挡**。
  // 注意:这只验证按钮的排版,不验证 `:hover` 这条触发本身。
  if (p.get('hover')) {
    var sh = document.createElement('style');
    sh.textContent = '.mb-row-switch-wrap{opacity:1 !important;pointer-events:auto !important}';
    document.head.appendChild(sh);
  }
  var cbid = 0, cbs = {}, listeners = {}, unknown = [], errors = [], clicks = [];

  // ★ 没有这个,渲染失败会表现为"一张空白页 + 零溢出",而零溢出看起来像通过 ——
  //   那是假阴性,比没测更糟(2026-08-11 已经中过一次)。
  window.addEventListener('error', function (e) {
    errors.push(String(e.message) + ' @' + (e.filename || '').split('/').pop() + ':' + e.lineno);
  });
  window.addEventListener('unhandledrejection', function (e) {
    errors.push('reject: ' + String(e.reason && (e.reason.stack || e.reason.message || e.reason)).slice(0, 200));
  });

  function fire(event, payload) {
    (listeners[event] || []).forEach(function (id) {
      var c = cbs[id]; if (c) c.cb({ event: event, id: id, payload: payload });
    });
  }

  // ★ IPC 调用计数。用来回答「这个操作到底有没有触发扫描」——`run_traffic` 是唯一会真起
  //   python 的那条,页面上完全看不出来,只能数。配 `--virtual-time-budget` 拉长虚拟时间,
  //   可以把 30s 的心跳压缩到秒级验证。
  var ipc = {};
  function invoke(cmd, args) {
    ipc[cmd] = (ipc[cmd] || 0) + 1;
    args = args || {};
    switch (cmd) {
      case 'plugin:event|listen':
        (listeners[args.event] = listeners[args.event] || []).push(args.handler);
        return Promise.resolve(1);
      case 'plugin:event|unlisten':
      case 'plugin:event|emit_to':
        return Promise.resolve(null);
      case 'plugin:event|emit':
        fire(args.event, args.payload);
        return Promise.resolve(null);
      case 'read_traffic_snapshot':
      case 'run_traffic':
        return Promise.resolve(SNAPSHOT);
      // ★ **脱敏** fixture。真实 state.json 的邮箱/account_id 能认人,绝不进伺服目录;
      //   结构、额度、套餐、到期日保留真实形状,否则量不出真实排版。
      case 'read_state':
        return Promise.resolve(STATE);
      // `slotToAccount(aid, slot, tokens)` 会直接索引 tokens[aid] —— 返回 null 会抛
      // 「Cannot read properties of null」并让整页零渲染。给每个槽位一个远期 exp 即可。
      case 'read_auth_tokens':
        return Promise.resolve(Object.fromEntries(Object.keys(STATE.slots).map(function (k) {
          return [k, { exp: Math.floor(Date.now() / 1000) + 7 * 86400 }];
        })));
      case 'read_logs':
        return Promise.resolve('');
      case 'set_dock_visible':
      case 'set_main_visible':
      case 'quit_app':
        return Promise.resolve(null);
      case 'plugin:app|version':
        return Promise.resolve(__VERSION__);
      case 'plugin:autostart|is_enabled':
        return Promise.resolve(false);
      default:
        unknown.push(cmd);
        return Promise.resolve(null);
    }
  }

  // Tauri v2 的 `@tauri-apps/api/event` 在 unlisten 时走这个**独立的全局**,不是 __TAURI_INTERNALS__。
  // 缺了它,每次组件卸载都抛一次 unhandledrejection(不致命,但会淹没真正的报错)。
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: function () {} };

  window.__TAURI_INTERNALS__ = {
    invoke: invoke,
    transformCallback: function (cb, once) { var id = ++cbid; cbs[id] = { cb: cb, once: once }; return id; },
    // ★ `metadata` 不能是空对象:`getCurrentWindow()` 直接取 `metadata.currentWindow.label`,
    //   缺了它模块初始化就抛 `Cannot read properties of undefined (reading 'label')`,
    //   整页零渲染 —— 而零渲染的页面量出来是"零溢出",看着像通过。
    metadata: {
      currentWindow: { label: 'main' },
      currentWebview: { label: 'main', windowLabel: 'main' },
    },
  };

  // 页面切换靠 app 自己监听的导航事件(App.tsx 的 navigate-traffic / navigate-settings /
  // navigate-platform),不去猜 DOM 结构点击侧栏。
  window.addEventListener('load', function () {
    setTimeout(function () {
      var nav = p.get('nav') || 'traffic';
      if (nav.indexOf('platform:') === 0) fire('navigate-platform', nav.slice(9));
      else if (nav === 'settings') fire('navigate-settings');
      else if (nav === 'home') { /* 账号池是默认页,不发导航事件 */ }
      else fire('navigate-traffic');
    }, 500);

    // `?click=a,b` —— 按**文本**依次点击(全站 45 处是 div/span+onClick,没有 button 可选)。
    // 用于验证需要交互才出现的形态(选中卡片 → 改名输入框)。取最内层匹配节点,
    // 否则会点到包住它的容器上 —— 那个容器往往挂着**另一个** onClick。
    // 写法 `文本` 或 `文本~2`(第 2 个匹配)。**分隔符不能用 `#`** —— 浏览器会把它之后的
    // 整段当 URL 片段截掉,序号永远传不进来(看起来像"选择器不生效")。★ 同一段文字常出现多次(卡片名在 Hero 里也有一份),
    // 不带序号时默认第 1 个,**并把匹配总数报进探针** —— 否则点错位置和没点中长得一模一样。
    (p.get('click') ? p.get('click').split(',') : []).forEach(function (spec, i) {
      setTimeout(function () {
        var parts = spec.split('~'), want = parts[0].trim(), nth = parseInt(parts[1] || '1', 10);
        // `*前缀` = **包含**匹配。图例这类元素的 textContent 是「名字+数字」连在一起
        // (`缓存读7.51B · 97.24%`),全等匹配永远命不中,而数字是活的没法写死。
        var loose = want.charAt(0) === '*';
        if (loose) want = want.slice(1);
        var all = [];
        document.querySelectorAll('div,span').forEach(function (e) {
          var txt = (e.textContent || '').trim();
          if (loose ? txt.indexOf(want) < 0 : txt !== want) return;
          all = all.filter(function (h) { return !h.contains(e); });   // 只留最内层
          all.push(e);
        });
        clicks.push(spec + ' →命中' + all.length + '个,点第' + nth);
        if (all[nth - 1]) all[nth - 1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
        else errors.push('click miss: ' + spec + ' (共' + all.length + '个)');
      }, 700 + i * 300);
    });

    // `?mm=<0..100>` 在图表命中带上派发 mousemove,把 hover 浮层逼出来。
    // headless 里鼠标事件不会自己发生,而"悬浮才出现的读数"恰恰只能这样验。
    if (p.get('mm')) {
      setTimeout(function () {
        var rects = document.querySelectorAll('svg rect[fill="transparent"]');
        var hit = rects[rects.length - 1];
        if (!hit) { errors.push('mm: 没找到命中带'); return; }
        var r = hit.getBoundingClientRect();
        var x = r.left + r.width * (parseFloat(p.get('mm')) / 100);
        ['mouseenter', 'mousemove'].forEach(function (type) {
          hit.dispatchEvent(new MouseEvent(type, {
            bubbles: true, clientX: x, clientY: r.top + r.height / 2,
          }));
        });
      }, 1400);
    }

    // 探针:横向溢出是本项目 UI 的主要失败模式(外层 overflow:hidden,溢出被静默裁掉)。
    setTimeout(function () {
      var over = [];
      var all = document.querySelectorAll('*');
      for (var i = 0; i < all.length && over.length < 6; i++) {
        var e = all[i];
        if (e.clientWidth > 0 && e.scrollWidth > e.clientWidth + 1) {
          over.push((e.className || e.tagName) + ' ' + e.scrollWidth + '/' + e.clientWidth);
        }
      }
      var r = document.getElementById('root');
      document.title = '__PROBE__' + JSON.stringify({
        // ★ 先看 mounted:它为 0 说明整页没渲染,此时 overflow 的"无"是**假阴性**,不是通过。
        mounted: r ? r.querySelectorAll('*').length : 0,
        rootW: r ? r.scrollWidth + '/' + r.clientWidth : null,
        overflow: over,
        errors: errors.slice(0, 4),
        unknownCmds: unknown.filter(function (v, i, a) { return a.indexOf(v) === i; }),
        clicks: clicks,
        // 只报关心的两个,别把 plugin:event|* 的噪音带进来
        ipc: { run_traffic: ipc['run_traffic'] || 0,
               read_traffic_snapshot: ipc['read_traffic_snapshot'] || 0 },
        // 字体探针:app 的字体是本地 woff2,没加载上会静默回落到系统 sans —— 截图上看不出来
        fonts: {
          mono: document.fonts.check('12px "JetBrains Mono"'),
          disp: document.fonts.check('12px "Space Grotesk"'),
          loaded: Array.from(document.fonts).map(function (f) { return f.family; })
            .filter(function (v, i, a) { return a.indexOf(v) === i; }),
        },
        computed: (function () {
          var pick = function (sel) {
            var e = document.querySelector(sel);
            return e ? getComputedStyle(e).fontFamily.split(',')[0].replace(/["']/g, '') : null;
          };
          return { h1: pick('h1'), body: getComputedStyle(document.body).fontFamily.split(',')[0].replace(/["']/g, '') };
        })(),
        inputs: Array.prototype.map.call(document.querySelectorAll('input'), function (e) {
          var r = e.getBoundingClientRect();
          return { v: e.value, w: Math.round(r.width), h: Math.round(r.height), focus: e === document.activeElement };
        }),
        text: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 700),
      });
    // ★ 探针是**一次性**的:到点写一次 title 就不再更新。默认 2200ms 足够等首屏+入场动效,
    //   但验**定时器驱动**的东西(30s 心跳)时必须调大,否则观测窗口根本没到 —— 我就因此
    //   量出「开关开/关都是 1 次扫描」,差点把"没测到"当成"闸没生效"。
    //   配 `--virtual-time-budget` 一起用,虚拟时间下 150s 只要几秒真实时间。
    }, parseInt(p.get('probe_ms') || '2200', 10));
  });
})();
</script>
"""

def redacted_state():
    """把真实 state.json 脱敏成 fixture。

    ★ **结构、额度、套餐、到期日、重置卡全部保真** —— 用设计稿假数据渲染量不出真实排版
    (上次正是真数据才暴露出徽章变长把日期挤断行)。**只替换能认人的三样**:邮箱、姓名、
    account_id。account_id 同时是槽位的键和 `active` 的值,必须整体重映射,否则「当前号」判错。
    """
    raw = json.loads((REPO / "state.json").read_text())
    idmap, out_slots = {}, {}
    for i, (aid, sl) in enumerate(raw.get("slots", {}).items(), 1):
        fake = f"user-demo{i:02d}0000000000000000000000"
        idmap[aid] = fake
        sl = dict(sl)
        sl["email"] = f"demo{i}@example.com"
        sl.pop("name", None)
        sl["file"] = f"{fake}.json"
        out_slots[fake] = sl
    return {"active": idmap.get(raw.get("active"), ""), "slots": out_slots,
            "last_proxy_ts": raw.get("last_proxy_ts")}


# 版本号从 tauri.conf.json 现取 —— 写死过 0.9.0,发到 0.9.1 后截图上的版本号就在说假话
VERSION = json.loads((HERE.parent / "src-tauri/tauri.conf.json").read_text())["version"]
stub = (STUB.replace("__SNAPSHOT__", json.dumps(snapshot))
            .replace("__VERSION__", json.dumps(VERSION))
            .replace("__STATE__", json.dumps(redacted_state())))
ANCHOR = "<script type=\"module\""
for src, dst in (("index.html", "harness.html"), ("menubar.html", "harness-menubar.html")):
    html = (APP / src).read_text()
    assert html.count(ANCHOR) >= 1, f"{src} 注入锚点未命中"
    (APP / dst).write_text(html.replace(ANCHOR, stub + "\n    " + ANCHOR, 1))
    print(f"  ✓ {dst}")
print(f"  ✓ 内联快照 {len(snapshot)//1024}KB，bundle 与部署产物同一份")
print("  ✓ state fixture 已脱敏（邮箱/姓名/account_id 全替换），真实 state.json 未进入伺服目录")
