# 安装指南

> 这套东西是**两半**，可以只装一半。先看清楚你要哪一半，再往下走。

| | **A · AI 用量看板** | **B · 账号池 + 轮换代理** |
|---|---|---|
| 干什么 | 汇总本机各 AI CLI **已经落盘**的 token 消耗，分平台/分模型看趋势与等效费用 | 把多个 ChatGPT 订阅做成池子，经 loopback 代理给 Codex CLI 逐请求透明轮换 |
| 要凭证吗 | **不要**。只读本机文件、不联网、不碰任何 token | 要。每个号 OAuth 登录 |
| 谁能用 | 任何 macOS 用户，装过下面任意一家 AI CLI 就有数据 | 需自备多个 ChatGPT Plus/Pro |
| 装法 | §0 → §1 → §5，**三步** | 全篇按顺序 |
| 风险 | 无 | ⚠️ 见 [§0 风险声明](#0-前置依赖) |

**只想看自己电脑烧了多少 token → 只装 A。**

---

## 0. 前置依赖

| 依赖 | 说明 |
|---|---|
| macOS | 全程本机、loopback-only |
| **Python 3.9+，必须 OpenSSL 构建** | `brew install python3`。★ **不能用系统自带的 `/usr/bin/python3`** —— 它链 LibreSSL 2.8.3，Cloudflare 按 TLS ClientHello 指纹对 `GET /backend-api/codex/usage` **恒返 403**；OpenSSL 3.x 同请求恒 200（受控实验，单一变量各 3 次）。纯 stdlib，无需 pip 包 |
| Node 18+ / Rust | 桌面应用需要：`brew install node` + `curl https://sh.rustup.rs -sSf \| sh` + `xcode-select --install` |
| Codex CLI | **仅 B 需要**：`npm i -g @openai/codex` |
| 多个 ChatGPT Plus/Pro | **仅 B 需要** |

> ### ⚠️ 关于 B 的风险声明
>
> 多账号轮换**受 OpenAI 服务条款约束，使用风险自负**。本仓库 `CHANGELOG.md` 的 B7/B8/B14/B21
> 记录了实测发生过的**掉号**事故。作者的用法是：一个人、自己付费购买的号、全程本机、
> loopback-only、同一家庭 IP。**这不构成任何形式的建议或担保。**
>
> 只装 A 完全没有这一层风险 —— 它连一个网络请求都不发。

---

## 1. clone

```bash
git clone https://github.com/zhuisen/codex-account-rotator.git
cd codex-account-rotator
```

clone 到**哪个目录都行**：`install-launchd.sh` 与 `quota_daemon.py` 自解析仓库根，
桌面应用由 `deploy.sh` 在**构建期**把仓库路径烧进二进制（GUI app 不继承 shell 环境，
运行期 env 对双击启动无效）。

> ★ 因此**换了 clone 目录必须重跑一次 `deploy.sh`**，光挪文件不行。

**只装 A 的话，跳到 [§5](#5-构建桌面应用)。**

---

## 2. 入口 symlink

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/codex-rotate" ~/.local/bin/codex-rotate   # 池管理 CLI
ln -sf "$PWD/cx"           ~/.local/bin/cx             # 单号 wrapper
ln -sf "$PWD/proxy/cxp"    ~/.local/bin/cxp            # 日常入口:经代理多号轮换
chmod +x codex-rotate cx proxy/cxp proxy/auth-token
```

把 `~/.local/bin` 放进 `PATH`。

---

## 3. 配置 Codex provider

在 `~/.codex/config.toml` 末尾追加（把路径换成你的 clone 位置）：

```toml
[model_providers.rotateproxy]
name = "codex-rotate proxy"
base_url = "http://127.0.0.1:8011"
wire_api = "responses"

[model_providers.rotateproxy.auth]
command = "/path/to/codex-account-rotator/proxy/auth-token"
```

> ★★ **如果你在用系统代理（Clash / Surge 等），必读。**
> 开着系统代理时，Codex 的 reqwest 会把发往 `http://127.0.0.1:8011` 的请求也送进代理，
> 而多数代理对 loopback 目标**连接受理、永不响应** ⇒ Codex **永久挂死、零输出**，
> 本地代理侧一条日志都没有。
> 仓库里的 `proxy/cxp` 已经 `export NO_PROXY=127.0.0.1,localhost,::1` —— **别删那两行**。
> ⚠️ 系统代理自己的例外表里本来就有 `127.0.0.1`，但 **reqwest 无视它**，所以在 Clash 里配
> bypass 没用。误导性症状是 `models_manager: timeout waiting for child process to exit`，
> 与子进程无关，顺着它查会走死。

---

## 4. launchd 服务与登录

**macOS**：

```bash
bash scripts/install-launchd.sh     # 生成 + 加载 3 个服务
launchctl list | grep codex-rotate  # 应有 3 行
```

**Windows**（v1.0.4 起）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
schtasks /Query /TN "com.doushutangmu.codex-rotate.proxy"
```

> ⚠️ **Windows 上有两处刻意的语义差异**（平台限制，不是 bug）：
> ① `autosync` 从「文件变化即触发」降级为**每分钟轮询** —— Task Scheduler 没有文件监视触发器，
>    所以 `codex login` 后新号入池最慢延迟 1 分钟（macOS 上是秒级）。
> ② 崩溃恢复靠 `RestartOnFailure`（**只认非零退出码**）+ 每 5 分钟补拉触发器，
>    不是 launchd 那种「退出就立刻重启」。
>
> 卸载：`powershell -File scripts\install-windows.ps1 -Uninstall`

| 服务 | 触发 | 作用 |
|---|---|---|
| `…proxy` | KeepAlive 常驻 | 轮换代理，听 `127.0.0.1:8011` |
| `…autosync` | WatchPaths `~/.codex/auth.json` | `codex login` 新号秒级入池 |
| `…quotad` | RunAtLoad + KeepAlive | 活动驱动读官方 usage API 刷额度（零消耗）+ 300s 全池扫描兜底 |

两个平台注册的是**同一组服务**（名字、入口脚本、端口都一致），由 `tests/test_installers_agree.py` 守着 —— 只改一边会让某个平台**静默少一个常驻进程**，而症状是「额度不更新」这类看起来跟安装器无关的现象。

脚本自解析仓库根并**校验 python3 是 OpenSSL 构建**，找不到就报错退出，不会静默装成坏的。

登录账号（每个号登一次，autosync 自动入池）：

```bash
codex login                  # 第 1 个号
codex-rotate list
codex-rotate rename <id> main
```

> ★★ **加号只用 `codex-rotate login`，不要自己跑 `codex logout` / `codex login`。**
> 受控实验三轮确证：`codex login`/`logout` 会把**当时躺在 `~/.codex/auth.json` 里的那个号**
> 在服务端 revoke，症状伪装成「这台电脑只能登 2 个号」。
> `codex-rotate login` 会先把 auth.json 整个移走、在本机无 token 状态下登录、失败自动还原。
>
> ★ 每个号必须用**独立无痕窗**打开授权 URL，否则同浏览器会话链里两个号会反复互顶
> （"signed in to another account"）。

日常用 `cxp` 代替 `codex` 即可。

---

## 5. 构建桌面应用

```bash
bash codexbar/scripts/setup-signing.sh   # 一次性:自签证书
bash codexbar/scripts/deploy.sh          # 构建 + 部署 + 启动
```

**自签是必须的**：macOS 会为每次重新构建的未签名 app 重新索要 TCC 授权；
用一张固定的自签证书签名后，授权跨重建保留。证书只在本机钥匙串，不外传。

装完顶栏出现 ⚡ 图标，`/Applications/CodexBar.app` 就位。

**没装账号池（跳过了 §2~§4）时，「总览」页和菜单栏「账号」Tab 是空的，属正常** ——
「AI 用量信息」页照常工作，那才是对所有人都有效的部分。

### 数据源

全部来自**本机 CLI 自己落的盘**，零额度消耗、不联网、不碰凭证：

| 平台 | 位置 |
|---|---|
| Claude Code | `~/.claude/projects/**/*.jsonl` |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` |
| Grok | `~/.grok/sessions/*/*/updates.jsonl` |
| Kimi | `~/.kimi-code/sessions/**/agents/*/wire.jsonl` |
| OpenClaw | `~/.openclaw/agents/*/sessions/*.jsonl` · **宿主源** |
| Reasonix | `~/.reasonix/stats/*.jsonl` · **宿主源** |
| DeepSeek Harness | `~/.dsh/sessions/**/session.jsonl.zstd` · **宿主源**，需本机 `zstd` |
| Antigravity | `traffic/agy-ledger/usage.jsonl` · ⚠️ 仅 print 模式，见下 |

**宿主源**自己不作为平台出现 —— 它们的每条记录按**模型名**回流到 Claude/Codex/Grok/Kimi/DeepSeek/MiMo。
所以**页面上的平台数不固定**，取决于你在里面跑过哪些模型。

加一家平台 = 在 `traffic/scan.py` 写个 `_scan_*` 解析器 + 注册表加一行，前端自动跟上。

> ⚠️ **Antigravity 只覆盖 print 模式**（`agy -p`，即 `omc ask` / `omc team` 走的那条）。
> agy 自己**不落用量**（123 个会话的 SQLite / transcript / cli.log 全部零命中），
> 数据靠 `bin/agy` wrapper 从 `--output-format json` 截获记账，**交互式会话拿不到**，
> 页面上有覆盖率徽章标注。启用需要：
>
> ```bash
> echo 'export PATH="/path/to/codex-account-rotator/bin:$PATH"' >> ~/.zshrc
> ```
>
> ★ **必须排在 `~/.local/bin` 之前** —— agy 自带 24h 自动更新且直接改写 `~/.local/bin/agy`，
> wrapper 放那里会被**静默抹掉**。这个目录只有 `agy` 一个文件，影响面就这一个命令。

### 性能

首次扫描约 **23 秒**（10000+ 文件全解析），之后走增量缓存 **~0.8s**
（Claude 的活跃 transcript 只解析追加部分，不再整个重读）。
界面画的是上次扫描的**成品快照**（读盘 ~1ms），所以进页面不等待。

### 费用口径

页面上的费用是**按公开牌价折算的等效 API 成本，订阅制下并非实付**，UI 各处均有标注。
缓存读按各平台各自的折扣计价（不是统一 10%）。

---

## 6. 卸载

```bash
# 服务
for s in proxy autosync quotad; do
  launchctl bootout gui/$(id -u)/com.doushutangmu.codex-rotate.$s 2>/dev/null
  rm -f ~/Library/LaunchAgents/com.doushutangmu.codex-rotate.$s.plist
done
# 应用
rm -rf /Applications/CodexBar.app
# 入口
rm -f ~/.local/bin/{codex-rotate,cx,cxp}
```

再移除 `~/.codex/config.toml` 里的 `rotateproxy` 块。

`auth/` 与 `state.json` 含凭证，删掉即清空本机账号池。

---

## 7. 一眼自检

```bash
codex-rotate health      # 每号 access token 寿命 + 是否失效 + 环境闸
codex-rotate list        # 池子与各号额度
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8011/  # 代理在不在听
```

> ★ **验健康用只读的 `health`，不要用 `refresh` 代替** —— `refresh` 会轮换 refresh_token，
> 它是一次性的，本身具破坏性。
