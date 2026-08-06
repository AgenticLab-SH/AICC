import AppKit
import Foundation

private struct NormalChromeConfiguration {
    let chromeApp: String
    let chromeExecutable: String
    let userData: String
    let profile: String
    let startURL: String

    static func load() throws -> NormalChromeConfiguration {
        let info = Bundle.main.infoDictionary ?? [:]
        func required(_ key: String) throws -> String {
            guard let value = info[key] as? String, !value.isEmpty else {
                throw NSError(
                    domain: "AICC.NormalChromeLauncher",
                    code: 2,
                    userInfo: [NSLocalizedDescriptionKey: "Missing launcher setting: \(key)"]
                )
            }
            return value
        }
        return NormalChromeConfiguration(
            chromeApp: try required("AICCChromeApplication"),
            chromeExecutable: try required("AICCChromeExecutable"),
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

final class NormalChromeDelegate: NSObject, NSApplicationDelegate {
    private var configuration: NormalChromeConfiguration?
    private var monitor: Timer?
    private var targetPID: pid_t?
    private var launching = false
    private var missingChecks = 0
    private var forwardingActivation = false
    private var showingFailure = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        do {
            configuration = try NormalChromeConfiguration.load()
        } catch {
            showFailure(error.localizedDescription)
            return
        }
        setBadge("…")
        startMonitor()
        focusOrLaunch()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        focusOrLaunch()
        return false
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first?.absoluteString else {
            focusOrLaunch()
            return
        }
        focusOrLaunch(url: url)
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        let status = NSMenuItem(title: targetPID == nil ? "일반 Chrome: 시작 대기" : "일반 Chrome: 실행 중", action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(NSMenuItem.separator())
        let focus = NSMenuItem(title: "일반 Chrome 열기", action: #selector(openFromDock(_:)), keyEquivalent: "")
        focus.target = self
        menu.addItem(focus)
        return menu
    }

    @objc private func openFromDock(_ sender: Any?) {
        focusOrLaunch()
    }

    private func startMonitor() {
        monitor = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            self?.refreshState()
        }
        if let monitor { RunLoop.main.add(monitor, forMode: .common) }
    }

    private func refreshState() {
        guard !showingFailure else { return }
        let exact = exactApplications()
        if exact.isEmpty {
            missingChecks += 1
            setBadge("…")
            if targetPID != nil, missingChecks >= 3 { NSApp.terminate(nil) }
        } else if exact.count == 1, let running = exact.first {
            targetPID = running.processIdentifier
            missingChecks = 0
            let frontmost = NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier
            setBadge(frontmost ? "▶" : "ON")
        } else {
            showFailure("둘 이상의 일반 Chrome 프로세스가 같은 프로필과 일치합니다. 런처가 임의로 선택하지 않습니다.")
        }
    }

    private func focusOrLaunch(url: String? = nil) {
        guard let configuration, !showingFailure else { return }
        let exact = exactApplications()
        if exact.count > 1 {
            showFailure("둘 이상의 일반 Chrome 프로세스가 같은 프로필과 일치합니다. 런처가 임의로 선택하지 않습니다.")
            return
        }
        if let running = exact.first {
            targetPID = running.processIdentifier
            missingChecks = 0
            if let url {
                forwardURL(configuration, url: url, running: running)
            } else {
                activate(running)
            }
            return
        }
        launchChrome(configuration, url: url ?? configuration.startURL)
    }

    private func launchChrome(_ configuration: NormalChromeConfiguration, url: String) {
        guard !launching else { return }
        launching = true
        setBadge("…")
        let openConfiguration = NSWorkspace.OpenConfiguration()
        openConfiguration.arguments = configuration.arguments(url: url)
        openConfiguration.createsNewApplicationInstance = true
        openConfiguration.activates = true
        NSWorkspace.shared.openApplication(
            at: URL(fileURLWithPath: configuration.chromeApp),
            configuration: openConfiguration
        ) { [weak self] running, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.launching = false
                if let error {
                    self.showFailure("일반 Google Chrome을 시작하지 못했습니다: \(error.localizedDescription)")
                    return
                }
                if let running {
                    self.targetPID = running.processIdentifier
                    self.activate(running)
                }
            }
        }
    }

    private func forwardURL(
        _ configuration: NormalChromeConfiguration,
        url: String,
        running: NSRunningApplication
    ) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: configuration.chromeExecutable)
        task.arguments = configuration.arguments(url: url)
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        do {
            try task.run()
            activate(running)
        } catch {
            showFailure("일반 Chrome 프로필로 링크를 전달하지 못했습니다: \(error.localizedDescription)")
        }
    }

    private func exactApplications() -> [NSRunningApplication] {
        guard let configuration else { return [] }
        return NSRunningApplication.runningApplications(withBundleIdentifier: "com.google.Chrome").filter {
            isNormalCommand(commandLine($0.processIdentifier), configuration)
        }
    }

    private func isNormalCommand(_ command: String, _ configuration: NormalChromeConfiguration) -> Bool {
        guard command == configuration.chromeExecutable || command.hasPrefix(configuration.chromeExecutable + " ") else {
            return false
        }
        guard !command.contains("--remote-debugging-port=") else { return false }
        let explicitRoot = command.contains("--user-data-dir=" + configuration.userData)
        let defaultRoot = !command.contains("--user-data-dir=")
        let explicitProfile = command.contains("--profile-directory=" + configuration.profile)
        let defaultProfile = !command.contains("--profile-directory=") && configuration.profile == "Default"
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

    private func activate(_ running: NSRunningApplication) {
        forwardingActivation = true
        if #available(macOS 14.0, *) {
            _ = running.activate(from: NSRunningApplication.current, options: [.activateAllWindows])
        } else {
            _ = running.activate(options: [.activateAllWindows])
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.forwardingActivation = false
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
        alert.messageText = "일반 Chrome 런처 오류"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = NormalChromeDelegate()
app.delegate = delegate
app.run()
