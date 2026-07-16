# CodexBar

**codex-rotate 的展示层** —— Tauri 2 + React 原生 macOS app，取代已退役的 SwiftBar 插件。
菜单栏弹窗 + 主窗口仪表盘，实时看多号 Codex 额度、一键切号、失效号折叠、开机自启。

## 构成

| 层 | 说明 |
|---|---|
| 菜单栏托盘 | 标题 `plusN 周 XX% ↻Nd Nh`；左键弹窗 / 右键菜单(打开主窗口·刷新·切最佳号·退出) |
| 弹窗(412px) | 当前号 hero + 可用账号列表(周额度油表)+ 失效号默认折叠 + 刷新 + 齿轮直达设置 |
| 主窗口(1000×660) | 3 列账号卡 + Hero 当前号 + 日志页 + 设置页;⌘1~⌘9 快捷键切号 |

数据源：读 `../state.json`（codex-rotate 的池状态）；所有操作经 IPC 调 `../codex-rotate` CLI。

## 开发 / 部署

```bash
npm install
npm run dev                    # 前端热更(需 Tauri dev 才有窗口)
bash scripts/setup-signing.sh  # ★一次性:建自签证书(跨重建保 TCC 授权)
bash scripts/deploy.sh         # 构建 → 签名 → 部署到 /Applications → 启动
```

- 版本号唯一真源：`src-tauri/tauri.conf.json` 的 `version`。
- 隐藏 Dock：`ActivationPolicy::Accessory`（仅菜单栏，不占 Dock）。
- 开机自启：设置页开关，走 `tauri-plugin-autostart`(LaunchAgent，注册 `com.doushutangmu.codexbar`)。

## 关键不变量

- **窗口标签由 `window_minutes` 动态判定**：周=10080 / 月=43200；`< 5000` 的（Codex 已废弃的 5h=300、空槽=0）一律不显示。
- OAuth `refresh_token` 单次有效——UI 只读 `state.json` + 调 CLI，绝不并发刷新。
- 完整 token 不显示，仅指纹（末 8 位）。
