// CodexBar — native macOS menu-bar app for the codex-account-rotator pool.
// P1 display + P2 interaction: reads state.json, shows the active account's 5h remaining in the menu
// bar + a per-account dropdown; non-active accounts are clickable to switch; cool/uncool + refresh-all
// actions; native notifications (via osascript) ack switch/cool. Quota math mirrors the plugin's
// captured_at-aware win_remaining (a window past its reset is only "100%" when our snapshot predates
// the reset; otherwise used_percent is real). The rollout-tailing accuracy daemon (P3) keeps state.json
// current independently; CodexBar just reads + acts. Built with plain swiftc (no Xcode) → CodexBar.app.
import AppKit
import Foundation

let STORE = "/Users/you/Projects/tools/codex-account-rotator"
let STATE = STORE + "/state.json"
let ROT = STORE + "/codex-rotate"
// Version per CLAUDE.md: X.Y.Z+B. CFBundleShortVersionString = release baseline (X.Y.Z, bumped only on
// a real release), CFBundleVersion = build number (B, +1 per local build). Single source = Info.plist.
let _info = Bundle.main.infoDictionary
let VERSION = ((_info?["CFBundleShortVersionString"] as? String) ?? "0.1.0")
            + "+" + ((_info?["CFBundleVersion"] as? String) ?? "?")

func nowTS() -> Double { Date().timeIntervalSince1970 }

func winRemaining(_ w: [String: Any]?, _ capturedAt: Double) -> Double? {
    guard let w = w, let used = w["used_percent"] as? Double else { return nil }
    if let ra = w["resets_at"] as? Double, ra <= nowTS(), capturedAt > 0, capturedAt < ra { return 100.0 }
    return 100 - used
}

func fmtEta(_ ts: Any?) -> String {
    guard let ts = ts as? Double else { return "?" }
    let d = Int(ts - nowTS())
    if d <= 0 { return "已重置" }
    let h = d / 3600, m = (d % 3600) / 60
    if h >= 24 { return "\(h / 24)d\(h % 24)h" }
    return h > 0 ? "\(h)h" + String(format: "%02dm", m) : "\(m)m"
}

func fmtAge(_ ts: Any?) -> String {
    guard let ts = ts as? Double, ts > 0 else { return "?" }
    let d = Int(nowTS() - ts)
    if d < 90 { return "刚刚" }
    let h = d / 3600
    if h >= 24 { return "\(h / 24)d前" }
    return h > 0 ? "\(h)h前" : "\(d / 60)m前"
}

func bar(_ rem: Double, _ width: Int = 10) -> String {
    let r = max(0, min(100, rem))
    let full = Int((r / 100.0) * Double(width) + 0.0001)
    return "▕" + String(repeating: "█", count: full) + String(repeating: " ", count: max(0, width - full)) + "▏"
}

func colorFor(_ rem: Double) -> NSColor {
    rem <= 10 ? .systemRed : (rem <= 30 ? .systemOrange : .systemGreen)
}

final class Controller: NSObject {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    var timer: Timer?

    override init() {
        super.init()
        rebuild()
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in self?.rebuild() }
    }

    func loadState() -> [String: Any] {
        guard let data = FileManager.default.contents(atPath: STATE),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return [:] }
        return obj
    }

    func mono(_ s: String, _ color: NSColor? = nil, _ size: CGFloat = 12) -> NSAttributedString {
        var attrs: [NSAttributedString.Key: Any] = [.font: NSFont.monospacedSystemFont(ofSize: size, weight: .regular)]
        if let color = color { attrs[.foregroundColor] = color }
        return NSAttributedString(string: s, attributes: attrs)
    }

    // run a codex-rotate subcommand, then notify + rebuild. Commands are fast (state edit + auth copy).
    func runRot(_ args: [String], notify: String? = nil) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        p.arguments = ["python3", ROT] + args
        try? p.run()
        p.waitUntilExit()
        if let n = notify { notifyMac(n) }
        rebuild()
    }

    func notifyMac(_ msg: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        p.arguments = ["-e", "display notification \"\(msg)\" with title \"CodexBar\""]
        try? p.run()
    }

    func rebuild() {
        let st = loadState()
        let slots = st["slots"] as? [String: [String: Any]] ?? [:]
        let active = st["active"] as? String

        // ---- menu-bar title: active account's 5h remaining ----
        var title = "⚡ codex"
        if let active = active, let slot = slots[active], let q = slot["quota"] as? [String: Any] {
            let cap = q["captured_at"] as? Double ?? 0
            if let rem = winRemaining(q["primary"] as? [String: Any], cap) {
                let pr = q["primary"] as? [String: Any]
                title = "⚡ \(Int(rem))% · \(fmtEta(pr?["resets_at"]))"
            }
        }
        item.button?.title = title

        // ---- dropdown ----
        let menu = NSMenu()
        let header = NSMenuItem(); header.attributedTitle = mono("CODEX · 剩余额度 · CodexBar \(VERSION)", .secondaryLabelColor, 11)
        menu.addItem(header)
        menu.addItem(.separator())

        let ordered = slots.sorted { ($0.value["label"] as? String ?? "") < ($1.value["label"] as? String ?? "") }
        for (aid, slot) in ordered {
            let label = slot["label"] as? String ?? "?"
            let email = slot["email"] as? String ?? ""
            let q = slot["quota"] as? [String: Any]
            let dead = slot["auth_dead"] as? Bool ?? false
            let isActive = (aid == active)
            let dot = dead ? "⚠️" : (isActive ? "●" : "○")
            let snap = (!isActive && q != nil) ? "  · 快照 \(fmtAge(q?["captured_at"]))" : ""
            let head = NSMenuItem(); head.attributedTitle = mono("\(dot) \(label)\(snap)", nil, 13)
            if !isActive && !dead {                  // non-active → clickable to switch
                head.action = #selector(switchAccount(_:)); head.target = self; head.representedObject = label
            }
            menu.addItem(head)
            let subTxt = "   " + email + (dead ? "  · 失效,终端 \\codex login 复活" : "")
            let sub = NSMenuItem(); sub.attributedTitle = mono(subTxt, dead ? .systemRed : .secondaryLabelColor, 11)
            menu.addItem(sub)
            if let q = q {
                let cap = q["captured_at"] as? Double ?? 0
                for (key, name) in [("primary", "5h"), ("secondary", "周")] {
                    let w = q[key] as? [String: Any]
                    if let rem = winRemaining(w, cap) {
                        let line = "   \(name) \(bar(rem)) " + String(format: "%3d", Int(rem)) + "%  ↻\(fmtEta(w?["resets_at"]))"
                        let mi = NSMenuItem(); mi.attributedTitle = mono(line, colorFor(rem), 12)
                        menu.addItem(mi)
                    }
                }
            } else if !dead {
                let mi = NSMenuItem(); mi.attributedTitle = mono("   用量未知 · 刷新一次", .secondaryLabelColor, 11)
                menu.addItem(mi)
            }
            menu.addItem(.separator())
        }

        addAction(menu, "🔄 立即刷新全池额度（各号 +1% 5h）", #selector(refreshAll))
        addAction(menu, "❄️ 把当前号冷却 5h", #selector(coolCurrent))
        addAction(menu, "♻️ 清除所有冷却", #selector(uncoolAll))
        addAction(menu, "重新读取", #selector(reload), "r")
        addAction(menu, "退出 CodexBar", #selector(quitApp), "q")
        item.menu = menu
    }

    func addAction(_ menu: NSMenu, _ title: String, _ sel: Selector, _ key: String = "") {
        let mi = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        mi.target = self
        menu.addItem(mi)
    }

    @objc func switchAccount(_ sender: NSMenuItem) {
        guard let label = sender.representedObject as? String else { return }
        runRot(["switch", label], notify: "已切换到 \(label)（下次 codex/cxp 生效）")
    }
    @objc func coolCurrent() { runRot(["cool", "300"], notify: "当前号已冷却 5h") }
    @objc func uncoolAll() { runRot(["uncool", "all"], notify: "已清除所有冷却") }
    @objc func refreshAll() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        p.arguments = ["python3", ROT, "refresh-all", "--notify"]
        try? p.run()  // async (~2s); the 10s timer picks up fresh state, refresh-all itself notifies
    }
    @objc func reload() { rebuild() }
    @objc func quitApp() { NSApp.terminate(nil) }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = Controller()
app.run()
