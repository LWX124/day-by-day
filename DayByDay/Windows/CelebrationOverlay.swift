// CelebrationOverlay.swift
// 全屏特效 overlay：.screenSaver level + 点击穿透 + 跨 Space。
// design.md §8：CelebrationOverlay = 全屏, .screenSaver level, ignoresMouseEvents, 跨 Space。
// M0 spike：验证点击穿透（overlay 播放时能在下方编辑器打字）。M3 加 sprite 烟花。

import AppKit
import SwiftUI

/// 全屏 overlay 窗口：点击穿透、跨 Space、不抢焦点。
/// canBecomeKey/canBecomeMain 重写为 false（只读属性，用子类重写而非赋值）。
final class CelebrationOverlayWindow: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    init() {
        super.init(
            contentRect: NSScreen.main?.frame ?? .zero,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        // screenSaver level：在所有窗口之上（含 menu bar）
        level = .screenSaver
        // 点击穿透：鼠标事件穿透到下方窗口
        ignoresMouseEvents = true
        // 跨 Space
        collectionBehavior = [.canJoinAllSpaces, .stationary]
        isReleasedWhenClosed = true
    }
}

/// overlay 内容：M0 spike 用透明视图占位，M3 换 SpriteKit 粒子烟花。
struct CelebrationOverlayView: View {
    let tier: Int
    @State private var opacity: Double = 0.0

    var body: some View {
        VStack {
            Text("🎉 Tier \(tier) 🎉")
                .font(.system(size: 48, weight: .bold))
                .foregroundStyle(.white)
                .shadow(radius: 10)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(opacity)
        .onAppear {
            withAnimation(.easeIn(duration: 0.3)) { opacity = 1.0 }
        }
        .accessibilityElement(children: .ignore)
    }
}

/// overlay 控制器：M0 spike 用。M3 由 PetCommand.celebrate 驱动。
@MainActor
final class CelebrationController {
    static let shared = CelebrationController()
    private var window: CelebrationOverlayWindow?

    func show(tier: Int, duration: TimeInterval = 3.0) {
        let w = CelebrationOverlayWindow()
        w.contentView = NSHostingView(rootView: CelebrationOverlayView(tier: tier))
        w.makeKeyAndOrderFront(nil)  // 注：ignoresMouseEvents 让它不抢焦点
        window = w
        // 持续 duration 后销毁
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(duration * 1_000_000_000))
            w.orderOut(nil)
            self.window = nil
        }
    }
}
