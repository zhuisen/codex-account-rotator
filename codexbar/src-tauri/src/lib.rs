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
/// 脚本目录 —— **只放代码,不放数据**。
///
/// 优先安装包里的资源:CI 构建出来的 .exe / .dmg 身边没有仓库,而 app 本质上是
/// `codex-rotate` 与 `traffic/scan.py` 的壳。2026-08-31 用户实测:Windows 安装包
/// 装完后每条命令都报 `can't open file '…\\traffic\\scan.py'` —— 因为 `store_dir()`
/// 只能猜一个 `%USERPROFILE%\\Projects\\tools\\…`,而那里什么都没有。
/// 回落到 `store_dir()` 是给「从仓库跑 deploy.sh」这条既有路径留的,行为不变。
static SCRIPT_ROOT: std::sync::OnceLock<String> = std::sync::OnceLock::new();
fn script_dir() -> String {
    SCRIPT_ROOT.get().cloned().unwrap_or_else(store_dir)
}

/// 数据目录 —— `state.json` / `auth/` / 缓存 / 快照。
///
/// ★ **绝不能等于脚本目录**:脚本进了安装包之后,按 `__file__` 推出来的数据位置就会
/// 落在 app 内部 —— macOS 上那里只读,Windows 上每次更新被整个替换。
/// 优先级刻意让 macOS 现状**零变化**:`deploy.sh` 会把仓库路径烧进 `CODEXBAR_STORE_DEFAULT`,
/// 所以老装法仍然指向仓库,已有的 state.json/auth 一个都不会"丢"。
/// 只有两者都没有(= CI 构建的安装包)才回落到系统的 app 数据目录。
static DATA_ROOT: std::sync::OnceLock<String> = std::sync::OnceLock::new();
fn data_dir() -> String {
    DATA_ROOT.get().cloned().unwrap_or_else(store_dir)
}

/// ★★ **所有子进程的唯一入口**。两件事只在这里做一次:
///
/// ① **Windows 上不带 `CREATE_NO_WINDOW`,每次 spawn 都会闪一个控制台窗口。**
///    本 app 每 2 分钟扫一次流量、每次切号/刷新都起 python —— 用户看到的就是
///    命令行窗口不停地闪。macOS 上没有这个概念,所以这个坑只在 Windows 显形,
///    而开发机是 macOS ⇒ 只能靠"所有 spawn 都走这里"来保证不漏。
/// ② **把数据目录用环境变量交给 python**。脚本本来按 `__file__` 推数据位置,
///    脚本一旦被打进安装包,数据就会跟着写进 app 内部(macOS 只读、更新即抹掉)。
///
/// 新增任何子进程调用都必须走这里,别再直接 `Command::new`。
fn spawn_cmd(program: &str) -> Command {
    let mut c = Command::new(program);
    c.env("CODEX_ROTATE_STORE", data_dir());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        c.creation_flags(CREATE_NO_WINDOW);
    }
    c
}

/// python 子进程。等价于 `spawn_cmd(&python_bin())`,单独留个名字是因为调用点多。
fn py_cmd() -> Command {
    spawn_cmd(&python_bin())
}

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
    // ★ Windows 上 **`HOME` 通常没有设置**(那是 POSIX 惯例),取到空串会拼出
    //   `/Projects/tools/...` 这种指向盘根的路径 —— 于是每一条命令都失败,
    //   而报错是 "找不到 codex-rotate",完全指不到真因。用 USERPROFILE。
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default();
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
    #[cfg(not(target_os = "windows"))]
    {
        for cand in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"] {
            if std::path::Path::new(cand).exists() {
                return cand.into();
            }
        }
        "python3".into()
    }
    // ★★ Windows 上不能靠"文件存在"判断。`python.exe` 在没装 Python 时是**应用商店的占位存根**:
    //    它存在、能启动、退出码为 0,却什么都不执行 —— 用 `Path::exists()` 判会选中它,
    //    然后每条命令都返回空输出,而 UI 上看到的是"没有数据",不是"解释器没找到"。
    //    所以必须**真的跑一次 `--version` 并检查输出**。
    //    上面那条 LibreSSL 403 的顾虑在这里不适用:Windows 版 CPython 链的是 OpenSSL。
    //    结果缓存 —— 有 6 个调用点,每次都探测等于每条命令多起一个进程。
    #[cfg(target_os = "windows")]
    {
        use std::sync::OnceLock;
        static RESOLVED: OnceLock<String> = OnceLock::new();
        RESOLVED
            .get_or_init(|| {
                for cand in ["py", "python3", "python"] {
                    // ★ 不能走 py_cmd():那会递归回 python_bin()。这里手动加同一个 flag ——
                    //   探测发生在启动时且逐个候选试,不加就是开机连闪几个黑窗。
                    let mut probe = std::process::Command::new(cand);
                    probe.arg("--version");
                    {
                        use std::os::windows::process::CommandExt;
                        probe.creation_flags(0x0800_0000);
                    }
                    let ok = probe
                        .output()
                        .map(|o| {
                            o.status.success()
                                && (String::from_utf8_lossy(&o.stdout).contains("Python 3")
                                    || String::from_utf8_lossy(&o.stderr).contains("Python 3"))
                        })
                        .unwrap_or(false);
                    if ok {
                        return cand.to_string();
                    }
                }
                // 一个都探不到:仍返回 "python",让调用方拿到真实的启动失败错误,
                // 而不是在这里静默换成别的东西。
                "python".to_string()
            })
            .clone()
    }
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
    let path = format!("{}/state.json", data_dir());
    let data = fs::read_to_string(&path).map_err(|e| format!("read state: {}", e))?;
    serde_json::from_str(&data).map_err(|e| format!("parse state: {}", e))
}

#[tauri::command]
async fn run_rotate(app: AppHandle, args: Vec<String>) -> Result<String, String> {
    let store = script_dir();
    if args.first().map_or(true, |c| !ALLOWED_CMDS.contains(&c.as_str())) {
        return Err(format!("disallowed command: {:?}", args.first()));
    }
    let rot = format!("{}/codex-rotate", store);
    let out = tauri::async_runtime::spawn_blocking(move || {
        py_cmd().arg(&rot).args(&args).output()
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
    // Windows has no Dock and no activation policy. The nearest equivalent to "don't take up a
    // slot" is keeping the window out of the taskbar; unlike macOS it is a *per-window* property,
    // so there is no cold-start flash to avoid and no `Reopen` event to handle.
    // ★ Deliberately NOT tied to `main_visible`: a hidden window is already absent from the
    //   taskbar, so recomputing it from visibility would be a no-op that reads as if it did
    //   something. The switch alone is the whole condition here.
    #[cfg(target_os = "windows")]
    {
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.set_skip_taskbar(!DOCK_ENABLED.load(Ordering::Relaxed));
        }
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
    let script = format!("{}/traffic/discover.py", script_dir());
    let out = tauri::async_runtime::spawn_blocking(move || {
        py_cmd().arg(&script).arg("--json").output()
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
    let script = format!("{}/traffic/scan.py", script_dir());
    let forced = args.iter().any(|a| a == "--no-cache");
    let out = tauri::async_runtime::spawn_blocking(move || {
        // 串行化:第二个调用者在这里等第一个扫完
        let _guard = SCAN_LOCK.lock();
        if !forced {
            if let Some(fresh) = fresh_snapshot(SCAN_COALESCE_SECS) {
                return Ok(Err(fresh)); // Err 分支借用来表示"复用快照",不是错误
            }
        }
        py_cmd()
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

/// grok 周额度的 sidecar。**刻意不进 `state.json`** —— `slots` 里的每个 key 都被轮换器当池成员
/// 遍历(`_pick`/`cmd_refresh_all`/`cmd_keepalive`),而 `cmd_keepalive` 就是拿 refresh_token 去刷的。
/// grok 的 refresh_token 单次有效、且与 grok CLI 共用同一份凭证,进池即进刷新器射程 ——
/// 与 §8「绝不刷 active 号的 token(B7/B8/B14 连环杀号)」完全同族。
/// 含 email + user_id,已进 `.gitignore`。
const GROK_SNAPSHOT: &str = ".grok-quota.json";

/// ★ 独立于 `SCAN_LOCK`:取额度是**联网**、重扫描是读本机盘,两种成本共用一把锁会互相阻塞
/// (用户在 grok 详情页点 ↻,不该被一个正在跑的 1.4s 全盘扫描堵住)。
static GROK_LOCK: Mutex<()> = Mutex::new(());
/// 拿到锁后若 sidecar 比这个还新,就认为刚有人取过,直接复用,不起 python、不发外网请求。
const GROK_COALESCE_SECS: u64 = 300;

fn grok_snapshot_path() -> String {
    format!("{}/{}", data_dir(), GROK_SNAPSHOT)
}

/// sidecar 若比 `max_age_secs` 还新就返回它。`fetched_at` 成败都会写,所以过期判断对降级态同样成立。
fn fresh_grok(max_age_secs: u64) -> Option<String> {
    let body = fs::read_to_string(grok_snapshot_path()).ok()?;
    let v: Value = serde_json::from_str(&body).ok()?;
    let at = v.get("fetched_at")?.as_u64()?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs();
    if now.saturating_sub(at) <= max_age_secs {
        Some(body)
    } else {
        None
    }
}

/// 原子落盘,理由同 `write_traffic_snapshot`。
fn write_grok_snapshot(body: &str) {
    let path = grok_snapshot_path();
    let tmp = format!("{}.tmp{}", path, std::process::id());
    if fs::write(&tmp, body).is_ok() && fs::rename(&tmp, &path).is_err() {
        let _ = fs::remove_file(&tmp);
    }
}

/// 读 grok 额度 sidecar。`Ok(None)` = 从未取过(前端据此显示「未探测 · 点 ↻」而不是 0%)。
#[tauri::command]
fn read_grok_quota() -> Result<Option<String>, String> {
    match fs::read_to_string(grok_snapshot_path()) {
        Ok(s) if !s.trim().is_empty() => Ok(Some(s)),
        Ok(_) => Ok(None),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("read grok snapshot: {}", e)),
    }
}

/// 取一次 grok 周额度。**这是本 app 唯一一条主动联网的数据路径**(`check_update` 是点按钮才跑的 git)。
///
/// ★★ `grok-quota` 的退出码**恒 0**,任何失败都以 `available:false` 的 JSON 回来 ——
/// 所以这里几乎不会走 `Err` 分支。这是刻意的:`Err(String)` 在前端会被读成"没数据",
/// 而"读不到额度"必须作为**有内容的降级数据**送达,否则项目铁律
/// 「『读不到』和『确实没有』不能返回同一个值」就在这一层被折叠掉了。
/// 只有 spawn 本身失败(python 不存在之类)才是真的 `Err`。
///
/// ★ 不 `emit("state-changed")`、不 `refresh_tray()` —— 那两件事是账号池状态变更的信号,
/// grok 不在池里,发了就是噪音。
#[tauri::command]
async fn run_grok_quota() -> Result<String, String> {
    let script = format!("{}/grok-quota", script_dir());
    let prev = grok_snapshot_path();
    let out = tauri::async_runtime::spawn_blocking(move || {
        let _guard = GROK_LOCK.lock();
        // 双检:两个 webview 同时判定要取时,只有第一个真的发请求。
        if let Some(fresh) = fresh_grok(GROK_COALESCE_SECS) {
            return Ok(Err(fresh));
        }
        py_cmd()
            .arg(&script)
            .arg("--prev")   // 只读上一份,用来搬运 last_good(降级时保留陈旧读数)
            .arg(&prev)
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
        let body = String::from_utf8_lossy(&out.stdout).to_string();
        write_grok_snapshot(&body);
        Ok(body)
    } else {
        Err(format!(
            "{}\n{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        ))
    }
}

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
    format!("{}/{}", data_dir(), SNAPSHOT)
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
    let store = store_dir();   // ★ 第三种概念:git 要的是**仓库**,既不是脚本目录也不是数据目录
    let out = tauri::async_runtime::spawn_blocking(move || {
        spawn_cmd("git")
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
        let path = format!("{}/auth/{}", data_dir(), file);
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
        let path = format!("{}/{}", data_dir(), name);
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
    let path = format!("{}/auth/{}", data_dir(), file);
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
    let path = format!("{}/.traffic-latest.json", data_dir());
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
// 只有 macOS 的 attributedTitle 会用到它 —— Windows 托盘没有文字可上色。
#[cfg(target_os = "macos")]
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
        // ★★ **Windows 托盘没有文字**。`TrayIcon::set_title` 在 Windows 上是**空实现**
        //   (tray-icon 的 win/mod.rs 里那个 fn 体是空的),所以上面那行不报错、也什么都不做 ——
        //   四种样式、百分比、ETA、颜色**全部消失**,而编译和运行都不会有任何抱怨。
        //   这正是本仓库最怕的形态:失败是静默的。
        //   Windows 上唯一能显示这串信息的位置是 tooltip(悬停气泡),上限 127 字符。
        //   ⚠️ 这不是等价替换:tooltip 要**悬停才看得见**,而 macOS 是常驻可见。
        //   把百分比烧进图标是后续方案(见 docs/WINDOWS_PORT_PLAN.md),不在本轮。
        #[cfg(target_os = "windows")]
        {
            let tip: String = title.chars().take(127).collect();
            let _ = tray.set_tooltip(Some(&tip));
        }
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
    let path = format!("{}/state.json", data_dir());
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
                // ★★ 2026-08-25:Plus 的 5 小时窗口回来了(实测 window_minutes=300)。
                // 只丢**空槽**(wm<=0),不再按量级丢 —— 旧判据 `wm>=5000` 会把合法的 5h 当垃圾。
                // ★ 取**最紧的**那个窗口,不是"第一个":plus 的 primary 现在是 5h、周退到
                //   secondary,而 pro 只有周。取第一个会让两类号显示的不是同一种东西,
                //   且与主界面 hero 环(取 tightest)说的不一致。
                let now_ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs_f64();
                // ★★ 快照的拍摄时刻。判据要用它,所以在过滤之前取出来。
                //    `captured_at` 挂在 quota 对象上、不在窗口里。
                let cap = q["captured_at"].as_f64();
                let win = ["primary", "secondary"]
                    .iter()
                    .filter_map(|k| {
                        let w = &q[*k];
                        let wm = w["window_minutes"].as_f64().unwrap_or(0.0);
                        let used = w["used_percent"].as_f64();
                        // ★★ 与 `helpers.ts::winRem` **同一条判据**(跨语言没法共用,只能同步改):
                        //    `resets_at` 过了**不等于**已确认重置为满额。分两种 ——
                        //    · 快照晚于重置点 ⇒ 读数属于新窗口,采信;
                        //    · 快照更旧     ⇒ 重置了但没有任何新读数 ⇒ **不参与**,
                        //      于是走下面已有的「额度未知 → —」那条路,而不是编一个 100。
                        //    旧版这里是 `if ra <= now_ts { 100 }`,画出来的 100% 与实测的
                        //    100% 长得一模一样 —— 用户无从分辨。闸在 test_quota_never_fabricated.py。
                        let ra = w["resets_at"].as_f64().unwrap_or(0.0);
                        let confirmed = !(ra > 0.0 && ra <= now_ts) || cap.map_or(false, |c| c > ra);
                        match (wm > 0.0, used, confirmed) {
                            (true, Some(u), true) => Some((w, u)),
                            _ => None,
                        }
                    })
                    // 剩余最少 = 已用最多 ⇒ 取 used 最大的那个
                    .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
                    .map(|(w, _)| w);
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
                // ★★ 标签按**实际时长**算,不是两分法。旧版 `>=40000 ? 月 : 周` 会把
                //    5 小时窗口(300)标成「周」—— **那比不显示更糟:它把 5 小时的余量
                //    说成一周的余量**。与 helpers.ts 的 `winLabel` 同一套档位。
                let win_tag: String = if wm >= 40000.0 {
                    "月".into()
                } else if wm >= 10000.0 {
                    "周".into()
                } else if wm >= 1440.0 {
                    format!("{}天", (wm / 1440.0).round() as i64)
                } else {
                    format!("{}h", (wm / 60.0).round() as i64)
                };
                let ra = w["resets_at"].as_f64().unwrap_or(0.0);
                // ★ 不再有「过期 → 100」这一支:未确认的窗口在上面的过滤里就出局了。
                let rem = (100.0 - used).max(0.0) as u32;
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

/// 弹窗落点的**纯算术**部分,抽出来是为了能在没有 Windows 机器的情况下测到它。
///
/// 全部是**物理**像素。`icon` = 托盘图标的 (x, y, w, h);`mon` = 图标所在屏的 (x, y, w, h)。
///
/// 两条判据:
/// - **下方放不下且上方放得下 ⇒ 翻到图标上方**。不看平台看空间 —— macOS 菜单栏在顶部所以恒走下方,
///   而 Windows 任务栏通常在底部,托盘在右下角,无条件向下 = 整个弹窗在屏幕外(用户 2026-08-31 实测
///   报「什么都看不到」)。任务栏也可能在左/右/上,所以硬编码平台是错的。
/// - **双轴钳位**:托盘贴着屏幕右缘是 Windows 的常态,居中会把面板推出屏外。
fn place_popover(
    icon: (f64, f64, f64, f64),
    mon: (f64, f64, f64, f64),
    panel_w: f64,
    panel_h: f64,
) -> (f64, f64) {
    let (px, py, sw, sh) = icon;
    let (mx, my, mw, mh) = mon;
    let below = py + sh + 4.0;
    let above = py - panel_h - 4.0;
    let y = if below + panel_h > my + mh && above >= my { above } else { below };
    // ★ 钳位顺序:先 `min`(不越出右/下缘)再 `max`(不越出左/上缘)。反过来的话,
    //   **面板比屏幕还大**时 `min` 会算出负数,窗口被丢到屏幕外 —— 单测抓到的正是这个。
    //   两者冲突时让左/上缘赢:宁可右/下被裁,也不能整个不可见。
    let x = (px + sw / 2.0 - panel_w / 2.0).min(mx + mw - panel_w).max(mx);
    let y = y.min(my + mh - panel_h).max(my);
    (x, y)
}

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
                // ★★ **托盘图标所在的那块屏**,不是主屏。多屏 / 混合 DPI 下用主屏会把弹窗
                //    拽回主屏,用自身 scale 换算则在缩放不同的副屏上偏出去。
                let mon = win
                    .available_monitors()
                    .ok()
                    .and_then(|ms| {
                        ms.into_iter().find(|m| {
                            let mp = m.position();
                            let sz = m.size();
                            px >= mp.x as f64
                                && px < mp.x as f64 + sz.width as f64
                                && py >= mp.y as f64
                                && py < mp.y as f64 + sz.height as f64
                        })
                    })
                    .or_else(|| win.primary_monitor().ok().flatten());

                // `panel_w`/窗口高度是**逻辑**像素,而 set_position 收的是**物理**像素 ——
                // 不乘 scale 的话 Retina 上居中会偏半个面板宽(既有缺陷,顺手一并修)。
                let scale = mon.as_ref().map(|m| m.scale_factor()).unwrap_or(1.0);
                let panel_w = 352.0 * scale; // 逻辑宽守卫见 tests/test_menubar_width_sync.py
                let panel_h = win
                    .outer_size()
                    .map(|s| s.height as f64)
                    .unwrap_or(600.0 * scale);

                let (mx, my, mw, mh) = match mon.as_ref() {
                    Some(m) => {
                        let mp = m.position();
                        let sz = m.size();
                        (mp.x as f64, mp.y as f64, sz.width as f64, sz.height as f64)
                    }
                    None => (0.0, 0.0, f64::MAX, f64::MAX),
                };

                // ★★ **不能无条件向下开**。macOS 菜单栏恒在顶部,所以"图标下方"一直是对的;
                //    **Windows 任务栏通常在底部**,托盘在右下角 —— 往下开整个弹窗都在屏幕外,
                //    用户报的就是"什么都看不到"。任务栏还可能在任意一边。
                //    判据不看平台、看**放得下放不下**:下方溢出且上方放得下 ⇒ 翻到图标上方。
                //    图标本身在任务栏里,所以"图标上方"天然避开了任务栏。
                let (x, y) = place_popover((px, py, sw, sh), (mx, my, mw, mh), panel_w, panel_h);
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
/// `Acquired` 里的 guard 必须由调用方持有到进程结束 —— 一旦 drop,fd/句柄关闭,锁就没了。
///
/// ★★ **Windows 用命名互斥体,不是锁文件**(2026-08-30 补齐平权)。`CreateMutexW` 同样是
/// 内核级原子操作:并发创建时**恰好一个**拿到全新对象,其余拿到已存在句柄并置
/// `ERROR_ALREADY_EXISTS`,不存在"检查与获取之间的窗口"。崩溃安全也同源 —— 内核对象随
/// **进程终止**自动释放,`kill`/panic/断电都不会留陈旧锁。
/// 名字用 `Local\` 前缀:限定在当前登录会话,多用户各自一个实例才是对的行为
/// (`Global\` 会让第二个登录用户被第一个挡住)。
/// ⚠️ 这里刻意**不**用锁文件 —— Windows 上"删掉正被持有的锁文件再重建"这条路径和 `/tmp`
/// 被清理那个坑同族,而命名内核对象根本没有文件可删。
/// 三态语义与 unix 侧逐字对应,尤其 `Undetermined` 必须 fail-open。
enum InstanceLock {
    /// 拿到锁,本进程是唯一实例。
    /// ★ 这个字段**从不被读**,它的全部作用就是"活着" —— drop 即放锁。
    Acquired(#[allow(dead_code)] InstanceGuard),
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

/// 持有到进程结束的守卫。unix 是持锁的 fd,windows 是互斥体句柄 —— 两边都靠"活着"维持锁。
#[cfg(unix)]
type InstanceGuard = std::fs::File;

/// ★ 不实现 `Drop` 关句柄:进程退出时内核回收,而提前 drop 反而会**提前放锁**。
///   包一层 newtype 只是为了让 `InstanceLock::Acquired(..)` 在两个平台上同形。
#[cfg(windows)]
struct InstanceGuard(#[allow(dead_code)] windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
unsafe impl Send for InstanceGuard {}

#[cfg(windows)]
fn acquire_single_instance_lock() -> InstanceLock {
    use windows_sys::Win32::Foundation::{GetLastError, ERROR_ALREADY_EXISTS};
    use windows_sys::Win32::System::Threading::CreateMutexW;

    // UTF-16、NUL 结尾。名字里不能有反斜杠以外的路径分隔符,`Local\` 前缀是命名空间不是目录。
    let name: Vec<u16> = "Local\\com.doushutangmu.codexbar.single-instance\0"
        .encode_utf16()
        .collect();
    // SAFETY: name 是刚构造、仍存活的 NUL 结尾 UTF-16 缓冲;其余参数为空/false 的合法取值。
    let h = unsafe { CreateMutexW(std::ptr::null(), 0, name.as_ptr()) };
    if h.is_null() {
        // 建不出对象(极少见:名字冲突到别的类型、会话受限)。**按判定不了处理** ——
        // 与 unix 侧一样,宁可多开一个,也不能静默到一个都起不来。
        return InstanceLock::Undetermined;
    }
    // ★ 必须在 `CreateMutexW` **成功之后**立刻读:GetLastError 会被后续任何 API 覆盖。
    //   句柄非空且 ERROR_ALREADY_EXISTS ⇒ 对象本来就在 ⇒ 另一个实例正活着。
    if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        return InstanceLock::HeldByOther;
    }
    InstanceLock::Acquired(InstanceGuard(h))
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
    // ★ 两个平台都要:Windows 上开机自启(注册表 Run 键)与用户手点会并发,
    //   没有守卫就是两个托盘、两个池同时读写 state.json。
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
            // ★★ 先把「脚本在哪」「数据在哪」定下来 —— 后面所有 python 调用都依赖它。
            //    2026-08-31 Windows 实测:CI 构建的安装包身边没有仓库,`store_dir()` 只能猜一个
            //    `%USERPROFILE%\Projects\tools\…`,于是每条命令都报 can't open file。
            {
                use tauri::Manager;
                // ① 脚本:安装包里的 resources/scripts 优先
                if let Ok(res) = app.path().resource_dir() {
                    let cand = res.join("scripts");
                    if cand.join("traffic").join("scan.py").is_file() {
                        let _ = SCRIPT_ROOT.set(cand.to_string_lossy().to_string());
                    }
                }
                // ② 数据:env > 构建期烧进去的仓库路径 > app 数据目录
                //    前两条保证「从仓库跑 deploy.sh」这条既有路径**行为完全不变** ——
                //    已有的 state.json / auth/ 仍在仓库里，不会因为这次改动而"消失"。
                let data = std::env::var("CODEXBAR_STORE").ok().filter(|v| !v.is_empty())
                    .or_else(|| option_env!("CODEXBAR_STORE_DEFAULT").map(|v| v.to_string())
                                 .filter(|v| !v.is_empty()))
                    .or_else(|| app.path().app_data_dir().ok()
                                 .map(|d| d.to_string_lossy().to_string()));
                if let Some(d) = data {
                    let _ = fs::create_dir_all(&d);
                    let _ = DATA_ROOT.set(d);
                }
            }

            // Hide from Dock — LSUIElement alone isn't reliable with Tauri.
            // ★ Both the method and the enum are #[cfg(macos)] in tauri 2.x, so an un-gated call
            //   is a hard compile error on Windows — not a no-op. `apply_activation_policy()`
            //   above was already gated; this second call site was missed.
            //   Windows has no Dock: the taskbar equivalent is set_skip_taskbar(), applied to the
            //   main window in apply_activation_policy().
            #[cfg(target_os = "macos")]
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
            // ★★ **两个平台不能共用同一张图**。`icons/tray.png` 是 macOS 模板图:36x36、
            //    218 个不透明像素**全是 #000000**,靠 `icon_as_template` 让系统按明暗主题反色。
            //    Windows 没有模板图这个概念,直接用它 = 深色任务栏上画黑色 = **图标隐形**,
            //    而且不报任何错(用户只会觉得"装完没反应")。所以 Windows 走彩色 icon.ico。
            #[cfg(not(target_os = "windows"))]
            let tray_bytes: &[u8] = include_bytes!("../icons/tray.png");
            #[cfg(target_os = "windows")]
            let tray_bytes: &[u8] = include_bytes!("../icons/32x32.png");
            let tray_icon = tauri::image::Image::from_bytes(tray_bytes)?;

            // ★ NO native menu is attached. On macOS a tray icon with a menu ALWAYS opens that menu on
            // right-click — there is no per-button opt-out — so the only way to make both buttons show
            // our own popover is to have no menu at all. The actions that lived there moved: 打开主窗口
            // = click any account row, 刷新全池/检查 token = popover footer, 退出 = Settings (quit_app).
            let builder = TrayIconBuilder::with_id("main").icon(tray_icon);
            // `icon_as_template` 是 macOS 专属语义(系统按主题反色);Windows/Linux 上设它无意义。
            #[cfg(target_os = "macos")]
            let builder = builder.icon_as_template(true);
            // Windows 托盘不显示标题,只有 tooltip —— 建的时候就给上,别等第一次 refresh_tray。
            #[cfg(target_os = "windows")]
            let builder = builder.tooltip(format_tray_title());
            let _tray = builder
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
            let store_startup = script_dir();
            let handle_startup = handle.clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_secs(3)).await;
                let rot = format!("{}/codex-rotate", store_startup);
                let _ = tokio::task::spawn_blocking(move || {
                    // refresh-all brings back the free credit COUNTS; `credits` then fills in the
                    // expiry dates the banner needs. It self-limits — it only hits the rate-limited
                    // detail endpoint when an account actually holds cards and the 12h cache is
                    // stale — so running it on every launch costs nothing on a warm cache.
                    let c = py_cmd().arg(&rot).arg("refresh-all").output();
                    let _ = py_cmd().arg(&rot).arg("credits").output();
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
                let path = format!("{}/state.json", data_dir());
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
            read_grok_quota,
            run_grok_quota,
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


#[cfg(test)]
mod popover_tests {
    use super::place_popover;

    // macOS:菜单栏在顶部,图标 (100,0,24,24),屏 1440x900,面板 352x600
    #[test]
    fn macos_top_menubar_opens_below() {
        let (x, y) = place_popover((100.0, 0.0, 24.0, 24.0), (0.0, 0.0, 1440.0, 900.0), 352.0, 600.0);
        assert_eq!(y, 28.0, "顶部菜单栏应向下开");
        // 图标在最左侧,居中会算出 -64 ⇒ 被钳到 0。这是对的:钳位优先于居中。
        assert_eq!(x, 0.0, "越出左缘时应钳到屏幕内");
    }

    // 居中本身:图标在屏幕中部,不触发任何钳位
    #[test]
    fn centers_under_the_icon_when_no_clamping_applies() {
        let (x, _) = place_popover((700.0, 0.0, 24.0, 24.0), (0.0, 0.0, 1440.0, 900.0), 352.0, 600.0);
        assert_eq!(x, 700.0 + 12.0 - 176.0, "未触发钳位时应严格以图标中心居中");
    }

    // ★★ Windows:任务栏在底部,托盘图标在右下角。向下开会整个出屏 —— 必须翻到上方。
    #[test]
    fn windows_bottom_taskbar_flips_above() {
        // 1920x1080 屏,图标在 (1850, 1050),任务栏高 ~30
        let (_x, y) = place_popover((1850.0, 1050.0, 24.0, 24.0), (0.0, 0.0, 1920.0, 1080.0), 352.0, 600.0);
        assert!(y < 1050.0, "底部任务栏时弹窗必须开在图标上方,实际 y={}", y);
        assert!(y >= 0.0, "翻上去之后不能越出屏幕顶部,实际 y={}", y);
        assert_eq!(y, 1050.0 - 600.0 - 4.0, "应紧贴图标上沿");
    }

    // ★ 托盘贴右缘:居中会把面板推出屏外,必须钳位
    #[test]
    fn right_edge_icon_is_clamped_into_screen() {
        let (x, _y) = place_popover((1900.0, 1050.0, 16.0, 16.0), (0.0, 0.0, 1920.0, 1080.0), 352.0, 600.0);
        assert!(x + 352.0 <= 1920.0, "面板右缘越出屏幕,x={}", x);
        assert!(x >= 0.0);
    }

    // ★ 副屏:坐标不是从 0 开始,钳位必须按**该屏**的原点算,不能按 0
    #[test]
    fn secondary_monitor_uses_its_own_origin() {
        // 副屏在主屏右侧,原点 (1920,0),尺寸 1920x1080
        let (x, y) = place_popover(
            (3800.0, 1050.0, 16.0, 16.0), (1920.0, 0.0, 1920.0, 1080.0), 352.0, 600.0);
        assert!(x >= 1920.0, "被错误地拽回主屏,x={}", x);
        assert!(x + 352.0 <= 3840.0, "越出副屏右缘,x={}", x);
        assert!(y < 1050.0, "副屏底部同样要翻转");
    }

    // 上下都放不下时不能返回负数把窗口丢到屏外
    #[test]
    fn tiny_screen_still_stays_on_screen() {
        let (x, y) = place_popover((10.0, 300.0, 16.0, 16.0), (0.0, 0.0, 400.0, 500.0), 352.0, 600.0);
        assert!(x >= 0.0 && y >= 0.0, "极小屏下越出屏幕 x={} y={}", x, y);
    }
}
