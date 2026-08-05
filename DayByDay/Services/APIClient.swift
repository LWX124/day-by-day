// APIClient.swift
// 后端 HTTP API 客户端。
// design.md §2：所有请求带 Bearer token 鉴权，与 PetCommand SSE 长连接分离。

import Foundation

/// API 请求错误
enum APIError: Error, Equatable {
    case invalidURL
    case noHealthyBackend
    case invalidResponse
    case httpError(statusCode: Int, message: String)
    case encodingError
    case decodingError
}

/// Intent 请求模型
struct IntentRequest: Codable {
    let sessionId: String
    let text: String
    let context: [Message]?

    struct Message: Codable {
        let role: String
        let content: String
        let timestamp: String
    }
}

/// Intent 响应模型
struct IntentResponse: Codable {
    let intent: String?
    let args: [String: AnyCodable]?
    let confidence: Double
    let action: String  // "execute" | "confirm" | "clarify"
    let message: String
    let result: [String: AnyCodable]?
    let pendingActionId: String?
    let sessionId: String

    enum CodingKeys: String, CodingKey {
        case intent, args, confidence, action, message, result
        case pendingActionId = "pending_action_id"
        case sessionId = "session_id"
    }
}

/// 通用 API 客户端
@MainActor
final class APIClient {
    static let shared = APIClient()

    private var healthObserver: Any?
    private var baseURL: URL?
    private var token: String?

    init() {
        // 监听 BackendSupervisor 健康状态变化
        healthObserver = NotificationCenter.default.addObserver(
            forName: .init("BackendHealthChanged"),
            object: nil,
            queue: .main
        ) { [weak self] note in
            if let health = note.object as? (url: URL, token: String) {
                self?.baseURL = health.url
                self?.token = health.token
            }
        }
    }

    /// 从 BackendSupervisor 健康状态更新配置
    func configure(baseURL: URL, token: String) {
        self.baseURL = baseURL
        self.token = token
    }

    /// 发送意图解析请求
    /// - Parameters:
    ///   - sessionId: 会话 ID
    ///   - text: 用户输入文本
    ///   - context: 可选的对话上下文
    /// - Returns: IntentResponse
    func sendIntent(
        sessionId: String,
        text: String,
        context: [IntentRequest.Message]? = nil
    ) async throws -> IntentResponse {
        guard let baseURL = baseURL, let token = token else {
            throw APIError.noHealthyBackend
        }

        guard let url = URL(string: "/intent", relativeTo: baseURL) else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 30

        let body = IntentRequest(
            sessionId: sessionId,
            text: text,
            context: context
        )

        do {
            request.httpBody = try JSONEncoder().encode(body)
        } catch {
            throw APIError.encodingError
        }

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard httpResponse.statusCode == 200 else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(statusCode: httpResponse.statusCode, message: message)
        }

        do {
            return try JSONDecoder().decode(IntentResponse.self, from: data)
        } catch {
            throw APIError.decodingError
        }
    }

    /// 发送确认请求（M1 confirm-action 任务）
    func confirmAction(actionId: String, confirm: Bool) async throws {
        guard let baseURL = baseURL, let token = token else {
            throw APIError.noHealthyBackend
        }

        guard let url = URL(string: "/confirm", relativeTo: baseURL) else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 10

        let body: [String: Any] = [
            "action_id": actionId,
            "confirm": confirm
        ]

        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }
    }
}

/// AnyCodable 用于解析未知结构的 JSON 值
struct AnyCodable: Codable, Equatable {
    let value: Any

    init(_ value: Any) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues { $0.value }
        } else {
            value = ()
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            try container.encodeNil()
        }
    }

    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        String(describing: lhs.value) == String(describing: rhs.value)
    }
}

// MARK: - PetCommand 通知扩展

extension Notification.Name {
    static let petCommandReceived = Notification.Name("PetCommandReceived")
}
