import AppKit
import Foundation

private struct SlotConfiguration {
    let appName: String
    let chromeApp: String
    let chromeExecutable: String
    let userData: String
    let profile: String
    let port: String
    let startURL: String
    let badgeExtension: String

    /// Chrome launch arguments shared by the cold-start and new-window paths.
    /// `--load-extension` is intentionally absent: current Google Chrome
    /// removed that switch, so the identity badge is installed over CDP once
    /// the slot's page window exists.
    var chromeArguments: [String] {
        [
            "--user-data-dir=" + userData,
            "--profile-directory=" + profile,
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=" + port,
            "--new-window",
            startURL
        ]
    }

    var hasBadgeExtension: Bool {
        !badgeExtension.isEmpty &&
            FileManager.default.fileExists(atPath: badgeExtension + "/manifest.json")
    }

    /// The badge renders the last two digits of this slot's port.
    var badgeSlotLabel: String { String(port.suffix(2)) }

    static func load() throws -> SlotConfiguration {
        let info = Bundle.main.infoDictionary ?? [:]

        func required(_ key: String) throws -> String {
            guard let value = info[key] as? String, !value.isEmpty else {
                throw NSError(
                    domain: "AICC.CdpChromeStatusLauncher",
                    code: 2,
                    userInfo: [NSLocalizedDescriptionKey: "Missing launcher setting: \(key)"]
                )
            }
            return value
        }

        let environment = ProcessInfo.processInfo.environment
        let userDataEnvironment = try required("AICCUserDataEnvironment")
        let profileEnvironment = try required("AICCProfileEnvironment")
        let portEnvironment = try required("AICCPortEnvironment")
        let defaultUserData = try required("AICCUserData")
        let defaultProfile = try required("AICCProfileDirectory")
        let defaultPort = try required("AICCPort")

        return SlotConfiguration(
            appName: (info["CFBundleDisplayName"] as? String) ?? "CDP Chrome",
            chromeApp: try required("AICCChromeApplication"),
            chromeExecutable: try required("AICCChromeExecutable"),
            userData: environment[userDataEnvironment] ?? defaultUserData,
            profile: environment[profileEnvironment] ?? defaultProfile,
            port: environment[portEnvironment] ?? defaultPort,
            startURL: try required("AICCStartURL"),
            badgeExtension: (info["AICCBadgeExtension"] as? String) ?? ""
        )
    }
}

private enum SlotResolution {
    case ready(NSRunningApplication)
    case starting(NSRunningApplication)
    case registering(pid_t)
    case absent
    case conflict(String)
}

private enum PageTargetState {
    case present
    case absent
    case unavailable
}

private final class WebSocketOpenGate: NSObject, URLSessionWebSocketDelegate {
    private let lock = NSLock()
    private var resolved = false
    var completion: ((Result<Void, Error>) -> Void)?

    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        resolve(.success(()))
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        guard let error else { return }
        resolve(.failure(error))
    }

    func failIfPending(_ error: Error) {
        resolve(.failure(error))
    }

    private func resolve(_ result: Result<Void, Error>) {
        lock.lock()
        guard !resolved else {
            lock.unlock()
            return
        }
        resolved = true
        let callback = completion
        lock.unlock()
        callback?(result)
    }
}

final class LauncherDelegate: NSObject, NSApplicationDelegate {
    private var configuration: SlotConfiguration?
    private var monitor: Timer?
    private var targetPID: pid_t?
    private var launchDeadline: Date?
    private var missingChecks = 0
    private var didFinishLaunching = false
    private var launchRequestInFlight = false
    private var windowRequestInFlight = false
    private var windowRequestProcess: Process?
    private var isForwardingActivation = false
    private var isShowingFailure = false
    private var badgeInstallInFlight = false
    private var backgroundLaunchRequested = false
    /// Browser process the badge was last installed into.
    ///
    /// `Extensions.loadUnpacked` is not written to the profile, so the badge is
    /// lost whenever Chrome exits. Tracking the owning PID instead of a plain
    /// flag makes the launcher reinstall the badge for each new browser process,
    /// including after a browser or machine restart.
    private var badgeInstalledForPID: pid_t?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        do {
            configuration = try SlotConfiguration.load()
        } catch {
            showFailure(error.localizedDescription)
            return
        }

        didFinishLaunching = true
        backgroundLaunchRequested = ProcessInfo.processInfo.environment["AICC_BACKGROUND_LAUNCH"] == "1"
        setBadge("…")
        startMonitor()
        focusOrLaunch(activateWhenReady: !backgroundLaunchRequested)
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        guard didFinishLaunching, !backgroundLaunchRequested, !isForwardingActivation, !isShowingFailure else { return }
        DispatchQueue.main.async { [weak self] in
            self?.focusOrLaunch()
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        backgroundLaunchRequested = false
        focusOrLaunch()
        return false
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        guard let configuration else { return nil }
        let menu = NSMenu()
        let state = NSMenuItem(title: dockMenuStatus(), action: nil, keyEquivalent: "")
        state.isEnabled = false
        menu.addItem(state)
        menu.addItem(NSMenuItem.separator())
        let focus = NSMenuItem(
            title: "Focus \(configuration.appName)",
            action: #selector(focusFromDockMenu(_:)),
            keyEquivalent: ""
        )
        focus.target = self
        menu.addItem(focus)
        return menu
    }

    @objc private func focusFromDockMenu(_ sender: Any?) {
        focusOrLaunch()
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

    private func refreshState() {
        guard configuration != nil, !isShowingFailure else { return }
        switch resolveSlot() {
        case .ready(let running):
            targetPID = running.processIdentifier
            launchDeadline = nil
            missingChecks = 0
            // A replacement browser process has no badge yet, because the badge
            // is not persisted in the profile. Reinstall it without waiting for
            // the user to click the launcher again.
            if let configuration, badgeInstalledForPID != running.processIdentifier {
                installBadgeExtension(configuration)
            }
            let isFrontmost = NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier
            setBadge(isFrontmost ? "▶" : "ON")
        case .starting(let running):
            targetPID = running.processIdentifier
            missingChecks = 0
            setBadge("…")
            if let launchDeadline, Date() > launchDeadline {
                showFailure("Official Google Chrome started, but CDP port \(configuration?.port ?? "") did not become ready.")
            }
        case .registering(let listener):
            targetPID = listener
            missingChecks = 0
            setBadge("…")
            launchDeadline = launchDeadline ?? Date(timeIntervalSinceNow: 12)
            if let launchDeadline, Date() > launchDeadline {
                showFailure("The expected Google Chrome process is listening on CDP port \(configuration?.port ?? "") as PID \(listener), but macOS did not register its application identity before the timeout.")
            }
        case .absent:
            missingChecks += 1
            setBadge("…")
            if targetPID != nil, missingChecks >= 3 {
                monitor?.invalidate()
                NSApp.terminate(nil)
            }
        case .conflict(let message):
            showFailure(message)
        }
    }

    private func focusOrLaunch(activateWhenReady: Bool = true) {
        guard let configuration, !isShowingFailure else { return }
        switch resolveSlot() {
        case .ready(let running):
            targetPID = running.processIdentifier
            launchDeadline = nil
            missingChecks = 0
            switch pageTargetState(configuration.port) {
            case .absent:
                requestNewWindow(configuration, running, activateWhenReady: activateWhenReady)
            case .present, .unavailable:
                installBadgeExtension(configuration)
                if activateWhenReady { activate(running) }
            }
        case .starting(let running):
            targetPID = running.processIdentifier
            launchDeadline = launchDeadline ?? Date(timeIntervalSinceNow: 12)
            missingChecks = 0
            setBadge("…")
        case .registering(let listener):
            targetPID = listener
            launchDeadline = launchDeadline ?? Date(timeIntervalSinceNow: 12)
            missingChecks = 0
            setBadge("…")
        case .absent:
            if launchRequestInFlight {
                setBadge("…")
            } else {
                launchChrome(configuration, activateWhenReady: activateWhenReady)
            }
        case .conflict(let message):
            showFailure(message)
        }
    }

    private func activate(_ running: NSRunningApplication, remainingAttempts: Int = 6) {
        isForwardingActivation = true
        if #available(macOS 14.0, *) {
            let launcher = NSRunningApplication.current
            NSApp.yieldActivation(to: running)
            _ = running.activate(from: launcher, options: [.activateAllWindows])
        } else {
            _ = running.activate(options: [.activateAllWindows])
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            guard let self else { return }
            if NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier ||
                remainingAttempts <= 1 {
                self.isForwardingActivation = false
                self.refreshState()
                return
            }
            self.activate(running, remainingAttempts: remainingAttempts - 1)
        }
    }

    private func requestNewWindow(_ configuration: SlotConfiguration, _ running: NSRunningApplication, activateWhenReady: Bool) {
        guard !windowRequestInFlight else { return }
        windowRequestInFlight = true
        setBadge("…")

        // Chrome keeps the browser process alive briefly after its last page
        // closes. Let that teardown settle before asking that exact process for
        // a replacement window.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.75) { [weak self] in
            guard let self, self.windowRequestInFlight else { return }
            self.startWindowRequestProcess(configuration, running, activateWhenReady: activateWhenReady)
        }
    }

    private func startWindowRequestProcess(
        _ configuration: SlotConfiguration,
        _ running: NSRunningApplication,
        activateWhenReady: Bool,
        beginWaiting: Bool = true
    ) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: configuration.chromeExecutable)
        task.arguments = configuration.chromeArguments
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice

        do {
            try task.run()
            windowRequestProcess = task
            if beginWaiting {
                waitForPageWindow(configuration, running, activateWhenReady: activateWhenReady, remainingChecks: 40)
            }
        } catch {
            windowRequestInFlight = false
            windowRequestProcess = nil
            showFailure("The exact Chrome slot is running without a page window, and a new window could not be requested: \(error.localizedDescription)")
        }
    }

    private func waitForPageWindow(
        _ configuration: SlotConfiguration,
        _ running: NSRunningApplication,
        activateWhenReady: Bool,
        remainingChecks: Int
    ) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            guard let self, self.windowRequestInFlight else { return }
            if self.pageTargetState(configuration.port) == .present {
                self.positionPageWindowOnMainScreen(configuration) { [weak self] result in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        self.windowRequestInFlight = false
                        self.windowRequestProcess = nil
                        switch result {
                        case .success:
                            self.installBadgeExtension(configuration)
                            if activateWhenReady { self.activate(running) }
                        case .failure(let error):
                            self.showFailure("The exact Chrome slot opened a page window, but the window could not be placed on the main screen: \(error.localizedDescription)")
                        }
                    }
                }
                return
            }
            // A just-closed Chrome window can consume the first command while
            // its native teardown is still finishing. Retry only while this
            // same verified slot still has no page target, and keep the
            // original bounded wait as the single source of timeout state.
            if remainingChecks == 32 || remainingChecks == 24 {
                self.startWindowRequestProcess(configuration, running, activateWhenReady: activateWhenReady, beginWaiting: false)
            }
            if remainingChecks <= 1 {
                self.windowRequestInFlight = false
                self.windowRequestProcess = nil
                self.showFailure("The exact Chrome slot is listening on port \(configuration.port), but its page window did not open before the timeout.")
                return
            }
            self.waitForPageWindow(configuration, running, activateWhenReady: activateWhenReady, remainingChecks: remainingChecks - 1)
        }
    }

    private func launchChrome(_ configuration: SlotConfiguration, activateWhenReady: Bool) {
        guard !launchRequestInFlight else { return }
        launchRequestInFlight = true
        setBadge("…")
        launchDeadline = Date(timeIntervalSinceNow: 12)
        missingChecks = 0

        let openConfiguration = NSWorkspace.OpenConfiguration()
        openConfiguration.arguments = configuration.chromeArguments
        openConfiguration.createsNewApplicationInstance = true
        openConfiguration.activates = activateWhenReady

        NSWorkspace.shared.openApplication(
            at: URL(fileURLWithPath: configuration.chromeApp),
            configuration: openConfiguration
        ) { [weak self] running, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.launchRequestInFlight = false
                if let error {
                    self.showFailure("Official Google Chrome could not be started: \(error.localizedDescription)")
                    return
                }
                if let running {
                    self.targetPID = running.processIdentifier
                    self.windowRequestInFlight = true
                    self.waitForPageWindow(configuration, running, activateWhenReady: activateWhenReady, remainingChecks: 40)
                }
            }
        }
    }

    private func resolveSlot() -> SlotResolution {
        guard let configuration else { return .absent }
        let chromeApplications = NSRunningApplication.runningApplications(withBundleIdentifier: "com.google.Chrome")
        let listeners = listenerPIDs(configuration.port)
        if listeners.count > 1 {
            return .conflict("CDP port \(configuration.port) has multiple listener processes: \(listeners.map(String.init).joined(separator: ", ")).")
        }
        if let listener = listeners.first {
            let mismatches = listenerIdentityMismatches(listener, configuration)
            guard mismatches.isEmpty else {
                return .conflict("Port \(configuration.port) listener PID \(listener) does not match the required Chrome slot identity (\(mismatches.joined(separator: ", "))). The launcher will not attach to it.")
            }
            guard let running = chromeApplications.first(where: { $0.processIdentifier == listener }) else {
                // Chrome can bind the CDP socket just before LaunchServices publishes
                // its NSRunningApplication. The process identity already matches, so
                // wait for registration instead of reporting a false port conflict.
                return .registering(listener)
            }
            return .ready(running)
        }

        let exactApplications = chromeApplications.filter {
            isExactCommand(commandLine($0.processIdentifier), configuration)
        }
        if exactApplications.count > 1 {
            return .conflict("More than one Google Chrome process matches CDP port \(configuration.port) and its profile.")
        }
        if let exact = exactApplications.first {
            return .starting(exact)
        }
        return .absent
    }

    private func isExactCommand(_ command: String, _ configuration: SlotConfiguration) -> Bool {
        command.hasPrefix(configuration.chromeExecutable + " ") &&
            command.contains("--remote-debugging-port=" + configuration.port) &&
            command.contains("--user-data-dir=" + configuration.userData) &&
            command.contains("--profile-directory=" + configuration.profile)
    }

    private func listenerIdentityMismatches(_ pid: pid_t, _ configuration: SlotConfiguration) -> [String] {
        let command = commandLine(pid)
        var mismatches: [String] = []
        if executablePath(pid) != configuration.chromeExecutable ||
            !command.hasPrefix(configuration.chromeExecutable + " ") {
            mismatches.append("executable")
        }
        if !command.contains("--remote-debugging-port=" + configuration.port) {
            mismatches.append("port")
        }
        if !command.contains("--user-data-dir=" + configuration.userData) {
            mismatches.append("user-data")
        }
        if !command.contains("--profile-directory=" + configuration.profile) {
            mismatches.append("profile")
        }
        return mismatches
    }

    private func commandLine(_ pid: pid_t) -> String {
        run("/bin/ps", ["-p", String(pid), "-o", "command="])
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func executablePath(_ pid: pid_t) -> String {
        run("/bin/ps", ["-p", String(pid), "-o", "comm="])
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func listenerPIDs(_ port: String) -> [pid_t] {
        run("/usr/sbin/lsof", ["-nP", "-iTCP:" + port, "-sTCP:LISTEN", "-t"])
            .split(whereSeparator: \.isNewline)
            .compactMap { pid_t($0) }
    }

    private func pageTargetState(_ port: String) -> PageTargetState {
        let response = run(
            "/usr/bin/curl",
            ["-fsS", "--max-time", "1", "http://127.0.0.1:" + port + "/json/list"]
        )
        guard let data = response.data(using: .utf8), !data.isEmpty,
              let object = try? JSONSerialization.jsonObject(with: data),
              let targets = object as? [[String: Any]] else {
            return .unavailable
        }
        return targets.contains { ($0["type"] as? String) == "page" } ? .present : .absent
    }

    private func firstPageTargetID(_ port: String) -> String? {
        let response = run(
            "/usr/bin/curl",
            ["-fsS", "--max-time", "1", "http://127.0.0.1:" + port + "/json/list"]
        )
        guard let data = response.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              let targets = object as? [[String: Any]] else {
            return nil
        }
        return targets.first { ($0["type"] as? String) == "page" }?["id"] as? String
    }

    private func browserWebSocketURL(_ port: String) -> URL? {
        let response = run(
            "/usr/bin/curl",
            ["-fsS", "--max-time", "1", "http://127.0.0.1:" + port + "/json/version"]
        )
        guard let data = response.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              let version = object as? [String: Any],
              let value = version["webSocketDebuggerUrl"] as? String else {
            return nil
        }
        return URL(string: value)
    }

    private func positionPageWindowOnMainScreen(
        _ configuration: SlotConfiguration,
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard let targetID = firstPageTargetID(configuration.port) else {
            completion(.failure(launcherError("The page target ID is unavailable.")))
            return
        }
        guard let socketURL = browserWebSocketURL(configuration.port) else {
            completion(.failure(launcherError("The browser WebSocket endpoint is unavailable.")))
            return
        }
        guard let screen = NSScreen.screens.first else {
            completion(.failure(launcherError("The main screen geometry is unavailable.")))
            return
        }

        let frame = screen.visibleFrame
        let bounds: [String: Any] = [
            "left": 60,
            "top": 60,
            "width": max(320, Int(frame.width) - 120),
            "height": max(240, Int(frame.height) - 120)
        ]
        let connectionGate = WebSocketOpenGate()
        let session = URLSession(
            configuration: .ephemeral,
            delegate: connectionGate,
            delegateQueue: nil
        )
        let socket = session.webSocketTask(with: socketURL)
        connectionGate.completion = { [weak self] connectionResult in
            guard let self else { return }
            switch connectionResult {
            case .failure(let error):
                socket.cancel(with: .goingAway, reason: nil)
                session.invalidateAndCancel()
                completion(.failure(error))
            case .success:
                self.sendCDP(
                    socket,
                    id: 1,
                    method: "Browser.getWindowForTarget",
                    params: ["targetId": targetID]
                ) { [weak self] result in
                    guard let self else { return }
                    switch result {
                    case .failure(let error):
                        socket.cancel(with: .goingAway, reason: nil)
                        session.invalidateAndCancel()
                        completion(.failure(error))
                    case .success(let payload):
                        guard let number = payload["windowId"] as? NSNumber else {
                            socket.cancel(with: .goingAway, reason: nil)
                            session.invalidateAndCancel()
                            completion(.failure(self.launcherError("Chrome did not return a window ID.")))
                            return
                        }
                        self.normalizeAndPositionWindow(
                            socket,
                            session: session,
                            windowID: number.intValue,
                            bounds: bounds,
                            completion: completion
                        )
                    }
                }
            }
        }
        socket.resume()
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 3) { [weak self, weak connectionGate] in
            guard let self else { return }
            connectionGate?.failIfPending(self.launcherError("The browser WebSocket did not connect before the timeout."))
        }
    }

    private func normalizeAndPositionWindow(
        _ socket: URLSessionWebSocketTask,
        session: URLSession,
        windowID: Int,
        bounds: [String: Any],
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        sendCDP(
            socket,
            id: 2,
            method: "Browser.setWindowBounds",
            params: ["windowId": windowID, "bounds": ["windowState": "normal"]]
        ) { [weak self] normalizeResult in
            guard let self else { return }
            switch normalizeResult {
            case .failure(let error):
                socket.cancel(with: .goingAway, reason: nil)
                session.invalidateAndCancel()
                completion(.failure(error))
            case .success:
                self.sendCDP(
                    socket,
                    id: 3,
                    method: "Browser.setWindowBounds",
                    params: ["windowId": windowID, "bounds": bounds]
                ) { moveResult in
                    socket.cancel(with: .goingAway, reason: nil)
                    session.finishTasksAndInvalidate()
                    completion(moveResult.map { _ in () })
                }
            }
        }
    }

    private func sendCDP(
        _ socket: URLSessionWebSocketTask,
        id: Int,
        method: String,
        params: [String: Any],
        sessionId: String? = nil,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        var message: [String: Any] = ["id": id, "method": method, "params": params]
        if let sessionId {
            message["sessionId"] = sessionId
        }
        guard let data = try? JSONSerialization.data(withJSONObject: message) else {
            completion(.failure(launcherError("The CDP request could not be encoded.")))
            return
        }
        guard let text = String(data: data, encoding: .utf8) else {
            completion(.failure(launcherError("The CDP request could not be encoded as UTF-8 text.")))
            return
        }
        // Chrome DevTools Protocol messages are JSON text frames. A binary
        // frame is accepted by the HTTP upgrade but Chrome closes the socket
        // before returning the command result.
        socket.send(.string(text)) { [weak self] error in
            guard let self else { return }
            if let error {
                completion(.failure(error))
                return
            }
            self.receiveCDP(socket, id: id, completion: completion)
        }
    }

    private func receiveCDP(
        _ socket: URLSessionWebSocketTask,
        id: Int,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        socket.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error):
                completion(.failure(error))
            case .success(let message):
                let data: Data
                switch message {
                case .data(let value):
                    data = value
                case .string(let value):
                    data = Data(value.utf8)
                @unknown default:
                    completion(.failure(self.launcherError("Chrome returned an unsupported WebSocket message.")))
                    return
                }
                guard let object = try? JSONSerialization.jsonObject(with: data),
                      let response = object as? [String: Any] else {
                    completion(.failure(self.launcherError("Chrome returned an invalid CDP response.")))
                    return
                }
                guard (response["id"] as? NSNumber)?.intValue == id else {
                    self.receiveCDP(socket, id: id, completion: completion)
                    return
                }
                if let error = response["error"] as? [String: Any] {
                    let message = (error["message"] as? String) ?? "Chrome rejected the CDP request."
                    completion(.failure(self.launcherError(message)))
                    return
                }
                completion(.success((response["result"] as? [String: Any]) ?? [:]))
            }
        }
    }

    private func launcherError(_ message: String) -> Error {
        NSError(
            domain: "AICC.CdpChromeStatusLauncher",
            code: 4,
            userInfo: [NSLocalizedDescriptionKey: message]
        )
    }

    /// Installs the port identity badge into this slot's profile.
    ///
    /// Current Google Chrome removed `--load-extension`, so the badge can only
    /// be attached through the DevTools protocol after the slot is listening.
    /// Failure here never blocks the browser window: the slot stays usable and
    /// the badge is retried on the next launcher-triggered open.
    ///
    /// The install is tracked per browser process, so a browser or machine
    /// restart gets a fresh badge instead of being skipped by a sticky flag.
    private func installBadgeExtension(_ configuration: SlotConfiguration) {
        guard configuration.hasBadgeExtension, !badgeInstallInFlight else { return }
        guard let browserPID = targetPID else { return }
        guard badgeInstalledForPID != browserPID else { return }
        badgeInstallInFlight = true

        guard let socketURL = browserWebSocketURL(configuration.port) else {
            badgeInstallInFlight = false
            return
        }

        let connectionGate = WebSocketOpenGate()
        let session = URLSession(configuration: .ephemeral, delegate: connectionGate, delegateQueue: nil)
        let socket = session.webSocketTask(with: socketURL)
        let finish: (Bool) -> Void = { [weak self] installed in
            socket.cancel(with: .goingAway, reason: nil)
            session.invalidateAndCancel()
            DispatchQueue.main.async {
                guard let self else { return }
                self.badgeInstallInFlight = false
                self.badgeInstalledForPID = installed ? browserPID : nil
            }
        }

        connectionGate.completion = { [weak self] connectionResult in
            guard let self else { return }
            guard case .success = connectionResult else {
                finish(false)
                return
            }
            self.sendCDP(
                socket,
                id: 101,
                method: "Extensions.loadUnpacked",
                params: ["path": configuration.badgeExtension]
            ) { [weak self] loadResult in
                guard let self else { return }
                guard case .success(let payload) = loadResult,
                      let extensionID = payload["id"] as? String else {
                    finish(false)
                    return
                }
                self.configureBadgeSlot(
                    socket,
                    configuration: configuration,
                    extensionID: extensionID,
                    completion: finish
                )
            }
        }
        socket.resume()
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 5) { [weak self, weak connectionGate] in
            guard let self else { return }
            connectionGate?.failIfPending(self.launcherError("The badge install socket did not connect."))
        }
    }

    /// Records this slot's port in the badge extension's own profile storage so
    /// the toolbar shows the matching port label.
    private func configureBadgeSlot(
        _ socket: URLSessionWebSocketTask,
        configuration: SlotConfiguration,
        extensionID: String,
        completion: @escaping (Bool) -> Void
    ) {
        sendCDP(
            socket,
            id: 102,
            method: "Target.createTarget",
            params: ["url": "chrome-extension://\(extensionID)/popup.html", "background": true]
        ) { [weak self] targetResult in
            guard let self else { return }
            guard case .success(let target) = targetResult,
                  let targetID = target["targetId"] as? String else {
                completion(false)
                return
            }
            self.sendCDP(
                socket,
                id: 103,
                method: "Target.attachToTarget",
                params: ["targetId": targetID, "flatten": true]
            ) { [weak self] attachResult in
                guard let self else { return }
                guard case .success(let attached) = attachResult,
                      let sessionID = attached["sessionId"] as? String else {
                    completion(false)
                    return
                }
                let expression = """
                (async () => {
                  await chrome.storage.local.set({ slot: "\(configuration.port)" });
                  const stored = await chrome.storage.local.get("slot");
                  // The service worker applies the toolbar badge asynchronously from
                  // storage.onChanged. Give that event time to settle before deciding the
                  // install failed; otherwise the launcher retries every monitor tick and
                  // repeatedly creates and closes the hidden popup target.
                  await new Promise((resolve) => setTimeout(resolve, 200));
                  return stored.slot === "\(configuration.port)"
                    ? await chrome.action.getBadgeText({})
                    : "";
                })()
                """
                self.sendCDP(
                    socket,
                    id: 104,
                    method: "Runtime.evaluate",
                    params: ["expression": expression, "awaitPromise": true, "returnByValue": true],
                    sessionId: sessionID
                ) { [weak self] evaluateResult in
                    guard let self else { return }
                    var badgeMatches = false
                    if case .success(let evaluated) = evaluateResult,
                       evaluated["exceptionDetails"] == nil,
                       let value = (evaluated["result"] as? [String: Any])?["value"] as? String {
                        badgeMatches = value == configuration.badgeSlotLabel
                    }
                    self.sendCDP(
                        socket,
                        id: 105,
                        method: "Target.closeTarget",
                        params: ["targetId": targetID]
                    ) { _ in
                        completion(badgeMatches)
                    }
                }
            }
        }
    }

    private func run(_ executable: String, _ arguments: [String]) -> String {
        let task = Process()
        let pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = arguments
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        do {
            try task.run()
            task.waitUntilExit()
            return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        } catch {
            return ""
        }
    }

    private func dockMenuStatus() -> String {
        guard let configuration else { return "CDP slot unavailable" }
        switch resolveSlot() {
        case .ready(let running):
            let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier
            return "Port \(configuration.port) · \(front ? "Active" : "Running") · PID \(running.processIdentifier)"
        case .starting(let running):
            return "Port \(configuration.port) · Starting · PID \(running.processIdentifier)"
        case .registering(let listener):
            return "Port \(configuration.port) · Registering · PID \(listener)"
        case .absent:
            return "Port \(configuration.port) · Stopped"
        case .conflict:
            return "Port \(configuration.port) · Identity conflict"
        }
    }

    private func setBadge(_ label: String) {
        NSApp.dockTile.badgeLabel = label
        NSApp.dockTile.display()
    }

    private func showFailure(_ message: String) {
        guard !isShowingFailure else { return }
        isShowingFailure = true
        monitor?.invalidate()
        setBadge("!")
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = configuration?.appName ?? "CDP Chrome"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }
}

let application = NSApplication.shared
let delegate = LauncherDelegate()
application.delegate = delegate
application.run()
