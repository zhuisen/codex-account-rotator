# CodexBar 整改实施计划 (v3 — 综合 Opus 4.8 + Codex GPT-5.5 双方评审)

> 2026-06-30 · 基于 ~/Downloads/design_handoff_codexbar/ 设计交接文档
> Opus 4.8 评审: 1 CRITICAL + 5 HIGH + 6 MEDIUM 全部修正
> Codex GPT-5.5 增量: Phase 0 spike / Vite 8 rolldownOptions / hide 不 close / async spawn_blocking / 统一 tray builder

---

## 现状

- **技术栈**: Tauri 2.11.3 + Vite 8 + React 19 + TypeScript
- **已就绪**: theme.ts(完整 Design Tokens)、helpers.ts(数据模型+转换)、Rust IPC(read_state/run_rotate/read_auth_tokens)、窗口 1000×660
- **约束**: 无完整 Xcode(只有 CLT)

---

## 评审修正清单

| 原计划 | 评审发现 | 修正 |
|---|---|---|
| 双击 tray → 开主窗口 | **[CRITICAL]** `DoubleClick` 是 Windows Only,macOS 不触发 | 左键 toggle 弹窗 + 右键菜单含「打开主窗口」;需 `.show_menu_on_left_click(false)` |
| capabilities 只有 core:default + shell:default | **[HIGH]** 缺窗口写权限,前端调 close/minimize 被拒 | 加 window:allow-close/minimize/hide/show/set-focus/set-position/center + menubar 窗口 |
| Phase 4(tray) 在 Phase 3(弹窗) 后 | **[HIGH]** 弹窗的创建/定位/show-hide 在 Rust 侧,依赖倒置 | Phase 3 和 4 合并(先做 tray 基础 → 再做弹窗 UI) |
| tray 定时刷新 spawn thread | **[HIGH]** TrayIcon 不是 Send | 改 `tauri::async_runtime::spawn` + `tokio::time::sleep` |
| App.tsx 内联 types/helpers/theme | **[HIGH]** 与 theme.ts/helpers.ts 重复,会漂移 | Phase 2 第一步删内联重复,统一 import |
| 弹窗定位"计算位置" | **[HIGH]** 方案不具体 | 从 Click 事件 rect 精确定位:x=rect.x + rect.w/2 - win_w/2, y=rect.y + rect.h |
| 弹窗顶部小箭头 | [MEDIUM] transparent WebView 已知问题 | **第一版不做**,纯矩形弹窗 |
| 弹窗不自动关闭 | [MEDIUM] 漏了 blur→hide | 监听窗口 blur 事件,失焦自动收起 |
| ThemeToggle 独立组件 | [MEDIUM] 10 行,两处布局不同 | **删掉**,各自内联 |
| tray 文字状态色 | [MEDIUM] macOS 不可自定义 tray title 颜色 | 接受系统默认颜色,状态只影响图标 |
| 两窗口状态同步 | [MEDIUM] 各自轮询有延迟 | Rust 操作完成后 `app.emit("state-changed")` 广播 |
| 第二窗口 tauri.conf.json 声明 | [MEDIUM] URL 映射不灵活 | **改 Rust `WebviewWindowBuilder::new()` 动态创建** |

---

## Codex 增量修正

| 原计划 | Codex 发现 | 修正 |
|---|---|---|
| 直接 Phase 1 开始写 UI | 先跑通 tray/popover/双入口/capabilities 再像素级 | **新增 Phase 0 spike**(空白页验证管道) |
| Vite `rollupOptions.input` | Vite 8.1 中 `rollupOptions` deprecated | 改 `rolldownOptions.input` |
| 红黄绿红点调 `close()` | close 销毁窗口,tray 后续拿不到 | 改 `hide()`;右键菜单退出才真 `close()` |
| `run_rotate` 同步 `waitUntilExit` | Python 子进程(refresh-all ~2s)阻塞 command thread | 改 `async` + `spawn_blocking` |
| tauri.conf.json 有 trayIcon + Rust 也 build tray | 重复 | 移除 config tray,统一 Rust `TrayIconBuilder` |
| 无 LSUIElement 考虑 | skipTaskbar ≠ 隐藏 Dock;纯 menu bar app 需 LSUIElement | 暂保留 Dock 图标(点 Dock 也能开主窗口);后续可加 |

---

## 阶段拆分 (修正后)

### Phase 0: Spike — 管道验证 (~50 行)

用空白页跑通所有 Tauri/Vite 管道:
1. **双入口**: `menubar.html`(根目录) + `vite.config.ts` 的 `rolldownOptions.input` → 确认 `dist/menubar.html` 生成
2. **第二窗口**: Rust `WebviewWindowBuilder::new()` 创建 menubar → 确认加载 `menubar.html`
3. **Tray**: 移除 config tray,Rust `TrayIconBuilder` + `show_menu_on_left_click(false)` + 左键 toggle menubar + `set_title(Some("⚡ test"))` → 确认 macOS 菜单栏文字
4. **Capabilities**: 加 window 写权限 + menubar 窗口 → 确认前端 `getCurrentWindow().hide()` 不报权限错
5. **通过标准**: 菜单栏显示 `⚡ test` + 左键弹空白窗口 + 右键菜单开主窗口 + 红点 hide = 全过

### Phase 1: 共享组件 (~80 行)

| 文件 | 内容 |
|---|---|
| `src/components/Ring.tsx` | SVG 环形进度圈 |
| `src/components/Toast.tsx` | 底部居中 Toast |
| `src/components/GhostButton.tsx` | 幽灵按钮(从现有 GhostBtn 提取) |

~~ThemeToggle~~ — 删掉,各页面内联(评审:10 行不值得抽组件)。

### Phase 2: 主窗口重写 (~300 行)

重写 `src/App.tsx`:

**第一步**: 删除所有内联 types/helpers/theme,统一 import from theme.ts/helpers.ts(修复评审 HIGH)。

布局 1:1 复刻设计稿:
- 自定义标题栏(38px): `decorations:false` + `data-tauri-drag-region` + CSS 红黄绿圆点 → 调 `getCurrentWindow().close()/.minimize()` (需 capabilities 权限)
- 明暗切换: 太阳/月亮段控件,各自内联
- Sidebar(52px): 4 个 SVG 图标,柱状图 accent 高亮
- 总览页头: 标题 + 汇总 + 操作按钮组(刷新全池/刷新各号+1%/冷却/清除)
- Hero 推荐卡: 80px ring + "现在该用 · USE NOW" + 号名 24px + 指标行 + "设为当前号→"
- 3×2 卡片网格: gap:11px, 52px ring, 周进度条, 状态色, 当前号 accent 描边
- Toast: 底部居中弹出
- 1s interval: 冷却倒计时(独立 `cooldowns` state + React.memo 避免全量重渲染)

### Phase 3: Tray + 菜单栏弹窗 (合并,~350 行)

**先做 Rust tray 基础**:
1. `show_menu_on_left_click(false)` — 左键不弹原生菜单
2. 左键 `Click` 事件: toggle menubar 窗口(从 `rect` 定位)
3. 右键菜单: 「打开主窗口」+「退出」
4. tray title: `set_title(Some("⚡ {label} {h5}%"))`,系统默认颜色
5. 定时刷新: `tauri::async_runtime::spawn` + `tokio::time::sleep(30s)` 循环读 state 更新 title
6. 弹窗窗口: **`WebviewWindowBuilder::new()`** 动态创建(非 tauri.conf.json 静态),URL = `menubar.html`
7. 弹窗失焦关闭: 窗口 `on_window_event` 监听 `Focused(false)` → hide

**再做弹窗前端** (`src/MenuBar.tsx` + `menubar.html` + `menubar-entry.tsx`):
- 412px 宽, 深浅双主题
- 头部: ⚡ + CodexBar + 彩色计数点 + 明暗切换 + 齿轮
- 推荐区: 58px ring + "现在该用" + 号名 + "设为当前→"
- 账号列表: max-h 286px scroll, 42px ring per row
- 底部 2×2: 刷新全池/刷新各号+1%/冷却/清除
- Toast

**Vite 多页**: `vite.config.ts` 加 `build.rollupOptions.input = { main: 'index.html', menubar: 'menubar.html' }`

**状态同步**: Rust 操作完成后 `app.emit("state-changed")`;两窗口 `listen("state-changed")` 立即 refresh。

### Phase 4: Capabilities + 构建验证

1. 更新 `capabilities/default.json`:
   ```json
   {
     "windows": ["main", "menubar"],
     "permissions": [
       "core:default", "shell:default",
       "core:window:allow-close", "core:window:allow-minimize",
       "core:window:allow-hide", "core:window:allow-show",
       "core:window:allow-set-focus", "core:window:allow-set-position",
       "core:window:allow-center"
     ]
   }
   ```
2. `cargo build` (Rust tray 改动)
3. `npm run tauri -- dev` 端到端验证:
   - 主窗口: 5 号卡片 + Hero + 操作 + 暗亮切换
   - 菜单栏: tray 显示 `⚡ main 93%` + 左键开合弹窗 + 弹窗操作
   - 失焦关闭 + 两窗口同步
4. `npm run tauri -- build` 打 release .app (若 xcodebuild 失败 → cargo build --release + 手动组装)

---

## 文件变更清单

| 操作 | 文件 | 说明 |
|---|---|---|
| 新建 | `src/components/Ring.tsx` | SVG 环形进度圈 |
| 新建 | `src/components/Toast.tsx` | Toast 提示 |
| 新建 | `src/components/GhostButton.tsx` | 幽灵按钮 |
| 重写 | `src/App.tsx` | 主窗口(~300 行,删内联重复) |
| 新建 | `src/MenuBar.tsx` | 菜单栏弹窗(~200 行) |
| 新建 | `src/menubar-entry.tsx` | 弹窗 React 入口(3 行) |
| 新建 | `menubar.html` | 弹窗 HTML 入口 |
| 改 | `src/App.css` | 仅 @font-face + keyframes |
| 微调 | `src/theme.ts` | 已完成 |
| 微调 | `src/helpers.ts` | 已完成 |
| 重写 | `src-tauri/src/lib.rs` | tray 逻辑 + 弹窗创建 + emit |
| 改 | `src-tauri/Cargo.toml` | 可能加 tokio feature |
| 改 | `src-tauri/capabilities/default.json` | 窗口权限 |
| 改 | `vite.config.ts` | 多页入口 |

总变更: ~700 行新/改代码(评审修正:从 1200 降到 700)

---

## 已排除(设计妥协)

1. 弹窗小箭头 — 第一版不做(transparent WebView 已知问题)
2. tray title 状态色文字 — macOS 不支持自定义颜色
3. 硬编码 STORE 路径 — 个人工具,第一版保持;后续 SETUP 提供替换说明
