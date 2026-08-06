// PetView.swift
// 宠物渲染占位：SF Symbols + SwiftUI 动画（design.md §8 PetRenderer 协议占位实现）。
// M0 spike：让宠物能动，验证窗口组合。正式 sprite sheet 在 M3 替换。

import SwiftUI

struct PetView: View {
    let emotion: EmotionState
    let onOpenIntent: () -> Void
    @State private var breathe = false

    var body: some View {
        ZStack {
            Circle()
                .fill(emotionColor.opacity(0.3))
                .frame(width: 100, height: 100)
                .scaleEffect(breathe ? 1.05 : 0.95)
                .animation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true), value: breathe)

            // SF Symbol 占位宠物形象
            Image(systemName: symbol)
                .font(.system(size: 44))
                .foregroundStyle(emotionColor)
                .scaleEffect(breathe ? 1.0 : 0.95)
                .animation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true), value: breathe)
        }
        .onAppear { breathe = true }
        .accessibilityLabel("Day by Day 宠物")
        .accessibilityAddTraits(.isButton)
        // 整个视图可拖拽（配合 movableByWindowBackground）
        .contentShape(Circle())
        // 双击打开意图对话框
        .onTapGesture(count: 2) {
            onOpenIntent()
        }
    }

    private var symbol: String {
        switch emotion {
        case .idle: return "pawprint.fill"
        case .happy: return "face.smiling.fill"
        case .focused: return "eye.fill"
        case .worried: return "exclamationmark.triangle.fill"
        case .grumpy: return "cloud.rain.fill"
        case .sleeping: return "moon.zzz.fill"
        }
    }

    private var emotionColor: Color {
        switch emotion {
        case .idle: return .blue
        case .happy: return .green
        case .focused: return .purple
        case .worried: return .orange
        case .grumpy: return .gray
        case .sleeping: return .indigo
        }
    }
}
