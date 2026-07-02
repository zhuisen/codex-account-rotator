use serde_json::Value;
use std::fs;
use std::process::Command;
use std::time::Duration;
use tauri::{
    menu::{Menu, MenuItem},
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

const ALLOWED_CMDS: &[&str] = &["switch", "cool", "uncool", "refresh-all", "health", "list", "quota", "refresh-all"];

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
        Command::new("python3").arg(&rot).args(&args).output()
    })
    .await
    .map_err(|e| format!("join: {}", e))?
    .map_err(|e| format!("exec: {}", e))?;
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).to_string();
    let _ = app.emit("state-changed", ());
    if out.status.success() {
        Ok(stdout)
    } else {
        Err(format!("{}\n{}", stdout, stderr))
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
        if let Some(slot) = slots.get(active) {
            let label = slot["label"].as_str().unwrap_or("?");
            let dead = slot["auth_dead"].as_bool().unwrap_or(false);
            if dead {
                return format!("✗ {}", label);
            }
            if let Some(q) = slot.get("quota") {
                let used = q["primary"]["used_percent"].as_f64().unwrap_or(0.0);
                let now_ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs_f64();
                let ra = q["primary"]["resets_at"].as_f64().unwrap_or(0.0);
                let rem = if ra > 0.0 && ra <= now_ts { 100 } else { (100.0 - used).max(0.0) as u32 };
                return format!("{} {}%", label, rem);
            }
            return label.to_string();
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
                let x = px + sw / 2.0 - 206.0;
                let y = py + sh + 4.0;
                let _ = win.set_position(PhysicalPosition::new(x as i32, y as i32));
            }
            let _ = win.show();
            let _ = win.set_focus();
        }
    }
}

// ---- app entry ----

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
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

            let quit = MenuItem::with_id(app, "quit", "退出 CodexBar", true, None::<&str>)?;
            let show =
                MenuItem::with_id(app, "show", "打开主窗口", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;

            let _tray = TrayIconBuilder::with_id("main")
                .icon(tray_icon)
                .icon_as_template(true)
                .title(format_tray_title())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                            let _ = w.center();
                        }
                    }
                    "quit" => { app.exit(0); }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        rect,
                        ..
                    } = event
                    {
                        toggle_menubar(tray.app_handle(), Some(rect));
                    }
                })
                .build(app)?;

            // ---- startup: auto refresh-all to get fresh quota ----
            let store_startup = store_dir();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_secs(3)).await; // wait for app to settle
                let rot = format!("{}/codex-rotate", store_startup);
                let _ = tokio::task::spawn_blocking(move || {
                    std::process::Command::new("python3").arg(&rot).args(["refresh-all"]).output()
                }).await;
            });

            // ---- periodic tray title refresh (every 30s) ----
            let handle_timer = handle.clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    tokio::time::sleep(Duration::from_secs(30)).await;
                    let title = format_tray_title();
                    if let Some(tray) = handle_timer.tray_by_id("main") {
                        let _ = tray.set_title(Some(&title));
                    }
                }
            });

            // ---- show main window (hidden by default in config, show on first launch) ----
            if let Some(w) = handle.get_webview_window("main") {
                let _ = w.show();
                let _ = w.center();
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
            read_auth_tokens,
            read_logs
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
