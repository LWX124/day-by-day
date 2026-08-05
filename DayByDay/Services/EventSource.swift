// EventSource.swift
// SSE 长连接：监听后端 PetCommand 推送。
// design.md §2：GET /events SSE，推 PetCommand JSON。
// 本模块负责连接管理、心跳保活、JSON 解码 → NotificationCenter 分发。

import Foundation
import Combine

/// SSE 事件源管理器
@MainActor
final class EventSource: ObservableObject {
    static let shared = EventSource()

    /// 连接状态
    enum State: Equatable {
        case idle
        case connecting
        case connected
        case disconnected
    }

    @Published private(set) var state: State = .idle
    @Published private(set) var lastError: Error?

    private var task: Task<Void, Never>?
    private var baseURL: URL?
    private var token: String?

    /// 从 BackendSupervisor 健康状态更新配置
    func configure(baseURL: URL, token: String) {
        self.baseURL = baseURL
        self.token = token
    }

    /// 启动 SSE 连接
    func start() {
        guard task == nil else { return }
        task = Task { @MainActor in
            await runLoop()
        }
    }

    /// 停止 SSE 连接
    func stop() {
        task?.cancel()
        task = nil
        state = .idle
    }

    /// 主循环：断线重连
    private func runLoop() async {
        while !Task.isCancelled {
            state = .connecting
            do {
                try await connect()
                state = .connected
                // 连接断开（正常或异常）
                state = .disconnected
            } catch {
                if Task.isCancelled { break }
                lastError = error
                state = .disconnected
            }
            // 退避重连：1s → 2s → 4s → 8s → 30s
            let backoff = min(30, max(1, 1 << min(reconnectCount, 5)))
            reconnectCount += 1
            try? await Task.sleep(nanoseconds: UInt64(backoff * 1_000_000_000))
        }
    }

    private var reconnectCount = 0

    /// 建立 SSE 连接并消费事件
    private func connect() async throws {
        guard let baseURL = baseURL, let token = token else {
            throw APIError.noHealthyBackend
        }
        guard let url = URL(string: "/events", relativeTo: baseURL) else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 60

        let (bytes, response) = try await URLSession.shared.bytes(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }

        var eventName: String = "message"
        var eventData: String = ""

        for try await line in bytes.lines {
            if Task.isCancelled { break }

            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)

            if trimmed.hasPrefix("event: ") {
                eventName = String(trimmed.dropFirst(7))
            } else if trimmed.hasPrefix("data: ") {
                let dataPart = String(trimmed.dropFirst(6))
                if eventData.isEmpty {
                    eventData = dataPart
                } else {
                    eventData += "\n" + dataPart
                }
            } else if trimmed.isEmpty {
                // 空行 = 事件结束
                if eventName == "pet_command" && !eventData.isEmpty {
                    parseAndDispatch(eventData)
                }
                // ping 事件忽略
                eventName = "message"
                eventData = ""
                reconnectCount = 0  // 收到任何事件都重置重连计数
            }
        }
    }

    /// 解析 PetCommand JSON 并通知分发
    private func parseAndDispatch(_ json: String) {
        guard let data = json.data(using: .utf8) else { return }
        guard let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        guard let type = dict["type"] as? String else { return }

        let command: PetCommand

        switch type {
        case "set_emotion":
            if let state = dict["state"] as? String, let emotion = EmotionState(rawValue: state) {
                command = .setEmotion(emotion)
            } else { return }

        case "bubble":
            let text = dict["text"] as? String ?? ""
            let ttl = dict["ttl"] as? TimeInterval ?? 5.0
            let quickReplies = dict["quick_replies"] as? [String]
            command = .bubble(text: text, ttl: ttl, quickReplies: quickReplies)

        case "celebrate":
            let tier = dict["tier"] as? Int ?? 1
            let text = dict["text"] as? String ?? ""
            command = .celebrate(tier: tier, text: text)

        case "notify":
            let title = dict["title"] as? String ?? ""
            let body = dict["body"] as? String ?? ""
            command = .notify(title: title, body: body)

        case "open_panel":
            let section = dict["section"] as? String ?? ""
            command = .openPanel(section: section)

        case "request_confirm":
            let actionId = dict["action_id"] as? String ?? ""
            let title = dict["title"] as? String ?? ""
            let detail = dict["detail"] as? String
            command = .requestConfirm(actionId: actionId, title: title, detail: detail ?? "")

        case "badge":
            let count = dict["count"] as? Int ?? 0
            command = .badge(count: count)

        // Intent Dialog 相关命令
        case "intent_response":
            let text = dict["text"] as? String ?? ""
            let actions: [IntentAction] = (dict["actions"] as? [[String: Any]])?.compactMap { a in
                guard let t = a["type"] as? String else { return nil }
                let payload = a["payload"] as? [String: String]
                return IntentAction(type: t, payload: payload)
            } ?? []
            command = .intentResponse(text: text, actions: actions)

        case "clarify":
            let question = dict["question"] as? String ?? ""
            command = .clarify(question: question)

        default:
            // 未知命令类型，忽略
            return
        }

        // 通过 NotificationCenter 分发，PetWindowDelegate 监听
        NotificationCenter.default.post(name: .petCommandReceived, object: command)
    }
}
