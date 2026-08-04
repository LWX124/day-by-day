// PetWindow.swift
// 宠物窗口：透明无边框 + 始终置顶 + 跨 Space + 不抢焦点 + 可拖拽。
// design.md §8：PetWindow = NSPanel, .floating, [canJoinAllSpaces, stationary], 透明无边框。
//
// NSPanel 的 canBecomeKey/canBecomeMain/isFloatingPanel 是只读，需用子类重写。

import AppKit
import SwiftUI

/// 宠物窗口（NSPanel 子类）。
/// canBecomeKey/canBecomeMain 重写为 false——宠物窗绝不抢焦点（spec/frontend/quality-guidelines §1）。
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

    /// 配置宠物窗样式：透明、置顶、跨 Space、可拖拽。
    private func configurePetStyle() {
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        isMovableByWindowBackground = true
        // 始终置顶
        level = .floating
        // 跨所有 Space + 不随 Space 切换移动
        collectionBehavior = [.canJoinAllSpaces, .stationary]
        // 隐藏标准窗口按钮
        styleMask.remove(.closable)
        styleMask.remove(.miniaturizable)
        styleMask.remove(.resizable)
        isReleasedWhenClosed = false
    }
}

/// App delegate：手动创建并管理 PetPanel（不走 WindowGroup，因为 WindowGroup 创建的是 NSWindow 不能重写只读属性）。
/// 同时提供内容切换入口（情绪状态、overlay 触发）。
@MainActor
final class PetWindowDelegate: NSObject, NSApplicationDelegate {
    private var petPanel: PetPanel?
    private var currentEmotion: EmotionState = .idle

    func applicationDidFinishLaunching(_ notification: Notification) {
        showPetWindow()
    }

    func showPetWindow() {
        if petPanel == nil {
            let rect = NSRect(x: 100, y: 100, width: 120, height: 120)
            let panel = PetPanel(contentRect: rect)
            panel.contentView = NSHostingView(rootView: PetView(emotion: currentEmotion))
            // 居中放一下，避免初始在角落
            panel.center()
            petPanel = panel
        }
        petPanel?.orderFrontRegardless()
    }

    /// 切换情绪（spike 验收：单击宠物）。
    func cycleEmotion() {
        let all = EmotionState.allCases
        currentEmotion = all[(all.firstIndex(of: currentEmotion)! + 1) % all.count]
        petPanel?.contentView = NSHostingView(rootView: PetView(emotion: currentEmotion))
    }

    /// 触发满屏 overlay（spike 验收：双击或菜单）。
    func celebrate(tier: Int) {
        CelebrationController.shared.show(tier: tier, duration: 3.0)
    }
}
