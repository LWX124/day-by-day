// DayByDayApp.swift
// app 入口。LSUIElement=true（隐藏 Dock 图标，见 project.yml）。
// M0 spike：手动管理 PetPanel（不走 WindowGroup，因为要重写 canBecomeKey 等只读属性）。

import SwiftUI

@main
struct DayByDayApp: App {
    @NSApplicationDelegateAdaptor(PetWindowDelegate.self) private var delegate

    var body: some Scene {
        // 菜单栏场景：提供 spike 验收入口。LSUIElement app 仍可有菜单栏。
        Settings {
            EmptyView()
        }
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(replacing: .pasteboard) {}
            CommandGroup(replacing: .textEditing) {}
            // spike 验收菜单
            CommandMenu("Spike") {
                Button("切换情绪（验证宠物能动）") { delegate.cycleEmotion() }
                Button("测试满屏特效 Tier 3") { delegate.celebrate(tier: 3) }
                Button("测试满屏特效 Tier 4") { delegate.celebrate(tier: 4) }
            }
        }
    }
}

/// 宠物情绪状态（design.md §5.4）。M0 spike 只用占位。
enum EmotionState: String, CaseIterable {
    case idle, happy, focused, worried, grumpy, sleeping
}
