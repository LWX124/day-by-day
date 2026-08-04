// PositionStore.swift
// 宠物拖拽位置持久化（design.md §8 / spec/frontend §state-management）。
// 用 UserDefaults 存最后一帧位置，重启后恢复。

import AppKit
import CoreGraphics

enum PositionStore {
    private static let key = "petWindowFrame"

    /// 读上次保存的位置；没有则返回 nil（调用方决定默认位置）。
    static func load() -> NSRect? {
        guard let s = UserDefaults.standard.string(forKey: key) else { return nil }
        // "x,y,w,h"
        let parts = s.split(separator: ",").compactMap { Double($0) }
        guard parts.count == 4 else { return nil }
        return NSRect(x: parts[0], y: parts[1], width: parts[2], height: parts[3])
    }

    /// 保存当前窗口位置。
    static func save(_ rect: NSRect) {
        UserDefaults.standard.set(
            "\(rect.origin.x),\(rect.origin.y),\(rect.size.width),\(rect.size.height)",
            forKey: key
        )
    }
}
