import AppKit
import Carbon.HIToolbox
import Foundation

final class CdpWhaleLauncher: NSObject, NSApplicationDelegate {
    private var pendingTargets: [String] = []
    private var applicationReady = false
    private var launchRequestInFlight = false
    private var targetPID: pid_t?
    private var monitor: Timer?
    private var missingChecks = 0
    private var isForwardingActivation = false
    private var isShowingFailure = false
    private var terminationInFlight = false

    private lazy var userData: String = {
        ProcessInfo.processInfo.environment["WHALE_CDP_USER_DATA_DIR"]
            ?? "\(FileManager.default.homeDirectoryForCurrentUser.path)/.ai-control-center/browser-profiles/whale/9335/UserData"
    }()
    private lazy var profile: String = {
        ProcessInfo.processInfo.environment["WHALE_CDP_PROFILE_DIRECTORY"] ?? "Profile 1"
    }()
    private lazy var port: String = {
        ProcessInfo.processInfo.environment["WHALE_CDP_PORT"] ?? "9335"
    }()
    private let whale = "/Applications/Whale.app/Contents/MacOS/Whale"

    func applicationWillFinishLaunching(_ notification: Notification) {
        NSAppleEventManager.shared().setEventHandler(
            self,
            andSelector: #selector(handleGetURL(_:withReplyEvent:)),
            forEventClass: AEEventClass(kInternetEventClass),
            andEventID: AEEventID(kAEGetURL)
        )
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        applicationReady = true
        setBadge("…")
        startMonitor()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.openOrFocus()
        }
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        guard applicationReady, !isForwardingActivation, !isShowingFailure else { return }
        DispatchQueue.main.async { [weak self] in
            self?.openOrFocus()
        }
    }

    func applicationShouldHandleReopen(
        _ sender: NSApplication,
        hasVisibleWindows flag: Bool
    ) -> Bool {
        openOrFocus()
        return false
    }

    func applicationShouldTerminate(
        _ sender: NSApplication
    ) -> NSApplication.TerminateReply {
        if terminationInFlight {
            return .terminateLater
        }
        guard let listenerPID = listenerPID(),
              hasExpectedIdentity(pid: listenerPID) else {
            return .terminateNow
        }

        terminationInFlight = true
        monitor?.invalidate()
        setBadge("…")
        _ = kill(listenerPID, SIGTERM)
        waitForBrowserTermination(pid: listenerPID)
        return .terminateLater
    }

    func applicationWillTerminate(_ notification: Notification) {
        monitor?.invalidate()
        NSAppleEventManager.shared().removeEventHandler(
            forEventClass: AEEventClass(kInternetEventClass),
            andEventID: AEEventID(kAEGetURL)
        )
    }

    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        pendingTargets.append(contentsOf: filenames.map { URL(fileURLWithPath: $0).absoluteString })
        sender.reply(toOpenOrPrint: .success)
        openOrFocus()
    }

    @objc private func handleGetURL(
        _ event: NSAppleEventDescriptor,
        withReplyEvent replyEvent: NSAppleEventDescriptor
    ) {
        if let value = event.paramDescriptor(forKeyword: AEKeyword(keyDirectObject))?.stringValue,
           !value.isEmpty {
            pendingTargets.append(value)
        }
        openOrFocus()
    }

    private func openOrFocus() {
        guard applicationReady else { return }
        guard FileManager.default.fileExists(atPath: "\(userData)/\(profile)") else {
            failAndTerminate("CDP Whale profile missing: \(userData)/\(profile)")
            return
        }
        guard FileManager.default.isExecutableFile(atPath: whale) else {
            failAndTerminate("Whale executable missing: \(whale)")
            return
        }

        if pendingTargets.isEmpty,
           let targetPID,
           processExists(targetPID),
           hasExpectedIdentity(pid: targetPID),
           listenerPID() == targetPID {
            let page = ensurePageAvailable()
            guard page.available else {
                failAndTerminate("CDP Whale is running on port \(port), but it could not create a page to show.")
                return
            }
            if let targetID = page.targetToActivate {
                _ = activatePage(targetID: targetID)
            }
            activateBrowser(pid: targetPID)
            return
        }

        if let listenerPID = listenerPID() {
            guard hasExpectedIdentity(pid: listenerPID) else {
                failAndTerminate("Port \(port) is owned by a different browser or profile.")
                return
            }
            targetPID = listenerPID
            missingChecks = 0
            launchRequestInFlight = false
            let openedTarget = openPendingTargets()
            let page = ensurePageAvailable(preferredTargetID: openedTarget)
            guard page.available else {
                failAndTerminate("CDP Whale is running on port \(port), but it could not create a page to show.")
                return
            }
            if let targetID = page.targetToActivate {
                _ = activatePage(targetID: targetID)
            }
            activateBrowser(pid: listenerPID)
            return
        }

        guard !launchRequestInFlight else { return }
        launchRequestInFlight = true
        let process = Process()
        process.executableURL = URL(fileURLWithPath: whale)
        var arguments = [
            "--user-data-dir=\(userData)",
            "--profile-directory=\(profile)",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=\(port)",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        if pendingTargets.isEmpty {
            if hasRestorableSession() {
                arguments.append("--restore-last-session")
            } else {
                arguments.append(contentsOf: ["--new-window", "chrome://newtab/"])
            }
        } else {
            arguments.append(contentsOf: pendingTargets)
            pendingTargets.removeAll()
        }
        process.arguments = arguments

        do {
            try process.run()
            waitForEndpoint(expectedProcessPID: process.processIdentifier)
        } catch {
            launchRequestInFlight = false
            failAndTerminate("Failed to launch CDP Whale: \(error.localizedDescription)")
        }
    }

    private func hasRestorableSession() -> Bool {
        let sessions = "\(userData)/\(profile)/Sessions"
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: sessions) else {
            return false
        }
        return names.contains { $0.hasPrefix("Session_") || $0.hasPrefix("Tabs_") }
    }

    private func waitForEndpoint(expectedProcessPID: pid_t, attempt: Int = 0) {
        if let listenerPID = listenerPID() {
            guard hasExpectedIdentity(pid: listenerPID) else {
                launchRequestInFlight = false
                failAndTerminate("Port \(port) became owned by a different browser or profile.")
                return
            }
            targetPID = listenerPID
            missingChecks = 0
            launchRequestInFlight = false
            let openedTarget = openPendingTargets()
            let page = ensurePageAvailable(preferredTargetID: openedTarget)
            guard page.available else {
                guard attempt < 80 else {
                    failAndTerminate("CDP Whale started on port \(port), but it could not create a page to show.")
                    return
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
                    self?.waitForEndpoint(expectedProcessPID: expectedProcessPID, attempt: attempt + 1)
                }
                return
            }
            if let targetID = page.targetToActivate {
                _ = activatePage(targetID: targetID)
            }
            activateBrowser(pid: listenerPID)
            return
        }

        guard processExists(expectedProcessPID) else {
            launchRequestInFlight = false
            failAndTerminate("CDP Whale exited before port \(port) became ready.")
            return
        }
        guard attempt < 80 else {
            launchRequestInFlight = false
            failAndTerminate("CDP Whale did not expose port \(port) within 20 seconds.")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.waitForEndpoint(expectedProcessPID: expectedProcessPID, attempt: attempt + 1)
        }
    }

    private func activatePage(targetID: String) -> Bool {
        let response = run("/usr/bin/curl", [
            "--max-time", "2", "-fsS", "http://127.0.0.1:\(port)/json/activate/\(targetID)"
        ])
        return response.contains("Target activated")
    }

    private func openPendingTargets() -> String? {
        let targets = pendingTargets
        pendingTargets.removeAll()
        var lastTargetID: String?
        for target in targets {
            if let targetID = createPageTarget(target) {
                lastTargetID = targetID
            }
        }
        return lastTargetID
    }

    private func ensurePageAvailable(
        preferredTargetID: String? = nil
    ) -> (available: Bool, targetToActivate: String?) {
        if let preferredTargetID {
            return (true, preferredTargetID)
        }
        if existingPageTargetID() != nil {
            return (true, nil)
        }
        guard let createdTargetID = createPageTarget("chrome://newtab/") else {
            return (false, nil)
        }
        return (true, createdTargetID)
    }

    private func existingPageTargetID() -> String? {
        let response = run("/usr/bin/curl", [
            "--max-time", "2", "-fsS", "http://127.0.0.1:\(port)/json/list"
        ])
        guard let data = response.data(using: .utf8),
              let targets = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            return nil
        }
        return targets.first(where: { $0["type"] as? String == "page" })?["id"] as? String
    }

    private func createPageTarget(_ target: String) -> String? {
        let queryAllowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        guard let encodedTarget = target.addingPercentEncoding(withAllowedCharacters: queryAllowed) else {
            return nil
        }
        let endpoint = "http://127.0.0.1:\(port)/json/new?\(encodedTarget)"
        let response = run("/usr/bin/curl", [
            "--max-time", "2", "-fsS", "-X", "PUT", endpoint
        ])
        guard let data = response.data(using: .utf8),
              let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return result["id"] as? String
    }

    private func activateBrowser(pid: pid_t, remainingAttempts: Int = 8) {
        guard let running = NSRunningApplication(processIdentifier: pid) else {
            guard remainingAttempts > 1 else {
                failAndTerminate("CDP Whale is ready on port \(port), but macOS did not register its application identity.")
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                self?.activateBrowser(pid: pid, remainingAttempts: remainingAttempts - 1)
            }
            return
        }

        targetPID = pid
        isForwardingActivation = true
        let launcher = NSRunningApplication.current
        if #available(macOS 14.0, *) {
            NSApp.yieldActivation(to: running)
            _ = running.activate(from: launcher, options: [.activateAllWindows])
        } else {
            _ = running.activate(options: [.activateAllWindows])
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            guard let self else { return }
            self.isForwardingActivation = false
            self.refreshState()
        }
    }

    private func startMonitor() {
        monitor?.invalidate()
        monitor = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            self?.refreshState()
        }
        if let monitor {
            RunLoop.main.add(monitor, forMode: .common)
        }
    }

    private func waitForBrowserTermination(pid: pid_t, attempt: Int = 0) {
        guard processExists(pid), hasExpectedIdentity(pid: pid) else {
            targetPID = nil
            NSApp.reply(toApplicationShouldTerminate: true)
            return
        }

        if attempt == 20 {
            _ = kill(pid, SIGTERM)
        } else if attempt == 40 {
            _ = kill(pid, SIGKILL)
        } else if attempt >= 60 {
            fputs("CDP Whale did not exit after a verified Dock quit request.\n", stderr)
            NSApp.reply(toApplicationShouldTerminate: true)
            return
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.waitForBrowserTermination(pid: pid, attempt: attempt + 1)
        }
    }

    private func refreshState() {
        guard applicationReady, !isShowingFailure else { return }
        guard let targetPID else {
            setBadge("…")
            return
        }
        guard processExists(targetPID), let listenerPID = listenerPID() else {
            missingChecks += 1
            setBadge("…")
            if missingChecks >= 3 {
                NSApp.terminate(nil)
            }
            return
        }
        guard listenerPID == targetPID, hasExpectedIdentity(pid: listenerPID) else {
            failAndTerminate("Port \(port) no longer belongs to the expected CDP Whale process.")
            return
        }
        missingChecks = 0
        let isFrontmost = NSWorkspace.shared.frontmostApplication?.processIdentifier == targetPID
        setBadge(isFrontmost ? "▶" : "35")
    }

    private func setBadge(_ value: String) {
        if NSApp.dockTile.badgeLabel != value {
            NSApp.dockTile.badgeLabel = value
            NSApp.dockTile.display()
        }
    }

    private func listenerPID() -> pid_t? {
        let result = run("/usr/sbin/lsof", [
            "-nP", "-iTCP:\(port)", "-sTCP:LISTEN", "-t"
        ])
        return result
            .split(whereSeparator: { $0.isNewline })
            .compactMap { pid_t($0.trimmingCharacters(in: .whitespaces)) }
            .first
    }

    private func hasExpectedIdentity(pid: pid_t) -> Bool {
        let command = run("/bin/ps", ["-p", String(pid), "-o", "command="])
        return hasExpectedArguments(command)
    }

    private func hasExpectedArguments(_ command: String) -> Bool {
        command.contains(whale)
            && command.contains("--user-data-dir=\(userData)")
            && command.contains("--profile-directory=\(profile)")
            && command.contains("--remote-debugging-port=\(port)")
    }

    private func processExists(_ pid: pid_t) -> Bool {
        kill(pid, 0) == 0
    }

    private func run(_ executable: String, _ arguments: [String]) -> String {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return String(data: data, encoding: .utf8) ?? ""
        } catch {
            return ""
        }
    }

    private func failAndTerminate(_ message: String) {
        guard !isShowingFailure else { return }
        isShowingFailure = true
        monitor?.invalidate()
        setBadge("!")
        fputs("\(message)\n", stderr)
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = "CDP Whale 9335"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
        NSApp.terminate(nil)
    }
}

private extension StringProtocol {
    var isNewline: Bool {
        allSatisfy(\.isNewline)
    }
}

let application = NSApplication.shared
let launcher = CdpWhaleLauncher()
application.delegate = launcher
application.setActivationPolicy(.regular)
application.run()
