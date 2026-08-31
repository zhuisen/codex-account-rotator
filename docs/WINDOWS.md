# Windows 支持状态

> **先读这段。** 本项目的开发机只有 macOS。Windows 端的每一行代码都经过
> `x86_64-pc-windows-msvc` 交叉编译检查，锁实现有在 `windows-latest` 上真跑的行为契约测试，
> 安装包由 GitHub Actions 在真 Windows 上构建 —— 但**没有任何一次端到端的真机使用验证**。
>
> 交叉编译能证明"编译得过"，CI 能证明"打得出包、锁的语义对"，
> 两者都**证明不了**"装上去、点开、账号池跑得起来"。
> 请把 Windows 端当作 **beta**，遇到问题请开 issue。

---

## 分块状态

| 子系统 | 状态 | 说明 |
|---|---|---|
| **AI 用量看板** | ✅ 应可用 | 8 个数据源里 7 个是 `%USERPROFILE%\.<name>`，与 macOS 同形，`Path.home()` 直接通用 |
| 桌面应用编译 | ✅ 已验证 | 交叉编译 0 error；CI 在 windows-latest 原生构建 NSIS + MSI |
| 跨进程锁 | ✅ 契约已在真 Windows 上验 | `LockFileEx`；行为测试跑在 CI 的 windows-latest |
| 单实例守卫 | ✅ 已实现 | 命名互斥体（`Local\` 命名空间） |
| 托盘 | ⚠️ **降级** | 见下「已知差异」 |
| **账号池 + 轮换代理** | ⚠️ **未经真机验证** | 代码路径已补齐，但 OAuth 登录、代理转发、轮换都没在 Windows 上跑过 |
| 定时服务 | ⚠️ **已实现，未真机验证** | `scripts/install-windows.ps1` 用任务计划程序注册同样的 3 个服务。★ 与 macOS **两处真实差异**：autosync 从「文件变化即触发」降级为**每分钟轮询**（Task Scheduler 没有文件监视触发器），新号入池最慢延迟 1 分钟；崩溃恢复靠 `RestartOnFailure`（只认非零退出码）+ 每 5 分钟补拉触发器，不是 launchd 那种立刻重启 |
| 开机自启 | ✅ 应可用 | `tauri-plugin-autostart` 在 Windows 上走注册表 Run 键 |

---

## 已知差异（不是 bug，是平台限制）

### 托盘没有文字

macOS 的菜单栏常驻显示 `plusN 周 XX% ↻Nd`，**Windows 做不到** ——
`TrayIcon::set_title` 在 Windows 上是**空实现**，托盘只有图标和 tooltip。

现状：那串信息进了 tooltip（127 字符上限），**要悬停才看得见**。

这不是等价替换。把百分比栅格化进图标是后续方案，尚未做。

### 图标

macOS 用的是模板图（全黑、由系统按主题反色）。Windows 没有模板图概念，
直接用会在深色任务栏上画黑色 = 隐形。Windows 走彩色图标。

### 锁语义

`LockFileEx` 是**强制锁**，`flock` 是**劝告锁**。本仓库所有写者都加锁，所以行为一致；
但如果将来有代码不加锁直接写文件，POSIX 上会成功、Windows 上会被拒。

另外**不要**把锁改成「打开一次、长期持有、反复加锁」的形态：
`flock` 对同一 fd 重复加锁是升级，`LockFileEx` 对同一句柄的重叠范围会**死锁**。

### 为什么不用 `msvcrt.locking`

它是显然的替代品，也是错的那个。本仓库依赖锁的四条性质里它只满足一条，
致命的是**阻塞获取约 10 秒就放弃** —— 而 `.refresh.lock` 要跨一整个 OAuth POST（实测可达 30 秒）。
放弃意味着第二个刷新者拿到了它以为的锁，两个进程消费同一个一次性 refresh_token，
即 `CHANGELOG.md` 里 B7/B8/B14 那串掉号事故的机制。

细节与四条性质的对照表见 `portalock.py` 的模块文档。

---

## 数据源路径对照

| 源 | macOS | Windows | 依据 |
|---|---|---|---|
| Claude Code | `~/.claude/projects/**/*.jsonl` | `%USERPROFILE%\.claude\projects\**\*.jsonl` | 从安装的 bundle 抽取：`knc()??join(homedir(),".claude")`，**无 win32 分支** |
| Codex | `~/.codex/sessions/**` | `%USERPROFILE%\.codex\sessions\**` | openai/codex 源码 `home-dir/src/lib.rs`：`dirs::home_dir()+".codex"` |
| Grok | `~/.grok/**` | `%USERPROFILE%\.grok\**` | 二进制里的 `xai-dirs` crate 解析单一 `$GROK_HOME` 根 |
| Kimi | `~/.kimi-code/sessions/**` | `%USERPROFILE%\.kimi-code\sessions\**` | 同上族 |
| OpenClaw | `~/.openclaw/agents/**` | `%USERPROFILE%\.openclaw\agents\**` | 源码 |
| DeepSeek Harness | `~/.dsh/sessions/**` | `%USERPROFILE%\.dsh\sessions\**` | 源码 |
| **Reasonix** | `~/.reasonix/stats/` | **`%APPDATA%\reasonix\stats\`** | ★ **唯一例外**，从其二进制里抽出的表实证 |
| Antigravity | `~/.gemini/antigravity-cli/` | `%USERPROFILE%\.gemini\antigravity-cli\` | 官方 CHANGELOG（含 Windows 路径修复条目） |

★ **为什么这张表值得这么较真**：路径猜错的症状是**静默扫出 0 行** —— 不报错、不告警，
页面上只是少一个平台。所以每一行都要求「从对方自己的代码/二进制里拿到证据」，
而不是按 `~/.x` 的惯例推。上面每条都经过一次独立的对抗核验（重新抽 strings、
重新 clone 源码、追 `dirs` crate 区分 `home_dir()`=FOLDERID_Profile 与
`config_dir()`=%APPDATA%），无一被推翻。

`dirs::home_dir()` 在 Windows 上走 `FOLDERID_Profile`（即 `C:\Users\<你>`），
与 `config_dir()` 的 `%APPDATA%` 是**两个不同的 API** —— 这排除了
「Electron / env-paths 系工具其实落在 Roaming 下」那个常见陷阱。

---

## 仍未做的事

1. ~~**定时服务**~~ **已实现**（`scripts/install-windows.ps1`，v1.0.4）。仍未真机验证；
   两处刻意的语义差异（autosync 轮询、崩溃恢复不是立刻）写在脚本文件头。
   两个安装器的服务集合由 `tests/test_installers_agree.py` 守着 —— 只改一边会让某个平台
   静默少一个常驻进程，而这正是 Windows 端从 v1.0.0 到 v1.0.3 的实际状态。
2. **托盘百分比**：见上。
3. **端到端真机验证**：需要一台 Windows 机器。以下全部**未验证**：
   - 安装包能否正常安装、WebView2 缺失时 NSIS bootstrapper 是否正确拉起
   - 托盘弹窗在任务栏位于不同边缘 / 多屏 / 混合 DPI 下的定位
   - `codex login` 的浏览器 OAuth 回流
   - 代理转发与轮换
   - 单实例守卫在真实开机竞态下的表现
   - 中文路径、带空格的用户名
4. **代码签名**：Windows 产物未签名，SmartScreen 会警告。个人开源项目的现实选择是
   要么用户手动放行，要么自费购买 OV/EV 证书（EV 才能立即消除警告）。当前选择是不签。
