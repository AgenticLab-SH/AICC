import AppKit
import CoreGraphics
import Foundation

private struct NormalWhaleConfiguration {
    let whaleApp: String
    let whaleExecutable: String
    let userData: String
    let profile: String
    let startURL: String

    static func load() throws -> NormalWhaleConfiguration {
        let info = Bundle.main.infoDictionary ?? [:]
        func required(_ key: String) throws -> String {
            guard let value = info[key] as? String, !value.isEmpty else {
                throw NSError(
                    domain: "AICC.NormalWhaleLauncher",
                    code: 2,
                    userInfo: [NSLocalizedDescriptionKey: "Missing launcher setting: \(key)"]
                )
            }
            return value
        }
        return NormalWhaleConfiguration(
            whaleApp: try required("AICCWhaleApplication"),
            whaleExecutable: try required("AICCWhaleExecutable"),
            userData: try required("AICCUserData"),
            profile: try required("AICCProfileDirectory"),
            startURL: try required("AICCStartURL")
        )
    }

    func arguments(url: String) -> [String] {
        [
            "--user-data-dir=" + userData,
            "--profile-directory=" + profile,
            "--new-window",
            url
        ]
    }
}

final class NormalWhaleDelegate: NSObject, NSApplicationDelegate {
    private var configuration: NormalWhaleConfiguration?
    private var targetPID: pid_t?
    private var launching = false
    private var showingFailure = false
    private var observers: [NSObjectProtocol] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        do {
            configuration = try NormalWhaleConfiguration.load()
        } catch {
            showFailure(error.localizedDescription)
            return
        }
        observeWorkspace()
        setBadge("…")
        focusOrLaunch()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        focusOrLaunch()
        return false
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        let title = targetPID == nil ? "일반 Whale: 시작 대기" : "일반 Whale: 실행 중"
        let status = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(NSMenuItem.separator())
        let focus = NSMenuItem(title: "일반 Whale 열기", action: #selector(openFromDock(_:)), keyEquivalent: "")
        focus.target = self
        menu.addItem(focus)
        return menu
    }

    @objc private func openFromDock(_ sender: Any?) {
        focusOrLaunch()
    }

    private func observeWorkspace() {
        let center = NSWorkspace.shared.notificationCenter
        observers.append(center.addObserver(
            forName: NSWorkspace.didLaunchApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in self?.refreshState() })
        observers.append(center.addObserver(
            forName: NSWorkspace.didTerminateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in self?.refreshState() })
    }

    private func refreshState() {
        guard !showingFailure else { return }
        let exact = exactApplications()
        if exact.isEmpty {
            targetPID = nil
            setBadge(launching ? "…" : nil)
            if !launching { NSApp.terminate(nil) }
        } else if exact.count == 1, let running = exact.first {
            targetPID = running.processIdentifier
            setBadge(isFrontmost(running) ? "▶" : "ON")
        } else {
            showFailure("둘 이상의 일반 Whale 프로세스가 같은 프로필과 일치합니다. 런처가 임의로 선택하지 않습니다.")
        }
    }

    private func focusOrLaunch() {
        guard let configuration, !showingFailure else { return }
        let exact = exactApplications()
        if exact.count > 1 {
            showFailure("둘 이상의 일반 Whale 프로세스가 같은 프로필과 일치합니다. 런처가 임의로 선택하지 않습니다.")
            return
        }
        if let running = exact.first {
            targetPID = running.processIdentifier
            if hasOnScreenWindow(running.processIdentifier) {
                activate(running)
            } else {
                openWindow(configuration, running: running)
            }
            return
        }
        launchWhale(configuration)
    }

    private func launchWhale(_ configuration: NormalWhaleConfiguration) {
        guard !launching else { return }
        launching = true
        setBadge("…")
        let openConfiguration = NSWorkspace.OpenConfiguration()
        openConfiguration.arguments = configuration.arguments(url: configuration.startURL)
        openConfiguration.createsNewApplicationInstance = true
        openConfiguration.activates = true
        NSWorkspace.shared.openApplication(
            at: URL(fileURLWithPath: configuration.whaleApp),
            configuration: openConfiguration
        ) { [weak self] _, error in
            DispatchQueue.main.async {
                guard let self else { return }
                if let error {
                    self.launching = false
                    self.showFailure("일반 NAVER Whale을 시작하지 못했습니다: \(error.localizedDescription)")
                    return
                }
                self.finishLaunchVerification(attempt: 0)
            }
        }
    }

    private func finishLaunchVerification(attempt: Int) {
        let exact = exactApplications()
        if exact.count > 1 {
            launching = false
            showFailure("둘 이상의 일반 Whale 프로세스가 같은 프로필과 일치합니다. 런처가 임의로 선택하지 않습니다.")
            return
        }
        if let running = exact.first {
            launching = false
            targetPID = running.processIdentifier
            activate(running)
            return
        }
        guard attempt < 30 else {
            launching = false
            showFailure("일반 NAVER Whale이 검증된 프로필로 시작되지 않았습니다.")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            self?.finishLaunchVerification(attempt: attempt + 1)
        }
    }

    private func openWindow(_ configuration: NormalWhaleConfiguration, running: NSRunningApplication) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: configuration.whaleExecutable)
        task.arguments = configuration.arguments(url: configuration.startURL)
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        do {
            try task.run()
            activate(running)
        } catch {
            showFailure("일반 Whale 프로필로 창을 열지 못했습니다: \(error.localizedDescription)")
        }
    }

    private func exactApplications() -> [NSRunningApplication] {
        guard let configuration else { return [] }
        return NSRunningApplication.runningApplications(withBundleIdentifier: "com.naver.Whale").filter {
            isNormalCommand(commandLine($0.processIdentifier), configuration)
        }
    }

    private func isNormalCommand(_ command: String, _ configuration: NormalWhaleConfiguration) -> Bool {
        guard command == configuration.whaleExecutable || command.hasPrefix(configuration.whaleExecutable + " ") else {
            return false
        }
        guard !command.contains("--remote-debugging-port=") else { return false }
        let explicitRoot = command.contains("--user-data-dir=" + configuration.userData)
        let defaultRoot = !command.contains("--user-data-dir=")
        let explicitProfile = command.contains("--profile-directory=" + configuration.profile)
        let defaultProfile = !command.contains("--profile-directory=")
        return (explicitRoot || defaultRoot) && (explicitProfile || defaultProfile)
    }

    private func commandLine(_ pid: pid_t) -> String {
        let task = Process()
        let pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: "/bin/ps")
        task.arguments = ["-p", String(pid), "-o", "command="]
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        try? task.run()
        task.waitUntilExit()
        return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private func hasOnScreenWindow(_ pid: pid_t) -> Bool {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return true
        }
        return windows.contains { item in
            let owner = item[kCGWindowOwnerPID as String] as? Int
            let layer = item[kCGWindowLayer as String] as? Int
            return owner == Int(pid) && layer == 0
        }
    }

    private func isFrontmost(_ running: NSRunningApplication) -> Bool {
        NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier
    }

    private func activate(_ running: NSRunningApplication) {
        _ = running.activate(options: [.activateAllWindows])
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.refreshState()
        }
    }

    private func setBadge(_ value: String?) {
        NSApp.dockTile.badgeLabel = value
        NSApp.dockTile.display()
    }

    private func showFailure(_ message: String) {
        guard !showingFailure else { return }
        showingFailure = true
        setBadge("!")
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "일반 Whale 런처 오류"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = NormalWhaleDelegate()
app.delegate = delegate
app.run()
