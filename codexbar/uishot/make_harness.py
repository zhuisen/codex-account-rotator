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
import time

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
    } else if (p.get('plat') === 'grokoff') {
      // ★ 专门用来验「设置页停用 grok ⇒ 额度卡零像素」。`plat=demo` 停的是 kimi 不是 grok,
      //   拿它验会得到假绿(我第一次就是这么验的)。
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: [], by: { grok: { off: true } },
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
  // grok 额度的六个夹具。**全部脱敏**(邮箱/user_id 都是假的) —— 真 sidecar 含 email + user_id,
  // 与 state.json 同级敏感,绝不进 HTTP 伺服目录。
  // `_NOW` 由 python 侧现算,否则 `↻重置` 与「N 分钟前」会随夹具一起腐烂成"已重置"。
  var _NOW = __NOW__;
  function _acc(o) {
    var base = { account_key: 'https://auth.x.ai::demo', user_id: 'u-demo',
                 email: 'grok@example.com', token_expires_at: _NOW + 3600,
                 available: false, reason: null, detail: null, http_status: null,
                 quota: null, last_good: null };
    for (var k in o) base[k] = o[k];
    return base;
  }
  var _Q = { used_percent: 35.0, period_type: 'USAGE_PERIOD_TYPE_WEEKLY',
             period_start: _NOW - 345600, period_end: _NOW + 259200,
             window_minutes: 10080.0,
             products: [{ product: 'GrokBuild', used_percent: 27.0 },
                        { product: 'GrokAppBuilder', used_percent: 4.0 },
                        { product: 'GrokImagine', used_percent: 4.0 }],
             on_demand_cap: 0.0, on_demand_used: 0.0, prepaid_balance: 0.0 };
  var GROK = {
    ok:      { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ available: true, http_status: 200, quota: _Q })] },
    expired: { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ reason: 'token_expired', token_expires_at: _NOW - 600,
                                 detail: '本地 expires_at 已过,未发请求' })] },
    '401':   { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ reason: 'unauthorized', http_status: 401, detail: 'HTTP 401' })] },
    missing: { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ account_key: null, email: null, token_expires_at: null,
                                 reason: 'auth_file_missing' })] },
    // 降级 + 保留陈旧读数:细条要变琥珀并写明是几时的,横幅在上。两者必须同时出现。
    stale:   { schema: 1, fetched_at: _NOW - 60, auth_path: '~/.grok/auth.json',
               accounts: [_acc({ reason: 'network_error', detail: 'TimeoutError: 超过 20s 整体上限',
                                 last_good: { used_percent: 35.0, fetched_at: _NOW - 10800,
                                              period_end: _NOW + 259200 } })] },
  };
  var ipc = {}, sizes = [], emitted = [];
  function invoke(cmd, args) {
    ipc[cmd] = (ipc[cmd] || 0) + 1;
    // 记下每次 setSize 的目标高度 —— 菜单栏的高度就是这么定的,只数次数看不出设成了多少
    if (cmd.indexOf('set_size') >= 0 || cmd.indexOf('setSize') >= 0) {
      try { sizes.push(JSON.stringify(args)); } catch (e) { sizes.push('?'); }
    }
    args = args || {};
    switch (cmd) {
      case 'plugin:event|listen':
        (listeners[args.event] = listeners[args.event] || []).push(args.handler);
        return Promise.resolve(1);
      case 'plugin:event|unlisten':
      case 'plugin:event|emit_to':
        return Promise.resolve(null);
      case 'plugin:event|emit':
        // ★ 记下**发了哪个事件**。验"点菜单栏的账号跳去哪一页"只能靠它 ——
        //   `ipc` 只数 run_traffic/read_traffic_snapshot,截图也看不出跳转意图
        //   (菜单栏与主窗是两个 webview,harness 里只渲染其中一个)。
        emitted.push(args.event + (args.payload != null ? '=' + args.payload : ''));
        fire(args.event, args.payload);
        return Promise.resolve(null);
      // ★ `?snap_delay=<ms>` 让快照**异步**送达。默认 0(同步)保持既有行为。
      //   真机上快照是 `invoke` 异步取的,内容会在挂载**之后**才长出来 —— harness 原本内联同步给,
      //   按设计绕开了这个竞态,也就**看不见**任何"挂载时量了一次、之后再没量"的缺陷。
      //   菜单栏高度钉死在 PANEL_H_MIN 那个 bug 就是这么漏掉的。
      case 'read_traffic_snapshot':
      case 'run_traffic': {
        var dly = parseInt(p.get('snap_delay') || '0', 10);
        if (!dly) return Promise.resolve(SNAPSHOT);
        return new Promise(function (res) { setTimeout(function () { res(SNAPSHOT); }, dly); });
      }
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
      // ★ grok 周额度。**不打桩就是假绿**:落到 default 会返回 null,页面永远画「未探测」,
      //   而你想验的六个降级态一张都截不到 —— 页面照常渲染、零报错,看着像通过。
      //   同族的前车之鉴:`metadata` 空对象 / `read_auth_tokens` 返 null 那两次假阴性。
      //   `?grok=ok|expired|401|missing|never|stale`,email 一律脱敏。
      case 'read_grok_quota':
      case 'run_grok_quota': {
        var g = p.get('grok') || 'ok';
        if (g === 'never') return Promise.resolve(null);
        return Promise.resolve(JSON.stringify(GROK[g] || GROK.ok));
      }
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

      // ★ `?mbshow=<ms>` 在指定时刻发 `menubar-shown` —— Rust 是在 `win.show()` 之后发它的
      //   (lib.rs 的 `toggle_menubar`)。菜单栏的高度靠这个事件在**窗口真正可见时**重量一次,
      //   所以要验那条路径,必须能在 harness 里模拟"用户点了托盘"。
      var mbs = parseInt(p.get('mbshow') || '0', 10);
      if (mbs) setTimeout(function () { fire('menubar-shown'); }, mbs);
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
          // ★ 带上文本片段。只报 `SPAN 210/174` 没法诊断 —— 得知道是**哪段内容**装不下。
          //   同时排掉**本来就可滚动**的容器:每个页面自带滚动容器是项目规则,报它们纯属噪音。
          var ocs = getComputedStyle(e);
          if (ocs.overflowX === 'auto' || ocs.overflowX === 'scroll'
              || ocs.overflow === 'auto' || ocs.overflow === 'scroll') continue;
          // ★ **带省略号的元素本来就 scrollWidth > clientWidth** —— 那正是省略号在工作,
          //   不是缺陷。不排掉的话,每个刻意做了截断的标签(数据源路径、长模型名)都会被报一次,
          //   真缺陷淹在噪音里。这与「散文允许换行」是同一条原则:**刻意的取舍不是缺陷**。
          if (ocs.textOverflow === 'ellipsis') continue;
          over.push((e.className || e.tagName) + ' ' + e.scrollWidth + '/' + e.clientWidth
                    + ' 「' + (e.textContent || '').trim().slice(0, 22) + '」');
        }
      }
      var r = document.getElementById('root');
      document.title = '__PROBE__' + JSON.stringify({
        // ★ 先看 mounted:它为 0 说明整页没渲染,此时 overflow 的"无"是**假阴性**,不是通过。
        mounted: r ? r.querySelectorAll('*').length : 0,
        rootW: r ? r.scrollWidth + '/' + r.clientWidth : null,
        // 菜单栏弹窗的高度由 JS 量 `.mb-root` 的 scrollHeight 再 setSize 出来。
        // 量它随时间怎么变,才能区分「内容超过 PANEL_H_MAX 被钳」和「量早了、之后没再量」。
        mbH: (function () {
          var e = document.querySelector('.mb-root');
          return e ? { scroll: e.scrollHeight, client: e.clientHeight,
                       bodyScroll: document.body.scrollHeight } : null;
        })(),
        // ★ 溢出探针会把**本来就可滚动**的容器算进去(每个页面都有自己的滚动容器,那是项目规则)。
        //   过滤掉 overflow:auto/scroll 的元素,否则每次扫描都带一堆无意义的 DIV。
        overflow: (over || []).filter(function (x) { return true; }),
        // ★★ **被 flex 压扁的元素** —— 既有的 `overflow` 探针对它完全是瞎的:
        //   flex 布局在空间不够时**压缩子项**而不是溢出,所以 `scrollWidth > clientWidth` 永远不成立,
        //   元素还在 DOM 里、文本也还在,只是渲染宽被压到接近 0 ⇒ 肉眼看是"这个字段没了"。
        //   2026-08-23 缩菜单栏宽度时踩到:332px 下当前号那行的「到期 2026-09-08」整个消失,
        //   而 overflow=无、DOM 里日期一个不少,两种自动检查全绿。判据只能是**渲染宽 vs 自然宽**。
        squeezed: (function () {
          var r0 = document.getElementById('root');
          var out = [], all = r0 ? r0.querySelectorAll('*') : [];
          for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (e.children.length) continue;                 // 只看叶子节点
            var tag = e.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TITLE') continue;
            if (tag === 'svg' || tag === 'path' || tag === 'circle' || tag === 'rect') continue;
            var t = (e.textContent || '').trim();
            if (!t) continue;
            var shown = e.getBoundingClientRect().width;
            if (shown > 4) continue;                          // 还看得见就不算
            out.push(t.slice(0, 24) + ' →' + Math.round(shown) + 'px');
          }
          return out.slice(0, 8);
        })(),
        // ★★ **折行探针** —— 前面三个探针对"文字在控件内部折行"全是瞎的:
        //   `overflow` 要 scrollWidth>clientWidth(flex 压缩时不成立);
        //   `squeezed` 只认渲染宽 ≤4px,而「切换到此号」被压到 ~20px 竖排,正好漏过;
        //   `--dump-dom` 拿的是源文本,根本看不到浏览器在哪断的行。
        //   判据只能是**渲染高 vs 单行高**:叶子文本节点高过 1.6 行 = 它折行了。
        //   2026-08-24 用户连报三处(头部按钮 / 菜单栏刷新时间 / 卡片动作条),
        //   全部靠肉眼截图发现 —— 这个探针就是为了让下一次不必再靠肉眼。
        wrapped: (function () {
          var r0 = document.getElementById('root');
          var out = [], all = r0 ? r0.querySelectorAll('*') : [];
          for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (e.children.length) continue;
            var tag = e.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TITLE') continue;
            if (tag === 'svg' || tag === 'path' || tag === 'circle' || tag === 'rect') continue;
            var t = (e.textContent || '').trim();
            if (!t) continue;
            var cs = getComputedStyle(e);
            var lh = parseFloat(cs.lineHeight);
            if (!lh || isNaN(lh)) lh = parseFloat(cs.fontSize) * 1.2;
            // ★ 必须减掉 padding,比的是 **content box**。第一版拿 border box 比,
            //   `padding: 7px 11px` 的按钮单行高就有 27px,对 13px 行高判成"折行" ——
            //   一次扫描报出 4 个假阳性,而真正折行的那条淹没在里面。
            var h = e.clientHeight
                    - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.paddingBottom) || 0);
            if (h <= lh * 1.6) continue;               // 单行,正常
            // ★★ **折行不等于缺陷。** 规则是「控件与原子值不许折行,散文可以」——
            //   设置页的说明段落、降级横幅的那句话本来就该换行。第一版不分青红皂白全报,
            //   一次扫描 10 处里 6 处是误报,而项目铁律说「一盏长亮的灯指错方向比没有更糟」。
            //   判据三选一(命中即视为控件/原子值):
            //     · 可点(cursor:pointer)—— 按钮、分段控件、可点的时间戳
            //     · 等宽字体 —— 设计规范规定"一切数字/时间/代码/标签/模型名"都用 JetBrains Mono
            //     · 短文本(≤12 字)—— 标题、徽章、单位这类不该断的碎片
            // ★ **散文一律放行,先于任何其它判据** —— grok 降级横幅那段话在可点的卡片里,
            //   会从祖先**继承** `cursor:pointer`,第一版据此把它判成控件。继承来的 pointer
            //   说明不了这个元素是控件。控件文本天然短,所以长度门是更可靠的判据。
            if (t.length > 20) continue;
            var interactive = cs.cursor === 'pointer';
            var mono = (cs.fontFamily || '').indexOf('JetBrains Mono') >= 0;
            var atomic = t.length <= 12;
            if (!interactive && !mono && !atomic) continue;   // 散文:允许换行
            out.push(t.slice(0, 20) + ' 内容高' + Math.round(h) + '/行' + Math.round(lh)
                     + (interactive ? ' [可点]' : mono ? ' [等宽]' : ' [短]'));
          }
          return out.slice(0, 12);
        })(),
        errors: errors.slice(0, 4),
        unknownCmds: unknown.filter(function (v, i, a) { return a.indexOf(v) === i; }),
        clicks: clicks,
        // 只报关心的两个,别把 plugin:event|* 的噪音带进来
        sizes: sizes,
        ipc: { run_traffic: ipc['run_traffic'] || 0,
               read_traffic_snapshot: ipc['read_traffic_snapshot'] || 0 },
        emitted: emitted.slice(0, 12),
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
            # ★ 现算,不写死:grok 夹具里的重置时间和"N 分钟前"都是相对 now 的,
            #   钉死一个时间戳会让夹具随日子腐烂成「已重置 / 3 天前」,那时截出来的图是错的。
            .replace("__NOW__", str(int(time.time())))
            .replace("__STATE__", json.dumps(redacted_state())))
ANCHOR = "<script type=\"module\""
for src, dst in (("index.html", "harness.html"), ("menubar.html", "harness-menubar.html")):
    html = (APP / src).read_text()
    assert html.count(ANCHOR) >= 1, f"{src} 注入锚点未命中"
    (APP / dst).write_text(html.replace(ANCHOR, stub + "\n    " + ANCHOR, 1))
    print(f"  ✓ {dst}")
print(f"  ✓ 内联快照 {len(snapshot)//1024}KB，bundle 与部署产物同一份")
print("  ✓ state fixture 已脱敏（邮箱/姓名/account_id 全替换），真实 state.json 未进入伺服目录")
