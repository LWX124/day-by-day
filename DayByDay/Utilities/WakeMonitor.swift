// WakeMonitor.swift
// 监听机器唤醒，通知后端补偿调度（design.md §7 / ADR-0001）。
// M0 占位：只监听并打日志。M2 接 POST /wake。

import AppKit
import Combine

@MainActor
final class WakeMonitor: ObservableObject {
    private var workspaceObserver: NSObjectProtocol?

    func start(onWake: @escaping () -> Void) {
        workspaceObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { _ in
            onWake()
        }
    }

    deinit {
        if let o = workspaceObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(o)
        }
    }
}
