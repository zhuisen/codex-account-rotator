use serde_json::Value;
use std::fs;
use std::process::Command;
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    webview::WebviewWindowBuilder,
    AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl,
};

/// 仓库根目录 —— `codex-rotate` / `traffic/scan.py` / `state.json` 都从这里找。
///
/// ★ **GUI app 从 Finder / launchd 启动时不继承 shell 环境**,所以"让用户配个 `CODEXBAR_STORE`"
/// 对别人的机器根本不成立(他 `export` 完双击图标,进程里依然读不到)。唯一可靠的做法是
/// **构建期烧进去**:`deploy.sh` 把自己所在仓库的绝对路径传成 `CODEXBAR_STORE_DEFAULT`,
/// `option_env!` 在编译时取到它。这样别人 clone 到任何目录、跑一次 deploy.sh 就能用。
///
/// 运行期 env 仍然优先 —— 那条留给隔离测试(从终端起 app 时才有效)。
fn store_dir() -> String {
    if let Ok(p) = std::env::var("CODEXBAR_STORE") {
        if !p.is_empty() {
            return p;
        }
    }
    if let Some(p) = option_env!("CODEXBAR_STORE_DEFAULT") {
        if !p.is_empty() {
            return p.to_string();
        }
    }
    // 兜底:仓库默认位置。走到这里说明不是用 deploy.sh 构建的。
    let home = std::env::var("HOME").unwrap_or_default();
    format!("{}/Projects/tools/codex-account-rotator", home)
}

// ★ 白名单守的是**账号池命令**。加 `rename`:改名后托盘标题和两个 webview 都要跟着变,而
//   `run_rotate` 成功后已经 `emit("state-changed")` + `refresh_tray()`,所以走这条通道自动同步。
//   (流量相关的走独立的 `run_traffic`/`run_discover`,两套语义不混一个白名单。)
const ALLOWED_CMDS: &[&str] = &["switch", "cool", "uncool", "refresh-all", "health", "list", "quota", "remove", "credits", "probe", "tokens", "rename"];

/// Interpreter for codex-rotate. NOT a bare `python3`: Cloudflare fingerprints the TLS ClientHello,
/// and macOS's `/usr/bin/python3` (LibreSSL 2.8.3) gets a hard 403 from /backend-api/codex/usage while
/// an OpenSSL 3.x build gets 200 with the identical token, headers and IP (measured 2026-08-01, 3
/// trials each). A bare `python3` resolved through whatever PATH the app inherits at launch, which
/// worked only by luck — the login PATH happened to put an OpenSSL build first. Pin it, and fall back
/// only if the preferred one is gone.
fn python_bin() -> String {
    if let Ok(p) = std::env::var("CODEXBAR_PYTHON") {
        if !p.is_empty() {
            return p;
        }
    }
    for cand in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"] {
        if std::path::Path::new(cand).exists() {
            return cand.into();
        }
    }
    "python3".into()
}

/// The tray has no native menu any more (a menu forces macOS to open it on right-click, and both
/// buttons must open the popover instead), so this is the ONLY quit path besides ⌘Q. It lives in
/// Settings.
#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

// ---- IPC commands ----

#[tauri::command]
fn read_state() -> Result<Value, String> {
    let path = format!("{}/state.json", store_dir());
    let data = fs::read_to_string(&path).map_err(|e| format!("read state: {}", e))?;
    serde_json::from_str(&data).map_err(|e| format!("parse state: {}", e))
}

#[tauri::command]
async fn run_rotate(app: AppHandle, args: Vec<String>) -> Result<String, String> {
    let store = store_dir();
    if args.first().map_or(true, |c| !ALLOWED_CMDS.contains(&c.as_str())) {
        return Err(format!("disallowed command: {:?}", args.first()));
    }
    let rot = format!("{}/codex-rotate", store);
    let out = tauri::async_runtime::spawn_blocking(move || {
        Command::new(python_bin()).arg(&rot).args(&args).output()
    })
    .await
    .map_err(|e| format!("join: {}", e))?
    .map_err(|e| format!("exec: {}", e))?;
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).to_string();
    let _ = app.emit("state-changed", ());
    refresh_tray(&app);
    if out.status.success() {
        Ok(stdout)
    } else {
        Err(format!("{}\n{}", stdout, stderr))
    }
}

/// 用户在设置页开没开「在程序坞显示」。**策略要按"开关 AND 主窗可见"两个条件合成**,所以得
/// 在 Rust 侧记住这个偏好 —— 它存在前端 localStorage 里,Rust 读不到。
static DOCK_ENABLED: AtomicBool = AtomicBool::new(false);

/// 按当前状态重算激活策略。**唯一改 activation policy 的地方**,别在别处零散调用。
///
/// ★ 规则:Dock 图标 = 用户开了开关 **且** 主窗口正显示着。
/// 关掉主窗只 `hide()` 而不降级策略的话,图标会一直占着程序坞的位置,点它还没反应
/// (macOS 点 Dock 图标发的是 `RunEvent::Reopen`,不处理就等于死图标)——用户 2026-08-09 实测。
#[allow(unused_variables)]
fn apply_activation_policy(app: &AppHandle) {
    #[cfg(target_os = "macos")]
    {
        let main_visible = app
            .get_webview_window("main")
            .and_then(|w| w.is_visible().ok())
            .unwrap_or(false);
        let regular = DOCK_ENABLED.load(Ordering::Relaxed) && main_visible;
        let _ = app.set_activation_policy(if regular {
            tauri::ActivationPolicy::Regular
        } else {
            tauri::ActivationPolicy::Accessory
        });
    }
}

/// 显示/隐藏主窗口。**前端一切显示隐藏主窗的地方都要走这里**,不要直接 `win.hide()` ——
/// 那样绕过了激活策略的同步,程序坞图标就会和窗口状态脱节。
#[tauri::command]
fn set_main_visible(app: AppHandle, show: bool) {
    if let Some(w) = app.get_webview_window("main") {
        if show {
            let _ = w.show();
            let _ = w.set_focus();
        } else {
            let _ = w.hide();
        }
    }
    apply_activation_policy(&app);
}

/// 程序坞(Dock)图标的显示开关。
///
/// ★ `Info.plist` 的 `LSUIElement=true` **保持不变** —— 它决定的是"启动瞬间要不要出现在 Dock",
/// 留 true 才不会在冷启动时闪一下图标。macOS 允许运行期用 `setActivationPolicy(.regular)` 给
/// LSUIElement 应用补上 Dock 图标,所以这条命令能在两种形态间来回切,不需要重启。
///
/// 做成开关而不是直接改成常驻 Dock:纯菜单栏形态是现有行为,砍掉它属于"顺手简化掉已有功能"。
#[tauri::command]
fn set_dock_visible(app: AppHandle, on: bool) {
    DOCK_ENABLED.store(on, Ordering::Relaxed);
    apply_activation_policy(&app);
}

/// 多 AI 流量总览(Claude / Codex / Grok)。
///
/// **刻意不复用 `run_rotate`**:那条通道的白名单守的是账号池命令(switch/probe/remove…),把一个只读
/// `~/.claude`、`~/.codex`、`~/.grok` 的脚本挂进去,等于让同一个白名单同时管两套语义完全不同的东西,
/// 迟早有人往里加错命令。这里自带一份极小的参数白名单。
///
/// 脚本只读本机 CLI 落盘记录,**不碰凭证、不动 state.json、不联网**,所以既不广播 `state-changed`
/// 也不刷托盘标题 —— 那两件事是账号池状态变更的信号,在这里发就是噪音。
/// 扫描互斥锁 + 新鲜度双检。
///
/// ★ 主窗口和菜单栏是**两个独立 webview**,各跑一份 `useTraffic`,谁也不知道对方在干什么。
/// 前端的新鲜度判断只能挡住"对方**已经扫完**"的情况;两边**同时**判定该扫时,会各起一个
/// python 各跑 1.4s(用户 2026-08-11 报的「菜单栏刚刷新,进主界面又刷一次」就是这类)。
/// 这里做经典的双检:拿到锁后**再看一眼快照岁数**,已经新鲜就直接把它返回,不起 python。
static SCAN_LOCK: Mutex<()> = Mutex::new(());
/// 拿到锁后若快照比这个还新,就认为刚有人扫过,直接复用。比前端的窗口略紧一点。
const SCAN_COALESCE_SECS: u64 = 90;

/// 扫描本机还有哪些地方存着 AI 用量(设置页「扫描新数据源」按钮)。
///
/// **刻意与 `run_traffic` 分开**:那条是日常热路径、有互斥锁和新鲜度双检;这条是用户点一次才跑的
/// 全盘体检(实测 ~40s,要走遍 60 多个候选目录)。混进同一个命令会让体检的耗时挂在图表刷新上。
/// 它只读本机文件、不联网、不碰凭证 —— 和 `traffic/scan.py` 同一条安全线。
///
/// ★ 它**只产出报告,不改任何配置**。要不要把新发现接进来,得人去写解析器(见 discover.py 头部)。
#[tauri::command]
async fn run_discover() -> Result<String, String> {
    let script = format!("{}/traffic/discover.py", store_dir());
    let out = tauri::async_runtime::spawn_blocking(move || {
        Command::new(python_bin()).arg(&script).arg("--json").output()
    })
    .await
    .map_err(|e| format!("join: {}", e))?
    .map_err(|e| format!("exec: {}", e))?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&out.stderr).to_string())
    }
}

#[tauri::command]
async fn run_traffic(app: AppHandle, args: Vec<String>) -> Result<String, String> {
    const ALLOWED_FLAGS: &[&str] = &["--days", "--json", "--no-cache"];
    if let Some(bad) = args
        .iter()
        .find(|a| !ALLOWED_FLAGS.contains(&a.as_str()) && a.parse::<u32>().is_err())
    {
        return Err(format!("disallowed arg: {:?}", bad));
    }
    let script = format!("{}/traffic/scan.py", store_dir());
    let forced = args.iter().any(|a| a == "--no-cache");
    let out = tauri::async_runtime::spawn_blocking(move || {
        // 串行化:第二个调用者在这里等第一个扫完
        let _guard = SCAN_LOCK.lock();
        if !forced {
            if let Some(fresh) = fresh_snapshot(SCAN_COALESCE_SECS) {
                return Ok(Err(fresh)); // Err 分支借用来表示"复用快照",不是错误
            }
        }
        Command::new(python_bin())
            .arg(&script)
            .args(&args)
            .output()
            .map(Ok)
    })
    .await
    .map_err(|e| format!("join: {}", e))?
    .map_err(|e: std::io::Error| format!("exec: {}", e))?;
    let out = match out {
        Ok(o) => o,
        Err(cached) => return Ok(cached),
    };
    if out.status.success() {
        // ★ 样式 2(今日消耗)的数字来自这次扫描的结果 —— 扫完不刷托盘,标题会一直停在上一次的值。
        //   其余样式刷一次也无害(只读 state.json)。
        refresh_tray(&app);
        let body = String::from_utf8_lossy(&out.stdout).to_string();
        write_traffic_snapshot(&body);
        Ok(body)
    } else {
        Err(format!(
            "{}\n{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        ))
    }
}

/// 最近一次成功扫描的完整结果。**两个 webview 共用的"立刻能画"的那份数据。**
///
/// 为什么需要它:`scan.py` 的逐文件增量缓存已经把冷启动 18s 压到热路径 ~1s,但那 1s 是
/// **每次进页面都要付**的(读 10MB 缓存 + stat 8500 个文件 + 重新聚合),而菜单栏弹窗是"点一下就要
/// 立刻出来"的东西 —— 交接稿 §5 明写「弹窗只读缓存,不重复解析」。所以在扫描之外再落一份**成品**,
/// 读它就是一次 100KB 的文件读。
const SNAPSHOT: &str = ".traffic-latest.json";

/// 快照若比 `max_age_secs` 还新就返回它,否则 None。用于扫描前的合并判断。
fn fresh_snapshot(max_age_secs: u64) -> Option<String> {
    let body = fs::read_to_string(snapshot_path()).ok()?;
    let v: Value = serde_json::from_str(&body).ok()?;
    let gen = v.get("generated_at")?.as_u64()?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs();
    if now.saturating_sub(gen) <= max_age_secs {
        Some(body)
    } else {
        None
    }
}

fn snapshot_path() -> String {
    format!("{}/{}", store_dir(), SNAPSHOT)
}

/// 原子落盘:先写同目录临时文件再 `rename`。直接覆写会让并发的读者读到半截 JSON —— 主窗口在扫描、
/// 用户同时点开菜单栏,是每天都会发生的时序。
fn write_traffic_snapshot(body: &str) {
    let path = snapshot_path();
    let tmp = format!("{}.tmp{}", path, std::process::id());
    if fs::write(&tmp, body).is_ok() && fs::rename(&tmp, &path).is_err() {
        let _ = fs::remove_file(&tmp);
    }
}

/// 读快照。返回 `null` 表示"还没有任何一次成功扫描",调用方据此显示首扫提示而不是空图。
///
/// 只读、无解析、不起 python。**故意不判断新鲜度** —— 新鲜度是展示层的策略(菜单栏能接受几分钟前的
/// 数字、主窗口进页面就该顺手刷新),放在这里会把两种策略焊死成一种。
#[tauri::command]
fn read_traffic_snapshot() -> Result<Option<String>, String> {
    match fs::read_to_string(snapshot_path()) {
        Ok(s) if !s.trim().is_empty() => Ok(Some(s)),
        Ok(_) => Ok(None),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("read snapshot: {}", e)),
    }
}

/// 查远端最新的 `vX.Y.Z` tag。
///
/// ★ **走 `git ls-remote` 而不是 GitHub Releases API**:这个仓库是私有的,匿名调
/// `/repos/…/releases/latest` 一律返回 404(GitHub 对无权限私仓统一报 404 而非 403,防探测),
/// 所以 API 那条路在当前可见性下**永远查不出结果**。`git ls-remote` 复用本机 git 已有的凭证
/// (keychain / gh auth),对仓库所有者和已接受邀请的协作者都能用;仓库将来转公开也照样能用。
///
/// **只在用户点按钮时才跑**,没有任何定时器 —— 这是本 app 除探针外唯一会主动联网的动作。
#[tauri::command]
async fn check_update() -> Result<String, String> {
    let store = store_dir();
    let out = tauri::async_runtime::spawn_blocking(move || {
        Command::new("git")
            .args(["-C", &store, "ls-remote", "--tags", "--refs", "origin"])
            .output()
    })
    .await
    .map_err(|e| format!("join: {}", e))?
    .map_err(|e| format!("git 起不来: {}", e))?;
    if !out.status.success() {
        return Err(format!(
            "git ls-remote 失败(网络或凭证): {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    // 每行形如 "<sha>\trefs/tags/v0.8.0"。按 (major, minor, patch) 数值比较,
    // **不能按字符串排** —— 那样 v0.10.0 会排在 v0.9.0 前面。
    let mut best: Option<(u32, u32, u32, String)> = None;
    for line in String::from_utf8_lossy(&out.stdout).lines() {
        let Some(tag) = line.rsplit('/').next() else { continue };
        let Some(rest) = tag.strip_prefix('v') else { continue };
        let mut it = rest.split('.');
        let (Some(a), Some(b), Some(c)) = (it.next(), it.next(), it.next()) else { continue };
        let (Ok(a), Ok(b), Ok(c)) = (a.parse::<u32>(), b.parse::<u32>(), c.parse::<u32>()) else {
            continue;
        };
        if best.as_ref().map_or(true, |(x, y, z, _)| (a, b, c) > (*x, *y, *z)) {
            best = Some((a, b, c, tag.to_string()));
        }
    }
    best.map(|(_, _, _, t)| t)
        .ok_or_else(|| "远端没有 vX.Y.Z 形态的 tag".to_string())
}

#[tauri::command]
fn read_auth_tokens() -> Result<Value, String> {
    let state: Value = read_state()?;
    let slots = state["slots"].as_object().ok_or("no slots")?;
    let mut result = serde_json::Map::new();
    for (aid, slot) in slots {
        let file = slot["file"].as_str().unwrap_or("");
        let path = format!("{}/auth/{}", store_dir(), file);
        if let Ok(data) = fs::read_to_string(&path) {
            if let Ok(auth) = serde_json::from_str::<Value>(&data) {
                if let Some(tokens) = auth.get("tokens") {
                    let mut info = serde_json::Map::new();
                    if let Some(at) = tokens["access_token"].as_str() {
                        if let Some(payload) = at.split('.').nth(1) {
                            let padded =
                                format!("{}{}", payload, "=".repeat((4 - payload.len() % 4) % 4));
                            if let Ok(decoded) = b64_decode(&padded) {
                                if let Ok(claims) = serde_json::from_slice::<Value>(&decoded) {
                                    if let Some(exp) = claims["exp"].as_f64() {
                                        info.insert("exp".into(), Value::from(exp));
                                    }
                                }
                            }
                        }
                    }
                    result.insert(aid.clone(), Value::Object(info));
                }
            }
        }
    }
    Ok(Value::Object(result))
}

fn b64_decode(input: &str) -> Result<Vec<u8>, String> {
    let std_b64: String = input
        .chars()
        .map(|c| match c {
            '-' => '+',
            '_' => '/',
            c => c,
        })
        .collect();
    let alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut buf = Vec::new();
    let mut acc: u32 = 0;
    let mut bits = 0;
    for c in std_b64.bytes() {
        if c == b'=' {
            break;
        }
        let val = alphabet
            .iter()
            .position(|&b| b == c)
            .ok_or("bad b64")? as u32;
        acc = (acc << 6) | val;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            buf.push((acc >> bits) as u8);
            acc &= (1 << bits) - 1;
        }
    }
    Ok(buf)
}

// ---- read logs for the UI ----

#[tauri::command]
fn read_logs() -> Result<String, String> {
    let mut lines = Vec::new();
    for name in ["keepalive.log", "refreshquota.log", "proxy/proxy.log", "quotad.log"] {
        let path = format!("{}/{}", store_dir(), name);
        if let Ok(data) = fs::read_to_string(&path) {
            for line in data.lines().rev().take(100) {
                if !line.trim().is_empty() {
                    lines.push(line.to_string());
                }
            }
        }
    }
    lines.truncate(300);
    Ok(lines.join("\n"))
}

// ---- read single account auth detail ----

#[tauri::command]
fn read_account_detail(aid: String) -> Result<Value, String> {
    let state: Value = read_state()?;
    let slot = state["slots"].get(&aid).ok_or("account not found")?;
    let file = slot["file"].as_str().unwrap_or("");
    let path = format!("{}/auth/{}", store_dir(), file);
    let data = fs::read_to_string(&path).map_err(|e| format!("read: {}", e))?;
    let auth: Value = serde_json::from_str(&data).map_err(|e| format!("parse: {}", e))?;
    let tokens = auth.get("tokens").cloned().unwrap_or(Value::Null);

    let mut detail = serde_json::Map::new();
    detail.insert("account_id".into(), tokens["account_id"].clone());
    detail.insert("email".into(), Value::from(slot["email"].as_str().unwrap_or("")));
    detail.insert("label".into(), Value::from(slot["label"].as_str().unwrap_or("")));
    detail.insert("plan".into(), Value::from(slot["plan"].as_str().unwrap_or("")));
    detail.insert("sub_until".into(), Value::from(slot["sub_until"].as_str().unwrap_or("")));
    // OpenAI 上次复核订阅的时刻。到期日只是那次复核的快照,续费后不会随新 token 更新 ——
    // 摆出复核时间,「为什么显示已过期」才有据可查,不必再逐个解 JWT。
    detail.insert("sub_checked".into(), Value::from(slot["sub_checked"].as_str().unwrap_or("")));
    detail.insert("last_refresh".into(), Value::from(auth["last_refresh"].as_str().unwrap_or("")));
    detail.insert("auth_dead".into(), Value::from(slot["auth_dead"].as_bool().unwrap_or(false)));
    detail.insert("file".into(), Value::from(file));

    // token fingerprints (last 8 chars) — never expose full tokens
    if let Some(at) = tokens["access_token"].as_str() {
        let len = at.len();
        detail.insert("access_token_tail".into(), Value::from(if len > 8 { &at[len-8..] } else { at }));
        detail.insert("access_token_len".into(), Value::from(len));
        // decode exp
        if let Some(payload) = at.split('.').nth(1) {
            let padded = format!("{}{}", payload, "=".repeat((4 - payload.len() % 4) % 4));
            if let Ok(decoded) = b64_decode(&padded) {
                if let Ok(claims) = serde_json::from_slice::<Value>(&decoded) {
                    if let Some(exp) = claims["exp"].as_f64() { detail.insert("access_exp".into(), Value::from(exp)); }
                    if let Some(iat) = claims["iat"].as_f64() { detail.insert("access_iat".into(), Value::from(iat)); }
                }
            }
        }
    }
    if let Some(rt) = tokens["refresh_token"].as_str() {
        let len = rt.len();
        detail.insert("refresh_token_tail".into(), Value::from(if len > 8 { &rt[len-8..] } else { rt }));
        detail.insert("refresh_token_len".into(), Value::from(len));
    }
    if let Some(id) = tokens["id_token"].as_str() {
        detail.insert("id_token_len".into(), Value::from(id.len()));
    }

    // quota snapshot
    if let Some(q) = slot.get("quota") {
        detail.insert("quota_source".into(), q["source"].clone());
        detail.insert("quota_captured_at".into(), q["captured_at"].clone());
    }

    Ok(Value::Object(detail))
}

// ---- tray title from state.json ----

/// 菜单栏标题样式(用户 2026-08-12 从 demo 里选)。**索引与前端 `TRAY_STYLES` 数组一一对应**。
/// 0 完整 `pro1 周 67% ↻5d21h` · 1 简 `pro1 67%` · 2 极简 `67%` · 3 今日 `67% 🔹 1.29B`
static TRAY_STYLE: AtomicU8 = AtomicU8::new(0);

/// ★★ 给菜单栏标题的**百分比那一段**上色。
///
/// macOS 本身完全支持(`NSStatusItem.button.attributedTitle` + `NSForegroundColorAttributeName`),
/// 是 **Tauri 没把接口透出来**:`TrayIcon::set_title` 只收 `AsRef<str>`,而 `TrayIcon.inner`
/// (真正的 `tray_icon::TrayIcon`,它有 public 的 `ns_status_item()`)是私有字段、无 Deref、
/// 无访问器 —— 已核 tauri 2.11.3 的 `src/tray/mod.rs:398`。
///
/// 所以绕道:状态栏按钮就在**本进程**的 `NSApp.windows` 里(NSStatusBarWindow 的 contentView),
/// 遍历找到那个 `NSStatusBarButton` 直接设 attributedTitle。只在自己进程里找,不碰别的 app。
///
/// ★ **fail-open**:找不到按钮就什么都不做,Tauri 那句纯文本标题仍然在,只是没颜色。
/// 宁可掉色,不可让菜单栏空掉 —— 这是 macOS 版本升级时最可能坏的一块。
/// 必须在主线程调用(AppKit 硬性要求),调用方用 `run_on_main_thread` 包一层。
#[cfg(target_os = "macos")]
fn paint_tray_title(title: &str, hi: Option<(std::ops::Range<usize>, (f64, f64, f64))>) {
    use objc2::rc::{Allocated, Retained};
    use objc2::{AnyThread, Message};
    use objc2_app_kit::{NSApplication, NSButton, NSColor, NSFont};
    use objc2_foundation::{NSMutableAttributedString, NSRange, NSString};
    let _ = std::marker::PhantomData::<Allocated<NSMutableAttributedString>>;
    let Some(mtm) = objc2_foundation::MainThreadMarker::new() else { return };
    let app = NSApplication::sharedApplication(mtm);

    // 找本进程的状态栏按钮。NSStatusBarWindow 是私有类,所以按**类名**认而不是 downcast。
    fn find_button(v: &objc2_app_kit::NSView) -> Option<Retained<NSButton>> {
        if let Some(b) = v.downcast_ref::<NSButton>() {
            return Some(b.retain());
        }
        for sub in v.subviews().iter() {
            if let Some(b) = find_button(&sub) {
                return Some(b);
            }
        }
        None
    }
    let mut btn: Option<Retained<NSButton>> = None;
    for w in app.windows().iter() {
        let cls = w.class().name().to_string_lossy().to_string();
        if !cls.contains("StatusBar") {
            continue;
        }
        if let Some(v) = unsafe { w.contentView() } {
            if let Some(b) = find_button(&v) {
                btn = Some(b);
                break;
            }
        }
    }
    let Some(btn) = btn else { return };            // fail-open

    let ns = NSString::from_str(title);
    let attr = unsafe { NSMutableAttributedString::initWithString(NSMutableAttributedString::alloc(), &ns) };
    // 字号跟随菜单栏:不写死,否则系统调整菜单栏字号时会和别的项对不齐
    let font = unsafe { NSFont::menuBarFontOfSize(0.0) };
    let full = NSRange::new(0, ns.length());
    unsafe {
        attr.addAttribute_value_range(objc2_app_kit::NSFontAttributeName, &*font, full);
        // 基线色:用 labelColor,它**自动跟随菜单栏明暗**(深色栏白、浅色栏黑)。
        // 写死白色会让浅色模式下整条标题看不见 —— 这正是模板图那套机制要解决的问题。
        attr.addAttribute_value_range(
            objc2_app_kit::NSForegroundColorAttributeName,
            &*NSColor::labelColor(),
            full,
        );
        if let Some((r, (cr, cg, cb))) = hi {
            // NSRange 用的是 UTF-16 单位,而 Rust 的 range 是字节。标题里可能有中文和 emoji,
            // 直接拿字节偏移当 UTF-16 偏移会**染错位置**,所以现算。
            let pre_u16 = title[..r.start].encode_utf16().count();
            let len_u16 = title[r.clone()].encode_utf16().count();
            if pre_u16 + len_u16 <= ns.length() {
                let r = NSRange::new(pre_u16, len_u16);
                let color = NSColor::colorWithSRGBRed_green_blue_alpha(cr, cg, cb, 1.0);
                attr.addAttribute_value_range(
                    objc2_app_kit::NSForegroundColorAttributeName, &*color, r);
                // ★ 只给百分比加粗(用户 2026-08-12)。字号取**菜单栏字体的实际 pointSize**,
                //   不写死 —— 系统调整菜单栏字号时,粗体那段才不会和周围文字错位。
                let bold = NSFont::boldSystemFontOfSize(font.pointSize());
                attr.addAttribute_value_range(
                    objc2_app_kit::NSFontAttributeName, &*bold, r);
            }
        }
        // NSMutableAttributedString Deref 到 NSAttributedString,直接传引用即可
        btn.setAttributedTitle(&attr);
    }
}

#[tauri::command]
fn set_tray_style(app: AppHandle, style: u8) {
    TRAY_STYLE.store(style.min(3), Ordering::Relaxed);
    refresh_tray(&app);
}

/// 今日全平台 token 合计,给样式 2 用。
///
/// ★ 读快照的 `hours` 而不是 `days[今天]`:`hours` **按定义只覆盖今天**(scan.py 从 00 点补到当前
/// 小时),所以求和即今日总量 —— 省掉在 Rust 里做本地日期算术。本 crate 没有 chrono,手算
/// localtime 在 DST / 半小时时区上很容易错,而那种错会静默算到别的日子上去。
fn today_tokens() -> Option<u64> {
    let path = format!("{}/.traffic-latest.json", store_dir());
    let data = fs::read_to_string(&path).ok()?;
    let v: Value = serde_json::from_str(&data).ok()?;
    let mut sum = 0u64;
    for p in v["platforms"].as_object()?.values() {
        if let Some(hours) = p["hours"].as_object() {
            for b in hours.values() {
                sum += b["total"].as_u64().unwrap_or(0);
            }
        }
    }
    Some(sum)
}

fn fmt_tok(n: u64) -> String {
    let f = n as f64;
    if f >= 1e9 { format!("{:.2}B", f / 1e9) }
    else if f >= 1e6 { format!("{:.0}M", f / 1e6) }
    else if f >= 1e3 { format!("{:.1}K", f / 1e3) }
    else { n.to_string() }
}

/// 阈值 → RGB。沿用仓库既有那条(handoff §5.1.5:剩余 <50% 琥珀、否则绿),
/// 只把「耗尽」单独标红 —— 0 是天然边界,不是新发明的阈值。
fn rem_rgb(rem: u32) -> (f64, f64, f64) {
    if rem == 0 { (0.878, 0.322, 0.302) }        // #E0524D 红
    else if rem < 50 { (0.878, 0.565, 0.110) }   // #E0901C 琥珀
    else { (0.153, 0.698, 0.420) }               // #27B26B 绿
}

/// 设标题 + 给百分比那段上色。**所有刷托盘的地方都走这里**,别再直接 `tray.set_title` ——
/// 只设纯文本的话颜色不会更新,标题变了色还停在上一次的阈值上。
fn refresh_tray(app: &AppHandle) {
    let title = format_tray_title();
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_title(Some(&title));
    }
    #[cfg(target_os = "macos")]
    {
        // 百分比那一段:直接在标题里找 `NN%`。四档样式里它的位置都不同,find 比各档各算一遍稳。
        let hi = ACTIVE_REM.load(Ordering::Relaxed);
        let hi = if hi <= 100 {
            let pat = format!("{}%", hi);
            title.find(&pat).map(|i| (i..i + pat.len(), rem_rgb(hi)))
        } else { None };
        let t2 = title.clone();
        // AppKit 只能在主线程碰
        let _ = app.run_on_main_thread(move || paint_tray_title(&t2, hi));
    }
}

/// 当前号余量,给上色用。`u32::MAX` = 未知(不上色)。
static ACTIVE_REM: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(u32::MAX);

fn format_tray_title() -> String {
    let path = format!("{}/state.json", store_dir());
    let Ok(data) = fs::read_to_string(&path) else {
        return "codex".into();
    };
    let Ok(state) = serde_json::from_str::<Value>(&data) else {
        return "codex".into();
    };
    let active = state["active"].as_str().unwrap_or("");
    let slots = state["slots"].as_object();
    if let Some(slots) = slots {
        // Dead accounts other than the active one used to be invisible here: the title only showed ✗ when
        // the ACTIVE account died, so a node could quietly go dead and nothing on screen said so. Surface
        // the count so a revoked token is noticeable without opening the app.
        // ★ `✗N` 失效角标已按用户 2026-08-12 的要求去掉(三种样式都不带)。
        //   代价明说:非当前号悄悄失效时,菜单栏**不再有持续可见的信号**,只剩 `useDeadWatch`
        //   的系统通知(弹一次就过去)。当初加它正是为了解决"死号在界面上完全不出现"。
        let dead_n = slots.values().filter(|s| s["auth_dead"].as_bool().unwrap_or(false)).count();
        let dead_tag = String::new();
        let _ = dead_n;
        if let Some(slot) = slots.get(active) {
            let label = slot["label"].as_str().unwrap_or("?");
            let dead = slot["auth_dead"].as_bool().unwrap_or(false);
            if dead {
                return format!("✗ {} 失效", label);
            }
            if let Some(q) = slot.get("quota") {
                // Codex retired 5h; only weekly(10080)/monthly(43200) are real. Pick the first
                // real window (primary then secondary); phantom slots (wm<5000) are ignored.
                let win = ["primary", "secondary"].iter().find_map(|k| {
                    let w = &q[*k];
                    let wm = w["window_minutes"].as_f64().unwrap_or(0.0);
                    if wm >= 5000.0 && w["used_percent"].is_number() { Some(w) } else { None }
                });
                let Some(w) = win else {
                    // 额度未知:**不编数字**,也不上色(那是对余量的判断,没余量就没得判),
                    // 按档位退成 "—"(与仓库那条老规矩一致)
                    ACTIVE_REM.store(u32::MAX, Ordering::Relaxed);
                    return match TRAY_STYLE.load(Ordering::Relaxed) {
                        1 => format!("{} —", label),
                        2 => "—".into(),
                        3 => format!("— 🔹 {}", today_tokens().map(fmt_tok).unwrap_or_else(|| "—".into())),
                        _ => format!("{} —", label),
                    };
                };
                let used = w["used_percent"].as_f64().unwrap_or(0.0);
                let wm = w["window_minutes"].as_f64().unwrap_or(0.0);
                let win_tag = if wm >= 40000.0 { "月" } else { "周" };
                let now_ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs_f64();
                let ra = w["resets_at"].as_f64().unwrap_or(0.0);
                let rem = if ra > 0.0 && ra <= now_ts { 100 } else { (100.0 - used).max(0.0) as u32 };
                let eta = if ra > 0.0 && ra > now_ts {
                    let secs = (ra - now_ts) as u64;
                    let h = secs / 3600;
                    let m = (secs % 3600) / 60;
                    if h >= 24 { format!(" ↻{}d{}h", h / 24, h % 24) } else if h > 0 { format!(" ↻{}h{:02}m", h, m) } else { format!(" ↻{}m", m) }
                } else { String::new() };
                // ★ 三档样式(用户从 demo 里选的)。分隔符 🔹 也是选的 —— 已知它是彩色位图、
                //   不跟随菜单栏明暗(左边的 tray.png 是模板图会跟随),浅色模式下会显出差异。
                let today = today_tokens().map(fmt_tok);
                //   ★ 三档都带 `%`(用户 2026-08-12 定):裸数字在极简档下语义全压在颜色上,
                //     色觉障碍时「67 是好是坏」看不出来;加个 % 只多 ~12px 就补上了。
                ACTIVE_REM.store(rem, Ordering::Relaxed);
                return match TRAY_STYLE.load(Ordering::Relaxed) {
                    1 => format!("{} {}%{}", label, rem, dead_tag),
                    2 => format!("{}%{}", rem, dead_tag),
                    3 => format!("{}% 🔹 {}{}", rem,
                                 today.unwrap_or_else(|| "—".into()), dead_tag),
                    _ => format!("{} {} {}%{}{}", label, win_tag, rem, eta, dead_tag),
                };
            }
            return format!("{}{}", label, dead_tag);
        }
    }
    "codex".into()
}

// ---- toggle menubar popover ----

fn toggle_menubar(app: &AppHandle, tray_rect: Option<tauri::Rect>) {
    if let Some(win) = app.get_webview_window("menubar") {
        if win.is_visible().unwrap_or(false) {
            let _ = win.hide();
        } else {
            if let Some(rect) = tray_rect {
                let (px, py) = match rect.position {
                    tauri::Position::Physical(p) => (p.x as f64, p.y as f64),
                    tauri::Position::Logical(p) => (p.x, p.y),
                };
                let (sw, sh) = match rect.size {
                    tauri::Size::Physical(s) => (s.width as f64, s.height as f64),
                    tauri::Size::Logical(s) => (s.width, s.height),
                };
                let panel_w = 352.0; // must match inner_size width（守卫见 tests/test_menubar_width_sync.py）
                let x = px + sw / 2.0 - panel_w / 2.0;
                let y = py + sh + 4.0;
                let _ = win.set_position(PhysicalPosition::new(x as i32, y as i32));
            }
            let _ = win.show();
            let _ = win.set_focus();
            // ★ 弹窗**只在启动时挂载一次**(show/hide 不重建 webview),所以前端的"首次取数"守卫
            //   之后再也不会触发 —— 不给这个信号,今日 Tab 的数字会冻在开机那一刻。
            //   收到后前端按新鲜度自行决定要不要重扫(见 `useTraffic.refreshIfStale`)。
            let _ = win.emit("menubar-shown", ());
        }
    }
}

// ---- 单实例闸门 ----

/// 抢占单实例锁。**拿不到就说明已经有一个 CodexBar 在跑,本进程必须立刻退出。**
///
/// 用户 2026-08-11 报「死机重启后会打开两个 CodexBar」。根因是**两条启动路径在开机时并发**:
/// ① `~/Library/LaunchAgents/CodexBar.plist`(autostart 插件建的,`RunAtLoad` + 直接 exec
///    `…/Contents/MacOS/codexbar` **裸二进制**);② macOS 脏关机后由 LaunchServices 恢复。
/// 平时手点复现不出来:实测 app 已在跑时 `open -a CodexBar` 会正确去重、只发 `Reopen`。
/// 但**那个去重要求第一个进程已在 LaunchServices 注册完毕**;开机时两条路并发,裸二进制还没注册完,
/// 恢复那条 `open` 就已经发出去了 —— 去重不是原子的,于是漏过。修法只能落在 app 自己身上。
///
/// ★★ **为什么是 `flock` 而不是 `tauri-plugin-single-instance`**(2026-08-11 换掉,别换回去):
/// 那个插件的闸门**本身就有竞态**,而竞态恰恰是本 bug 的触发条件 —— 它的逻辑是
/// `connect 失败 → socket_cleanup() 删文件 → spawn 异步任务里再 bind`。两个进程同时启动时,
/// B 的 connect 会早于 A 的 bind,于是 B 也走进这个分支,**B 的 cleanup 把 A 刚建的 socket 删掉**,
/// 两边各自 bind、各自存活。用它 GUI 压测「通过」只是没撞进那个窗口,不是没有窗口。
///
/// `flock(LOCK_EX | LOCK_NB)` 是内核级原子操作:两个进程同时抢,**保证恰好一个拿到**,
/// 不存在检查与获取之间的窗口。崩溃安全也更好 —— 锁随 fd 关闭由内核释放,进程被 `kill -9`、
/// panic、断电重启后都不会留下陈旧锁,**不可能出现"一个都起不来"**(那会比原 bug 更糟)。
///
/// 锁文件放在 app 数据目录而不是 `/tmp`:`/tmp` 会被系统清理,文件一旦在持锁期间被删,
/// 新进程会在**另一个 inode** 上建文件并成功加锁,两个又都活了。
///
/// `Acquired` 里的 `File` 必须由调用方持有到进程结束 —— 一旦 drop,fd 关闭,锁就没了。
#[cfg(unix)]
enum InstanceLock {
    /// 拿到锁,本进程是唯一实例。
    Acquired(std::fs::File),
    /// **确定**另一个实例正持锁(`flock` 返回 `EWOULDBLOCK`)—— 本进程必须退出。
    HeldByOther,
    /// ★ **判定不了**:锁文件打不开(HOME 缺失/目录建不了/磁盘满/权限异常),或该文件系统
    /// 不支持 `flock`(部分网络卷会返回 `ENOTSUP`/`EINVAL`/`ENOLCK`)。
    ///
    /// 这一档**必须按"正常启动"处理(fail-open)**,不能和 `HeldByOther` 合并成一个值 ——
    /// 合并的话,一次打不开锁文件就会让 app **一个都起不来**,比"多开一个"糟得多,
    /// 而且症状是静默的(没有窗口、没有托盘、没有报错),几乎无法诊断。
    /// 这是仓库那条铁律的同一形态:「这一枪没打中」绝不能和「确实没有」返回同一个值。
    Undetermined,
}

#[cfg(unix)]
fn acquire_single_instance_lock() -> InstanceLock {
    use std::os::unix::io::AsRawFd;
    let Ok(home) = std::env::var("HOME") else {
        return InstanceLock::Undetermined;
    };
    let dir = format!("{}/Library/Application Support/com.doushutangmu.codexbar", home);
    let _ = fs::create_dir_all(&dir);
    let Ok(f) = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(format!("{}/single-instance.lock", dir))
    else {
        return InstanceLock::Undetermined;
    };
    // SAFETY: fd 来自上面刚打开、仍然存活的 File,flock 对它只做加锁不做别的。
    if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
        return InstanceLock::Acquired(f);
    }
    // ★ **只有 `EWOULDBLOCK` 才代表"另一个实例拿着锁"**。别的 errno 是"这个文件系统上
    //   flock 用不了",按判定不了处理 —— 否则在不支持 flock 的卷上每次启动都会被自己挡死。
    match std::io::Error::last_os_error().raw_os_error() {
        Some(e) if e == libc::EWOULDBLOCK => InstanceLock::HeldByOther,
        _ => InstanceLock::Undetermined,
    }
}

// ---- app entry ----

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // ★ 必须在 `tauri::Builder` **之前**:晚一步就会先把托盘和两个 webview 建出来再退出,
    //   开机瞬间照样闪两个图标。`_lock` 要一直活到进程结束,所以绑在这里而不是 `let _ =`。
    #[cfg(unix)]
    let _lock = match acquire_single_instance_lock() {
        // 已经有一个在跑。**静默退出,不弹主窗口** —— 能走到这里的现实路径只有上面那个开机竞态,
        // 在那个时刻弹窗会破坏「主窗关着就不占程序坞」这条已定稿的行为。用户想要主窗口时的入口
        // 已经有两个:菜单栏,以及点程序坞图标发的 `RunEvent::Reopen`(见文件末尾)。
        InstanceLock::HeldByOther => return,
        // `Acquired` 要持有到进程结束;`Undetermined` 一律照常启动(fail-open,理由见枚举注释)。
        held => held,
    };

    tauri::Builder::default()
        // ★ 主窗口的尺寸/位置持久化。用户 2026-08-09:"我调整了高度适配内容,每次更新都要再调一遍"。
        //   根因是尺寸写死在 tauri.conf.json + `center: true`,每次启动都回到 1000×660。
        //   其余偏好(主题/打码/Dock/菜单栏 Tab/自动切号)在 localStorage,数据在 app bundle **之外**,
        //   deploy.sh 只换 bundle,所以那些本来就跨更新存活 —— 唯独窗口几何在 Rust 侧,需要这个插件。
        //
        //   三个刻意的取舍:
        //   - **不含 `VISIBLE`**:主窗口是故意以隐藏态创建的(菜单栏优先),恢复可见性会让它每次开机弹出来。
        //   - **不含 `DECORATIONS`**:我们用自绘标题栏(`decorations: false`),恢复它可能把原生边框加回来。
        //   - **denylist 掉 `menubar`**:弹窗的高度由 ResizeObserver 按内容算、位置每次按托盘图标定位,
        //     恢复上次几何会同时和这两件事打架,把弹窗放到错误的位置。
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::SIZE
                        | tauri_plugin_window_state::StateFlags::POSITION,
                )
                .with_denylist(&["menubar"])
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .setup(|app| {
            // Hide from Dock — LSUIElement alone isn't reliable with Tauri
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            let handle = app.handle();

            // ---- create menubar popover window (hidden by default) ----
            let _menubar = WebviewWindowBuilder::new(
                handle,
                "menubar",
                WebviewUrl::App("menubar.html".into()),
            )
            .title("CodexBar")
            .inner_size(352.0, 580.0)
            .decorations(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .visible(false)
            .resizable(false)
            .build()?;

            // hide menubar on blur (click outside)
            let handle_blur = handle.clone();
            _menubar.on_window_event(move |event| {
                if let tauri::WindowEvent::Focused(false) = event {
                    if let Some(w) = handle_blur.get_webview_window("menubar") {
                        let _ = w.hide();
                    }
                }
            });

            // ---- tray icon ----
            let tray_bytes = include_bytes!("../icons/tray.png");
            let tray_icon = tauri::image::Image::from_bytes(tray_bytes)?;

            // ★ NO native menu is attached. On macOS a tray icon with a menu ALWAYS opens that menu on
            // right-click — there is no per-button opt-out — so the only way to make both buttons show
            // our own popover is to have no menu at all. The actions that lived there moved: 打开主窗口
            // = click any account row, 刷新全池/检查 token = popover footer, 退出 = Settings (quit_app).
            let _tray = TrayIconBuilder::with_id("main")
                .icon(tray_icon)
                .icon_as_template(true)
                .title(format_tray_title())
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left | MouseButton::Right,
                        button_state: MouseButtonState::Up,
                        rect,
                        ..
                    } = event
                    {
                        toggle_menubar(tray.app_handle(), Some(rect));
                    }
                })
                .build(app)?;

            // ---- startup: refresh every account from the official usage API (GET, zero quota) ----
            // Safe to run on every launch/login again: refresh-all no longer sends a billed
            // POST /codex/responses — it reads GET /backend-api/codex/usage, which costs no quota.
            let store_startup = store_dir();
            let handle_startup = handle.clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_secs(3)).await;
                let rot = format!("{}/codex-rotate", store_startup);
                let _ = tokio::task::spawn_blocking(move || {
                    // refresh-all brings back the free credit COUNTS; `credits` then fills in the
                    // expiry dates the banner needs. It self-limits — it only hits the rate-limited
                    // detail endpoint when an account actually holds cards and the 12h cache is
                    // stale — so running it on every launch costs nothing on a warm cache.
                    let c = std::process::Command::new(python_bin()).arg(&rot).arg("refresh-all").output();
                    let _ = std::process::Command::new(python_bin()).arg(&rot).arg("credits").output();
                    c
                }).await;
                let _ = handle_startup.emit("state-changed", ());
                refresh_tray(&handle_startup);
            });

            // ---- state.json watcher: push, don't poll ----
            // quotad writes state.json from ANOTHER process, so the UI had no way to learn about it and
            // sat on its own 30s poll — stacking up to 30s of lag on top of the daemon's. Watching the
            // file's mtime/len costs one stat per second and turns that into "visible within ~1s".
            // Deliberately a stat loop rather than the `notify` crate: one dependency-free stat on a
            // single known path, and an fsevents subscription would still need this fallback anyway.
            // The 30s branch stays as the tray-title floor (the countdown text ages even when the file
            // does not change).
            let handle_timer = handle.clone();
            tauri::async_runtime::spawn(async move {
                let path = format!("{}/state.json", store_dir());
                let mut seen: Option<(std::time::SystemTime, u64)> = None;
                let mut since_tick = 0u32;
                loop {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    since_tick += 1;

                    let stamp = fs::metadata(&path)
                        .ok()
                        .and_then(|m| m.modified().ok().map(|t| (t, m.len())));
                    // `seen.is_some()` guards the first observation: without it a cold start would fire
                    // a spurious state-changed before the UI has even read anything.
                    let changed = stamp.is_some() && seen.is_some() && stamp != seen;
                    if stamp.is_some() {
                        seen = stamp;
                    }

                    if changed || since_tick >= 30 {
                        since_tick = 0;
                        if changed {
                            let _ = handle_timer.emit("state-changed", ());
                        }
                        refresh_tray(&handle_timer);
                    }
                }
            });

            // ---- main window: show on launch, intercept close → hide ----
            if let Some(w) = handle.get_webview_window("main") {
                let _ = w.show();
                let _ = w.center();
                let handle_close = handle.clone();
                w.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        if let Some(win) = handle_close.get_webview_window("main") {
                            let _ = win.hide();
                        }
                        // 关窗必须让出程序坞的位置,否则图标一直占着还点不出窗口
                        apply_activation_policy(&handle_close);
                    }
                });
            }

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            read_state,
            run_rotate,
            run_traffic,
            run_discover,
            set_tray_style,
            read_traffic_snapshot,
            check_update,
            set_dock_visible,
            set_main_visible,
            read_auth_tokens,
            read_logs,
            read_account_detail,
            quit_app
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // ★ macOS 点程序坞图标发的是 `Reopen`,不处理 = 死图标(点了没反应)。
            //   这里把主窗唤回来 —— 图标存在的时刻正是主窗开着的时刻,所以这条覆盖的是
            //   "⌘Tab 切走后又点回来"这种场景。
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = event {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
                apply_activation_policy(app);
            }
            if let tauri::RunEvent::ExitRequested { code, api, .. } = event {
                if code.is_none() {
                    api.prevent_exit();
                    if let Some(w) = app.get_webview_window("main") {
                        let _ = w.hide();
                    }
                    apply_activation_policy(app);
                }
            }
        });
}
