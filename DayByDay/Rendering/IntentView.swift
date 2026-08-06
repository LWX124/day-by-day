// IntentView.swift
// 意图对话框 SwiftUI 视图：输入区 + 对话流。
// design.md §3：400×200，透明无边框，圆角，阴影。

import SwiftUI
import Observation

/// 对话消息模型
struct IntentMessage: Identifiable, Equatable {
    let id = UUID()
    let role: IntentMessageRole
    let text: String
    let timestamp: Date

    static func == (lhs: IntentMessage, rhs: IntentMessage) -> Bool {
        lhs.id == rhs.id && lhs.role == rhs.role && lhs.text == rhs.text
    }
}

enum IntentMessageRole: String, Equatable {
    case user
    case system
}

@Observable
final class IntentViewModel {
    var messages: [IntentMessage]
    var inputText: String

    init(messages: [IntentMessage] = [], inputText: String = "") {
        self.messages = messages
        self.inputText = inputText
    }
}

/// 意图对话框内容视图
struct IntentView: View {
    @Bindable var model: IntentViewModel
    var onSend: () -> Void
    var onClose: () -> Void

    @State private var isComposing = false
    @FocusState private var isInputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            // 顶部栏：标题 + 关闭按钮
            HStack {
                Text("Day by Day")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.primary)
                Spacer()
                Button(action: onClose) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 16))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 12)
            .padding(.top, 10)
            .padding(.bottom, 6)

            Divider()
                .background(Color.white.opacity(0.15))

            // 对话流
            ScrollViewReader { proxy in
                ScrollView(.vertical, showsIndicators: false) {
                    LazyVStack(spacing: 8) {
                        ForEach(model.messages) { msg in
                            MessageBubble(message: msg)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                }
                .onChange(of: model.messages.count) { oldValue, newValue in
                    if let last = model.messages.last {
                        withAnimation {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }

            // 输入区
            HStack(spacing: 8) {
                TextEditor(text: $model.inputText)
                    .font(.system(size: 14))
                    .foregroundStyle(.primary)
                    .scrollContentBackground(.hidden)
                    .background(Color.clear)
                    .frame(minHeight: 28, maxHeight: 80)
                    .focused($isInputFocused)
                    .onSubmit { onSend() }
                    .overlay(alignment: .leading) {
                        if model.inputText.isEmpty {
                            Text("想让我做什么...")
                                .font(.system(size: 14))
                                .foregroundStyle(.tertiary)
                                .padding(.leading, 4)
                                .allowsHitTesting(false)
                        }
                    }

                Button(action: onSend) {
                    Image(systemName: "paperplane.fill")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(model.inputText.isEmpty ? .tertiary : .primary)
                }
                .buttonStyle(.plain)
                .disabled(model.inputText.isEmpty)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color(nsColor: .controlBackgroundColor).opacity(0.5))
        }
        .frame(minWidth: 360, maxWidth: 400, minHeight: 180, maxHeight: .infinity)
        .background(.ultraThinMaterial)
        .cornerRadius(16)
        .shadow(color: .black.opacity(0.2), radius: 20, x: 0, y: 10)
        .onAppear {
            // 等 IntentPanel 成为 key window 后再申请第一响应者。
            DispatchQueue.main.async {
                isInputFocused = true
            }
        }
    }
}

// MARK: - MessageBubble

private struct MessageBubble: View {
    let message: IntentMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 40) }

            Text(message.text)
                .font(.system(size: 13))
                .foregroundStyle(message.role == .user ? .white : .primary)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    message.role == .user
                        ? Color.blue.opacity(0.85)
                        : Color(nsColor: .controlBackgroundColor).opacity(0.6)
                )
                .cornerRadius(12)

            if message.role == .system { Spacer(minLength: 40) }
        }
    }
}

// MARK: - Preview

#Preview {
    IntentView(
        model: IntentViewModel(messages: [
            IntentMessage(role: .user, text: "帮我创建明天下午3点的会议", timestamp: Date()),
            IntentMessage(role: .system, text: "已创建任务：明天下午3点的会议", timestamp: Date()),
        ]),
        onSend: {},
        onClose: {}
    )
    .frame(width: 400, height: 300)
}
