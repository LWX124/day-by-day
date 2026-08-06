// IntentPanel.swift
// 意图对话框窗口：双击宠物打开，输入自然语言指令。
// design.md §3：400×200，透明无边框，圆角，宠物上方，自动避边。

import AppKit
import SwiftUI

/// 意图对话框窗口（NSPanel 子类）。
/// 继承 PetPanel 的透明/无边框/不抢焦点特性，但输入框需要临时焦点。
final class IntentPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    /// 最小尺寸
    static let defaultSize = NSSize(width: 400, height: 200)
    /// 与宠物的间距
    static let petGap: CGFloat = 12

    init(contentRect: NSRect) {
        super.init(
            contentRect: contentRect,
            styleMask: [.borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        configureIntentStyle()
    }

    private func configureIntentStyle() {
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        isMovableByWindowBackground = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .stationary]
        styleMask.remove(.closable)
        styleMask.remove(.miniaturizable)
        styleMask.remove(.resizable)
        isReleasedWhenClosed = false
        hidesOnDeactivate = false
        becomesKeyOnlyIfNeeded = false
        styleMask.insert(.nonactivatingPanel)
    }

    /// 计算对话框位置：宠物中心上方，自动避边。
    static func frameForPosition(near petFrame: NSRect) -> NSRect {
        let screen = NSScreen.main?.visibleFrame ?? .zero
        let size = defaultSize

        // 默认：宠物中心上方
        var origin = CGPoint(
            x: petFrame.midX - size.width / 2,
            y: petFrame.maxY + petGap
        )

        // 水平避边：左溢出则左对齐，右溢出则右对齐
        if origin.x < screen.minX + 8 {
            origin.x = screen.minX + 8
        } else if origin.x + size.width > screen.maxX - 8 {
            origin.x = screen.maxX - size.width - 8
        }

        // 垂直避边：上方溢出则放到宠物下方
        if origin.y + size.height > screen.maxY - 8 {
            origin.y = petFrame.minY - petGap - size.height
        }
        if origin.y < screen.minY + 8 {
            origin.y = screen.minY + 8
        }

        return NSRect(origin: origin, size: size)
    }

    /// 打开时让面板成为 key window，使 TextEditor 可输入。
    func activateForInput() {
        makeKeyAndOrderFront(nil)
    }
}
