// PetWindow.swift
// 宠物窗口 + app delegate：守护后端 + 拖拽位置持久化 + 健康联动情绪。
// design.md §8：PetWindow = NSPanel, .floating, [canJoinAllSpaces, stationary], 透明无边框。

import AppKit
import Combine
import SwiftUI

/// 宠物窗口（NSPanel 子类）。
/// canBecomeKey/canBecomeMain 重写为 false——绝不抢焦点（spec/frontend/quality-guidelines §1/§6）。
final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    init(contentRect: NSRect) {
        super.init(
            contentRect: contentRect,
            styleMask: [.borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        configurePetStyle()
    }

    private func configurePetStyle() {
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        isMovableByWindowBackground = true  // 拖拽挪位
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .stationary]
        styleMask.remove(.closable)
        styleMask.remove(.miniaturizable)
        styleMask.remove(.resizable)
        isReleasedWhenClosed = false
        // 通知拖拽结束，供 delegate 持久化位置
        isMovable = true
        // NSPanel 默认 hidesOnDeactivate=true（失焦即隐藏）+ becomesKeyOnlyIfNeeded
        // 会导致 borderless panel 不成为 key 时根本不上屏。强制关掉。
        hidesOnDeactivate = false
        becomesKeyOnlyIfNeeded = false
        // 非 key panel 也可被推上前
        styleMask.insert(.nonactivatingPanel)
    }
}

@MainActor
final class PetWindowDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var petPanel: PetPanel?
    private var intentPanel: IntentPanel?
    private var currentEmotion: EmotionState = .idle
    @ObservedObject private var supervisor = BackendSupervisor()
    private var wakeMonitor = WakeMonitor()
    private var cancellables = Set<AnyCancellable>()

    // Intent dialog state
    @State private var intentMessages: [IntentMessage] = []
    @State private var intentInputText: String = ""
    private var intentSessionId: String = UUID().uuidString

    // MARK: - 生命周期

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 1. 启动后端守护
        supervisor.start()
        // 2. 监听唤醒
        wakeMonitor.start { [weak self] in
            // M2 接 POST /wake；M0 占位日志
            FileHandle.standardError.write("wake detected\n".data(using: .utf8)!)
            _ = self
        }
        // 3. 后端健康联动宠物情绪 + APIClient/EventSource 配置
        supervisor.$health.sink { [weak self] h in
            self?.applyHealthToEmotion(h)
            // 配置 APIClient 和 EventSource
            if case .healthy(let baseURL, let token) = h {
                APIClient.shared.configure(baseURL: baseURL, token: token)
                EventSource.shared.configure(baseURL: baseURL, token: token)
                EventSource.shared.start()
            }
        }.store(in: &cancellables)
        // 4. 监听 PetCommand SSE 推送
        NotificationCenter.default.addObserver(
            forName: .petCommandReceived,
            object: nil,
            queue: .main
        ) { [weak self] note in
            if let command = note.object as? PetCommand {
                self?.handlePetCommand(command)
            }
        }
        // 5. 显示宠物窗（恢复上次位置）
        showPetWindow()
    }

    func applicationWillTerminate(_ notification: Notification) {
        // app 退出即回收子进程（SIGTERM + 超时 SIGKILL）
        supervisor.shutdown()
        // 持久化位置
        if let frame = petPanel?.frame { PositionStore.save(frame) }
    }

    // MARK: - 窗口

    func showPetWindow() {
        let frame = PositionStore.load() ?? NSRect(x: 100, y: 200, width: 120, height: 120)
        if petPanel == nil {
            let panel = PetPanel(contentRect: frame)
            panel.delegate = self
            panel.contentView = NSHostingView(rootView: PetView(emotion: currentEmotion))
            petPanel = panel
        }
        petPanel?.setFrame(frame, display: true)
        petPanel?.orderFrontRegardless()
    }

    // 拖拽结束持久化位置
    func windowDidMove(_ notification: Notification) {
        if let frame = petPanel?.frame { PositionStore.save(frame) }
    }

    // MARK: - 情绪 / 健康

    private func applyHealthToEmotion(_ h: BackendSupervisor.Health) {
        switch h {
        case .starting, .healthy: currentEmotion = .idle
        case .degraded: currentEmotion = .worried
        case .failed: currentEmotion = .grumpy  // 后端连续失败，宠物不满
        }
        petPanel?.contentView = NSHostingView(rootView: PetView(emotion: currentEmotion))
    }

    // MARK: - spike 入口

    func cycleEmotion() {
        let all = EmotionState.allCases
        currentEmotion = all[(all.firstIndex(of: currentEmotion)! + 1) % all.count]
        petPanel?.contentView = NSHostingView(rootView: PetView(emotion: currentEmotion))
    }

    func celebrate(tier: Int) {
        CelebrationController.shared.show(tier: tier, duration: 3.0)
    }

    // MARK: - Intent Dialog

    /// 双击宠物打开意图对话框。
    func openIntentDialog() {
        guard let petPanel = petPanel else { return }
        guard intentPanel == nil else {
            // 已打开则前置
            intentPanel?.orderFrontRegardless()
            return
        }

        let frame = IntentPanel.frameForPosition(near: petPanel.frame)
        let panel = IntentPanel(contentRect: frame)
        panel.delegate = self

        // 绑定 SwiftUI 视图
        let view = IntentView(
            messages: $intentMessages,
            inputText: $intentInputText,
            onSend: { [weak self] in self?.sendIntent() },
            onClose: { [weak self] in self?.closeIntentDialog() }
        )
        panel.contentView = NSHostingView(rootView: view)

        intentPanel = panel
        panel.orderFrontRegardless()
        panel.activateForInput()
    }

    /// 关闭意图对话框。
    func closeIntentDialog() {
        intentPanel?.orderOut(nil)
        intentPanel = nil
        // 恢复宠物 idle
        if currentEmotion != .idle {
            currentEmotion = .idle
            petPanel?.contentView = NSHostingView(rootView: PetView(emotion: currentEmotion))
        }
        // 可选：重置 session（M2 再考虑持久化）
        // intentSessionId = UUID().uuidString
    }

    /// 发送用户输入到后端。
    private func sendIntent() {
        let text = intentInputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        // 本地追加用户消息
        let userMsg = IntentMessage(role: .user, text: text, timestamp: Date())
        intentMessages.append(userMsg)
        intentInputText = ""

        // 构建对话上下文
        let context: [IntentRequest.Message]? = intentMessages.map { msg in
            IntentRequest.Message(
                role: msg.role == .user ? "user" : "assistant",
                content: msg.text,
                timestamp: ISO8601DateFormatter().string(from: msg.timestamp)
            )
        }

        // 调用 APIClient 发送意图请求
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            do {
                let response = try await APIClient.shared.sendIntent(
                    sessionId: self.intentSessionId,
                    text: text,
                    context: context
                )

                // 更新 session ID（后端可能新建）
                self.intentSessionId = response.sessionId

                // 根据 action 类型展示不同响应
                switch response.action {
                case "execute":
                    // 直接执行成功，展示结果
                    let systemMsg = IntentMessage(
                        role: .system,
                        text: response.message,
                        timestamp: Date()
                    )
                    self.intentMessages.append(systemMsg)

                case "confirm":
                    // 需确认操作，展示确认 UI
                    let confirmMsg = IntentMessage(
                        role: .system,
                        text: "\(response.message)\n\n[确认执行?]",
                        timestamp: Date()
                    )
                    self.intentMessages.append(confirmMsg)
                    // 如果有 pending_action_id，后续用户确认时发送 POST /confirm
                    if let actionId = response.pendingActionId {
                        // 追加一个确认按钮消息（在对话流中以特殊标记展示）
                        let confirmActionMsg = IntentMessage(
                            role: .system,
                            text: "ACTION_CONFIRM:\(actionId)",
                            timestamp: Date()
                        )
                        self.intentMessages.append(confirmActionMsg)
                    }

                case "clarify":
                    // 追问用户
                    let clarifyMsg = IntentMessage(
                        role: .system,
                        text: response.message,
                        timestamp: Date()
                    )
                    self.intentMessages.append(clarifyMsg)

                default:
                    let fallbackMsg = IntentMessage(
                        role: .system,
                        text: response.message,
                        timestamp: Date()
                    )
                    self.intentMessages.append(fallbackMsg)
                }

            } catch APIError.noHealthyBackend {
                let errorMsg = IntentMessage(
                    role: .system,
                    text: "后端尚未就绪，请稍后再试。",
                    timestamp: Date()
                )
                self.intentMessages.append(errorMsg)
            } catch APIError.httpError(let code, let message) {
                let errorMsg = IntentMessage(
                    role: .system,
                    text: "请求失败 (\(code))：\(message)",
                    timestamp: Date()
                )
                self.intentMessages.append(errorMsg)
            } catch {
                let errorMsg = IntentMessage(
                    role: .system,
                    text: "出错了，请重试。",
                    timestamp: Date()
                )
                self.intentMessages.append(errorMsg)
            }
        }
    }

    /// 处理后端推送的 PetCommand（意图相关）。
    func handlePetCommand(_ command: PetCommand) {
        switch command {
        case .openIntentDialog:
            openIntentDialog()
        case .intentResponse(let text, _):
            let msg = IntentMessage(role: .system, text: text, timestamp: Date())
            intentMessages.append(msg)
        case .clarify(let question):
            let msg = IntentMessage(role: .system, text: question, timestamp: Date())
            intentMessages.append(msg)
        default:
            break
        }
    }
}