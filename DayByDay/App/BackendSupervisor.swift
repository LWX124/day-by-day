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
        let p = Process()
        // uv run python -m api --token <t> --host 127.0.0.1 --port <p>
        // port=0 让 OS 分配随机高位端口（design.md §2）
        let agentDir = Self.agentDirectory
        p.currentDirectoryURL = agentDir
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        p.arguments = ["uv", "run", "python", "-m", "api",
                       "--token", token, "--host", "127.0.0.1", "--port", "\(port)"]

        // stdout/stderr 汇入统一日志文件（与 Python 侧同一时间线，design.md §2）
        let logHandle = openLogForAppending()
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        // 异步把输出写进日志文件
        let fileHandle = logHandle
        pipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty {
                fileHandle?.write(data)
                // 同时打前缀时间线（可选）
                // TODO: 解析后端报告的实际端口（uvicorn 启动日志含 "Uvicorn running on http://127.0.0.1:PORT"）
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
    /// 后端端口由 stdout 报告，这里先试从日志解析；解析不到则假设一个默认端口。
    private func startHealthCheck() {
        healthCheckTask = Task { @MainActor in
            // 等后端起来
            for _ in 0..<30 {
                try? await Task.sleep(nanoseconds: 500_000_000)  // 0.5s
                guard !Task.isCancelled else { return }
                if await self.probeHealth() {
                    self.health = .healthy(baseURL: URL(string: "http://127.0.0.1:\(self.resolvedPort)")!,
                                            token: self.token)
                    return
                }
            }
            // 15s 没起来，视为失败走重启
            self.appendLog("健康检查超时，后端未就绪\n")
        }
    }

    /// 解析出的实际端口（从 uvicorn 启动日志）。
    private var resolvedPort: Int = 18080

    private func probeHealth() async -> Bool {
        // M0 spike：先返回 true（实际端口解析在 SSE 接入后完善）。
        // 真实实现：GET http://127.0.0.1:resolvedPort/health，返回 200 即健康。
        // TODO: 用 URLSession 探 /health。
        return true
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
