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

# ★★ **陈旧产物闸。** 2026-09-05 实测踩到:`uishot/app/` 的 bundle 停在 5 天前,
#    而我以为 `npm run build` 会喂给它 —— 那个命令只写 `dist/`,harness 读的是 `app/`。
#    后果不是报错,是**假绿**:sweep 把 8 个新视图全判成"干净",而那些页面里
#    新组件一个都没渲染。页面照常渲染、零报错,看着完全像通过。
#    正确姿势:`vite build --outDir uishot/app` 然后跑本脚本(顺序不能反,build 会清空 outDir)。
def _assert_fresh_bundle():
    src = HERE.parent / "src"
    if not src.is_dir() or not APP.is_dir():
        return
    newest_src = max((f.stat().st_mtime for f in src.rglob("*")
                      if f.is_file() and f.suffix in (".ts", ".tsx", ".css")), default=0)
    newest_app = max((f.stat().st_mtime for f in (APP / "assets").glob("*.js")), default=0)
    if newest_app and newest_src > newest_app + 1:
        import datetime
        fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M")
        raise SystemExit(
            "✗ uishot/app 的 bundle 比源码旧（bundle {} < 源码 {}）。\n"
            "  直接生成 harness 会得到**假绿**：sweep 测的是旧代码，新组件根本没渲染。\n"
            "  先跑：cd codexbar && ./node_modules/.bin/vite build --outDir uishot/app"
            .format(fmt(newest_app), fmt(newest_src)))


_assert_fresh_bundle()
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
      // ★ `?autoswitch=on` 打开「额度低自动切号」—— **阈值那一行只在它开着时才渲染**,
      //   不给这个开关的话新加的可输入数字框在 harness 里一个像素都验不到,
      //   而截图会正常渲染、探针会报干净(本仓反复踩的那种假绿)。
      autoSwitchEnabled: p.get('autoswitch') === 'on',
    }));
    // ★ `?privacy=1` 打开打码模式(`usePrivacy` + `maskId`)。默认 0 —— 与真实默认值一致。
    //   给对外截图用:夹具已把邮箱/姓名/account_id 换成假的,打码是**第二层**,
    //   两层都要 —— 夹具保证"截到的不是真人",打码保证"版式就是用户分享时看到的那个"。
    localStorage.setItem('codexbar_privacy', p.get('privacy') === '1' ? '1' : '0');
    // 菜单栏停留页:`?tab=today` 直接渲染今日 Tab(默认账号页)
    localStorage.setItem('codexbar_mb_tab', p.get('tab') === 'today' ? 'today' : 'acc');
    // ★★ `?h=<n>` 预置**记住的弹窗高度**。账号 Tab 用的就是这个数(今日页没渲染,量不到),
    //    所以「两个 Tab 等高」这条闸**必须能预置它** —— 否则每次加载 localStorage 都是空的,
    //    账号页永远落到兜底值,验出来的"相等"只是两个兜底值相等,与真实行为无关。
    if (p.get('h')) localStorage.setItem('codexbar_mb_h', p.get('h'));
    else localStorage.removeItem('codexbar_mb_h');
    // 平台偏好:`?plat=demo` 套一组示范偏好(停用一家 + 改名改色 + 换顺序),用来验设置面板与总览
    if (p.get('plat') === 'demo') {
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: ['grok', 'claude', 'codex', 'kimi'],
        by: { kimi: { off: true }, grok: { name: 'DeepSeek', color: '#7fd1ff' } },
      }));
    } else if (p.get('plat') === 'agyoff') {
      // 验「设置页停用 agy ⇒ 额度卡零像素」。与 grokoff 分开:两个开关各管各的,
      // 合成一个就验不出"关了 grok 顺手把 agy 也关了"这类串台。
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: [], by: { agy: { off: true } },
      }));
    } else if (p.get('plat') === 'few') {
      // ★★ **今日 Tab 只剩 4 家平台** —— 复现用户 2026-09-06 报的「菜单栏下方大片空白」。
      //    今日页的高度 ≈ 固定头部 + 图例行数 × 35px,而图例只列**今天有流量**的平台。
      //    本机快照有 7 家,所以默认夹具下今日页恰好填满 580 —— 那个"恰好"正是
      //    `PANEL_H_MAX = 580` 这个常量的来源,它把一个**随数据变化的量**写死成了常量。
      //    停掉 kimi/mimo/deepseek 得到 claude+codex+grok+agy = 4 家,与用户截图一致。
      localStorage.setItem('codexbar_platform_prefs', JSON.stringify({
        order: [], by: { kimi: { off: true }, mimo: { off: true }, deepseek: { off: true } },
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
  // agy 额度夹具。★ 与 grok 不同,agy 的响应里**没有任何身份信息**(接口无鉴权),
  // 所以这里无需脱敏 —— 但形状必须真实:2 组 × 2 窗口,`remaining_percent` 是**剩余**。
  // ★★ `rem === 100` 的桶**一定**是浮动锚点:一次都没用过 ⇒ 服务端每轮回「此刻 + 整窗」,
  //    倒计时永远停在 4h5xm。这里按剩余量**推导**判定,不另加开关。
  //    用过的桶不带 anchor ⇒ 前端回落到既有行为,与改动前逐像素相同。
  //
  // ⚠️ **`?agy=ok` 走不到「未启动」分支,别以为它覆盖了。** 我一开始就是这么以为的,
  //    `--dump-dom` 当场证伪:卡上与菜单栏行都只取**每个窗口最紧**的那个桶
  //    (`agyWinRows` / `agyTightest`),而 100% 的桶按定义永远不是最紧的 ⇒ 带 anchor 的桶
  //    一个都渲染不到。要验那条分支必须用 `?agy=idle`(四个桶全 100%,即"装了但一直没用")。
  //    ★ 这正是本仓那条「报干净之前先正面证明它渲染了」的又一个实例 ——
  //      推理说覆盖到了,DOM 说没有。
  function _bkt(id, win, rem, dt) {
    var b = { bucket_id: id, window: win, remaining_percent: rem, reset_at: _NOW + dt };
    if (rem >= 100) {
      b.anchor = { state: 'floating', held_secs: 0, samples: 1, slides: 3,
                   used_max: 0.0, reset: b.reset_at };
    }
    return b;
  }
  function _groups(gw, g5, tw, t5) {
    return { groups: [
      { name: 'Gemini Models', buckets: [_bkt('gemini-weekly', 'weekly', gw, 604800),
                                         _bkt('gemini-5h', '5h', g5, 18000)] },
      { name: 'Claude and GPT models', buckets: [_bkt('3p-weekly', 'weekly', tw, 604800),
                                                 _bkt('3p-5h', '5h', t5, 18000)] } ] };
  }
  function _agy(o) {
    var base = { schema: 1, fetched_at: _NOW - 30, available: false, reason: null,
                 detail: null, pid: 45366, quota: null, last_good: null };
    for (var k in o) base[k] = o[k];
    return base;
  }
  var AGY = {
    // 实测形状(2026-09-04,本机 agy 1.1.26)。
    ok:      _agy({ available: true, quota: _groups(99.56, 97.34, 100, 100) }),
    // 低水位:验数字的阈值色与 glow。最紧的是 3p-5h = 7% ⇒ 环上应显示 7、数字红。
    tight:   _agy({ available: true, quota: _groups(62.0, 41.0, 88.0, 7.0) }),
    // ★★ **装了 agy 但一直没用** —— 四个桶全满,于是最紧的那个也是浮动锚点,
    //    卡与菜单栏行都应渲染「↻未启动」而不是一个永远停在 4h5xm 的假倒计时。
    //    这是**唯一能证明那条分支真的渲染出来**的 agy 夹具(`ok` 证不了:100% 的桶
    //    永远不是最紧的,带 anchor 的桶一个都进不了渲染 —— `--dump-dom` 实测)。
    idle:    _agy({ available: true, quota: _groups(100, 100, 100, 100) }),
    // ★★ agy 没在跑 —— **常态,不是故障**。必须仍然显示(带上次读数 + 一个 `!`),
    //    且不得染成警告色。这条夹具就是为了截出"藏了"或"染红了"这两种回归。
    noproc:  _agy({ reason: 'no_process', detail: 'agy 没在运行',
                    last_good: { quota: _groups(99.56, 97.34, 100, 100),
                                 fetched_at: _NOW - 10800 } }),
    // 预热窗口(起后 ~10s 内),会自愈 ⇒ 琥珀。
    warm:    _agy({ reason: 'not_ready', detail: 'agy 刚起,额度服务还在预热' }),
    // ★ 本机没装 agy ⇒ **零像素**。截出来若还有卡就是回归。
    notinst: _agy({ reason: 'not_installed', detail: '本机没有 agy' }),
  };
  // ── 代理轮换泳道夹具(2026-09-07 交接稿)───────────────────────────
  // ★ 形状**逐字取自 `traffic/rotation.py` 的真实输出**,不是照着稿子想象编的 ——
  //   字段名编错的话页面照样渲染(全是 undefined),而 undefined 渲染出来是空白,
  //   看着就像"这段时间没数据"。
  function _seg(acc, sMin, eMin, reqs, tok, models, why, cur) {
    var st = _NOW - 24 * 3600 + sMin * 60;
    return { acc: acc, start: st, end: _NOW - 24 * 3600 + eMin * 60, requests: reqs,
             tokens: tok, by_model: models, enter_reason: why, current: !!cur };
  }
  function _M(a, b, c) {
    var m = [{ model: 'gpt-6-astra', tokens: a }];
    if (b) m.push({ model: 'gpt-5.6-luna', tokens: b });
    if (c) m.push({ model: 'gpt-5-codex', tokens: c });
    return m;
  }
  var ROT_SEGS = [
    _seg('plus5', 0, 200, 38, 61e6, _M(43e6, 13e6, 5e6), 'window_start'),
    _seg('plus4', 200, 330, 22, 31e6, _M(19e6, 9e6, 3e6), 'stream_err'),
    _seg('plus5', 330, 520, 41, 78e6, _M(58e6, 14e6, 6e6), 'quota_rotate'),
    _seg('Pro1', 520, 660, 30, 69e6, _M(56e6, 8e6, 5e6), 'pro_fallback'),
    _seg('plus6', 660, 780, 24, 36e6, _M(24e6, 9e6, 3e6), 'quota_rotate'),
    _seg('plus5', 780, 930, 41, 70e6, _M(48e6, 15e6, 7e6), 'quota_rotate'),
    _seg('plus7', 930, 1040, 31, 62e6, _M(45e6, 12e6, 5e6), 'stream_err'),
    _seg('plus4', 1040, 1160, 28, 42e6, _M(27e6, 12e6, 3e6), 'quota_rotate'),
    _seg('Pro1', 1160, 1280, 37, 89e6, _M(74e6, 9e6, 6e6), 'pro_fallback'),
    _seg('plus6', 1280, 1360, 26, 42e6, _M(28e6, 10e6, 4e6), 'quota_rotate'),
    _seg('plus7', 1360, 1388, 21, 44e6, _M(32e6, 8e6, 4e6), 'stream_err'),
    // ★ 极短段(4 分钟)+ **零 token**:验 `min-width:3px` 与"该时段无归属到的 token"分支。
    //   零 token 不是编的 —— 真机上 429 掉的请求就是有请求、无响应、无 token 记录。
    _seg('plus3', 1388, 1392, 2, 0, [], 'cool_429'),
    _seg('plus4', 1392, 1440, 30, 57e6, _M(40e6, 13e6, 4e6), 'cool_429', true),
  ];
  function _mk(acc, mins, kind) { return mins.map(function (m) {
    return { acc: acc, t: _NOW - 24 * 3600 + m * 60, kind: kind }; }); }
  var ROT_MARKERS = [].concat(
    _mk('plus5', [40, 95, 150, 360, 410, 470, 800, 840, 880, 910], 'stream_err'),
    _mk('plus4', [230, 270, 300, 1080, 1120, 1400, 1430], 'stream_err'),
    _mk('Pro1', [560, 620, 1200], 'stream_err'),
    _mk('plus7', [980, 1375], 'stream_err'),
    _mk('plus7', [1388], 'cool_429'), _mk('plus3', [1390, 1392], 'cool_429'));
  function _rotAccounts() {
    var by = {};
    ROT_SEGS.forEach(function (s) {
      var a = by[s.acc] || (by[s.acc] = { acc: s.acc, tokens: 0, requests: 0, models: {} });
      a.tokens += s.tokens; a.requests += s.requests;
      s.by_model.forEach(function (m) { a.models[m.model] = (a.models[m.model] || 0) + m.tokens; });
    });
    // 配色与线性探测口径同 rotation.py::assign_colors(此处直接给结果,夹具不复算)
    var C = { plus5: '#4d9fff', plus4: '#2dd4bf', Pro1: '#8b7cf6', plus7: '#27B26B',
              plus6: '#E0A21C', plus3: '#E0784F' };
    var Q = { plus5: 100, plus4: 100, Pro1: 100, plus7: 98, plus6: 100, plus3: 0 };
    return Object.keys(by).map(function (k) {
      var a = by[k], top = null;
      Object.keys(a.models).forEach(function (m) {
        if (!top || a.models[m] > top[1]) top = [m, a.models[m]]; });
      return { acc: k, plan: k.toLowerCase().indexOf('pro') === 0 ? 'pro' : 'plus',
               color: C[k], tokens: a.tokens, requests: a.requests,
               top_model: top ? { model: top[0], share: top[1] / a.tokens } : null,
               quota_pct: Q[k] === undefined ? null : Q[k] };
    }).sort(function (x, y) { return y.tokens - x.tokens; });
  }
  function _rotEvents() {
    var out = [], R = { cool_429: '429 冷却 → 故障转移', stream_err: '断流 → 轮换',
                        quota_rotate: '额度轮换', window_start: '窗口起点',
                        pro_fallback: 'Plus 全部不可用 → Pro 保底接管' };
    for (var i = 1; i < ROT_SEGS.length; i++) {
      var s = ROT_SEGS[i], p = ROT_SEGS[i - 1], is429 = s.enter_reason === 'cool_429';
      var ty = s.enter_reason === 'pro_fallback' ? 'pro_fallback' : (is429 ? 'failover' : 'switch');
      out.push({ t: s.start, type: ty, from: p.acc, to: s.acc,
                 reason: s.enter_reason, accs: [p.acc, s.acc],
                 text: p.acc + ' → ' + s.acc + ' · ' + R[s.enter_reason] + ' · 上号 ' +
                       Math.round((p.end - p.start) / 60) + 'm / ' +
                       (p.tokens / 1e6).toFixed(1) + 'M / ' + p.requests + ' 次' });
    }
    ROT_MARKERS.forEach(function (m) {
      out.push({ t: m.t, type: m.kind, from: m.acc, to: null, reason: m.kind, accs: [m.acc],
                 text: m.kind === 'cool_429' ? '429 → cooled [' + m.acc + '], failing over'
                                             : 'stream err [' + m.acc + ']' });
    });
    return out.sort(function (a, b) { return b.t - a.t; });
  }
  var ROT_LOG = [
    { t: _NOW - 60, text: '[quotad] activity → plus4:HTTP 200 · 1.9M tok' },
    { t: _NOW - 2600, text: "headers x-codex 头集合变化 -['x-codex-turn-state']" },
    { t: _NOW - 3100, text: 'cooled 429 → cooled [plus7], failing over' },
    { t: _NOW - 3300, text: '[quotad] window reset crossed → sweep now' },
    { t: _NOW - 3600, text: 'stream err [plus5]: IncompleteRead(2280 bytes read)' },
    { t: _NOW - 4000, text: 'switch plus6 → plus7 (stream-err x1)' },
    { t: _NOW - 4600, text: '[quotad] refresh plus5 ok' },
  ];
  function _rot(o) {
    var base = {
      ok: true, generated_at: _NOW,
      window: { start: _NOW - 24 * 3600, end: _NOW, hours: 24 },
      accounts: _rotAccounts(), segments: ROT_SEGS, markers: ROT_MARKERS,
      events: _rotEvents(), log: ROT_LOG,
      kpi: { tokens: 682e6, requests: 371, avg_tokens: 1.84e6, rotations: 12,
             avg_dwell: 6660, cool_429: 3, stream_err: 22,
             // ★ 保底接管:两段共 260 分钟。夹具必须**真的有**,否则那格 KPI 与 PRO 徽章
             //   一个像素都验不到,而截图会正常渲染、探针报干净。
             pro_segs: 2, pro_secs: 260 * 60 },
      coverage: { responses_seen: 371, responses_with_tokens: 346, responses_unplaced: 0,
                  attributed_pct: 0.933, undated_lines: 0, in_window_lines: 4200,
                  tail_truncated: false },
    };
    for (var k in o) base[k] = o[k];
    return base;
  }
  var ROT = {
    ok: _rot({}),
    // ★★ `?rot=procur` —— **Pro 号正在当班**:同一条泳道上同时挂 `PRO` 和 `当前` 两个徽章。
    //    这是名字列的**最坏情况**,也正是用户 2026-09-07 截图里被截成 `Pr…` 的那一种。
    //    默认夹具的「当前」在 plus4 上 ⇒ 这个组合**一次都没被渲染过**,
    //    所以那次截断在 harness 里完全看不见(缺陷探针对"没渲染"是沉默的)。
    procur: (function () {
      var segs = ROT_SEGS.map(function (x) {
        var y = {}; for (var k in x) y[k] = x[k];
        y.current = (x.acc === 'Pro1' && x.start === ROT_SEGS[8].start);
        return y;
      });
      return _rot({ segments: segs });
    })(),
    // ★ 旧格式无时间戳 + 尾读截断 —— 专门截那行覆盖率脚注。没有它,诚实度提示一次都验不到。
    undated: _rot({ coverage: { responses_seen: 371, responses_with_tokens: 214,
                                responses_unplaced: 3, attributed_pct: 0.577,
                                undated_lines: 21078, in_window_lines: 1372,
                                tail_truncated: true } }),
    // ★「这段时间代理没干活」——**不是**「读不到」。两者必须显示成不同的话。
    empty: _rot({ accounts: [], segments: [], markers: [], events: [], log: [],
                  kpi: { tokens: 0, requests: 0, avg_tokens: 0, rotations: 0,
                         avg_dwell: 0, cool_429: 0, stream_err: 0, pro_segs: 0, pro_secs: 0 },
                  coverage: { responses_seen: 0, responses_with_tokens: 0, responses_unplaced: 0,
                              attributed_pct: null, undated_lines: 0, in_window_lines: 0,
                              tail_truncated: false } }),
  };

  var ipc = {}, sizes = [], emitted = [];
  // ★★ **路由分账夹具必须自己注入,不能指望活快照。**
  //   `.traffic-latest.json` 会被**正在运行的 app** 用它自己打包的（旧）`scan.py` 覆盖 ——
  //   实测过一次:harness 刚生成好，app 一扫就把 `by_provider` 抹没了，
  //   于是 DOM 闸变红，而根因和"代码写错了"完全无关。
  //   数值取自真实 `scan.py --days 90` 的输出（含 `openai-nows` 这个**未登记** provider,
  //   它是 09-07 WS 实验的临时产物,专门用来验证三分类不会把它误判成中转站）。
  //   ⚠️ `SNAPSHOT` 是**字符串**不是对象（`read_traffic_snapshot` 的 Rust 签名是
  //     `Option<String>`）。我第一版直接读 `SNAPSHOT.platforms` —— `undefined`,
  //     被 try/catch 吞掉,注入静默没生效,而 DOM 闸红得像是组件写错了。
  (function () {
    try {
      var _o = JSON.parse(SNAPSHOT);
      var c = _o && _o.platforms && _o.platforms.codex;
      if (c && !c.by_provider) {
        // ★★ 形状是 **provider → 日期 → 桶**（2026-09-10 起）。前端按当前档位求和，
        //    所以路由分账与同页的 KPI/图必然同窗口。
        // ★ 各 provider 落在**不同的日子**上 —— 全放同一天的话，「跟随档位」那条闸
        //   换任何档位都得到同一批 provider，又是个空守卫。
        var _days = Object.keys(c.days || {}).sort();
        var _last = _days[_days.length - 1], _first = _days[0];
        var _bk = function (n) {
          return { total: n, uncached_in: 0, cache_read: 0, cache_write: 0,
                   output: 0, rounds: 0, models: {} };
        };
        c.by_provider = {};
        if (_last) {
          // 今天/最近：账号池 + 中转站 + 那个未登记的临时 provider
          c.by_provider.rotateproxy = {}; c.by_provider.rotateproxy[_last] = _bk(3529396103);
          c.by_provider.tokendun = {};    c.by_provider.tokendun[_last] = _bk(39513);
          c.by_provider['openai-nows'] = {}; c.by_provider['openai-nows'][_last] = _bk(38627);
          // 最早那天只有单号直连 —— 短档位里它必须消失
          c.by_provider.openai = {};      c.by_provider.openai[_first || _last] = _bk(4651131297);
        }
        c.provider_labels = { tokendun: 'TokenDun' };
        SNAPSHOT = JSON.stringify(_o);
      }
    } catch (e) { /* 快照形状变了就让 DOM 闸去发现 */ }
  })();

  var relayCalls = [];
  var agyPushed = false;

// ── 中转站（relay）夹具 ──────────────────────────────────────────────────────
// ★ 形状**照抄 `relay-ctl status` / `usage` 的真实输出**（2026-09-09 实测键集），
//   不是我凭印象编的。夹具与真实响应对不上时,页面在 harness 里绿、真机上空 ——
//   本仓已经栽过三次「不打桩 ⇒ 落 default 返 null ⇒ 页面画空 ⇒ 假绿」。
// ★ `cost` 与 `actual_cost` 用**真实的两个数**（0.36 / 0.0863,差 4.2 倍）——
//   夹具里让它们相等的话,"两列合并成一列"的实现也能绿。
var RELAY_USAGE_OK = {
  balance: 69.88, unit: 'USD', plan: '钱包余额', valid: true, mode: 'unrestricted',
  today: { cost: 0.36, actual_cost: 0.0863, requests: 1, total_tokens: 39513 },
  total: { cost: 82.82, actual_cost: 26.39, requests: 513, total_tokens: 37700219,
           cache_read_tokens: 29405179 },
  rpm: 0, tpm: 0, avg_ms: 30274.9,
  // ★ 每天两个分解维度都有：四类 token（上游 daily_usage 直接给）+ 按模型
  //   （后端逐日查 `?start_date=D&end_date=D` 拿到）。夹具必须两个都带，
  //   否则图一层都画不出来、而"画不出来"和"这段时间没用过"长得一样。
  // ★★ **20 天**，且模型构成**随时间变化**：`gpt-5.6-luna` 只出现在第 0~4 天。
  //    这不是为了好看 —— 夹具若各天相同，「模型表跟随档位」那条闸换任何档位都得到
  //    同一张表，是个**空守卫**。有了这条，7d 里必须查不到 luna、30d 里必须查得到。
  daily: (function () {
    var out = [];
    for (var k = 19; k >= 0; k--) {
      var d = new Date(Date.now() - k * 86400000);
      var date = d.toISOString().slice(0, 10);
      var old = k >= 15;                       // 最早 5 天
      var ms = old
        ? [{ model: 'gpt-5.6-luna', requests: 12, total_tokens: 480000, input_tokens: 90000,
             output_tokens: 6000, cache_read_tokens: 384000, cache_write_tokens: 0,
             cost: 2.4, actual_cost: 0.6 }]
        : [{ model: 'gpt-5.5', requests: 40, total_tokens: 1600000, input_tokens: 280000,
             output_tokens: 17000, cache_read_tokens: 1303000, cache_write_tokens: 0,
             cost: 8.2, actual_cost: 2.05 },
           { model: 'gpt-6-astra', requests: 9, total_tokens: 320000, input_tokens: 60000,
             output_tokens: 4000, cache_read_tokens: 256000, cache_write_tokens: 0,
             cost: 1.6, actual_cost: 0.42 }];
      var agg = { requests: 0, total_tokens: 0, input_tokens: 0, output_tokens: 0,
                  cache_read_tokens: 0, cache_write_tokens: 0, cost: 0, actual_cost: 0 };
      for (var i = 0; i < ms.length; i++) {
        for (var f in agg) agg[f] += ms[i][f] || 0;
      }
      // ★ 每天的四类之和**必须等于** total_tokens（真实数据实测差 0），
      //   夹具对不上的话「分层精确」就成了假绿。
      agg.total_tokens = agg.input_tokens + agg.output_tokens
                       + agg.cache_read_tokens + agg.cache_write_tokens;
      out.push(Object.assign({ date: date, models: ms }, agg));
    }
    return out;
  })(),
  models: [
    { model: 'gpt-5.5', requests: 226, total_tokens: 21400000, input_tokens: 3982390,
      output_tokens: 174123, cache_read_tokens: 17243487, cache_write_tokens: 0,
      cost: 30.0, actual_cost: 8.12 },
    { model: 'gpt-6-astra', requests: 134, total_tokens: 9100000, input_tokens: 1500000,
      output_tokens: 80000, cache_read_tokens: 7520000, cache_write_tokens: 0,
      cost: 14.2, actual_cost: 3.51 }
  ],
  runway: { days: 30.1, per_active_day: 2.32, sample_days: 7, reason: null },
  usage_path: '/usage', fetched_at: Math.floor(Date.now() / 1000)
};
// ★★ 2026-09-09「一个 provider,两种上游」之后 `path` 恒指向**账号池那一份** ——
//    中转站不再有自己的 profile。`profile_stale` 整个消失(没有第二份文件可漂移),
//    新增 `relay_disabled`(登记着但被停用 ⇒ 代理退回账号池、用户以为在花钱)。
var POOL_TOML = '/Users/x/.codex/rotateproxy.config.toml';
var RELAY_ROUTES = {
  pool:    { state: 'pool', profile: 'rotateproxy', path: POOL_TOML },
  relay:   { state: 'relay', profile: 'tokendun', path: POOL_TOML,
             label: 'TokenDun', key_fp: 'sk-73a1…294 (0f39111c7caf)' },
  missing: { state: 'profile_missing', profile: 'tokendun', path: POOL_TOML,
             detail: 'rotateproxy.config.toml 不存在 ⇒ codex 会静默退回 base 配置' },
  // ★ 键名叫 `offroute` 不叫 `disabled`:`disabled` 已经是**条目**的状态
  //   (用户把这个中转站停用了),两者同名会让 relayRoute() 与 relayEntry() 互相打架。
  offroute:{ state: 'relay_disabled', profile: 'tokendun', path: POOL_TOML, label: 'TokenDun',
             detail: 'TokenDun 已停用 ⇒ 代理退回账号池。你以为在按量付费,实际扣的是订阅额度。' },
  orphan:  { state: 'orphan', profile: 'tokendun', path: POOL_TOML,
             detail: "路由指向 'tokendun',但它已不在登记表里 ⇒ 代理退回账号池。你以为在按量付费,实际扣的是订阅额度。" },
  corrupt: { state: 'route_corrupt', profile: null, path: '/Users/x/relay/route.local.json',
             detail: '路由文件不是合法 JSON: Expecting value: line 1 column 2 (char 1)' }
};
// ★ `key` 是**诱饵**:真实 `relay-ctl status` 的 payload 里没有它(只有 key_fp)。
//   放在这里是为了让「页面不许渲染完整 key」那条闸**真的能失败** ——
//   夹具里没有完整 key 的话,那条断言永远红不了,是个空守卫。
var RELAY_ROW = { id: 'tokendun', label: 'TokenDun', base_url: 'https://api.tokendun.com/v1',
                  enabled: true, usage_path: '/usage', model: null,
                  key: 'sk-DECOY-must-never-be-rendered-0000000000',
                  key_fp: 'sk-73a1…294 (0f39111c7caf)', added_at: '2026-09-09T10:28:24+0800' };
function relayMode() { return p.get('relay') || 'relay'; }
function relayRoute() {
  var m = relayMode();
  return RELAY_ROUTES[m] || RELAY_ROUTES[m === 'never' || m === 'unreachable' || m === 'auth' || m === 'nobill' || m === 'empty' ? 'relay' : 'relay'];
}
function relayEntry() {
  var m = relayMode();
  var base = { id: 'tokendun', label: 'TokenDun', base_url: RELAY_ROW.base_url, key_fp: RELAY_ROW.key_fp };
  // ★ `disabled` 是**用户的选择**,不是故障 —— `collect()` 对它返回的 payload 没有 `ok`,
  //   页面原来把它渲染成"用量读不到（disabled）：undefined"。这个态必须有夹具。
  if (m === 'disabled') return { id: 'tokendun', label: 'TokenDun', state: 'disabled' };
  if (m === 'unreachable') return Object.assign(base, { ok: false, state: 'unreachable', detail: 'URLError: no route to host' });
  if (m === 'auth') return Object.assign(base, { ok: false, state: 'auth', http: 401, detail: '{"code":"INVALID_API_KEY"}' });
  if (m === 'nobill') return Object.assign(base, { ok: false, state: 'no_billing_endpoint',
    detail: '试过 /usage, /dashboard/billing/usage, /dashboard/billing/subscription,没有一条返回可解析的 JSON' });
  if (m === 'never') return Object.assign(base, { ok: true, state: 'ok', data: Object.assign({}, RELAY_USAGE_OK, {
    balance: null, today: { cost: null, actual_cost: null, requests: null, total_tokens: null },
    runway: { days: null, per_active_day: null, sample_days: 1, reason: '活跃日样本不足 2 天' } }) });
  return Object.assign(base, { ok: true, state: 'ok', data: RELAY_USAGE_OK });
}

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
        return Promise.resolve(LOGS_TXT);
      // ★ 代理轮换台账。**不打桩就是假绿** —— 落到 default 返回 null ⇒ `rot` 恒 null ⇒
      //   上半区永远画「读不到 proxy.log」,而页面照常渲染、零报错、零溢出,sweep 会报干净。
      //   这是本仓第三次踩同一个坑(前两次:grok 卡、agy 卡),所以这次一并把降级态也做成开关。
      //   `?rot=ok|busy|empty|undated|fail`
      // ★ 快照即时读取。harness 里直接返回与全扫**同一份**数据 —— 真机上快照可能更旧,
      //   但那条时序在 headless 里模拟不出来(两次调用之间没有真实时间流逝)。
      //   这里要验的是"快照这条路被走到了、且能画出页面",不是新鲜度。
      case 'read_rotation_snapshot': {
        var rs = p.get('rot') || 'ok';
        if (rs === 'fail' || rs === 'nosnap') return Promise.resolve(null);
        if (rs === 'snaponly') return Promise.resolve(ROT.ok);
        return Promise.resolve(ROT[rs] || ROT.ok);
      }
      case 'read_proxy_rotation': {
        var rk = p.get('rot') || 'ok';
        // ★★ `?rot=snaponly` —— **全扫永不返回**,只有快照能把页面画出来。
        //    这是"快照那条路真的被走到了"的**唯一有判别力**的证据:两条路平时返回同一份
        //    数据,页面画出来一模一样,光看截图分不出是哪条路画的
        //    (harness 的 `ipc` 探针只统计 run_traffic/read_traffic_snapshot 两个白名单命令,
        //     指望它也证不了)。
        if (rk === 'snaponly') return new Promise(function () {});
        if (rk === 'fail') return Promise.reject('读不到 proxy/proxy.log');
        return Promise.resolve(ROT[rk] || ROT.ok);
      }
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
      case 'read_relay_snapshot':
      case 'run_relay_usage': {
        if (relayMode() === 'empty') return Promise.resolve(JSON.stringify({ ok: true, relays: [], route: relayRoute(), fetched_at: Math.floor(Date.now()/1000) }));
        return Promise.resolve(JSON.stringify({ ok: true, relays: [relayEntry()], route: relayRoute(), fetched_at: Math.floor(Date.now()/1000) }));
      }
      case 'relay_ctl': {
        // ★ 记下调用(sub+arg),**不记 payload** —— 它含 key。
        relayCalls.push(String((args && args.sub) || '') + ((args && args.arg) ? ':' + args.arg : ''));
        var sub = args && args.sub;
        if (sub === 'status') {
          return Promise.resolve(JSON.stringify({ ok: true, v: 1,
            relays: relayMode() === 'empty' ? [] : [RELAY_ROW], route: relayRoute() }));
        }
        if (sub === 'test') return Promise.resolve(JSON.stringify({ ok: true, id: 'tokendun', state: 'ok', model_count: 22 }));
        return Promise.resolve(JSON.stringify({ ok: true, route: relayRoute() }));
      }
      case 'read_grok_quota':
      case 'run_grok_quota': {
        var g = p.get('grok') || 'ok';
        if (g === 'never') return Promise.resolve(null);
        return Promise.resolve(JSON.stringify(GROK[g] || GROK.ok));
      }
      // ★ agy 额度。**不打桩就是假绿** —— 落到 default 返回 null ⇒ `agyQuotaVisible` 判 false
      //   ⇒ 整张卡 `return null`,于是 sweep 一张 agy 卡都没渲染却报"干净"。
      //   与 grok 那条同族的坑,这里再踩一次的代价是新加的卡从未被任何一次布局验证覆盖过。
      //   `?agy=ok|tight|noproc|warm|notinst|never`。
      case 'read_agy_quota':
      case 'run_agy_quota': {
        var ag = p.get('agy') || 'ok';
        if (ag === 'never') return Promise.resolve(null);
        var base = AGY[ag] || AGY.ok;
        // ★ `?agypush=<rem>`:**推送到达之后**的读取返回一份更新过的快照。
        //   `agyPushed` 由下面的 `?agypush` 分支在 fire 事件前置位 ——
        //   这样这条测试判的是"推送触发了重读并采纳了新值",
        //   而不是"夹具本来就是新值"（后者恒绿，等于没测）。
        if (agyPushed) {
          var bumped = JSON.parse(JSON.stringify(base));
          bumped.fetched_at = (base.fetched_at || 0) + 600;
          try {
            bumped.quota.groups[0].buckets[0].remaining_percent = Number(p.get('agypush'));
          } catch (e) { /* 夹具形状变了就让断言去发现 */ }
          return Promise.resolve(JSON.stringify(bumped));
        }
        return Promise.resolve(JSON.stringify(base));
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
      // ★★ `?nav=logs` —— 日志页**没有** `navigate-logs` 事件(App.tsx 只监听 traffic/
      //   settings/platform 三个,因为只有它们是 Rust/托盘会发的)。所以只能点侧栏。
      //   ⚠️ **不能用 `?click=日志`**:窗口 <860 时侧栏自动折叠、只剩图标,文字压根不渲染
      //   ⇒ 命中 0 个。sweep 要在 860/900/940 三档扫这一页,那三档全会静默漏掉。
      //   按**位置**点(第 3 个 rail 项)在两种形态下都成立;图标恒在。
      // ★★ **按身份点,不按位置。** 原来点的是 `.cb-rail > div` 的第 3 项 ——
      //   2026-09-09 加「中转站」页时才发现:任何一次插入新页都会让它静默点到别处,
      //   而"点错位置"和"没点中"在截图里长得一模一样。App.tsx 已给每项加 `data-page`。
      //   ⚠️ 仍**不能**用 `?click=日志`:窗口 <860 时侧栏折叠、文字不渲染 ⇒ 命中 0 个,
      //     而 sweep 要在 860/900/940 三档扫这一页。图标恒在,`data-page` 也恒在。
      else if (nav === 'logs' || nav === 'relay') {
        setTimeout(function () {
          var want = nav === 'relay' ? 'relay' : 'logs';
          var el = document.querySelector('.cb-rail > div[data-page="' + want + '"]');
          if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          // ★ `?rtab=账号|用量` 切中转站页内的版块。**按文字身份点,不按位置** ——
          //   位置耦合在这个仓库已经静默点错过两次(插一页就全歪),而"点错"和"没点中"
          //   在截图里长得一模一样。
          var rtab = p.get('rtab');
          if (rtab) {
            setTimeout(function () {
              var box = document.querySelector('[data-relay-tabs]');
              var hit = 0;
              if (box) {
                var opts = box.querySelectorAll('span,div');
                for (var k = 0; k < opts.length; k++) {
                  if ((opts[k].textContent || '').trim() === rtab) {
                    opts[k].dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    hit++; break;
                  }
                }
              }
              clicks.push('rtab=' + rtab + ' →命中 ' + hit);
              if (!hit) errors.push('中转站页里点不到版块 "' + rtab + '" —— bundle 可能是旧的');
              // ★ `?rrange=30d` / `?rmode=总量` —— 在**用量版块内**按文字身份点档位。
              //   限定在 `[data-section="relay-usage"]` 里找,免得点到页签那个 Seg。
              //   位置耦合在本仓静默点错过两次,所以一律按文字。
              setTimeout(function () {
                ['rrange', 'rmode'].forEach(function (name) {
                  var want = p.get(name);
                  if (!want) return;
                  var scope = document.querySelector('[data-section="relay-usage"]');
                  var n = 0;
                  if (scope) {
                    var os = scope.querySelectorAll('span,div');
                    for (var q = 0; q < os.length; q++) {
                      if ((os[q].textContent || '').trim() === want) {
                        os[q].dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        n++; break;
                      }
                    }
                  }
                  clicks.push(name + '=' + want + ' →命中 ' + n);
                  if (!n) errors.push('用量版块里点不到档位 "' + want + '"');
                });
                // ★ `?riso=<模型名>` 点一行把它从图里摘掉。按 `data-model-row` 身份点。
                var riso = p.get('riso');
                if (riso) {
                  setTimeout(function () {
                    var row = document.querySelector('[data-model-row="' + riso + '"]');
                    if (row) row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    clicks.push('riso=' + riso + ' →命中 ' + (row ? 1 : 0));
                    if (!row) errors.push('点不到模型行 "' + riso + '"');
                  }, 120);
                }
              }, 260);
            }, 300);
          }
          var items = document.querySelectorAll('.cb-rail > div');
          clicks.push('nav=' + want + ' →rail 共' + items.length + '项,按 data-page 命中 ' + (el ? 1 : 0));
          // 命中数照样要报 —— 没有 `data-page` 的旧构建会静默什么都不点。
          if (!el) errors.push('rail 里没有 data-page="' + want + '" —— 前端 bundle 可能是旧的');
          if (items.length < 5) errors.push('rail 项数异常: ' + items.length);
        }, 500);
      }
      else fire('navigate-traffic');

      // ★ `?prange=7d|90d|今日…` 点平台详情页的档位。按**文字身份**点（本仓纪律:
      //   位置耦合已经静默点错过两次）。用来验"路由分账跟着档位走"。
      var prange = p.get('prange');
      if (prange) {
        setTimeout(function () {
          var hit = 0, os = document.querySelectorAll('#root span, #root div');
          for (var q = 0; q < os.length; q++) {
            if ((os[q].textContent || '').trim() === prange && !os[q].children.length) {
              os[q].dispatchEvent(new MouseEvent('click', { bubbles: true })); hit++; break;
            }
          }
          clicks.push('prange=' + prange + ' →命中 ' + hit);
          if (!hit) errors.push('点不到平台页档位 "' + prange + '"');
        }, 700);
      }

      // ★ `?mbshow=<ms>` 在指定时刻发 `menubar-shown` —— Rust 是在 `win.show()` 之后发它的
      //   (lib.rs 的 `toggle_menubar`)。菜单栏的高度靠这个事件在**窗口真正可见时**重量一次,
      //   所以要验那条路径,必须能在 harness 里模拟"用户点了托盘"。
      var mbs = parseInt(p.get('mbshow') || '0', 10);
      if (mbs) setTimeout(function () { fire('menubar-shown'); }, mbs);

      // ★★ `?busyfrom=<actionId>` 模拟**另一个 webview** 正在跑某个动作。
      //    harness 只渲染一个 webview,所以"跨窗口同步"这条路径**只能这样验**:
      //    `useBusyMirror` 的接收端不关心事件从哪来,只看 `from` 是不是自己 ——
      //    这里发 `from: 'other-window'`,正是真机上另一个窗口发来的形状。
      //    ⚠️ 没有这个开关,「两端同步」的改动在 harness 里**一个像素都验不到**,
      //      而截图会正常渲染、探针会报干净 —— 本仓点名过的那种假绿。
      // ★★ `?agypush=<rem>` 模拟**采样器写完 sidecar、Rust 广播**（Phase 5）。
      //   判据是"推送到达后 UI 上的数变了" —— 而不是源码里有没有 `listen`。
      if (p.get('agypush')) {
        setTimeout(function () { agyPushed = true; fire('agy-quota-updated'); }, 900);
      }
      if (p.get('busyfrom')) {
        setTimeout(function () {
          fire('action-busy', { action: p.get('busyfrom'), at: Date.now() / 1000,
                                from: 'other-window' });
        }, 200);
      }
      // `?busyself=<actionId>` 是它的**反向对照**:`from` 写成本窗口标签,
      // 接收端必须**忽略**它。少了这条,自过滤那行删掉也不会有测试变红。
      if (p.get('busyself')) {
        setTimeout(function () {
          fire('action-busy', { action: p.get('busyself'), at: Date.now() / 1000,
                                from: (window.__TAURI_INTERNALS__ &&
                                       window.__TAURI_INTERNALS__.metadata &&
                                       window.__TAURI_INTERNALS__.metadata.currentWindow &&
                                       window.__TAURI_INTERNALS__.metadata.currentWindow.label) || 'main' });
        }, 200);
      }
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

    // ★★ `?focusacc=<号名>` 点泳道左侧的号名 → 聚焦(稿子 §3:其余泳道 opacity .28
    //    且事件列表同步过滤)。★ **不能用通用的 `?click=`**:那个是**固定 700ms** 触发,
    //    而泳道要等异步 IPC 回来才渲染 —— 实测它「命中 1 个、零报错」,而截图里
    //    一条泳道都没变暗。命中的是**总览页**上同名的那个元素(切页之前还在)。
    //    「点中了」和「点中了想点的那个」是两回事,这是本轮第三次栽在固定延时上。
    if (p.get('focusacc')) {
      (function pollLane(tries) {
        var el = document.querySelector('[data-lane="' + p.get('focusacc') + '"]');
        if (!el && tries > 0) { setTimeout(function () { pollLane(tries - 1); }, 120); return; }
        clicks.push('focusacc=' + p.get('focusacc') + ' →' + (el ? '命中泳道' : '没找到泳道'));
        if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        else errors.push('focusacc miss: ' + p.get('focusacc'));
      })(20);
    }

    // ★★ `?tipseg=<n>` 给**泳道色块**派发 mouseenter,把时段明细浮层逼出来(稿子 §2)。
    //    与 `?mm=` 不是一回事:那个打的是 `svg rect[fill=transparent]`,而泳道是绝对定位的
    //    div,选择器根本命不中。没有这个开关,浮层(段 token / 模型构成 / 切入原因)
    //    **在 harness 里一个像素都验不到**,而截图会正常渲染、探针会报干净。
    if (p.get('tipseg')) {
      // ★ 必须**轮询等它出现**,不能定死一个延时:泳道要等 `read_proxy_rotation` 这个
      //   异步 IPC 回来才渲染,而固定延时下第一版量到「0 个色块」——那看着像"选择器写错了",
      //   实际只是发早了。同族教训:harness 里凡是等异步产物的驱动都别用固定延时。
      (function pollSeg(tries) {
        var segs = document.querySelectorAll('[data-seg]');
        if (!segs.length && tries > 0) { setTimeout(function () { pollSeg(tries - 1); }, 120); return; }
        var n = parseInt(p.get('tipseg'), 10);
        clicks.push('tipseg →色块共' + segs.length + '个,悬第' + n);
        // ★★ 必须派发 **`mouseover`(bubbles:true)**,不能派发 `mouseenter`。
        //    React 的 `onMouseEnter` 是**合成事件**:它在根节点上监听 `mouseover`/`mouseout`
        //    再自己算进出,原生 `mouseenter` 不冒泡、根本到不了它的委托监听器。
        //    实测:派发 mouseenter → 13 个色块全命中、零报错、浮层**一个字都没出来**;
        //    换成 mouseover 才真的渲染。这正是"命中了 ≠ 生效了"的又一例。
        if (segs[n - 1]) segs[n - 1].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        else errors.push('tipseg miss: 只有 ' + segs.length + ' 个色块');
      })(20);
    }

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
          // ★ **浮动读出层本来就在盒子外**（`.cb-hoverpop`，绝对定位、`pointer-events:none`）。
          //   它会计进父元素的 scrollWidth，但那不是"内容装不下"——是这个设计的定义。
          //   不排掉的话，每个带悬浮浮层的角标都会被报一次，真溢出淹在噪音里
          //   （同上面省略号那条：**刻意的取舍不是缺陷**）。
          if (e.querySelector && e.querySelector(':scope > .cb-hoverpop')) continue;
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
        // ★ 可滚容器的实测几何。加它是因为「内容放不下时到底是**滚动**还是**裁切**」
        //   在别的探针里分不出来:两种情况的 `overflow` 都是 0(裁切根本不算溢出)。
        //   而裁切比太高更糟 —— 下面的内容直接看不见,还没有滚动条提示。
        geom: (function () {
          var out = {};
          // ★ `mb-today` / `mb-pane` 是 2026-09-06 加的:面板固定高之后,**空白**成了新缺陷,
          //   而空白量 = 窗口高 − 内容自然高,少量一个就算不出来。
          ['mb-root', 'mb-pane', 'mb-list', 'mb-today'].forEach(function (c) {
            var el = document.querySelector('.' + c);
            if (!el) { out[c] = 'missing'; return; }
            var cs = getComputedStyle(el);
            out[c] = { h: Math.round(el.getBoundingClientRect().height),
                       scrollH: el.scrollHeight, clientH: el.clientHeight,
                       maxH: cs.maxHeight, flex: cs.flex, minH: cs.minHeight,
                       ovY: cs.overflowY, parent: el.parentElement ? el.parentElement.className : '?' };
          });
          return out;
        })(),
        scrollables: (function () {
          var out = [];
          document.querySelectorAll('*').forEach(function (el) {
            var cs = getComputedStyle(el);
            if (cs.overflowY !== 'auto' && cs.overflowY !== 'scroll') return;
            if (el.scrollHeight <= el.clientHeight + 1) return;   // 装得下,不是可滚状态
            out.push({ sel: el.className || el.tagName,
                       scrollH: el.scrollHeight, clientH: el.clientHeight,
                       hidden: el.scrollHeight - el.clientHeight });
          });
          return out;
        })(),
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
        // ★★ **对齐探针**:报每张账号卡里「到期」那行的 y 坐标。卡片之间要对齐到同一条
        //   水平线,靠肉眼比截图判不准(用户 2026-08-26 用红线标出来才发现),而且
        //   偏移可能有**多个来源**(窗口条数不同、徽章行折行数不同),只看一个会漏。
        //   同时报徽章行的高度 —— 那是第二个偏移源。
        alignY: (function () {
          var out = { expiry: [], bars: [], rings: [], expanded: [], cards: [] };
          var grid = document.querySelector('[data-cards-grid]');
          if (!grid) return out;

          // 这个元素属于哪张卡 = 网格的哪个**直接子元素**。比"向上找账号名"可靠 ——
          // 后者在某些层级会先撞到 hero 或相邻卡（我 2026-08-26 就被这样误导过一轮）。
          function cardOf(el) {
            var n = el;
            while (n && n.parentElement !== grid) n = n.parentElement;
            return n;
          }
          var meta = new Map();       // card 元素 → {name, expanded}
          Array.prototype.forEach.call(grid.children, function (card) {
            var name = '?';
            card.querySelectorAll('span').forEach(function (x) {
              if (name === '?' && /^(plus\d+|Pro\d+|grok)$/.test((x.textContent || '').trim()))
                name = x.textContent.trim();
            });
            // ★ 展开态判据 = 动作条里那颗「重命名」按钮。它只在选中时渲染,
            //   且不是任何其他地方的文案 —— 比按 class/结构猜稳。
            var expanded = false;
            card.querySelectorAll('span').forEach(function (x) {
              if ((x.textContent || '').trim() === '重命名') expanded = true;
            });
            var cr = card.getBoundingClientRect();
            var rowMain = card.querySelector(':scope > div');
            var col = rowMain && rowMain.children.length > 1 ? rowMain.children[1] : null;
            var hs = [];
            if (col) Array.prototype.forEach.call(col.children, function (c) {
              hs.push(Math.round(c.getBoundingClientRect().height));
            });
            out.cards.push(name + ' ' + Math.round(cr.width) + '×' + Math.round(cr.height)
                           + ' 列内=[' + hs.join(',') + ']');
            meta.set(card, { name: name, expanded: expanded });
            if (expanded) out.expanded.push(name);
          });
          // ★ 标签里带上**网格行号**（卡片顶边）。卡片多于 3 张时网格会换行，
          //   跨行比 y 必然把"第二行"读成错位 —— 那是把两排东西放一起比。
          function tag(el) {
            var c = cardOf(el);
            var m = c ? meta.get(c) : null;
            if (!m || !c) return '?#r0';
            return m.name + (m.expanded ? '(展开)' : '') + '#r'
                   + Math.round(c.getBoundingClientRect().top);
          }

          // 「到期」行
          grid.querySelectorAll('span').forEach(function (e) {
            var t = (e.textContent || '').trim();
            if (t.indexOf('到期') !== 0) return;
            var r = e.getBoundingClientRect();
            if (r.width >= 1) out.expiry.push(tag(e) + '@' + Math.round(r.top));
          });

          // 条形行:按「窗口标签 → y」收。同一种窗口(5h / 周)必须落在同一条线上 ——
          // 只看「到期」对齐不够,用户的红线画在条上。
          grid.querySelectorAll('span').forEach(function (e) {
            var t = (e.textContent || '').trim();
            if (t.charAt(0) !== '↻') return;              // ↻ = 重置倒计时,每条条形行都有
            var row = e.parentElement; if (!row) return;
            var lab = row.firstElementChild;
            var vis = row.style.visibility !== 'hidden';
            out.bars.push(tag(e) + '/' + (lab ? lab.textContent.trim() : '?') + (vis ? '' : '(空)')
                          + '@' + Math.round(row.getBoundingClientRect().top));
          });

          // 环:卡片里唯一 52×52 的 svg。报**中心 y** —— 环是圆的,比顶边更能反映"看起来在不在一条线上"。
          // ★ 用户 2026-08-26 指出环顶对齐难看,改回居中;居中之后它也必须跨卡对齐,所以一并守住。
          grid.querySelectorAll('svg').forEach(function (e) {
            var r = e.getBoundingClientRect();
            if (Math.round(r.width) !== 52) return;
            out.rings.push(tag(e) + '@' + Math.round(r.top + r.height / 2));
          });
          return out;
        })(),
        errors: errors.slice(0, 4),
        unknownCmds: unknown.filter(function (v, i, a) { return a.indexOf(v) === i; }),
        clicks: clicks,
        // ★ 只记 sub+arg,**不记 payload** —— 它含 API key。
        relayCalls: relayCalls,
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
    # ★★ `?lowquota=1` 把额度压到会**触发警告色**的档位。
    #    真实数据现在全是高额度,所以「低额度夺色」那条路径**截图根本证明不了** ——
    #    而它正是用户明确要求的行为(2026-08-26:「低额度靠条色报警」)。
    #    只改 used_percent,窗口结构/套餐/到期日全部保真。
    if os.environ.get("CODEXBAR_LOW_QUOTA"):
        levels = [(72.0, 5.0), (95.0, 58.0)]     # (5h 已用, 周已用) → 剩 28% 琥珀 / 剩 5% 红
        for i, sl in enumerate(out_slots.values()):
            q = sl.get("quota") or {}
            for k, used in zip(("primary", "secondary"), levels[i % len(levels)]):
                w = q.get(k)
                if isinstance(w, dict) and w.get("window_minutes"):
                    w["used_percent"] = used
    # ★★ `CODEXBAR_STALE_QUOTA=1` 把**第二个活号**的快照做旧(3.8 天前)。
    #    这是**唯一能验证陈旧标记的夹具**:真实数据里唯一陈旧的号是 Pro1,而它是死号、
    #    只在折叠的「失效账号」区渲染、根本没有卡片 —— 于是那个标记**永远截不到**,
    #    只能得到一个「看起来没问题、实际从未被验证过」的结论(本仓刚为同类问题栽过一次)。
    if os.environ.get("CODEXBAR_STALE_QUOTA"):
        # ★ 必须挑**活号**。第一版挑的是 `values()[1:2]`,而那恰好是死号 —— 死号只在折叠的
        #   「失效账号」区渲染、**根本没有卡片**,于是标记 0 次,夹具白造。
        #   (这也正是真实数据验不了这条的原因:线上唯一陈旧的号就是那个死号。)
        for sl in out_slots.values():
            q = sl.get("quota")
            if sl.get("auth_dead") or not isinstance(q, dict) or not q.get("captured_at"):
                continue
            q["captured_at"] -= int(3.8 * 86400)
            break

    # ★★ `CODEXBAR_FLOATING_ANCHOR=1` 给**第一个活号的每个窗口**造一份账本判定
    #    `floating`，于是倒计时渲染成「未启动」。
    #    这是**唯一能证明那条分支真的渲染出来的夹具**：真实 `state.json` 里 `quota_anchor`
    #    要 quotad 连观测三轮才会出现 `floating`，而截图当下多半是 `unknown`（回落成「待确认」）
    #    —— 只用真数据截图，只能证明回落路径没坏，**证不了新分支存在**。
    #    本仓 2026-09-05 刚为同类问题栽过：8 个新视图全判「干净」，而那些组件一个都没渲染。
    if os.environ.get("CODEXBAR_FLOATING_ANCHOR"):
        for sl in out_slots.values():
            q = sl.get("quota")
            if sl.get("auth_dead") or not isinstance(q, dict):
                continue
            anchor = {"at": q.get("captured_at")}
            for k in ("primary", "secondary"):
                w = q.get(k)
                if isinstance(w, dict) and w.get("window_minutes") and w.get("resets_at"):
                    # `reset` 必须与窗口现值对得上 —— 前端要核身份,对不上就回落。
                    anchor[str(int(w["window_minutes"]))] = {
                        "state": "floating", "held_secs": 0, "samples": 1,
                        "slides": 3, "used_max": 0.0, "reset": int(w["resets_at"])}
            if len(anchor) > 1:
                sl["quota_anchor"] = anchor
                break

    # ★★ `?cardexp=1` 只给**第一个**号一张快到期的重置卡 ⇒ 它的徽章文案变长
    #    （「重置卡 ×1 · 剩1天」），另一个号仍是短文案。
    #    这是**唯一能证伪"卡片已对齐"的夹具**：页脚一旦因文案长短而折行高度就不同，
    #    而条形区是从页脚往上推的 —— 真实数据里两个号的徽章恰好一样长，
    #    只用它截图会得到一个**看起来对齐、实际没被验过**的结论。
    if os.environ.get("CODEXBAR_CARD_EXPIRING"):
        soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        first = next(iter(out_slots.values()), None)
        if first is not None:
            first["credits_detail"] = {"credits": [{"status": "available", "expires_at": soon}]}
    # ★★ `?unprobed=1`：加一个**刚加进来、从没探测过**的号（`windows: []`）。
    #    这个夹具不是凑数的，它一次抓到两件事（2026-08-26）：
    #      ① 池里到 3 个号时，三列网格把 grok 挤到**第二行** —— 对齐必须按排比，跨排比必然误报；
    #      ② 没有窗口的卡不画任何条形行，行数与兄弟卡不同 ⇒ 它的「到期」高 9px。
    #    真实 state.json 里两个号都探测过，**不造这个状态就永远验不到**。
    if os.environ.get("CODEXBAR_UNPROBED"):
        fake = "user-demo990000000000000000000000"
        out_slots[fake] = {"label": "Newbie", "email": "newbie@example.com", "file": f"{fake}.json"}
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
