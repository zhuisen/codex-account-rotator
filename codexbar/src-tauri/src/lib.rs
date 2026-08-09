use serde_json::Value;
use std::fs;
use std::process::Command;
use std::time::Duration;
use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    webview::WebviewWindowBuilder,
    AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl,
};

fn store_dir() -> String {
    std::env::var("CODEXBAR_STORE").unwrap_or_else(|_| {
        let home = std::env::var("HOME").unwrap_or_default();
        format!("{}/Projects/tools/codex-account-rotator", home)
    })
}

const ALLOWED_CMDS: &[&str] = &["switch", "cool", "uncool", "refresh-all", "health", "list", "quota", "remove", "credits", "probe", "tokens"];

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
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_title(Some(&format_tray_title()));
    }
    if out.status.success() {
        Ok(stdout)
    } else {
        Err(format!("{}\n{}", stdout, stderr))
    }
}

/// 程序坞(Dock)图标的显示开关。
///
/// ★ `Info.plist` 的 `LSUIElement=true` **保持不变** —— 它决定的是"启动瞬间要不要出现在 Dock",
/// 留 true 才不会在冷启动时闪一下图标。macOS 允许运行期用 `setActivationPolicy(.regular)` 给
/// LSUIElement 应用补上 Dock 图标,所以这条命令能在两种形态间来回切,不需要重启。
///
/// 做成开关而不是直接改成常驻 Dock:纯菜单栏形态是现有行为,砍掉它属于"顺手简化掉已有功能"。
#[tauri::command]
#[allow(unused_variables)]
fn set_dock_visible(app: AppHandle, on: bool) {
    #[cfg(target_os = "macos")]
    {
        let _ = app.set_activation_policy(if on {
            tauri::ActivationPolicy::Regular
        } else {
            tauri::ActivationPolicy::Accessory
        });
    }
}

/// 多 AI 流量总览(Claude / Codex / Grok)。
///
/// **刻意不复用 `run_rotate`**:那条通道的白名单守的是账号池命令(switch/probe/remove…),把一个只读
/// `~/.claude`、`~/.codex`、`~/.grok` 的脚本挂进去,等于让同一个白名单同时管两套语义完全不同的东西,
/// 迟早有人往里加错命令。这里自带一份极小的参数白名单。
///
/// 脚本只读本机 CLI 落盘记录,**不碰凭证、不动 state.json、不联网**,所以既不广播 `state-changed`
/// 也不刷托盘标题 —— 那两件事是账号池状态变更的信号,在这里发就是噪音。
#[tauri::command]
async fn run_traffic(args: Vec<String>) -> Result<String, String> {
    const ALLOWED_FLAGS: &[&str] = &["--days", "--json", "--no-cache"];
    if let Some(bad) = args
        .iter()
        .find(|a| !ALLOWED_FLAGS.contains(&a.as_str()) && a.parse::<u32>().is_err())
    {
        return Err(format!("disallowed arg: {:?}", bad));
    }
    let script = format!("{}/traffic/scan.py", store_dir());
    let out = tauri::async_runtime::spawn_blocking(move || {
        Command::new(python_bin()).arg(&script).args(&args).output()
    })
    .await
    .map_err(|e| format!("join: {}", e))?
    .map_err(|e| format!("exec: {}", e))?;
    if out.status.success() {
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
        let dead_n = slots.values().filter(|s| s["auth_dead"].as_bool().unwrap_or(false)).count();
        let dead_tag = if dead_n > 0 { format!(" ✗{}", dead_n) } else { String::new() };
        if let Some(slot) = slots.get(active) {
            let label = slot["label"].as_str().unwrap_or("?");
            let dead = slot["auth_dead"].as_bool().unwrap_or(false);
            if dead {
                // dead_n includes the active account here, so it is the true total (≥1).
                return format!("✗ {} 失效{}", label, if dead_n > 1 { format!(" ✗{}", dead_n) } else { String::new() });
            }
            if let Some(q) = slot.get("quota") {
                // Codex retired 5h; only weekly(10080)/monthly(43200) are real. Pick the first
                // real window (primary then secondary); phantom slots (wm<5000) are ignored.
                let win = ["primary", "secondary"].iter().find_map(|k| {
                    let w = &q[*k];
                    let wm = w["window_minutes"].as_f64().unwrap_or(0.0);
                    if wm >= 5000.0 && w["used_percent"].is_number() { Some(w) } else { None }
                });
                let Some(w) = win else { return format!("{}{}", label, dead_tag); };
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
                return format!("{} {} {}%{}{}", label, win_tag, rem, eta, dead_tag);
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
                let panel_w = 412.0; // must match inner_size width
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

// ---- app entry ----

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
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
            .inner_size(412.0, 580.0)
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
                if let Some(tray) = handle_startup.tray_by_id("main") {
                    let _ = tray.set_title(Some(&format_tray_title()));
                }
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
                        if let Some(tray) = handle_timer.tray_by_id("main") {
                            let _ = tray.set_title(Some(&format_tray_title()));
                        }
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
            read_traffic_snapshot,
            set_dock_visible,
            read_auth_tokens,
            read_logs,
            read_account_detail,
            quit_app
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { code, api, .. } = event {
                if code.is_none() {
                    api.prevent_exit();
                    if let Some(w) = app.get_webview_window("main") {
                        let _ = w.hide();
                    }
                }
            }
        });
}
