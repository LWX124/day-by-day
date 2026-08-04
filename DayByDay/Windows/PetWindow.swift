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
    }
}

@MainActor
final class PetWindowDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var petPanel: PetPanel?
    private var currentEmotion: EmotionState = .idle
    @ObservedObject private var supervisor = BackendSupervisor()
    private var wakeMonitor = WakeMonitor()
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 1. 启动后端守护
        supervisor.start()
        // 2. 监听唤醒
        wakeMonitor.start { [weak self] in
            // M2 接 POST /wake；M0 占位日志
            FileHandle.standardError.write("wake detected\n".data(using: .utf8)!)
            _ = self
        }
        // 3. 后端健康联动宠物情绪
        supervisor.$health.sink { [weak self] h in
            self?.applyHealthToEmotion(h)
        }.store(in: &cancellables)
        // 4. 显示宠物窗（恢复上次位置）
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
}
