// BackendSupervisor.swift
// Swift app 作为父进程 spawn 并守护 Python 后端。
// design.md §2：spawn `uv run uvicorn`，传端口与 token 命令行参数；
// stdout/stderr 汇入统一日志；退避重启 1s→2s→4s→8s→30s；
// 连续 5 次失败后宠物切 worried 并气泡提示；app 退出即回收子进程。
//
// token 生成逻辑在此（design.md §2：32 字节随机 token，命令行传给 Python，不落盘不进环境变量）。

import AppKit
import Combine
import Foundation

@MainActor
final class BackendSupervisor: ObservableObject {
    /// 后端健康状态，宠物据此切 emotion。
    enum Health: Equatable {
        case starting
        case healthy(baseURL: URL, token: String)
        case degraded   // 退避重启中
        case failed     // 连续 5 次失败，宠物应切 worried
    }

    @Published private(set) var health: Health = .starting

    private var process: Process?
    private var restartAttempts = 0
    private var restartTask: Task<Void, Never>?
    private var healthCheckTask: Task<Void, Never>?
    private let logURL: URL

    /// 固定的退避序列（design.md §2：1s→2s→4s→8s→30s）。
    private let backoffSequence: [TimeInterval] = [1, 2, 4, 8, 30]
    private let maxAttempts = 5

    /// 32 字节随机 token（design.md §2：不落盘不进环境变量，命令行传给 Python）。
    private(set) var token: String

    /// 随机高位端口（0 让 OS 分配；实际端口由后端 stdout 报告，我们解析）。
    private let port: Int

    /// 解析出的实际端口（从 uvicorn 启动日志）。0 表示尚未解析出。
    /// nonisolated(unsafe)：由 resolvedPortLock 保护，可从 readabilityHandler 后台队列写。
    nonisolated(unsafe) private var resolvedPort: Int = 0

    /// 端口解析用锁：readabilityHandler 在后台队列，与 probeHealth(主队列) 读写竞争。
    /// let 自动 nonisolated。
    private let resolvedPortLock = NSLock()

    init() {
        self.token = Self.generateToken()
        // 用 0 让 uvicorn/OS 分配随机端口；后端启动后从 stdout/health 报告实际端口。
        self.port = 0
        let fm = FileManager.default
        let appSupport = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("DayByDay", isDirectory: true)
        let logs = appSupport.appendingPathComponent("logs", isDirectory: true)
        try? fm.createDirectory(at: logs, withIntermediateDirectories: true)
        self.logURL = logs.appendingPathComponent("agent.log")
    }

    // MARK: - 生命周期

    func start() {
        restartAttempts = 0
        spawn()
    }

    /// app 退出时调用：SIGTERM 优雅退出 + 超时 SIGKILL。
    func shutdown() {
        restartTask?.cancel()
        healthCheckTask?.cancel()
        guard let p = process, p.isRunning else { return }
        p.terminate()  // SIGTERM
        // 给 5 秒优雅退出，超时强杀
        Task.detached { [port = self.port] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            if p.isRunning { p.interrupt() }  // 兜底：SIGKILL 语义
        }
    }

    // MARK: - spawn

    private func spawn() {
        guard restartAttempts < maxAttempts else {
            health = .failed
            return
        }

        // uv 路径探测（修 GUI 启动 127）：launchd 启动的 GUI 进程 PATH 是
        // /usr/bin:/bin:/usr/sbin:/sbin，不含 ~/.local/bin，而 uv 装在那。
        // 先按序探测候选绝对路径，命中即用；全失败则快速失败，不进退避（127 是确定性失败）。
        guard let uvURL = resolveUvURL() else {
            appendLog("未找到 uv，请安装：curl -LsSf https://astral.sh/uv/install.sh | sh\n")
            health = .failed
            return
        }

        let p = Process()
        // uv run python -m api --token <t> --host 127.0.0.1 --port <p>
        // port=0 让 OS 分配随机高位端口（design.md §2）
        let agentDir = Self.agentDirectory
        p.currentDirectoryURL = agentDir
        p.executableURL = uvURL
        p.arguments = ["run", "python", "-m", "api",
                       "--token", token, "--host", "127.0.0.1", "--port", "\(port)"]

        // 子进程 PATH 注入：把候选目录前置，避免 uv run 内部 fork 的子进程同样找不到工具。
        // 显式设置，否则继承父进程 GUI 的窄 PATH。
        p.environment = augmentedEnvironment()

        // 每次启动重置端口解析状态
        setResolvedPort(0)

        // stdout/stderr 汇入统一日志文件（与 Python 侧同一时间线，design.md §2）
        let logHandle = openLogForAppending()
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        // 异步把输出写进日志文件，同时解析 uvicorn 报告的实际端口
        let fileHandle = logHandle
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if !data.isEmpty {
                fileHandle?.write(data)
                // 解析 uvicorn 启动日志："Uvicorn running on http://127.0.0.1:PORT"
                if let s = String(data: data, encoding: .utf8) {
                    self?.tryResolvePort(from: s)
                }
            }
        }

        p.terminationHandler = { [weak self] proc in
            Task { @MainActor in
                self?.handleTermination(exitCode: proc.terminationStatus)
            }
        }

        do {
            try p.run()
            process = p
            health = .starting
            // 探活后端起来没
            startHealthCheck()
        } catch {
            appendLog("spawn 失败: \(error)\n")
            scheduleRestart()
        }
    }

    private func handleTermination(exitCode: Int32) {
        process = nil
        // 进程已退出，取消进行中的健康检查，避免超时再触发一次 scheduleRestart（双重计数）
        healthCheckTask?.cancel()
        // 正常退出（shutdown 调的）不重启
        guard health != .failed else { return }
        appendLog("后端退出 code=\(exitCode)，准备退避重启\n")
        scheduleRestart()
    }

    private func scheduleRestart() {
        restartAttempts += 1
        if restartAttempts >= maxAttempts {
            health = .failed
            appendLog("连续 \(maxAttempts) 次失败，停止重启，宠物切 worried\n")
            return
        }
        health = .degraded
        let delay = backoffSequence[min(restartAttempts - 1, backoffSequence.count - 1)]
        appendLog("第 \(restartAttempts) 次退避，\(delay)s 后重启\n")
        restartTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            self.spawn()
        }
    }

    // MARK: - 健康检查

    /// 探活 /health 端点（design.md §2：后端起来后探活，确认连接）。
    /// 30 次 × 0.5s = 15s：探到就 healthy，超时走重启。
    private func startHealthCheck() {
        healthCheckTask = Task { @MainActor in
            for _ in 0..<30 {
                try? await Task.sleep(nanoseconds: 500_000_000)  // 0.5s
                guard !Task.isCancelled else { return }
                if await self.probeHealth() {
                    let port = self.getResolvedPort()
                    self.health = .healthy(baseURL: URL(string: "http://127.0.0.1:\(port)")!,
                                            token: self.token)
                    return
                }
            }
            // 15s 没起来，终止旧进程让 handleTermination 接管退避重启。
            // 不直接 scheduleRestart：避免旧进程后续退出再触发一次 handleTermination
            // 导致 restartAttempts 双重计数，同时清理卡住的旧进程（孤儿进程）。
            // 若 process 已被 handleTermination 置 nil（如 127 立即退出），不再处理。
            guard self.process != nil else { return }
            self.appendLog("健康检查超时，后端未就绪，终止旧进程\n")
            self.process?.terminate()
        }
    }

    /// 真实探 /health：resolvedPort==0 直接 false；GET 200 才算健康。超时 2s。
    private func probeHealth() async -> Bool {
        let port = getResolvedPort()
        guard port > 0 else { return false }
        guard let url = URL(string: "http://127.0.0.1:\(port)/health") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            if let http = resp as? HTTPURLResponse {
                return http.statusCode == 200
            }
            return false
        } catch {
            return false
        }
    }

    // MARK: - 端口解析（线程安全）

    /// readabilityHandler 在后台队列回调，需加锁读写 resolvedPort。
    /// 这三个方法 nonisolated：仅靠 NSLock 保护，不碰其他 main-isolated 状态。
    nonisolated private func getResolvedPort() -> Int {
        resolvedPortLock.lock()
        defer { resolvedPortLock.unlock() }
        return resolvedPort
    }

    nonisolated private func setResolvedPort(_ value: Int) {
        resolvedPortLock.lock()
        resolvedPort = value
        resolvedPortLock.unlock()
    }

    /// 从 uvicorn stdout 文本解析监听端口。匹配到即写入，已解析过则不再覆盖。
    nonisolated private func tryResolvePort(from text: String) {
        if getResolvedPort() > 0 { return }
        guard let range = text.range(of: #"Uvicorn running on http://127\.0\.0\.1:(\d+)"#,
                                      options: .regularExpression) else { return }
        let matched = String(text[range])
        // 提取末尾数字端口
        if let portRange = matched.range(of: #"\d+$"#, options: .regularExpression) {
            if let port = Int(matched[portRange]) {
                setResolvedPort(port)
            }
        }
    }

    // MARK: - uv 路径探测

    /// 按序探测 uv 可执行文件，命中第一个存在的即返回。全失败返回 nil。
    /// 候选顺序：~/.local/bin → ~/.cargo/bin → /usr/local/bin → /opt/homebrew/bin。
    /// `~` 用 homeDirectoryForCurrentUser 展开，不字符串拼。
    private func resolveUvURL() -> URL? {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let candidates = [
            home.appendingPathComponent(".local/bin/uv"),
            home.appendingPathComponent(".cargo/bin/uv"),
            URL(fileURLWithPath: "/usr/local/bin/uv"),
            URL(fileURLWithPath: "/opt/homebrew/bin/uv")
        ]
        let fm = FileManager.default
        for url in candidates {
            if fm.fileExists(atPath: url.path) && fm.isExecutableFile(atPath: url.path) {
                return url
            }
        }
        // 兜底：which uv（开发期从 shell 启动时 PATH 含 uv 仍可用）
        return whichUv()
    }

    /// `which uv` 兜底，返回绝对路径（开发期 shell PATH 含 uv 时仍可用）。
    private func whichUv() -> URL? {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        task.arguments = ["uv"]
        // 用显式 PATH 提高命中率
        task.environment = augmentedEnvironment()
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle(forWritingAtPath: "/dev/null")
        do {
            try task.run()
            task.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if !path.isEmpty {
                let url = URL(fileURLWithPath: path)
                if FileManager.default.isExecutableFile(atPath: url.path) {
                    return url
                }
            }
        } catch {
            return nil
        }
        return nil
    }

    /// 子进程环境：候选目录前置到 PATH，保留系统默认兜底。
    private func augmentedEnvironment() -> [String: String] {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let extra = [
            home.appendingPathComponent(".local/bin").path,
            home.appendingPathComponent(".cargo/bin").path,
            "/usr/local/bin",
            "/opt/homebrew/bin"
        ].joined(separator: ":")
        let base = ProcessInfo.processInfo.environment
        let existingPath = base["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        var env = base
        env["PATH"] = "\(extra):\(existingPath)"
        return env
    }

    // MARK: - 日志

    private func openLogForAppending() -> FileHandle? {
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        return FileHandle(forWritingAtPath: logURL.path)
    }

    private func appendLog(_ s: String) {
        let line = "\(Self.timestamp()) \(s)"
        if let h = openLogForAppending() {
            h.write(Data(line.utf8))
        }
        // stderr 也打一份，便于开发期看
        FileHandle.standardError.write(Data(line.utf8))
    }

    // MARK: - helpers

    private static func generateToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64URLEncodedString()
    }

    private static func timestamp() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }

    /// daybyday-agent 目录：项目根/daybyday-agent。
    private static var agentDirectory: URL {
        let repoRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return repoRoot.appendingPathComponent("daybyday-agent", isDirectory: true)
    }
}

private extension Data {
    /// base64url（URL 安全，无 padding），适合放命令行参数。
    func base64URLEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
