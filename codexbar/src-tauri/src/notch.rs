//! 刘海额度条（macOS 专属，**默认关**，设置页开）。用户 2026-10-17 从 demo 里选定
//! 「收起 = 刘海周围的光晕、悬停 = 额度环面板」（起初是刘海下沿的分段细线，用户嫌不明显换成光晕）。
//!
//! ★ 为什么能做成 Tauri 窗口而不是另起一个 Swift 进程：2026-10-17 独立验证程序实测 ——
//!   层级设到 `NSStatusWindowLevel + 1` 后窗口顶边与屏幕顶边间距 0、盖在菜单栏之上；
//!   全屏应用里可见（用户确认）；悬停在 CodexBar 不在前台时照样触发（用户试了十几次）。
//!
//! ★★ 刘海本身**没有像素**。画在刘海矩形里的东西看不见，所以光晕画在刘海**外沿**
//!    （窗口四周多留 `GLOW_X` / `GLOW_Y`）；两侧各 `FLARE` 是刘海上沿的内凹圆角。
//!
//! ★★ 悬停判定**不靠网页里的 mouseenter**：CodexBar 是 Accessory 应用、几乎永远不在前台，
//!    WKWebView 在后台窗口里收不收得到鼠标移动没验过，不赌它。做法分两段（Agent HUD 同理）：
//!    · 平时：系统鼠标事件监听（全局 + 本进程各一个）。鼠标不动就不触发 ——
//!      验证程序里纯轮询（80/250ms）空闲主进程 0.30% CPU（不轮询时的底数没量过）；
//!    · 光标进了刘海区：起一个 60ms 的跟踪线程，直到光标离开且面板收完。
//!      监听只负责"叫醒"，进出与停留的判定全在跟踪线程里 —— 光标停在我们自己的窗口上时，
//!      全局监听可能收不到事件，只靠事件会"离不开"。
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl};

pub const LABEL: &str = "notch";
/// 刘海上沿两侧的内凹圆角，窗口要比刘海各宽这么多。与 `notch.css` 的 `--flare` 同值。
const FLARE: f64 = 7.0;
/// 展开面板宽。与 `NotchHud.tsx` 的 `PANEL_W` 同值，闸在 `tests/test_notch_hud.py`。
pub const PANEL_W: f64 = 312.0;
const OPEN_DWELL: Duration = Duration::from_millis(90);
const CLOSE_DWELL: Duration = Duration::from_millis(220);
/// 前端收起动画时长（`notch.css` 的 clip-path 过渡 .34s）。收完再缩窗口，否则动画被裁掉。
const COLLAPSE: Duration = Duration::from_millis(340);
const TRACK_TICK: Duration = Duration::from_millis(60);
/// 收起态窗口在刘海两侧 / 下方多留的透明边，给光晕用。blur(σ) 要往外 ~2σ 才淡到看不见，
/// 外层光晕半宽 = 刘海半宽 + 圆角 + 14、blur 20 ⇒ 要 ≥ 54；下沿到刘海下 12 + 40 ⇒ 要 ≥ 52。
/// 不够的话 blur 的边缘会被窗口裁出一圈直边（第一版只留了 1σ，用户一眼看出「限制了范围」）。
/// 与 `notch.css` 的 `.nh-glow .g1/.g2` 尺寸配套。
/// 窗口收起时**不接收鼠标**，所以这圈边不会挡菜单栏图标。
const GLOW_X: f64 = 60.0;
const GLOW_Y: f64 = 60.0;
/// 活动检测的周期，以及「最近这么多秒内写过 = 正在跑」。
const ACTIVITY_TICK: Duration = Duration::from_secs(2);
const ACTIVE_SECS: u64 = 45;
/// 几何（刘海位置）最多多久重读一次。合盖/开盖/改分辨率后靠它自愈（下一次鼠标移动时）。
const GEOM_TTL: Duration = Duration::from_secs(3);

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Notch {
    /// 刘海左边界，桌面坐标（主屏左上为原点，逻辑 pt）
    pub left: f64,
    pub width: f64,
    pub height: f64,
    /// 刘海所在屏幕顶边在桌面坐标里的 y
    pub top: f64,
    /// 主屏高度：AppKit 坐标（左下原点）换算成桌面坐标要用
    #[serde(skip)]
    primary_h: f64,
}

/// `set_notch_hud` 的回答。★ 「开关记住了」与「屏幕上真有东西」是两件事 ——
/// 没有刘海屏时开关照样记着开，但必须让设置页说出来，不能让用户对着空屏幕猜（四方评审 2026-10-17）。
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Status {
    pub active: bool,
    /// `active == false` 的原因：`"no_notch"` = 现在没有带刘海的屏幕（外接屏 / 合盖 / 本来就没有）
    pub reason: Option<&'static str>,
}

static ENABLED: AtomicBool = AtomicBool::new(false);
static OPEN: AtomicBool = AtomicBool::new(false);
/// ★ 代次（四方评审 2026-10-17）：每次开/关 +1，每次展开/收起 +1。后台线程与排进主线程的闭包
///   **执行前**核对自己领到的那一代 —— 关掉之后旧线程不许再把窗口展开、旧的收起计时不许裁掉新一轮动画。
static ENABLE_GEN: AtomicU64 = AtomicU64::new(0);
static OPEN_GEN: AtomicU64 = AtomicU64::new(0);
/// 正在跑的跟踪线程领到的号；0 = 没有。退出时只清**自己那一号**（`compare_exchange`），
/// 否则旧线程退出会把新线程的标记抹掉，于是又起一条。
static TRACKER: AtomicU64 = AtomicU64::new(0);
static TRACKER_SEQ: AtomicU64 = AtomicU64::new(0);
/// 正在跑的活动检测线程领到的号；0 = 没有。★ 新起的一条**直接接管**（store），旧的看到不是自己就退 ——
/// 原来用一个 `WATCHING` 布尔：快速关了再开时它还是 true，新线程起不来，旧线程随后退出，就一条都没有了（评审 2026-10-17）。
static WATCHER: AtomicU64 = AtomicU64::new(0);
static WATCHER_SEQ: AtomicU64 = AtomicU64::new(0);
static ACTIVITY: Mutex<Activity> = Mutex::new(Activity { codex: false, agy: false });

/// 谁正在跑。用户 2026-10-17：Codex 跑时亮 Codex 的光、agy 跑时亮 agy 的光，同时跑两个都亮。
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Activity { pub codex: bool, pub agy: bool }
static GEOM: Mutex<Option<(Option<Notch>, Instant)>> = Mutex::new(None);
static PANEL_H: Mutex<f64> = Mutex::new(180.0);
/// 两个监听器对象（`Retained::into_raw` 出来的指针）。`Retained` 不是 Send，只能这样存。
static MONITORS: Mutex<Vec<usize>> = Mutex::new(Vec::new());

#[repr(C)]
#[derive(Clone, Copy)]
struct EdgeInsets { top: f64, left: f64, bottom: f64, right: f64 }
// SAFETY: 与 AppKit 的 NSEdgeInsets 同布局（四个 CGFloat），编码名一致。
unsafe impl objc2::Encode for EdgeInsets {
    const ENCODING: objc2::Encoding = objc2::Encoding::Struct(
        "NSEdgeInsets",
        &[f64::ENCODING, f64::ENCODING, f64::ENCODING, f64::ENCODING],
    );
}

/// 一块屏的 AppKit 几何 → 刘海在桌面坐标里的位置。纯函数，单测覆盖「刘海屏不是主屏」。
///
/// ★ 只用两块 auxiliary 区域的**宽度**，不用它们的 origin：左块从屏幕左沿开始、右块到屏幕右沿结束
///   是定义，于是刘海 = `[frame.x + 左块宽, frame.x + frame.w − 右块宽]`。这样不必赌 auxiliary
///   矩形用的是全局坐标还是屏幕局部坐标 —— 刘海屏是主屏（原点 0）时两种说法恰好相等，测不出来。
fn notch_from(frame: (f64, f64, f64, f64), primary_h: f64, inset_top: f64,
              left_w: f64, right_w: f64) -> Option<Notch> {
    let (fx, fy, fw, fh) = frame;
    if inset_top <= 0.0 { return None; }
    let left = fx + left_w;
    let right = fx + fw - right_w;
    if right <= left { return None; }
    Some(Notch { left, width: right - left, height: inset_top, top: primary_h - (fy + fh), primary_h })
}

/// 带刘海的那块屏幕上，刘海的位置。没有刘海的屏幕 ⇒ `None`（用户 2026-10-17 定：
/// 外接屏、合盖时**不显示**，不画替身条）。主线程调用。
fn read_notch() -> Option<Notch> {
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use objc2_foundation::NSRect;
    // SAFETY: 只读 NSScreen 的几何属性；对象来自 `+screens`，在本次调用内有效。
    unsafe {
        let screens: *mut AnyObject = msg_send![class!(NSScreen), screens];
        if screens.is_null() { return None; }
        let n: usize = msg_send![screens, count];
        if n == 0 { return None; }
        let primary: *mut AnyObject = msg_send![screens, objectAtIndex: 0usize];
        let pf: NSRect = msg_send![primary, frame];
        for i in 0..n {
            let s: *mut AnyObject = msg_send![screens, objectAtIndex: i];
            let ins: EdgeInsets = msg_send![s, safeAreaInsets];
            if ins.top <= 0.0 { continue; }
            let f: NSRect = msg_send![s, frame];
            let l: NSRect = msg_send![s, auxiliaryTopLeftArea];
            let r: NSRect = msg_send![s, auxiliaryTopRightArea];
            if let Some(g) = notch_from((f.origin.x, f.origin.y, f.size.width, f.size.height),
                                        pf.size.height, ins.top, l.size.width, r.size.width) {
                return Some(g);
            }
        }
        None
    }
}

/// 缓存过的几何；过期就重读（`GEOM_TTL`）。★ **只在主线程调**（NSScreen 是 AppKit 对象）：
/// 鼠标监听回调与同步命令都在主线程；后台线程一律用 `cached()`。
fn geometry() -> Option<Notch> {
    let mut g = GEOM.lock().unwrap();
    if let Some((v, at)) = *g {
        if at.elapsed() < GEOM_TTL { return v; }
    }
    let v = read_notch();
    *g = Some((v, Instant::now()));
    v
}

/// 后台线程用：只取缓存，从不碰 AppKit。
fn cached() -> Option<Notch> {
    GEOM.lock().unwrap().and_then(|(v, _)| v)
}

/// 收起/展开时窗口在桌面坐标里的矩形。
fn rect(g: &Notch, open: bool) -> (f64, f64, f64, f64) {
    if open {
        let h = *PANEL_H.lock().unwrap();
        let w = PANEL_W + FLARE * 2.0;
        (g.left + g.width / 2.0 - w / 2.0, g.top, w, h)
    } else {
        let m = FLARE + GLOW_X;
        (g.left - m, g.top, g.width + m * 2.0, g.height + GLOW_Y)
    }
}

/// 光标是否在触发区内。收起时只认刘海本身 —— 两侧圆角与光晕那圈都是菜单栏，不算。
fn hit(g: &Notch, open: bool, x: f64, y: f64) -> bool {
    let (rx, ry, rw, rh) = if open { rect(g, true) } else { (g.left, g.top, g.width, g.height) };
    x >= rx && x <= rx + rw && y >= ry - 2.0 && y <= ry + rh
}

/// 把窗口摆到收起/展开的位置。★ **只在主线程调**：`set_size` 本身会派发，但派发前读缩放
/// （`NSWindow.backingScaleFactor`）发生在调用线程；后台线程一律经 `place_soon`。
fn place(app: &AppHandle, open: bool) {
    let (Some(win), Some(g)) = (app.get_webview_window(LABEL), cached()) else { return };
    let (x, y, w, h) = rect(&g, open);
    let _ = win.set_size(LogicalSize::new(w, h));
    let _ = win.set_position(LogicalPosition::new(x, y));
    pass_clicks(&win, !open);
}

fn place_soon(app: &AppHandle, open: bool) {
    let a = app.clone();
    let _ = app.run_on_main_thread(move || place(&a, open));
}

/// ★ 收起态**不接鼠标**（四方评审 2026-10-17）：收起窗口比刘海左右各宽 7pt、向下多 7pt，
///   盖着菜单栏两侧和下面应用的顶边，接鼠标就会吞掉那里的点击、还会把自己变成 key window。
///   悬停判定本来就不靠窗口收事件（靠 NSEvent 监听 + 光标位置），所以收起时整个穿透没有代价。
fn pass_clicks(win: &tauri::WebviewWindow, through: bool) {
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    let Ok(ptr) = win.ns_window() else { return };
    if ptr.is_null() { return; }
    // SAFETY: 主线程；ptr 是本窗口仍存活的 NSWindow；只设一个 BOOL 属性。
    unsafe {
        let _: () = msg_send![ptr as *mut AnyObject, setIgnoresMouseEvents: through];
    }
}

/// Tauri 不给窗口层级与 Spaces 行为的接口，直接设到 NSWindow 上。必须在主线程。
fn raise(win: &tauri::WebviewWindow) {
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    let Ok(ptr) = win.ns_window() else { return };
    if ptr.is_null() { return; }
    // SAFETY: ptr 是本窗口仍存活的 NSWindow；只设置标量属性。
    unsafe {
        let w = ptr as *mut AnyObject;
        // NSStatusWindowLevel(25) + 1：盖过菜单栏(24)与状态栏图标。
        let _: () = msg_send![w, setLevel: 26isize];
        // canJoinAllSpaces | stationary | ignoresCycle | fullScreenAuxiliary
        // ★ 少了 fullScreenAuxiliary，切到全屏应用那一屏时它就不见了。
        let behavior: usize = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8);
        let _: () = msg_send![w, setCollectionBehavior: behavior];
        let _: () = msg_send![w, setHasShadow: false];
        let _: () = msg_send![w, setHidesOnDeactivate: false];
        let _: () = msg_send![w, setIgnoresMouseEvents: true];
        // ★ 不用 `win.show()`：tao 的 show 是 `makeKeyAndOrderFront`，`.focused(false)` 拦不住，
        //   刘海窗口一出现就抢走主窗口的键盘焦点（⌘1/2/3 失灵）。只排到最前、不当 key。
        let _: () = msg_send![w, orderFrontRegardless];
    }
}

/// 光标位置（桌面坐标：主屏左上为原点的逻辑 pt）。`+[NSEvent mouseLocation]` 给的是左下原点，翻一下。
/// ★ 唤醒（主线程）与跟踪（后台线程）**必须用同一套算法** —— 原来跟踪线程用
///   `cursor_position() / 刘海窗口的 scale`，而 tao 是按**主屏** scale 换的物理坐标：
///   主屏是 1× 外接屏、刘海在 2× 内建屏时坐标被减半，唤醒判进、跟踪判出，面板永远打不开。
///   `mouseLocation` 是只读类方法、tao 自己也在任意线程调它；后台线程不再碰 NSWindow / NSScreen。
fn mouse_desktop(g: &Notch) -> (f64, f64) {
    use objc2::{class, msg_send};
    // SAFETY: 类方法，无参数，返回值是值类型。
    let p: objc2_foundation::NSPoint = unsafe { msg_send![class!(NSEvent), mouseLocation] };
    (p.x, g.primary_h - p.y)
}

fn set_open(app: &AppHandle, open: bool) {
    if OPEN.swap(open, Ordering::SeqCst) == open { return; }
    let gen = OPEN_GEN.fetch_add(1, Ordering::SeqCst) + 1;
    if open {
        place_soon(app, true);
        let _ = app.emit_to(LABEL, "notch-open", true);
    } else {
        let _ = app.emit_to(LABEL, "notch-open", false);
        let app = app.clone();
        std::thread::spawn(move || {
            std::thread::sleep(COLLAPSE);
            // ★ 只收**这一轮**：中途又展开过一次再移出，旧计时醒来不许裁掉新一轮的动画。
            if OPEN_GEN.load(Ordering::SeqCst) == gen && !OPEN.load(Ordering::SeqCst) {
                place_soon(&app, false);
            }
        });
    }
}

/// 跟踪线程：光标进刘海区之后才存在，离开并收完就退出。
fn track(app: AppHandle) {
    let me = TRACKER_SEQ.fetch_add(1, Ordering::SeqCst) + 1;
    if TRACKER.compare_exchange(0, me, Ordering::SeqCst, Ordering::SeqCst).is_err() { return; }
    let gen = ENABLE_GEN.load(Ordering::SeqCst);
    std::thread::spawn(move || {
        let mut inside = true;
        let mut since = Instant::now();
        loop {
            std::thread::sleep(TRACK_TICK);
            if ENABLE_GEN.load(Ordering::SeqCst) != gen || !ENABLED.load(Ordering::SeqCst) { break; }
            let Some(g) = cached() else { break };
            let (x, y) = mouse_desktop(&g);
            let open = OPEN.load(Ordering::SeqCst);
            let now_in = hit(&g, open, x, y);
            if now_in != inside { inside = now_in; since = Instant::now(); }
            if inside && !open && since.elapsed() >= OPEN_DWELL {
                set_open(&app, true);
            } else if !inside && open && since.elapsed() >= CLOSE_DWELL {
                set_open(&app, false);
            } else if !inside && !open && since.elapsed() >= CLOSE_DWELL {
                break;   // 擦过没停够，或已经收完
            }
        }
        let _ = TRACKER.compare_exchange(me, 0, Ordering::SeqCst, Ordering::SeqCst);
    });
}

/// 建窗口（主线程）。已经有了就只摆位置。
fn ensure_window(app: &AppHandle, g: &Notch) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(LABEL) {
        raise(&w);
        place(app, OPEN.load(Ordering::SeqCst));
        // ★ `set_enabled` 每次都换代，旧的检测线程会因代次不符退出 —— 窗口还在就得接上一条新的
        watch_activity(app);
        return Ok(());
    }
    let (x, y, w, h) = rect(g, false);
    let win = tauri::webview::WebviewWindowBuilder::new(app, LABEL, WebviewUrl::App("notch.html".into()))
        .title("CodexBar Notch")
        .decorations(false)
        .transparent(true)
        .resizable(false)
        .skip_taskbar(true)
        .shadow(false)
        .focused(false)
        // ★ CodexBar 几乎从不在前台：不接首次点击的话，点面板只会激活窗口，「点这里打开」要点两下。
        .accept_first_mouse(true)
        .visible(false)
        .inner_size(w, h)
        .position(x, y)
        .build()
        .map_err(|e| e.to_string())?;
    raise(&win);
    watch_activity(app);
    Ok(())
}

fn drop_window(app: &AppHandle) {
    OPEN.store(false, Ordering::SeqCst);
    if let Some(w) = app.get_webview_window(LABEL) { let _ = w.destroy(); }
}

/// 刘海屏出现/消失/挪位置时让窗口跟上（主线程）。
/// ★ 原来 `geometry()` 读成 `None` 就直接 return：合盖后层级 26 的窗口留在原地、被系统挪到外接屏菜单栏正中
///   （一块黑块）；合盖时打开开关，开盖后也永远不出现（四方评审 2026-10-17）。
fn reconcile(app: &AppHandle) {
    let before = cached();
    let now = geometry();
    match now {
        None => if app.get_webview_window(LABEL).is_some() { drop_window(app); },
        Some(g) => {
            if app.get_webview_window(LABEL).is_none() {
                let _ = ensure_window(app, &g);
            } else if before != Some(g) {
                place(app, OPEN.load(Ordering::SeqCst));
                let _ = app.emit_to(LABEL, "notch-geom", g);
            }
        }
    }
}

/// 鼠标事件监听的回调（主线程）。先对齐几何，再看光标进没进刘海区，命中就叫醒跟踪线程。
fn on_mouse(app: &AppHandle) {
    if !ENABLED.load(Ordering::Relaxed) || TRACKER.load(Ordering::Relaxed) != 0 { return; }
    reconcile(app);
    let Some(g) = cached() else { return };
    let (x, y) = mouse_desktop(&g);
    if hit(&g, false, x, y) { track(app.clone()); }
}

fn install_monitors(app: &AppHandle) {
    use block2::RcBlock;
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use std::ptr::NonNull;
    let mut mons = MONITORS.lock().unwrap();
    if !mons.is_empty() { return; }
    // NSEventMaskMouseMoved | LeftMouseDragged | RightMouseDragged
    let mask: u64 = (1 << 5) | (1 << 6) | (1 << 7);
    let a1 = app.clone();
    let global = RcBlock::new(move |_e: NonNull<AnyObject>| on_mouse(&a1));
    let a2 = app.clone();
    let local = RcBlock::new(move |e: NonNull<AnyObject>| -> *mut AnyObject { on_mouse(&a2); e.as_ptr() });
    // SAFETY: AppKit 会 copy 这两个 block；返回的监听器对象由我们持有，`remove_monitors` 里释放。
    unsafe {
        let g: Option<Retained<AnyObject>> =
            msg_send![class!(NSEvent), addGlobalMonitorForEventsMatchingMask: mask, handler: &*global];
        let l: Option<Retained<AnyObject>> =
            msg_send![class!(NSEvent), addLocalMonitorForEventsMatchingMask: mask, handler: &*local];
        for m in [g, l].into_iter().flatten() {
            mons.push(Retained::into_raw(m) as usize);
        }
    }
}

fn remove_monitors() {
    use objc2::rc::Retained;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    let mut mons = MONITORS.lock().unwrap();
    for p in mons.drain(..) {
        // SAFETY: 指针来自 `install_monitors` 的 `Retained::into_raw`，只释放这一次。
        unsafe {
            let obj = Retained::from_raw(p as *mut AnyObject);
            if let Some(obj) = obj {
                let _: () = msg_send![class!(NSEvent), removeMonitor: &*obj];
            }
        }
    }
}

/// 开/关。开 = 装监听 +（有刘海屏时）建窗口；关 = 拆监听 + **销毁窗口**（不只是隐藏 —— 隐藏的
/// WKWebView 仍占着两个系统进程，默认关的功能不该常驻任何东西）。
/// ★ 监听**无论有没有刘海屏都装**：合盖时打开、之后开盖，下一次鼠标移动就由 `reconcile` 把窗口建出来。
/// ★ 调用方是**同步**命令（Tauri 2 的同步命令在主线程跑），这里要读 NSScreen、直接操作 NSWindow。
pub fn set_enabled(app: &AppHandle, on: bool) -> Result<Status, String> {
    ENABLE_GEN.fetch_add(1, Ordering::SeqCst);
    ENABLED.store(on, Ordering::SeqCst);
    if !on {
        remove_monitors();
        drop_window(app);
        return Ok(Status { active: false, reason: None });
    }
    install_monitors(app);
    *GEOM.lock().unwrap() = None;
    let Some(g) = geometry() else {
        return Ok(Status { active: false, reason: Some("no_notch") });
    };
    ensure_window(app, &g)?;
    Ok(Status { active: true, reason: None })
}

/// 设置页打开时问一句「现在有没有刘海屏」，不改任何状态（主线程）。
pub fn status() -> Status {
    let enabled = ENABLED.load(Ordering::SeqCst);
    match geometry() {
        Some(_) => Status { active: enabled, reason: None },
        None => Status { active: false, reason: Some("no_notch") },
    }
}

/// 一组文件里最新的修改时间（秒）。读不到的跳过。
fn newest_mtime<I: IntoIterator<Item = std::path::PathBuf>>(files: I) -> Option<u64> {
    files.into_iter()
        .filter_map(|p| std::fs::metadata(p).ok()?.modified().ok())
        .filter_map(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .max()
}

fn list(dir: &std::path::Path) -> Vec<std::path::PathBuf> {
    std::fs::read_dir(dir).map(|rd| rd.filter_map(|e| e.ok().map(|e| e.path())).collect()).unwrap_or_default()
}

/// Codex：最近 3 个日期目录里的 rollout。★ rollout 放在**会话开始那天**的目录里 ——
/// 昨天开的会话今天还在写 10/16，只看今天会漏；更早开的会话被续上时仍会漏（已知取舍，
/// 全量 stat 一千多个文件不值）。★ 不用 `state.json` 的 `last_proxy_ts`：codex 会定时
/// `GET /models`，代理照样刷新它，停手后仍显示「在跑」（2026-10-17 实测）。
fn codex_files(home: &std::path::Path) -> Vec<std::path::PathBuf> {
    let mut days = Vec::new();
    let mut years = list(&home.join("sessions"));
    years.sort();
    'outer: for y in years.iter().rev() {
        let mut months = list(y); months.sort();
        for m in months.iter().rev() {
            let mut ds = list(m); ds.sort();
            for d in ds.iter().rev() {
                days.push(d.clone());
                if days.len() >= 3 { break 'outer; }
            }
        }
    }
    days.iter().flat_map(|d| list(d)).filter(|p| {
        let n = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
        n.starts_with("rollout-") && n.ends_with(".jsonl")
    }).collect()
}

/// agy：对话库是 WAL 模式，生成时写的是 `-wal`（主库 mtime 不动，见 scan.py `_agy_db_sig`）。
fn agy_files(dir: &std::path::Path) -> Vec<std::path::PathBuf> {
    list(dir).into_iter().filter(|p| {
        let n = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
        n.ends_with(".db-wal") || n.ends_with(".db")
    }).collect()
}

fn active(newest: Option<u64>, now: u64) -> bool {
    newest.is_some_and(|t| now.saturating_sub(t) < ACTIVE_SECS)
}

/// 活动检测线程。只在状态**变了**才推 `notch-activity`。
/// ★ 只在**窗口存在**时跑（评审 2026-10-17）：由 `ensure_window` 起，窗口没了（合盖 / 外接屏 / 关掉）就退出，
///   刘海屏回来时 `reconcile` 建窗会再起一条 —— 开着但没有刘海屏时不再每 2s 扫一遍文件。
/// ★ 三条任一不满足就退：没被新的一条接管（`WATCHER`）、这一代没被开关过（`ENABLE_GEN`，同 `track`）、窗口还在。
fn watch_activity(app: &AppHandle) {
    let gen = ENABLE_GEN.load(Ordering::SeqCst);
    let me = WATCHER_SEQ.fetch_add(1, Ordering::SeqCst) + 1;
    WATCHER.store(me, Ordering::SeqCst);
    let app = app.clone();
    std::thread::spawn(move || {
        let home = std::path::PathBuf::from(std::env::var("HOME").unwrap_or_default());
        let codex_home = std::env::var("CODEX_HOME").map(std::path::PathBuf::from)
            .unwrap_or_else(|_| home.join(".codex"));
        let agy_dir = std::env::var("AGY_DB_DIR").map(std::path::PathBuf::from)
            .unwrap_or_else(|_| home.join(".gemini").join("antigravity-cli").join("conversations"));
        while WATCHER.load(Ordering::SeqCst) == me && ENABLE_GEN.load(Ordering::SeqCst) == gen
            && ENABLED.load(Ordering::SeqCst) && app.get_webview_window(LABEL).is_some()
        {
            let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs()).unwrap_or(0);
            let a = Activity {
                codex: active(newest_mtime(codex_files(&codex_home)), now),
                agy: active(newest_mtime(agy_files(&agy_dir)), now),
            };
            let changed = { let mut cur = ACTIVITY.lock().unwrap(); let c = *cur != a; *cur = a; c };
            if changed { let _ = app.emit_to(LABEL, "notch-activity", a); }
            std::thread::sleep(ACTIVITY_TICK);
        }
        // 被接管时状态归新的那条管，不清
        if WATCHER.compare_exchange(me, 0, Ordering::SeqCst, Ordering::SeqCst).is_ok() {
            *ACTIVITY.lock().unwrap() = Activity { codex: false, agy: false };
        }
    });
}

pub fn activity() -> Activity { *ACTIVITY.lock().unwrap() }

pub fn notch_geometry() -> Option<Notch> { cached() }

pub fn is_open() -> bool { OPEN.load(Ordering::SeqCst) }

/// 前端量出展开面板的自然高度后告诉这里（随额度窗口个数变）。
pub fn set_panel_height(app: &AppHandle, h: f64) {
    *PANEL_H.lock().unwrap() = h.clamp(80.0, 400.0);
    if OPEN.load(Ordering::SeqCst) { place_soon(app, true); }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn air13() -> Notch { Notch { left: 646.0, width: 179.0, height: 32.0, top: 0.0, primary_h: 956.0 } }

    #[test]
    fn collapsed_window_covers_notch_flares_and_glow_room() {
        assert_eq!(rect(&air13(), false), (579.0, 0.0, 313.0, 92.0));
    }
    #[test]
    fn the_glow_room_does_not_trigger() {
        let g = air13();
        assert!(!hit(&g, false, 620.0, 10.0), "光晕那圈是菜单栏");
        assert!(!hit(&g, false, 735.0, 40.0), "光晕下沿不算");
        assert!(hit(&g, false, 735.0, 30.0), "刘海本身算");
    }
    #[test]
    fn activity_is_recent_writes_only() {
        assert!(active(Some(1000), 1030));
        assert!(!active(Some(1000), 1000 + ACTIVE_SECS));
        assert!(!active(None, 1000));
    }
    #[test]
    fn codex_looks_at_the_three_newest_day_dirs() {
        let root = std::env::temp_dir().join(format!("notch-codex-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        for d in ["2026/09/30", "2026/10/01", "2026/10/16", "2026/10/17"] {
            let dir = root.join("sessions").join(d);
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join("rollout-x.jsonl"), b"").unwrap();
            std::fs::write(dir.join("rollout-x.jsonl.zst"), b"").unwrap();
        }
        let mut got: Vec<String> = codex_files(&root).iter()
            .map(|p| p.strip_prefix(root.join("sessions")).unwrap().to_string_lossy().into_owned()).collect();
        got.sort();
        assert_eq!(got, ["2026/10/01/rollout-x.jsonl", "2026/10/16/rollout-x.jsonl", "2026/10/17/rollout-x.jsonl"]);
        let _ = std::fs::remove_dir_all(&root);
    }
    #[test]
    fn open_panel_is_centred_on_the_notch() {
        let (x, _, w, _) = rect(&air13(), true);
        assert!(((x + w / 2.0) - (646.0 + 179.0 / 2.0)).abs() < 1e-9);
    }
    #[test]
    fn the_menubar_beside_the_notch_does_not_trigger() {
        let g = air13();
        assert!(hit(&g, false, 735.0, 10.0));
        assert!(!hit(&g, false, 641.0, 10.0), "左侧内凹圆角那 7pt 是菜单栏");
        assert!(!hit(&g, false, 735.0, 60.0));
    }
    #[test]
    fn notch_screen_as_primary_matches_the_measured_air() {
        // 13 寸 Air：屏 1470×956，左右 auxiliary 各 646 / 645 宽，safeArea.top 32
        let g = notch_from((0.0, 0.0, 1470.0, 956.0), 956.0, 32.0, 646.0, 645.0).unwrap();
        assert_eq!((g.left, g.width, g.height, g.top), (646.0, 179.0, 32.0, 0.0));
    }
    #[test]
    fn notch_screen_that_is_not_primary_is_offset_by_its_frame() {
        // 主屏 1920×1080 外接屏；内建刘海屏摆在它右边、底边对齐（AppKit 左下原点）
        let g = notch_from((1920.0, 0.0, 1470.0, 956.0), 1080.0, 32.0, 646.0, 645.0).unwrap();
        assert_eq!(g.left, 1920.0 + 646.0, "刘海 x 必须带上那块屏自己的 origin");
        assert_eq!(g.top, 1080.0 - 956.0, "那块屏顶边在桌面坐标里比主屏低 124pt");
    }
    #[test]
    fn a_screen_without_a_notch_has_none() {
        assert_eq!(notch_from((0.0, 0.0, 1920.0, 1080.0), 1080.0, 0.0, 0.0, 0.0), None);
        assert_eq!(notch_from((0.0, 0.0, 1470.0, 956.0), 956.0, 32.0, 800.0, 800.0), None);
    }
}
